from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capture_station.service import capture_station
from app.core.config import get_settings
from app.core.enums import BoxStatus, RobotTaskStatus, SlotStatus, SlotType
from app.core.models import Box, Fault, RobotTask, RobotTelemetry, Slot
from app.digital_twin.runtime import live_twin
from app.embedded.state import embedded_station
from app.robot.runtime import robot_runtime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _risk(
    code: str,
    severity: str,
    score: float,
    explanation: str,
    recommended_action: str,
    affected_task_id: str | None = None,
    kind: str = "PREDICTED_RISK",
) -> dict[str, Any]:
    return {
        "code": code,
        "kind": kind,
        "severity": severity,
        "probability_or_score": round(max(0.0, min(1.0, score)), 3),
        "explanation": explanation,
        "affected_task_id": affected_task_id,
        "expected_time": _now().isoformat(),
        "recommended_action": recommended_action,
    }


def current_predictions(db: Session) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    settings = get_settings()

    for fault in db.scalars(select(Fault).where(Fault.active.is_(True))).all():
        predictions.append(_risk(
            code=fault.type,
            severity="CRITICAL",
            score=1.0,
            explanation=f"Detected active fault: {fault.type}.",
            recommended_action="Resolve the active fault from the Admin Panel before dispatching more robot work.",
            affected_task_id=(fault.details or {}).get("task_id"),
            kind="DETECTED_FAULT",
        ))

    storage_slots = list(db.scalars(select(Slot).where(Slot.type == SlotType.STORAGE.value)).all())
    usable_slots = [s for s in storage_slots if s.enabled and s.status != SlotStatus.DISABLED.value]
    occupied_or_reserved = [s for s in usable_slots if s.status in {
        SlotStatus.OCCUPIED.value,
        SlotStatus.RESERVED.value,
        SlotStatus.RESERVED_FOR_RETURN.value,
    }]
    if usable_slots:
        occupancy = len(occupied_or_reserved) / len(usable_slots)
        if occupancy >= 0.82:
            predictions.append(_risk(
                "WAREHOUSE_NEAR_CAPACITY",
                "WARNING" if occupancy < 0.94 else "CRITICAL",
                occupancy,
                f"Storage occupancy is {occupancy:.0%}; incoming boxes may soon have no safe slot.",
                "Prepare overflow/quarantine capacity or prioritize production retrievals.",
            ))

    blocked_slots = [s for s in usable_slots if s.status in {SlotStatus.BLOCKED.value, SlotStatus.MAINTENANCE.value}]
    if blocked_slots:
        predictions.append(_risk(
            "PATH_BLOCKED",
            "WARNING",
            min(0.95, 0.55 + len(blocked_slots) / max(1, len(usable_slots))),
            f"{len(blocked_slots)} storage location(s) are blocked or in maintenance and may affect aisle access.",
            "Review blocked slots and choose an alternate route or slot before dispatch.",
        ))

    active_tasks = list(db.scalars(select(RobotTask).where(RobotTask.status.in_([
        RobotTaskStatus.QUEUED.value,
        RobotTaskStatus.DISPATCHED.value,
        RobotTaskStatus.RUNNING.value,
    ])).order_by(RobotTask.priority, RobotTask.sequence_number, RobotTask.created_at)).all())
    if len(active_tasks) >= 6:
        predictions.append(_risk(
            "ETA_THRESHOLD_RISK",
            "WARNING",
            min(0.9, 0.45 + len(active_tasks) * 0.06),
            f"{len(active_tasks)} robot task(s) are waiting or running; later orders may exceed demo ETA.",
            "Keep demo speed high or pause lower-priority inbound tasks.",
            affected_task_id=active_tasks[0].id if active_tasks else None,
        ))

    if live_twin.active and live_twin.estimated_duration_s > 0:
        overrun_ratio = live_twin.simulated_elapsed_s / max(live_twin.estimated_duration_s, 0.001)
        if overrun_ratio > 0.85 and live_twin.progress < 0.75:
            predictions.append(_risk(
                "ROBOT_TASK_TIMEOUT",
                "WARNING",
                min(0.95, overrun_ratio),
                "The active task is consuming most of its expected time before reaching matching progress.",
                "Slow the queue and inspect route, lift, and fork telemetry.",
                affected_task_id=live_twin.task_id,
            ))

    latest_telemetry = db.scalar(select(RobotTelemetry).order_by(RobotTelemetry.created_at.desc()))
    if latest_telemetry and robot_runtime.current_task_id and latest_telemetry.task_id == robot_runtime.current_task_id:
        drift = abs(float(latest_telemetry.x) - float(robot_runtime.x)) + abs(float(latest_telemetry.z) - float(robot_runtime.z))
        if drift > 0.35:
            predictions.append(_risk(
                "POSITION_DRIFT",
                "WARNING",
                min(0.95, drift / 1.5),
                f"Telemetry differs from expected robot pose by about {drift:.2f} route units.",
                "Reconcile position before confirming the task.",
                affected_task_id=robot_runtime.current_task_id,
            ))

    picking = db.scalar(select(Slot).where(Slot.code == "PICKING"))
    if picking and picking.box_id and any(t.type == "RETRIEVE_BOX" for t in active_tasks):
        predictions.append(_risk(
            "PICKING_STATION_OCCUPIED",
            "WARNING",
            0.82,
            "A retrieval is queued while the picking station is still occupied.",
            "Confirm the current pick or return the partial box before the next retrieval.",
            affected_task_id=next((t.id for t in active_tasks if t.type == "RETRIEVE_BOX"), None),
        ))

    entry = db.scalar(select(Slot).where(Slot.code == "ENTRY"))
    if entry and entry.box_id and embedded_station.entry_present:
        predictions.append(_risk(
            "ENTRY_STATION_BLOCKED",
            "WARNING",
            0.78,
            "The entry station already contains a box while the ESP32 still reports presence.",
            "Wait for the store task to release ENTRY before introducing the next package.",
        ))

    drying = db.scalar(select(Box.id).where(Box.status == BoxStatus.DRYING.value).limit(1))
    if drying and active_tasks:
        predictions.append(_risk(
            "DRYING_VIOLATION_ATTEMPT",
            "INFO",
            0.32,
            "Drying stock exists; production planning must continue to use READY boxes only.",
            "Use the FIFO plan view to show that drying boxes are excluded.",
            affected_task_id=active_tasks[0].id,
        ))

    last_capture = capture_station.last_result or {}
    classification = last_capture.get("classification") or last_capture.get("vision") or {}
    cv_confidence = float(classification.get("confidence", 1.0) or 0.0)
    if cv_confidence < settings.cv_min_confidence:
        predictions.append(_risk(
            "LOW_CV_CONFIDENCE",
            "WARNING",
            1.0 - cv_confidence,
            f"Last CV confidence was {cv_confidence:.0%}, below the configured {settings.cv_min_confidence:.0%} threshold.",
            "Hold the piece still in the ROI and rescan; do not auto-register this image.",
        ))
    if classification.get("image_quality_ok") is False:
        predictions.append(_risk(
            "IMAGE_QUALITY_BAD",
            "WARNING",
            0.8,
            "The last image was classified as unsuitable or empty.",
            "Retake the image with the core fully inside the green ROI.",
        ))

    quantity = last_capture.get("quantity_estimation") or {}
    for warning in quantity.get("warnings", []):
        predictions.append(_risk(
            warning,
            "WARNING",
            0.88,
            "Weight-based and vision-based quantity signals disagree beyond tolerance.",
            "Route the capture to operator review before registration.",
        ))

    return sorted(
        predictions,
        key=lambda item: (
            {"CRITICAL": 0, "WARNING": 1, "INFO": 2}.get(item["severity"], 3),
            -item["probability_or_score"],
            item["code"],
        ),
    )

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings, load_yaml
from app.cv_gateway.service import MockCVGateway


@dataclass
class CaptureStationRuntime:
    demo_weight_kg: float = 0.0
    last_result: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "weight_kg": round(self.demo_weight_kg, 3),
            "source": "DEMO_SCALE" if not getattr(get_settings(), "scale_base_url", None) else "HTTP_SCALE",
            "last_result": self.last_result,
        }


capture_station = CaptureStationRuntime()


async def current_weight() -> dict[str, Any]:
    base = get_settings().scale_base_url
    if not base:
        return {"weight_kg": round(capture_station.demo_weight_kg, 3), "source": "DEMO_SCALE"}
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f"{base.rstrip('/')}/weight")
        response.raise_for_status()
        payload = response.json()
        weight = float(payload.get("weight_kg", payload.get("weight", 0.0)))
        return {"weight_kg": round(weight, 3), "source": "HTTP_SCALE"}


def weight_profiles() -> dict[str, dict[str, float]]:
    return load_yaml("core_weights.yaml").get("core_weights", {})


def _quantity_contract(core_type: str, gross_weight_kg: float, vision_quantity: int | None = None) -> dict[str, Any]:
    estimate = estimate_quantity(core_type, gross_weight_kg)
    warnings: list[str] = []
    if vision_quantity is not None:
        tolerance = max(1, round(estimate["quantity"] * 0.10))
        if abs(int(vision_quantity) - int(estimate["quantity"])) > tolerance:
            warnings.append("QUANTITY_WEIGHT_VISION_MISMATCH")
    return {
        "gross_weight_kg": estimate["gross_weight_kg"],
        "tare_weight_kg": estimate["tare_weight_kg"],
        "net_weight_kg": estimate["net_weight_kg"],
        "unit_weight_kg": estimate["unit_weight_kg"],
        "weight_quantity": estimate["quantity"],
        "vision_quantity": vision_quantity,
        "final_quantity": estimate["quantity"],
        "confidence": estimate["count_confidence"],
        "warnings": warnings,
        "method": estimate["method"],
    }


def estimate_quantity(core_type: str, gross_weight_kg: float) -> dict[str, Any]:
    profile = weight_profiles().get(core_type)
    if not profile:
        raise ValueError(f"NO_WEIGHT_PROFILE:{core_type}")
    unit = float(profile["unit_weight_kg"])
    tare = float(profile.get("tare_weight_kg", 0.0))
    net = max(0.0, float(gross_weight_kg) - tare)
    if unit <= 0:
        raise ValueError("INVALID_UNIT_WEIGHT")
    raw = net / unit
    quantity = max(0, int(round(raw)))
    residual = abs(net - quantity * unit)
    # Confidence is a transparent calibration-quality score, not a learned probability.
    confidence = max(0.0, min(1.0, 1.0 - residual / max(unit, 1e-9))) if quantity else 0.0
    return {
        "quantity": quantity,
        "count_confidence": round(confidence, 4),
        "gross_weight_kg": round(float(gross_weight_kg), 3),
        "tare_weight_kg": round(tare, 3),
        "net_weight_kg": round(net, 3),
        "unit_weight_kg": round(unit, 4),
        "method": "WEIGHT_CALIBRATION",
    }


def _decode_data_url(data_url: str | None) -> tuple[bytes, str] | None:
    if not data_url or not data_url.startswith("data:") or "," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    mime = header.split(";", 1)[0].replace("data:", "") or "image/jpeg"
    return base64.b64decode(encoded), mime


async def classify_capture(image_data_url: str | None, demo_core_type: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    base = getattr(settings, "cv_base_url", None)
    decoded = _decode_data_url(image_data_url)
    if base and decoded:
        raw, mime = decoded
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # CV V1 contract is a multipart image classifier. Try the canonical route first.
                response = await client.post(
                    f"{base.rstrip('/')}/api/v1/classify",
                    files={"image": ("capture.jpg", raw, mime)},
                )
                if response.status_code == 404:
                    response = await client.post(
                        f"{base.rstrip('/')}/classify",
                        files={"image": ("capture.jpg", raw, mime)},
                    )
                response.raise_for_status()
                payload = response.json()
                prediction = payload.get("prediction", payload)
                core_type = prediction.get("core_type") or prediction.get("prediction") or payload.get("core_type")
                confidence = float(prediction.get("confidence", payload.get("confidence", 0.0)))
                status = payload.get("status", "ACCEPTED" if confidence >= settings.cv_min_confidence else "MANUAL_REVIEW")
                top_k = [
                    {"core_type_code": str(core_type), "confidence": confidence},
                    *[
                        {
                            "core_type_code": str(item.get("core_type") or item.get("core_type_code")),
                            "confidence": float(item.get("confidence", 0.0)),
                        }
                        for item in payload.get("alternatives", [])
                        if item.get("core_type") or item.get("core_type_code")
                    ],
                ]
                warnings = []
                if status != "ACCEPTED":
                    warnings.append("LOW_CV_CONFIDENCE")
                if core_type == "EMPTY":
                    warnings.append("IMAGE_QUALITY_BAD")
                return {
                    "core_type": core_type,
                    "core_type_code": core_type,
                    "confidence": confidence,
                    "status": status,
                    "model_version": payload.get("model_version"),
                    "alternatives": payload.get("alternatives", []),
                    "top_k": top_k,
                    "inference_ms": payload.get("inference_ms"),
                    "image_quality_ok": core_type != "EMPTY",
                    "warnings": warnings,
                    "source": "CV_HTTP",
                }
        except httpx.HTTPError:
            pass

    # Demo fallback preserves the same business contract without claiming model quality.
    result = await MockCVGateway({
        "core_type": demo_core_type or "CORE-A",
        "quantity": 0,
        "confidence": 0.96,
        "status": "ACCEPTED",
    }).classify(None)
    return {
        "core_type": result["core_type"],
        "core_type_code": result["core_type"],
        "confidence": float(result["confidence"]),
        "status": result["status"],
        "model_version": "mock-demo",
        "alternatives": [],
        "top_k": [{"core_type_code": result["core_type"], "confidence": float(result["confidence"])}],
        "inference_ms": 0.0,
        "image_quality_ok": True,
        "warnings": [] if not base else ["CV_HTTP_UNAVAILABLE_DEMO_FALLBACK"],
        "source": "MOCK_CV",
    }


async def analyze_capture(image_data_url: str | None, gross_weight_kg: float, demo_core_type: str | None = None) -> dict[str, Any]:
    vision = await classify_capture(image_data_url, demo_core_type=demo_core_type)
    core_type = demo_core_type or vision.get("core_type")
    if not core_type:
        raise ValueError("CV_DID_NOT_RETURN_CORE_TYPE")
    if demo_core_type:
        vision["confirmed_core_type"] = demo_core_type
    count = estimate_quantity(str(core_type), gross_weight_kg)
    quantity = _quantity_contract(str(core_type), gross_weight_kg, vision.get("quantity"))
    status = vision.get("status", "MANUAL_REVIEW")
    if float(vision.get("confidence", 0.0)) < get_settings().cv_min_confidence:
        status = "MANUAL_REVIEW"
    if count["quantity"] <= 0 or count["count_confidence"] < 0.65:
        status = "MANUAL_REVIEW"
    result = {
        "core_type": str(core_type),
        "type_confidence": round(float(vision.get("confidence", 0.0)), 4),
        "quantity": int(count["quantity"]),
        "count_confidence": count["count_confidence"],
        "status": status,
        "vision": vision,
        "weight": count,
        "quantity_estimation": quantity,
        "classification": {
            "core_type_code": str(core_type),
            "confidence": round(float(vision.get("confidence", 0.0)), 4),
            "top_k": vision.get("top_k", []),
            "model_version": vision.get("model_version"),
            "inference_ms": vision.get("inference_ms"),
            "image_quality_ok": bool(vision.get("image_quality_ok", True)),
            "warnings": vision.get("warnings", []),
        },
    }
    capture_station.last_result = result
    return result

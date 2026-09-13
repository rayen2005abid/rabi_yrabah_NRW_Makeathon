from __future__ import annotations
from math import hypot
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.catalog.service import get_by_code
from app.core.clock import clock
from app.core.config import get_settings, load_yaml
from app.core.enums import BoxStatus, FaultType, AlertSeverity, SlotType, SlotStatus, RobotTaskType
from app.core.models import Box, VisionResult, Alert, Slot, SimulationRun
from app.drying.service import ready_at_for
from app.slotting.service import choose_best_slot
from app.warehouse.service import occupy_slot
from app.events.service import emit
from app.core.state_machine import transition
from app.robot.service import create_task
from app.robot.planner import semantic_path
from app.safety.service import validate_motion_sequence


def register_box(db: Session, core_type_code: str, quantity: int, box_code: str | None = None, entered_at=None, vision_confidence: float | None = None) -> Box:
    core = get_by_code(db, core_type_code)
    if not core or not core.active:
        raise ValueError('unknown or inactive core type')
    if quantity <= 0:
        raise ValueError('quantity must be positive')
    if vision_confidence is not None and vision_confidence < get_settings().cv_min_confidence:
        db.add(Alert(code='CV_LOW_CONFIDENCE', severity=AlertSeverity.WARNING.value, message=f'CV confidence {vision_confidence:.2f} below threshold'))
        emit(db, 'FAULT_RAISED', payload={'type': FaultType.LOW_CV_CONFIDENCE.value, 'confidence': vision_confidence})
        db.commit()
        raise ValueError('CV confidence below acceptance threshold')

    entry = db.scalar(select(Slot).where(Slot.code == 'ENTRY').with_for_update())
    if not entry:
        raise ValueError('ENTRY_STATION_MISSING')
    if entry.status != SlotStatus.FREE.value or entry.box_id is not None:
        raise ValueError('ENTRY_STATION_OCCUPIED')

    entered = entered_at or clock.now()
    ready_at = ready_at_for(entered)
    storage_status = BoxStatus.READY.value if clock.now() >= ready_at else BoxStatus.DRYING.value
    box = Box(
        code=box_code or f'BOX-{uuid4().hex[:8].upper()}', core_type_id=core.id,
        quantity=quantity, initial_quantity=quantity, entered_at=entered, ready_at=ready_at,
        status=BoxStatus.REGISTERING.value, vision_confidence=vision_confidence,
    )
    db.add(box); db.flush()

    target = choose_best_slot(db, box)
    if not target:
        db.rollback()
        db.add(Alert(code='WAREHOUSE_FULL', severity=AlertSeverity.CRITICAL.value, message='No safe free storage slot is available'))
        emit(db, 'FAULT_RAISED', payload={'type': 'WAREHOUSE_FULL'})
        db.commit()
        raise ValueError('WAREHOUSE_FULL')

    # Simulate/validate the storage decision before any robot execution is queued.
    path = semantic_path(entry, target, RobotTaskType.STORE_BOX.value)
    safety = validate_motion_sequence(path)
    if not safety.ok:
        db.rollback()
        raise ValueError(f'INTAKE_SIMULATION_FAILED:{safety.reason}')
    cfg = load_yaml('robot.yaml')['robot']
    distance = hypot(target.x_coordinate-entry.x_coordinate, target.z_coordinate-entry.z_coordinate) + abs(target.y_coordinate-entry.y_coordinate)
    duration = abs(target.x_coordinate-entry.x_coordinate)/float(cfg['x_speed_mps']) + abs(target.z_coordinate-entry.z_coordinate)/float(cfg['z_speed_mps']) + 2*abs(target.y_coordinate-entry.y_coordinate)/float(cfg['y_speed_mps']) + float(cfg['load_time_s']) + float(cfg['unload_time_s'])
    sim = SimulationRun(kind='INTAKE_STORE', status='PASS', input_payload={'box_id':box.id,'target_slot':target.code}, result_payload={'status':'PASS','estimated_robot_distance_m':round(distance,3),'estimated_duration_s':round(duration,3),'safety_validation':True})
    db.add(sim)

    # Physical truth: the box starts at ENTRY. The target is only reserved until hardware ACK.
    occupy_slot(db, entry, box)
    box.status = transition(box.status, storage_status)
    target.status = SlotStatus.RESERVED.value
    task = create_task(db, RobotTaskType.STORE_BOX.value, box, entry, target, sequence=0)
    emit(db, 'BOX_REGISTERED', 'box', box.id, {'box_code': box.code, 'quantity': quantity, 'entry_slot': entry.code})
    emit(db, 'SIMULATION_PASSED', 'box', box.id, {'simulation_run_id':sim.id,'kind':'INTAKE_STORE'})
    emit(db, 'BOX_STORE_PLANNED', 'box', box.id, {'target_slot':target.code,'robot_task_id':task.id})

    total=db.scalar(select(func.count()).select_from(Slot).where(Slot.type==SlotType.STORAGE.value,Slot.enabled.is_(True))) or 0
    free=db.scalar(select(func.count()).select_from(Slot).where(Slot.type==SlotType.STORAGE.value,Slot.enabled.is_(True),Slot.status==SlotStatus.FREE.value)) or 0
    if total and free/total <= 0.10:
        db.add(Alert(code='WAREHOUSE_NEAR_FULL',severity=AlertSeverity.WARNING.value,message=f'Only {free} of {total} storage slots remain free'))
    db.commit(); db.refresh(box)
    return box


def register_from_cv(db: Session, payload: dict) -> Box:
    vr = VisionResult(core_type_code=payload['core_type'], quantity=payload['quantity'], confidence=payload['confidence'], status=payload.get('status','ACCEPTED'), raw_payload=payload)
    db.add(vr); db.flush()
    if vr.status != 'ACCEPTED':
        db.rollback()
        raise ValueError('CV result not accepted')
    box = register_box(db, vr.core_type_code, vr.quantity, vision_confidence=vr.confidence)
    box.vision_result_id = vr.id
    db.commit()
    return box

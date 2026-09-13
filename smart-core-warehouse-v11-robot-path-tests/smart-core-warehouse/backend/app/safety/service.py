from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Fault, Slot
from app.core.enums import FaultType, SlotStatus

@dataclass
class SafetyResult:
    ok: bool
    reason: str | None = None


def active_fault_types(db: Session) -> set[str]:
    return set(db.scalars(select(Fault.type).where(Fault.active.is_(True))).all())


def validate_dispatch(db: Session, source: Slot | None, target: Slot | None, carrying_box: bool = False, allow_occupied_target: bool = False) -> SafetyResult:
    faults = active_fault_types(db)
    if FaultType.ESTOP.value in faults:
        return SafetyResult(False, 'ESTOP_ACTIVE')
    if faults.intersection({FaultType.X_AXIS_FAULT.value, FaultType.Z_AXIS_FAULT.value, FaultType.FORK_FAULT.value, FaultType.POSITION_MISMATCH.value, FaultType.BOX_NOT_DETECTED.value}):
        return SafetyResult(False, 'ROBOT_FAULT')
    if source and source.status in {SlotStatus.BLOCKED.value, SlotStatus.MAINTENANCE.value, SlotStatus.DISABLED.value}:
        return SafetyResult(False, 'SOURCE_UNAVAILABLE')
    if target and target.status in {SlotStatus.BLOCKED.value, SlotStatus.MAINTENANCE.value, SlotStatus.DISABLED.value}:
        return SafetyResult(False, 'TARGET_UNAVAILABLE')
    if target and target.box_id is not None and (source is None or target.id != source.id) and not allow_occupied_target:
        return SafetyResult(False, 'TARGET_OCCUPIED')
    return SafetyResult(True)


def validate_motion_sequence(steps: list[dict]) -> SafetyResult:
    y_extended = False
    carrying = False
    for step in steps:
        action = step.get('action')
        if action in {'MOVE_X','MOVE_Z','MOVE_XZ'} and y_extended:
            return SafetyResult(False, 'AXIS_MOTION_WITH_FORK_EXTENDED')
        if action == 'EXTEND_Y': y_extended = True
        elif action == 'RETRACT_Y': y_extended = False
        elif action == 'LOAD':
            if carrying: return SafetyResult(False, 'LOAD_WHILE_CARRYING')
            carrying = True
        elif action == 'UNLOAD':
            if not carrying: return SafetyResult(False, 'UNLOAD_WITHOUT_BOX')
            carrying = False
    return SafetyResult(True)

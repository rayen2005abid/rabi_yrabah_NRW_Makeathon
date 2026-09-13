from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Fault, Alert, Slot
from app.core.enums import AlertSeverity, FaultType, SlotStatus
from app.events.service import emit
from app.robot.runtime import robot_runtime


def inject_fault(db: Session, fault_type: str, details: dict | None = None) -> Fault:
    FaultType(fault_type)
    f=Fault(type=fault_type,details=details or {},active=True); db.add(f)
    if fault_type==FaultType.ESTOP.value: robot_runtime.estop=True; robot_runtime.mode='ESTOP'
    elif fault_type in {FaultType.X_AXIS_FAULT.value,FaultType.Z_AXIS_FAULT.value,FaultType.FORK_FAULT.value}: robot_runtime.fault=fault_type; robot_runtime.mode='FAULT'
    if fault_type==FaultType.SLOT_BLOCKED.value and details and details.get('slot_code'):
        slot=db.scalar(select(Slot).where(Slot.code==details['slot_code']))
        if slot: slot.status=SlotStatus.BLOCKED.value
    db.add(Alert(code=fault_type,severity=AlertSeverity.CRITICAL.value,message=f'Fault active: {fault_type}'))
    db.flush(); emit(db,'FAULT_RAISED','fault',f.id,{'type':fault_type,'details':details or {}}); db.commit(); return f

def clear_fault(db: Session, fault_id: str) -> Fault:
    f=db.get(Fault,fault_id)
    if not f: raise ValueError('fault not found')
    f.active=False; f.cleared_at=datetime.now(timezone.utc)
    if f.type==FaultType.ESTOP.value: robot_runtime.estop=False
    if f.type==FaultType.SLOT_BLOCKED.value and f.details.get('slot_code'):
        slot=db.scalar(select(Slot).where(Slot.code==f.details['slot_code']))
        if slot and slot.status==SlotStatus.BLOCKED.value:
            slot.status=SlotStatus.OCCUPIED.value if slot.box_id else SlotStatus.FREE.value
    if robot_runtime.fault==f.type: robot_runtime.fault=None
    for alert in db.scalars(select(Alert).where(Alert.code==f.type,Alert.active.is_(True))).all():
        alert.active=False
    if not robot_runtime.estop and robot_runtime.fault is None: robot_runtime.mode='IDLE'
    emit(db,'FAULT_CLEARED','fault',f.id,{'type':f.type}); db.commit(); return f

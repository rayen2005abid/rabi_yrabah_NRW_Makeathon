from datetime import timedelta
from app.core.clock import clock
from app.core.models import Box, DomainEvent, Alert
from app.core.enums import BoxStatus, RobotTaskType, SlotStatus, FaultType, RobotTaskStatus, SlotType
from app.drying.service import ready_at_for
from app.warehouse.service import occupy_slot
from app.robot.service import create_task
from app.embedded.adapters import mock_adapter
from app.faults.service import inject_fault
from conftest import add_slot
from sqlalchemy import select


def test_required_z_axis_fault_does_not_finalize_movement(db,core_a):
    source=add_slot(db,'S10',x=1,z=2)
    picking=add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    entered=clock.now()-timedelta(hours=30)
    b=Box(code='B-FAULT',core_type_id=core_a.id,quantity=20,initial_quantity=20,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.READY.value)
    db.add(b); db.flush(); occupy_slot(db,source,b); db.commit()
    task=create_task(db,RobotTaskType.RETRIEVE_BOX.value,b,source,picking); db.commit()
    inject_fault(db,FaultType.Z_AXIS_FAULT.value,{})
    result=mock_adapter.dispatch_task(db,task)
    db.refresh(task); db.refresh(b); db.refresh(source)
    assert result['status']=='FAILED'
    assert task.status==RobotTaskStatus.INTERRUPTED.value
    assert b.quantity==20
    assert b.current_slot_id==source.id
    assert source.box_id==b.id
    assert source.status==SlotStatus.OCCUPIED.value
    assert db.scalar(select(DomainEvent).where(DomainEvent.event_type=='FAULT_RAISED')) is not None
    assert db.scalar(select(Alert).where(Alert.code==FaultType.Z_AXIS_FAULT.value)) is not None

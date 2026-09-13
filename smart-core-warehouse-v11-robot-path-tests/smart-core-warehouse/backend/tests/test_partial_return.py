from datetime import timedelta
from sqlalchemy import select
from app.core.clock import clock
from app.core.models import Box
from app.core.enums import BoxStatus, SlotType
from app.drying.service import ready_at_for
from app.warehouse.service import occupy_slot
from app.picking.service import confirm_pick
from app.embedded.adapters import mock_adapter
from conftest import add_slot


def test_required_partial_return_preserves_original_timestamp(db,core_a):
    original=clock.now()-timedelta(hours=48)
    s100=add_slot(db,'S100',x=9,z=9)
    better=add_slot(db,'S001',x=0.1,z=0.1)
    picking=add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    b=Box(code='BOX-A17',core_type_id=core_a.id,quantity=30,initial_quantity=30,entered_at=original,ready_at=ready_at_for(original),status=BoxStatus.AT_PICKING.value,reserved_return_slot_id=s100.id,current_slot_id=None)
    db.add(b); db.flush(); s100.status='RESERVED_FOR_RETURN'; db.commit()
    old_ready=b.ready_at
    persisted_original=b.entered_at.replace(tzinfo=None)
    persisted_ready=b.ready_at.replace(tzinfo=None)
    result=confirm_pick(db,b,20)
    assert b.quantity==10
    assert b.entered_at.replace(tzinfo=None)==persisted_original
    assert b.ready_at.replace(tzinfo=None)==persisted_ready
    assert result['status']=='RETURN_PLANNED'
    task_id=result['task_id']
    from app.core.models import RobotTask
    task=db.get(RobotTask,task_id)
    mock_adapter.dispatch_task(db,task)
    db.refresh(b)
    assert b.quantity==10
    assert b.entered_at.replace(tzinfo=None)==persisted_original
    assert b.ready_at.replace(tzinfo=None)==persisted_ready
    assert b.current_slot_id is not None

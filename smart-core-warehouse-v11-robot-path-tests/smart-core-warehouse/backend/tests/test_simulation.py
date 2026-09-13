from datetime import timedelta
from app.core.clock import clock
from app.core.models import Box
from app.core.enums import BoxStatus
from app.drying.service import ready_at_for
from app.warehouse.service import occupy_slot
from app.simulation.service import what_if_production
from conftest import add_slot


def test_what_if_does_not_mutate_inventory(db,core_a):
    s=add_slot(db,'S1')
    entered=clock.now()-timedelta(hours=30)
    b=Box(code='A1',core_type_id=core_a.id,quantity=30,initial_quantity=30,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.READY.value)
    db.add(b); db.flush(); occupy_slot(db,s,b); db.commit()
    before=(b.quantity,b.status,b.current_slot_id)
    result=what_if_production(db,core_a.id,20)
    db.refresh(b)
    assert result['status']=='PASS'
    assert (b.quantity,b.status,b.current_slot_id)==before

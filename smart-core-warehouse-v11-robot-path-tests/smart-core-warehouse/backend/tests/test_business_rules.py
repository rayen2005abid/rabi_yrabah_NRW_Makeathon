from datetime import timedelta
from sqlalchemy import select
from app.core.clock import clock
from app.core.models import Box, ProductionRequest, Slot
from app.core.enums import BoxStatus, ProductionRequestStatus, SlotStatus, SlotType
from app.drying.service import ready_at_for, is_ready
from app.warehouse.service import occupy_slot
from app.fulfillment.service import build_plan
from app.fifo.service import eligible_boxes
from app.core.state_machine import transition
from app.safety.service import validate_motion_sequence
from conftest import add_slot


def make_box(db, core, code, qty, age_h, slot_code):
    entered=clock.now()-timedelta(hours=age_h)
    b=Box(code=code,core_type_id=core.id,quantity=qty,initial_quantity=qty,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.READY.value if age_h>=24 else BoxStatus.DRYING.value)
    db.add(b); db.flush(); s=add_slot(db,slot_code); occupy_slot(db,s,b); db.commit(); return b

def test_drying_rule_exact_24h():
    now=clock.now(); entered=now-timedelta(hours=23,minutes=59)
    assert not is_ready(entered,now)
    assert is_ready(now-timedelta(hours=24),now)

def test_required_fifo_fulfillment_business_case(db,core_a):
    a1=make_box(db,core_a,'A01',10,35,'S1')
    a2=make_box(db,core_a,'A02',30,30,'S2')
    a3=make_box(db,core_a,'A03',40,27,'S3')
    a4=make_box(db,core_a,'A04',50,17,'S4')
    req=ProductionRequest(core_type_id=core_a.id,requested_quantity=55,status=ProductionRequestStatus.PENDING.value,priority=30)
    db.add(req); db.commit()
    plan=build_plan(db,req)
    assert [(i.box.code,i.quantity_to_take,i.quantity_after) for i in plan.items]==[('A01',10,0),('A02',30,0),('A03',15,25)]
    assert a4.quantity==50
    assert all(i.box.ready_at <= clock.now() for i in plan.items)
    assert [b.code for b in eligible_boxes(db,core_a.id)][:3]==['A01','A02','A03']

def test_state_machine_rejects_impossible_transition():
    assert transition('READY','RESERVED')=='RESERVED'
    try: transition('READY','EMPTY')
    except ValueError: pass
    else: raise AssertionError('illegal transition was accepted')

def test_safety_forbids_xz_with_fork_extended():
    result=validate_motion_sequence([{'action':'EXTEND_Y'},{'action':'MOVE_XZ'}])
    assert not result.ok

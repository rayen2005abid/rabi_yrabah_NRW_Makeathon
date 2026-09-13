from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core.clock import clock
from app.core.models import Box, ProductionRequest, FulfillmentPlan, Slot
from app.core.enums import BoxStatus, ProductionRequestStatus, SlotType, SlotStatus, RobotTaskType
from app.drying.service import ready_at_for
from app.warehouse.service import occupy_slot
from app.fulfillment.service import build_plan, shortage_info
from app.simulation.service import what_if_time_advance, what_if_blocked_slot, what_if_near_full
from app.picking.service import confirm_pick
from app.embedded.reconciliation import reconcile_position
from app.slotting.service import score_slot
from app.robot.service import queue_for_plan, process_next
from conftest import add_slot


def make(db,core,code,qty,age,slot):
    entered=clock.now()-timedelta(hours=age)
    b=Box(code=code,core_type_id=core.id,quantity=qty,initial_quantity=qty,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.READY.value if age>=24 else BoxStatus.DRYING.value)
    db.add(b);db.flush();s=add_slot(db,slot);occupy_slot(db,s,b);db.commit();return b

def test_shortage_never_consumes_drying_stock(db,core_a):
    make(db,core_a,'READY-1',20,30,'S1'); make(db,core_a,'DRY-1',50,10,'S2')
    req=ProductionRequest(core_type_id=core_a.id,requested_quantity=40,status='PENDING',priority=30);db.add(req);db.commit()
    plan=build_plan(db,req); info=shortage_info(db,req,plan)
    assert plan.total_planned==20 and info['shortage']==20 and info['drying_quantity']==50
    assert [i.box.code for i in plan.items]==['READY-1']

def test_partial_return_falls_back_to_original_when_no_free_storage(db,core_a):
    fallback=add_slot(db,'S100'); picking=add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    entered=clock.now()-timedelta(hours=30)
    b=Box(code='PARTIAL',core_type_id=core_a.id,quantity=30,initial_quantity=30,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.AT_PICKING.value,current_slot_id=picking.id,reserved_return_slot_id=fallback.id)
    db.add(b);db.flush(); picking.box_id=b.id;picking.status='OCCUPIED';fallback.status='RESERVED_FOR_RETURN';db.commit()
    r=confirm_pick(db,b,10)
    assert r['return_slot']=='S100' and b.quantity==20

def test_empty_box_releases_picking_and_fallback(db,core_a):
    fallback=add_slot(db,'S100'); picking=add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    entered=clock.now()-timedelta(hours=30)
    b=Box(code='EMPTY-ME',core_type_id=core_a.id,quantity=5,initial_quantity=5,entered_at=entered,ready_at=ready_at_for(entered),status=BoxStatus.AT_PICKING.value,current_slot_id=picking.id,reserved_return_slot_id=fallback.id)
    db.add(b);db.flush();picking.box_id=b.id;picking.status='OCCUPIED';fallback.status='RESERVED_FOR_RETURN';db.commit()
    r=confirm_pick(db,b,5);db.refresh(picking);db.refresh(fallback)
    assert r['status']=='EMPTY' and b.status=='EMPTY' and b.current_slot_id is None
    assert picking.status=='FREE' and picking.box_id is None and fallback.status=='FREE'

def test_slot_scoring_prefers_lower_travel_for_equal_factors():
    a=Slot(code='A',type='STORAGE',status='FREE',enabled=True,x_coordinate=0,y_coordinate=0,z_coordinate=0,travel_cost=1,accessibility_score=1)
    b=Slot(code='B',type='STORAGE',status='FREE',enabled=True,x_coordinate=0,y_coordinate=0,z_coordinate=0,travel_cost=5,accessibility_score=1)
    weights={'travel':1,'future':1,'congestion':0,'balance':0,'accessibility':0}
    assert score_slot(a,.5,weights)[0] < score_slot(b,.5,weights)[0]

def test_position_reconciliation_uses_tolerance():
    assert reconcile_position({'x':1,'y':0,'z':1},{'x':1.01,'y':0,'z':1.0},.02)['ok']
    bad=reconcile_position({'x':1,'y':0,'z':1},{'x':1.10,'y':0,'z':1.0},.02)
    assert not bad['ok'] and bad['reason']=='POSITION_MISMATCH'

def test_what_if_time_preview_does_not_advance_clock(db,core_a):
    before=clock.now(); make(db,core_a,'D1',10,10,'S1')
    r=what_if_time_advance(db,24)
    assert clock.now()==before and r['simulation_only'] is True and r['quantity_becoming_ready']==10

def test_blocked_slot_and_near_full_are_read_only(db):
    s=add_slot(db,'S1')
    r=what_if_blocked_slot(db,'S1'); db.refresh(s)
    assert r['projected_free_slots']==0 and s.status=='FREE'
    r2=what_if_near_full(db,2)
    assert r2['status']=='FAIL' and s.status=='FREE'

def test_duplicate_reservation_is_prevented_at_execution(db,core_a):
    make(db,core_a,'ONLY',30,40,'S1'); add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    r1=ProductionRequest(core_type_id=core_a.id,requested_quantity=10,status='PENDING',priority=30)
    r2=ProductionRequest(core_type_id=core_a.id,requested_quantity=10,status='PENDING',priority=30)
    db.add_all([r1,r2]);db.commit();p1=build_plan(db,r1);p2=build_plan(db,r2)
    p1.validation_state='PASS';p2.validation_state='PASS';db.commit();queue_for_plan(db,p1)
    with pytest.raises(ValueError): queue_for_plan(db,p2)

def test_scheduler_waits_if_picking_station_is_occupied(db,core_a):
    b1=make(db,core_a,'B1',10,40,'S1'); b2=make(db,core_a,'B2',10,30,'S2'); picking=add_slot(db,'PICKING',typ=SlotType.ENTRY_PICKING.value)
    req=ProductionRequest(core_type_id=core_a.id,requested_quantity=20,status='PENDING',priority=30);db.add(req);db.commit();plan=build_plan(db,req);plan.validation_state='PASS';db.commit();queue_for_plan(db,plan)
    first=process_next(db); assert first['status']=='COMPLETED'
    second=process_next(db); assert second['status']=='WAITING' and second['reason']=='PICKING_STATION_OCCUPIED'

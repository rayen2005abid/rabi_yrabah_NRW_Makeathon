from __future__ import annotations
from math import hypot
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.models import Slot, Box, RobotTask, Fault, SimulationRun, ProductionRequest, CoreType
from app.core.enums import SlotType, SlotStatus, BoxStatus, RobotTaskStatus, RobotTaskType
from app.core.clock import clock


def _elapsed(a,b):
    if not a or not b: return 0.0
    if (getattr(a,'tzinfo',None) is None) != (getattr(b,'tzinfo',None) is None):
        a=a.replace(tzinfo=None); b=b.replace(tzinfo=None)
    return max(0.0,(a-b).total_seconds())


def summary(db: Session) -> dict:
    storage=list(db.scalars(select(Slot).where(Slot.type==SlotType.STORAGE.value)).all())
    buffers=list(db.scalars(select(Slot).where(Slot.type==SlotType.BUFFER.value)).all())
    free=sum(1 for s in storage if s.status==SlotStatus.FREE.value and s.enabled)
    occupied=sum(1 for s in storage if s.box_id is not None)
    active_boxes=list(db.scalars(select(Box).where(Box.quantity>0)).all())
    ready_qty=sum(b.quantity for b in active_boxes if b.status==BoxStatus.READY.value)
    drying_qty=sum(b.quantity for b in active_boxes if b.status==BoxStatus.DRYING.value)
    partial=sum(1 for b in active_boxes if b.quantity < b.initial_quantity)
    avg_fill=(sum(b.quantity/max(b.initial_quantity,1) for b in active_boxes)/len(active_boxes)*100) if active_boxes else 0
    tasks=list(db.scalars(select(RobotTask)).all())
    failed=sum(1 for t in tasks if t.status in {RobotTaskStatus.FAILED.value,RobotTaskStatus.INTERRUPTED.value})
    completed=[t for t in tasks if t.status==RobotTaskStatus.COMPLETED.value and t.started_at and t.completed_at]
    retrievals=[t for t in completed if t.type==RobotTaskType.RETRIEVE_BOX.value]
    avg_retrieval=sum(_elapsed(t.completed_at,t.started_at) for t in retrievals)/len(retrievals) if retrievals else 0.0
    busy=sum(_elapsed(t.completed_at,t.started_at) for t in completed)
    if tasks:
        first=min(t.created_at for t in tasks); window=max(1.0,_elapsed(clock.now(),first))
        utilization=min(100.0,busy/window*100)
    else: utilization=0.0
    slot_by_code={s.code:s for s in db.scalars(select(Slot)).all()}
    distance=0.0
    for t in completed:
        a=slot_by_code.get(t.source_location or ''); b=slot_by_code.get(t.target_location or '')
        if a and b: distance+=hypot(a.x_coordinate-b.x_coordinate,a.z_coordinate-b.z_coordinate)+abs(a.y_coordinate-b.y_coordinate)
    requests=list(db.scalars(select(ProductionRequest)).all())
    waits=[_elapsed(r.started_at,r.created_at) for r in requests if r.started_at]
    avg_wait=sum(waits)/len(waits) if waits else 0.0
    faults=db.scalar(select(func.count()).select_from(Fault)) or 0
    sims=list(db.scalars(select(SimulationRun)).all())
    quantities={}
    cores={c.id:c.code for c in db.scalars(select(CoreType)).all()}
    for b in active_boxes: quantities[cores.get(b.core_type_id,b.core_type_id)]=quantities.get(cores.get(b.core_type_id,b.core_type_id),0)+b.quantity
    return {
        'occupancy_pct': round((occupied/len(storage)*100) if storage else 0,2),
        'free_slot_count': free,
        'occupied_slot_count': occupied,
        'ready_stock': ready_qty,
        'drying_stock': drying_qty,
        'quantities_per_core_type': quantities,
        'partial_box_count': partial,
        'average_box_fill_ratio_pct': round(avg_fill,2),
        'average_retrieval_time_s': round(avg_retrieval,3),
        'robot_utilization_pct': round(utilization,2),
        'robot_travel_distance_m': round(distance,3),
        'production_request_waiting_time_s': round(avg_wait,3),
        'fifo_violations': 0,
        'failed_robot_tasks': failed,
        'warehouse_fault_count': faults,
        'buffer_utilization_pct': round((sum(1 for b in buffers if b.box_id)/len(buffers)*100) if buffers else 0,2),
        'simulation_pass_count': sum(1 for s in sims if s.status=='PASS'),
        'simulation_fail_count': sum(1 for s in sims if s.status!='PASS'),
    }

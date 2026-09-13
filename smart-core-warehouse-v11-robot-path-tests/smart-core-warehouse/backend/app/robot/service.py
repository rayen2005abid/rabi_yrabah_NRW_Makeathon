from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import RobotTask, Slot, Box, ProductionRequest, FulfillmentPlan, Alert
from app.core.enums import RobotTaskType, RobotTaskStatus, BoxStatus, SlotStatus, ProductionRequestStatus, PlanStatus, AlertSeverity
from app.robot.planner import semantic_path
from app.safety.service import validate_motion_sequence
from app.embedded.adapters import mock_adapter
from app.events.service import emit
from app.core.config import load_yaml
from app.core.clock import clock
from app.core.state_machine import transition

def priority_for(task_type: str, requested: int | None = None) -> int:
    if requested is not None: return requested
    p=load_yaml('robot.yaml')['robot'].get('priorities',{})
    mapping={RobotTaskType.RECOVERY.value:'recovery',RobotTaskType.RETURN_BOX.value:'return_box',RobotTaskType.STORE_BOX.value:'incoming_storage'}
    return int(p.get(mapping.get(task_type,'normal_production'),30))

def create_task(db: Session, task_type: str, box: Box | None, source: Slot | None, target: Slot | None, request_id: str | None = None, sequence: int = 0, priority: int | None = None) -> RobotTask:
    path = semantic_path(source, target, task_type) if source and target else []
    check = validate_motion_sequence(path)
    if not check.ok: raise ValueError(check.reason)
    task = RobotTask(type=task_type, priority=priority_for(task_type, priority), box_id=box.id if box else None, source_location=source.code if source else None, target_location=target.code if target else None, sequence_number=sequence, request_id=request_id, planned_path=path)
    db.add(task); db.flush(); emit(db,'ROBOT_TASK_CREATED','robot_task',task.id,{'type':task_type})
    return task

def queue_for_plan(db: Session, plan: FulfillmentPlan):
    req = db.get(ProductionRequest, plan.request_id)
    tasks=[]
    picking = db.scalar(select(Slot).where(Slot.code=='PICKING'))
    for i,item in enumerate(plan.items, start=1):
        box=db.scalar(select(Box).where(Box.id==item.box_id).with_for_update()); source=db.scalar(select(Slot).where(Slot.code==item.source_slot).with_for_update())
        if not box or not source or not picking: raise ValueError('invalid plan location')
        if box.status != BoxStatus.READY.value: raise ValueError(f'box {box.code} no longer ready')
        if box.quantity != item.quantity_before: raise ValueError(f'box {box.code} quantity changed since planning')
        if source.box_id != box.id or box.current_slot_id != source.id: raise ValueError(f'box {box.code} physical source changed since planning')
        box.status=transition(box.status,BoxStatus.RESERVED.value); source.status=SlotStatus.RESERVED_FOR_RETURN.value
        box.reserved_return_slot_id=source.id
        t=create_task(db,RobotTaskType.RETRIEVE_BOX.value,box,source,picking,req.id,i,req.priority)
        box.status=transition(box.status,BoxStatus.RETRIEVAL_PLANNED.value)
        tasks.append(t)
    plan.status=PlanStatus.EXECUTING.value; req.status=ProductionRequestStatus.EXECUTING.value; req.started_at=clock.now()
    db.commit(); return tasks

def process_next(db: Session):
    from app.robot.runtime import robot_runtime
    if robot_runtime.current_task_id is not None:
        return {'status':'WAITING','reason':'ROBOT_BUSY','task_id':robot_runtime.current_task_id}
    task=db.scalar(select(RobotTask).where(RobotTask.status==RobotTaskStatus.QUEUED.value).order_by(RobotTask.priority,RobotTask.sequence_number,RobotTask.created_at))
    if not task: return None
    if task.type == RobotTaskType.RETRIEVE_BOX.value and task.target_location:
        target=db.scalar(select(Slot).where(Slot.code==task.target_location))
        if target and target.box_id is not None:
            existing=db.scalar(select(Alert).where(Alert.code=='PICKING_STATION_BLOCKED',Alert.active.is_(True)))
            if not existing:
                db.add(Alert(code='PICKING_STATION_BLOCKED',severity=AlertSeverity.WARNING.value,message='Picking station occupied; next retrieval is waiting'))
                db.commit()
            return {'status':'WAITING','reason':'PICKING_STATION_OCCUPIED','task_id':task.id}
    return mock_adapter.dispatch_task(db,task)

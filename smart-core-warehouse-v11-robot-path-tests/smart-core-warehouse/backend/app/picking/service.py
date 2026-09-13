from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Box, Slot, RobotTask, FulfillmentPlanItem, FulfillmentPlan, ProductionRequest, Fault, Alert
from app.core.enums import BoxStatus, SlotStatus, RobotTaskType, PlanStatus, ProductionRequestStatus, FaultType, AlertSeverity
from app.slotting.service import choose_return_slot
from app.robot.service import create_task
from app.events.service import emit
from app.core.state_machine import transition


def _mark_plan_progress(db: Session, box: Box, removed: int) -> str | None:
    item = db.scalar(select(FulfillmentPlanItem).join(FulfillmentPlan).join(ProductionRequest).where(
        FulfillmentPlanItem.box_id == box.id,
        FulfillmentPlanItem.actual_quantity_removed.is_(None),
        ProductionRequest.status == ProductionRequestStatus.EXECUTING.value,
    ).order_by(FulfillmentPlan.created_at.asc()))
    if not item:
        return None
    item.actual_quantity_removed = removed
    item.completed_at = datetime.now(timezone.utc)
    plan = db.get(FulfillmentPlan, item.plan_id)
    req = db.get(ProductionRequest, plan.request_id) if plan else None
    if removed != item.quantity_to_take:
        if plan: plan.status = PlanStatus.FAILED.value
        if req:
            req.status = ProductionRequestStatus.FAILED.value
            req.failure_reason = f'QUANTITY_MISMATCH planned={item.quantity_to_take} actual={removed}'
        f=Fault(type=FaultType.QUANTITY_MISMATCH.value,active=True,details={'box_id':box.id,'planned':item.quantity_to_take,'actual':removed})
        db.add(f); db.add(Alert(code='QUANTITY_MISMATCH',severity=AlertSeverity.CRITICAL.value,message=f'{box.code}: planned {item.quantity_to_take}, actual {removed}'))
        db.flush(); emit(db,'FAULT_RAISED','fault',f.id,{'type':'QUANTITY_MISMATCH','box_id':box.id})
        return req.id if req else None
    if plan and all(i.actual_quantity_removed is not None for i in plan.items):
        # If this is a partial box, completion is deferred until the physical
        # return task finishes. Full/empty final picks can complete immediately.
        if box.quantity == 0:
            plan.status = PlanStatus.COMPLETED.value
            if req:
                req.status = ProductionRequestStatus.COMPLETED.value
                req.completed_at = datetime.now(timezone.utc)
                emit(db,'PRODUCTION_REQUEST_COMPLETED','production_request',req.id,{})
        else:
            plan.status = PlanStatus.EXECUTING.value
            if req:
                req.status = ProductionRequestStatus.EXECUTING.value
    return req.id if req else None


def confirm_pick(db: Session, box: Box, removed: int) -> dict:
    if box.status != BoxStatus.AT_PICKING.value: raise ValueError('box is not at picking')
    if removed < 0 or removed > box.quantity: raise ValueError('invalid removed quantity')
    before = box.quantity
    box.quantity -= removed
    fallback = db.get(Slot, box.reserved_return_slot_id) if box.reserved_return_slot_id else None
    picking = db.get(Slot, box.current_slot_id) if box.current_slot_id else None
    emit(db,'QUANTITY_UPDATED','box',box.id,{'before':before,'removed':removed,'after':box.quantity})
    request_id = _mark_plan_progress(db, box, removed)
    if box.quantity == 0:
        box.status = transition(box.status,BoxStatus.EMPTY.value); box.current_slot_id=None; box.reserved_return_slot_id=None
        if picking and picking.box_id == box.id:
            picking.box_id=None; picking.status=SlotStatus.FREE.value
        if fallback:
            fallback.status=SlotStatus.FREE.value; fallback.box_id=None
        emit(db,'BOX_EMPTIED','box',box.id,{})
        db.commit(); return {'status':'EMPTY','box_id':box.id,'remaining':0}
    box.status=transition(box.status,BoxStatus.RETURN_PLANNED.value)
    target = choose_return_slot(db,box,fallback)
    if target is None:
        box.status=transition(box.status,BoxStatus.FAULTED.value)
        db.add(Alert(code='RETURN_SLOT_PROBLEM',severity=AlertSeverity.CRITICAL.value,message=f'No safe return slot for {box.code}; box remains at picking'))
        emit(db,'FAULT_RAISED','box',box.id,{'type':'RETURN_SLOT_PROBLEM'})
        db.commit()
        raise ValueError('NO_SAFE_RETURN_SLOT')
    # New target is reserved before the original fallback is released.
    if fallback is None or target.id != fallback.id:
        target.status=SlotStatus.RESERVED.value
    box.reserved_return_slot_id = target.id
    if fallback and target.id != fallback.id:
        fallback.status=SlotStatus.FREE.value; fallback.box_id=None
    box.status=transition(box.status,BoxStatus.RETURNING.value)
    task=create_task(db,RobotTaskType.RETURN_BOX.value,box,picking,target,request_id=request_id,sequence=999,priority=10)
    db.commit()
    return {'status':'RETURN_PLANNED','box_id':box.id,'remaining':box.quantity,'return_slot':target.code,'task_id':task.id}

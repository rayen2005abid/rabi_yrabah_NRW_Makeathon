from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.clock import clock
from app.core.models import ProductionRequest, FulfillmentPlan, FulfillmentPlanItem, Slot, Box, Alert
from app.core.enums import ProductionRequestStatus, PlanStatus, AlertSeverity
from app.fifo.service import eligible_boxes
from app.events.service import emit


def build_plan(db: Session, request: ProductionRequest) -> FulfillmentPlan:
    existing = db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id == request.id).order_by(FulfillmentPlan.created_at.desc()))
    if existing:
        return existing
    request.status = ProductionRequestStatus.PLANNING.value
    remaining = request.requested_quantity
    boxes = eligible_boxes(db, request.core_type_id)
    plan = FulfillmentPlan(request_id=request.id, status=PlanStatus.DRAFT.value, total_requested=request.requested_quantity, total_planned=0)
    db.add(plan); db.flush()
    for rank, box in enumerate(boxes, start=1):
        if remaining <= 0: break
        take = min(box.quantity, remaining)
        source = db.get(Slot, box.current_slot_id)
        if not source: continue
        item = FulfillmentPlanItem(plan_id=plan.id, box_id=box.id, fifo_rank=rank, quantity_before=box.quantity, quantity_to_take=take, quantity_after=box.quantity-take, source_slot=source.code, return_required=(box.quantity-take)>0)
        db.add(item)
        plan.total_planned += take
        remaining -= take
    request.planned_at = clock.now()
    request.status = ProductionRequestStatus.PENDING.value if plan.total_planned == request.requested_quantity else ProductionRequestStatus.PARTIALLY_FULFILLABLE.value
    if plan.total_planned < request.requested_quantity:
        db.add(Alert(code='REQUEST_UNFULFILLABLE',severity=AlertSeverity.WARNING.value,message=f'Request {request.id} shortage: {request.requested_quantity-plan.total_planned}'))
    emit(db, 'FULFILLMENT_PLAN_CREATED', 'production_request', request.id, {'plan_id': plan.id, 'total_planned': plan.total_planned})
    db.commit(); db.refresh(plan)
    return plan


def shortage_info(db: Session, request: ProductionRequest, plan: FulfillmentPlan) -> dict:
    from app.core.models import Box
    from app.core.enums import BoxStatus
    drying = list(db.scalars(select(Box).where(Box.core_type_id==request.core_type_id, Box.status==BoxStatus.DRYING.value, Box.quantity>0).order_by(Box.ready_at)).all())
    return {
        'requested': request.requested_quantity,
        'ready_available': plan.total_planned,
        'shortage': max(0, request.requested_quantity-plan.total_planned),
        'drying_quantity': sum(b.quantity for b in drying),
        'next_ready_at': drying[0].ready_at if drying else None,
        'next_ready_quantity': drying[0].quantity if drying else 0,
    }

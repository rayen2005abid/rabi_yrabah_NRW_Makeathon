from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Slot, Box, RobotTask, CoreType, FulfillmentPlanItem, FulfillmentPlan, ProductionRequest
from app.core.enums import RobotTaskStatus
from app.robot.runtime import robot_runtime
from app.digital_twin.runtime import live_twin


def _pick_context(db: Session, box: Box | None) -> dict | None:
    if box is None:
        return None
    item = db.scalar(
        select(FulfillmentPlanItem)
        .join(FulfillmentPlan, FulfillmentPlanItem.plan_id == FulfillmentPlan.id)
        .where(
            FulfillmentPlanItem.box_id == box.id,
            FulfillmentPlanItem.completed_at.is_(None),
            FulfillmentPlan.status.in_(['EXECUTING', 'APPROVED', 'SIMULATED']),
        )
        .order_by(FulfillmentPlanItem.fifo_rank)
    )
    if item is None:
        return {'suggested_quantity': None, 'request_id': None, 'fifo_rank': None}
    plan = db.get(FulfillmentPlan, item.plan_id)
    req = db.get(ProductionRequest, plan.request_id) if plan else None
    return {
        'suggested_quantity': item.quantity_to_take,
        'request_id': req.id if req else None,
        'fifo_rank': item.fifo_rank,
    }


def state(db: Session) -> dict:
    slots = []
    core_codes = {c.id: c.code for c in db.scalars(select(CoreType)).all()}
    for s in db.scalars(select(Slot)).all():
        box = db.get(Box, s.box_id) if s.box_id else None
        slots.append({
            'id': s.id,
            'code': s.code,
            'type': s.type,
            'status': s.status,
            'rack_face': s.rack_face,
            'rack_number': s.rack_face,
            'rack_side': (s.metadata_json or {}).get('rack_side'),
            'rack_module_index': (s.metadata_json or {}).get('rack_module_index'),
            'column': s.column,
            'level': s.level,
            'x': s.x_coordinate,
            'y': s.y_coordinate,
            'z': s.z_coordinate,
            'box': ({
                'id': box.id,
                'code': box.code,
                'core_type': core_codes.get(box.core_type_id),
                'quantity': box.quantity,
                'initial_quantity': box.initial_quantity,
                'status': box.status,
                'entered_at': box.entered_at,
                'ready_at': box.ready_at,
            } if box else None),
        })

    picking = next((x for x in slots if x['code'] == 'PICKING'), None)
    picking_box = db.get(Box, picking['box']['id']) if picking and picking.get('box') else None
    if picking is None:
        picking_state = 'FAULT'
    elif picking['status'] in {'BLOCKED', 'MAINTENANCE', 'DISABLED'}:
        picking_state = 'FAULT'
    elif picking['box'] is not None:
        picking_state = 'WAITING_CONFIRMATION'
    else:
        picking_state = 'FREE'

    queue = [{
        'id': t.id,
        'type': t.type,
        'status': t.status,
        'box_id': t.box_id,
        'request_id': t.request_id,
        'sequence_number': t.sequence_number,
        'source': t.source_location,
        'target': t.target_location,
        'planned_path': t.planned_path,
    } for t in db.scalars(
        select(RobotTask).where(RobotTask.status.in_([
            RobotTaskStatus.QUEUED.value,
            RobotTaskStatus.RUNNING.value,
            RobotTaskStatus.DISPATCHED.value,
        ])).order_by(RobotTask.priority, RobotTask.sequence_number, RobotTask.created_at)
    ).all()]

    storage = [x for x in slots if x['type'] == 'STORAGE']
    racks = sorted({x['rack_number'] for x in storage if x['rack_number'] is not None})
    geometry = {
        'rack_count': len(racks),
        'columns_per_rack': max((x['column'] or 0 for x in storage), default=0),
        'levels_per_rack': max((x['level'] or 0 for x in storage), default=0),
        'racks': [
            {
                'rack_number': r,
                'side': next((x['rack_side'] for x in storage if x['rack_number'] == r and x.get('rack_side')), None),
                'occupied': sum(1 for x in storage if x['rack_number'] == r and x['box'] is not None),
                'capacity': sum(1 for x in storage if x['rack_number'] == r),
                'x_min': min((x['x'] for x in storage if x['rack_number'] == r), default=0.0),
                'x_max': max((x['x'] for x in storage if x['rack_number'] == r), default=0.0),
            }
            for r in racks
        ],
    }

    return {
        'geometry': geometry,
        'robot': robot_runtime.as_dict(),
        'live_execution': live_twin.snapshot(),
        'picking_station': {
            'state': picking_state,
            'slot': picking,
            'pick_context': _pick_context(db, picking_box),
        },
        'slots': slots,
        'task_queue': queue,
    }

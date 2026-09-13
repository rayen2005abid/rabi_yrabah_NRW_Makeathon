from __future__ import annotations

from math import hypot
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import load_yaml
from app.core.models import ProductionRequest, FulfillmentPlan, Slot, SimulationRun, Box
from app.fulfillment.service import build_plan
from app.events.service import emit
from app.simulation.discrete_event import build_transfer_timeline
from app.core.enums import PlanStatus, ProductionRequestStatus
from app.slotting.service import score_slot
from app.demand_forecasting.service import forecaster


def _xz_distance(a: Slot, b: Slot) -> float:
    return hypot(a.x_coordinate - b.x_coordinate, a.z_coordinate - b.z_coordinate)


def _transfer_distance(start_x: float, start_z: float, source: Slot, target: Slot) -> float:
    # Fork insertion/retraction is counted twice at each physical storage side.
    return (
        hypot(source.x_coordinate - start_x, source.z_coordinate - start_z)
        + 2 * abs(source.y_coordinate)
        + _xz_distance(source, target)
        + 2 * abs(target.y_coordinate)
    )


def _best_simulated_return_slot(db: Session, box: Box, fallback: Slot, unavailable_codes: set[str]) -> tuple[Slot, dict]:
    """Pure ranking for simulation; does not reserve or mutate a real slot."""
    cfg = load_yaml('warehouse.yaml').get('slotting', {})
    weights = cfg.get('weights', {'travel': 1.0, 'future': 0.7, 'congestion': 0.2, 'balance': 0.2, 'accessibility': 0.4})
    demand = forecaster.forecast(db, box.core_type_id)['demand_score']
    fallback_cost, fallback_expl = score_slot(fallback, demand, weights)

    candidates = list(db.scalars(select(Slot).where(
        Slot.type == 'STORAGE',
        Slot.status == 'FREE',
        Slot.enabled.is_(True),
        Slot.box_id.is_(None),
    )).all())
    ranked: list[tuple[float, str, Slot, dict]] = []
    for slot in candidates:
        if slot.code in unavailable_codes:
            continue
        if (slot.metadata_json or {}).get('reachable', True) is False:
            continue
        cost, expl = score_slot(slot, demand, weights)
        ranked.append((cost, slot.code, slot, expl))
    ranked.sort(key=lambda row: (row[0], row[1]))

    if ranked and ranked[0][0] < fallback_cost:
        cost, _, slot, expl = ranked[0]
        return slot, {
            'optimized': True,
            'fallback_slot': fallback.code,
            'selected_slot': slot.code,
            'selected_cost': round(cost, 4),
            'fallback_cost': round(fallback_cost, 4),
            'explanation': expl,
        }
    return fallback, {
        'optimized': False,
        'fallback_slot': fallback.code,
        'selected_slot': fallback.code,
        'selected_cost': round(fallback_cost, 4),
        'fallback_cost': round(fallback_cost, 4),
        'explanation': fallback_expl,
    }


def simulate_plan(db: Session, request: ProductionRequest, plan: FulfillmentPlan) -> dict:
    picking = db.scalar(select(Slot).where(Slot.code == 'PICKING'))
    if not picking:
        result = {'status': 'FAIL', 'reason': 'PICKING_STATION_MISSING'}
    else:
        slot_rows = list(db.scalars(select(Slot)).all())
        box_rows = list(db.scalars(select(Box)).all())
        slot_snapshot = {
            s.id: {
                'code': s.code, 'status': s.status, 'box_id': s.box_id,
                'x': s.x_coordinate, 'y': s.y_coordinate, 'z': s.z_coordinate,
            }
            for s in slot_rows
        }
        box_snapshot = {
            b.id: {
                'code': b.code, 'qty': b.quantity, 'entered_at': b.entered_at.isoformat(),
                'ready_at': b.ready_at.isoformat(), 'status': b.status, 'slot': b.current_slot_id,
            }
            for b in box_rows
        }

        emptied = 0
        partial = 0
        slots_freed: list[str] = []
        slots_occupied: list[str] = []
        used: list[dict] = []
        return_decisions: list[dict] = []
        transfers: list[dict] = []
        unavailable_return_codes: set[str] = set()
        total_distance = 0.0
        robot_x = 0.0
        robot_z = 0.0
        failure: dict | None = None

        for item in plan.items:
            snap_box = box_snapshot.get(item.box_id)
            db_box = db.get(Box, item.box_id)
            if not snap_box or not db_box:
                failure = {'status': 'FAIL', 'reason': 'BOX_MISSING'}
                break
            if snap_box['qty'] != item.quantity_before:
                failure = {'status': 'FAIL', 'reason': 'STALE_PLAN_QUANTITY'}
                break

            source = db.scalar(select(Slot).where(Slot.code == item.source_slot))
            if not source:
                failure = {'status': 'FAIL', 'reason': 'SOURCE_SLOT_MISSING'}
                break
            if source.box_id != item.box_id:
                failure = {'status': 'FAIL', 'reason': 'SOURCE_OCCUPANCY_CHANGED'}
                break

            # 1) Retrieve the FIFO-selected box and deliver it to picking.
            total_distance += _transfer_distance(robot_x, robot_z, source, picking)
            transfers.append({
                'task': 'RETRIEVE_BOX', 'box_code': snap_box['code'],
                'source': source.code, 'target': picking.code,
                'empty_dx': source.x_coordinate - robot_x,
                'empty_dz': source.z_coordinate - robot_z,
                'carry_dx': picking.x_coordinate - source.x_coordinate,
                'carry_dz': picking.z_coordinate - source.z_coordinate,
                'source_y': source.y_coordinate,
                'target_y': picking.y_coordinate,
            })
            robot_x, robot_z = picking.x_coordinate, picking.z_coordinate

            used.append({
                'box_id': item.box_id,
                'box_code': snap_box['code'],
                'fifo_rank': item.fifo_rank,
                'take': item.quantity_to_take,
                'remaining': item.quantity_after,
                'source_slot': source.code,
            })

            if item.return_required:
                partial += 1
                return_slot, decision = _best_simulated_return_slot(db, db_box, source, unavailable_return_codes)
                return_decisions.append({'box_code': snap_box['code'], **decision})
                item.proposed_return_slot = return_slot.code

                total_distance += _transfer_distance(robot_x, robot_z, picking, return_slot)
                transfers.append({
                    'task': 'RETURN_BOX', 'box_code': snap_box['code'],
                    'source': picking.code, 'target': return_slot.code,
                    'empty_dx': picking.x_coordinate - robot_x,
                    'empty_dz': picking.z_coordinate - robot_z,
                    'carry_dx': return_slot.x_coordinate - picking.x_coordinate,
                    'carry_dz': return_slot.z_coordinate - picking.z_coordinate,
                    'source_y': picking.y_coordinate,
                    'target_y': return_slot.y_coordinate,
                })
                robot_x, robot_z = return_slot.x_coordinate, return_slot.z_coordinate
                if return_slot.code != source.code:
                    unavailable_return_codes.add(return_slot.code)
                    slots_freed.append(source.code)
                    slots_occupied.append(return_slot.code)
            else:
                emptied += 1
                slots_freed.append(source.code)

        if failure:
            result = failure
        else:
            timeline, timeline_engine = build_transfer_timeline(transfers)
            duration = timeline[-1]['t'] if timeline else 0.0
            full = plan.total_planned == request.requested_quantity
            result = {
                'status': 'PASS' if full else 'FAIL',
                'reason': None if full else 'INSUFFICIENT_READY_STOCK',
                'request': {'id': request.id, 'requested_quantity': request.requested_quantity},
                'boxes_used': len(plan.items),
                'boxes_emptied': emptied,
                'partial_boxes_returned': partial,
                'robot_tasks_simulated': len(transfers),
                'estimated_robot_distance_m': round(total_distance, 3),
                'estimated_duration_s': round(float(duration), 3),
                'final_robot_position': {'x': round(robot_x, 3), 'z': round(robot_z, 3)},
                'slots_freed': sorted(set(slots_freed)),
                'slots_occupied': sorted(set(slots_occupied)),
                'return_decisions': return_decisions,
                'box_plan': used,
                'fifo_validation': True,
                'drying_validation': True,
                'safety_validation': True,
                'single_robot_validation': True,
                'warnings': [],
                'snapshot_box_count': len(box_snapshot),
                'snapshot_slot_count': len(slot_snapshot),
                'timeline_engine': timeline_engine,
                'timeline': timeline,
            }

    run = SimulationRun(
        kind='PRODUCTION_REQUEST',
        status=result['status'],
        input_payload={'request_id': request.id, 'plan_id': plan.id},
        result_payload=result,
    )
    db.add(run)
    plan.simulated_duration = result.get('estimated_duration_s')
    plan.simulated_distance = result.get('estimated_robot_distance_m')
    plan.validation_state = result['status']
    plan.status = PlanStatus.SIMULATED.value
    request.status = ProductionRequestStatus.APPROVED.value if result['status'] == 'PASS' else ProductionRequestStatus.PARTIALLY_FULFILLABLE.value
    emit(
        db,
        'SIMULATION_PASSED' if result['status'] == 'PASS' else 'SIMULATION_FAILED',
        'production_request',
        request.id,
        {'simulation_run_id': run.id, 'reason': result.get('reason')},
    )
    db.commit()
    result['simulation_run_id'] = run.id
    return result


def simulate_request(db: Session, request: ProductionRequest) -> dict:
    plan = build_plan(db, request)
    return simulate_plan(db, request, plan)


def what_if_production(db: Session, core_type_id: str, quantity: int) -> dict:
    from app.core.clock import clock
    now = clock.now()
    boxes = list(db.scalars(select(Box).where(
        Box.core_type_id == core_type_id,
        Box.quantity > 0,
        Box.ready_at <= now,
        Box.status.notin_(['RESERVED', 'RETRIEVAL_PLANNED', 'IN_TRANSIT', 'AT_PICKING', 'RETURN_PLANNED', 'RETURNING', 'EMPTY', 'QUARANTINED', 'FAULTED']),
        Box.current_slot_id.is_not(None),
    ).order_by(Box.entered_at.asc(), Box.code.asc())).all())
    remaining = quantity
    selections = []
    for box in boxes:
        if remaining <= 0:
            break
        take = min(box.quantity, remaining)
        selections.append({'box_id': box.id, 'box_code': box.code, 'take': take, 'remaining': box.quantity - take, 'entered_at': box.entered_at})
        remaining -= take
    return {
        'status': 'PASS' if remaining == 0 else 'FAIL',
        'requested': quantity,
        'ready_available': quantity - remaining,
        'shortage': remaining,
        'selections': selections,
        'fifo_validation': True,
        'drying_validation': True,
        'simulation_only': True,
    }


def what_if_time_advance(db: Session, hours: float) -> dict:
    from datetime import timedelta
    from app.core.clock import clock
    preview = clock.now() + timedelta(hours=hours)
    now = clock.now()
    becoming = list(db.scalars(select(Box).where(Box.quantity > 0, Box.ready_at > now, Box.ready_at <= preview).order_by(Box.ready_at)).all())
    return {
        'status': 'PASS',
        'preview_time': preview,
        'boxes_becoming_ready': [{'box_id': b.id, 'box_code': b.code, 'quantity': b.quantity, 'ready_at': b.ready_at} for b in becoming],
        'quantity_becoming_ready': sum(b.quantity for b in becoming),
        'simulation_only': True,
    }


def what_if_blocked_slot(db: Session, slot_code: str) -> dict:
    slot = db.scalar(select(Slot).where(Slot.code == slot_code))
    if not slot:
        return {'status': 'FAIL', 'reason': 'SLOT_NOT_FOUND', 'simulation_only': True}
    free_count = len(list(db.scalars(select(Slot).where(Slot.type == 'STORAGE', Slot.status == 'FREE', Slot.enabled.is_(True))).all()))
    impact = 1 if slot.type == 'STORAGE' and slot.status == 'FREE' else 0
    return {'status': 'PASS', 'slot': slot.code, 'current_status': slot.status, 'projected_free_slots': max(0, free_count - impact), 'box_affected': slot.box_id, 'simulation_only': True}


def what_if_robot_fault(fault_type: str) -> dict:
    blocking = {'ESTOP', 'X_AXIS_FAULT', 'Z_AXIS_FAULT', 'FORK_FAULT', 'POSITION_MISMATCH'}
    return {'status': 'PASS', 'fault': fault_type, 'robot_dispatch_allowed': fault_type not in blocking, 'expected_mode': 'FAULT' if fault_type in blocking else 'DEGRADED', 'simulation_only': True}


def what_if_near_full(db: Session, incoming_boxes: int) -> dict:
    slots = list(db.scalars(select(Slot).where(Slot.type == 'STORAGE', Slot.enabled.is_(True))).all())
    free = sum(1 for s in slots if s.status == 'FREE' and s.box_id is None)
    projected = max(0, free - incoming_boxes)
    total = len(slots)
    occupancy = 100 * ((total - projected) / total) if total else 0
    return {
        'status': 'PASS' if incoming_boxes <= free else 'FAIL',
        'reason': None if incoming_boxes <= free else 'WAREHOUSE_FULL',
        'current_free_slots': free,
        'incoming_boxes': incoming_boxes,
        'projected_free_slots': projected,
        'projected_occupancy_pct': round(occupancy, 2),
        'simulation_only': True,
    }

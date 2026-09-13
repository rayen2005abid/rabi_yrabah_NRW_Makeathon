from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import hypot
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    Box,
    CoreType,
    FulfillmentPlan,
    FulfillmentPlanItem,
    ProductionRequest,
    RobotTask,
    Slot,
)
from app.core.enums import RobotTaskType
from app.slotting.service import ranked_candidates, score_slot
from app.core.config import load_yaml
from app.demand_forecasting.service import forecaster


# ---------------------------------------------------------------------------
# Passage graph
# ---------------------------------------------------------------------------
# The Digital Twin uses an explicit top-down passage graph inspired by the
# physical 6 m x 6 m sketch: a left/main spine feeds four horizontal rack
# passages. Storage remains 8 columns x 8 levels per rack; the passage graph
# represents floor routing while X/Z/Y telemetry represents the stacker motion.

RACK_Y = {1: 0.18, 2: 0.38, 3: 0.58, 4: 0.78}
TRANSFER_POINT = (0.08, 0.08)
SPINE_X = 0.18
RACK_ENTRY_X = 0.28
RACK_END_X = 0.92


@dataclass(frozen=True)
class GraphNode:
    id: str
    x: float
    y: float
    label: str
    kind: str


def _graph_for_geometry(columns: int = 8, rack_count: int = 4) -> tuple[dict[str, GraphNode], dict[str, list[tuple[str, float]]]]:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, list[tuple[str, float]]] = {}

    def add(node: GraphNode) -> None:
        nodes[node.id] = node
        edges.setdefault(node.id, [])

    def link(a: str, b: str) -> None:
        na, nb = nodes[a], nodes[b]
        d = hypot(nb.x - na.x, nb.y - na.y)
        edges[a].append((b, d))
        edges[b].append((a, d))

    add(GraphNode('TRANSFER', *TRANSFER_POINT, 'Transfer zone', 'TRANSFER'))

    previous_spine = 'TRANSFER'
    for rack in range(1, rack_count + 1):
        ry = RACK_Y.get(rack, 0.18 + (rack - 1) * 0.20)
        spine_id = f'SPINE_R{rack}'
        entry_id = f'R{rack}_ENTRY'
        add(GraphNode(spine_id, SPINE_X, ry, f'Main passage · Rack {rack}', 'PASSAGE'))
        add(GraphNode(entry_id, RACK_ENTRY_X, ry, f'Rack {rack} aisle entry', 'TURN'))
        link(previous_spine, spine_id)
        link(spine_id, entry_id)
        previous = entry_id
        for col in range(1, columns + 1):
            x = RACK_ENTRY_X + (RACK_END_X - RACK_ENTRY_X) * (col / columns)
            cid = f'R{rack}_C{col:02d}'
            add(GraphNode(cid, x, ry, f'Rack {rack} · Column {col}', 'RACK_ACCESS'))
            link(previous, cid)
            previous = cid
        previous_spine = spine_id

    return nodes, edges


def _node_for_slot(slot: Slot | None) -> str:
    if slot is None or slot.type != 'STORAGE' or not slot.rack_face or not slot.column:
        return 'TRANSFER'
    return f'R{int(slot.rack_face)}_C{int(slot.column):02d}'


def _astar(start: str, goal: str, nodes: dict[str, GraphNode], edges: dict[str, list[tuple[str, float]]]) -> tuple[list[str], float]:
    if start == goal:
        return [start], 0.0
    frontier: list[tuple[float, str]] = []
    heappush(frontier, (0.0, start))
    came_from: dict[str, str | None] = {start: None}
    cost: dict[str, float] = {start: 0.0}

    while frontier:
        _, current = heappop(frontier)
        if current == goal:
            break
        for nxt, step_cost in edges.get(current, []):
            new_cost = cost[current] + step_cost
            if nxt not in cost or new_cost < cost[nxt]:
                cost[nxt] = new_cost
                h = hypot(nodes[goal].x - nodes[nxt].x, nodes[goal].y - nodes[nxt].y)
                heappush(frontier, (new_cost + h, nxt))
                came_from[nxt] = current

    if goal not in came_from:
        return [start], float('inf')
    path = []
    cur: str | None = goal
    while cur is not None:
        path.append(cur)
        cur = came_from[cur]
    path.reverse()
    return path, cost[goal]


def passage_route(source: Slot | None, target: Slot | None, columns: int = 8, rack_count: int = 4) -> dict:
    nodes, edges = _graph_for_geometry(columns, rack_count)
    start = _node_for_slot(source)
    goal = _node_for_slot(target)
    path_ids, distance = _astar(start, goal, nodes, edges)
    route = [
        {
            'node_id': nid,
            'x': round(nodes[nid].x, 4),
            'y': round(nodes[nid].y, 4),
            'label': nodes[nid].label,
            'kind': nodes[nid].kind,
        }
        for nid in path_ids
    ]
    return {
        'algorithm': 'A*',
        'start_node': start,
        'goal_node': goal,
        'distance_units': round(distance, 4),
        'nodes': route,
        'passage_clear': True,
    }


def route_distance(source: Slot | None, target: Slot | None) -> float:
    return float(passage_route(source, target)['distance_units'])


# ---------------------------------------------------------------------------
# Explainable decisions
# ---------------------------------------------------------------------------

def _slot_payload(slot: Slot, score: float | None = None, explanation: dict | None = None, selected: bool = False) -> dict:
    return {
        'slot_code': slot.code,
        'rack': slot.rack_face,
        'column': slot.column,
        'level': slot.level,
        'selected': selected,
        'score': round(float(score), 3) if score is not None else None,
        'factors': explanation or {},
    }


def destination_candidates(db: Session, box: Box, selected_target: Slot | None = None, origin: Slot | None = None, limit: int = 8) -> list[dict]:
    """Return explainable destination candidates, lower raw cost = better.

    The display score is normalized to 0-100 where the best candidate is 100.
    Passage distance is included as an explicit factor so the admin can see how
    route efficiency affects the recommendation.
    """
    ranked = ranked_candidates(db, box, limit=max(limit * 2, 12))
    rows: list[tuple[Slot, float, dict]] = []
    for row in ranked:
        slot = row['slot']
        factors = dict(row['explanation'])
        p_dist = route_distance(origin, slot) if origin else route_distance(None, slot)
        raw = float(row['cost']) + p_dist * 0.55
        factors['passage_distance'] = round(p_dist, 4)
        factors['weighted_total_cost'] = round(raw, 4)
        rows.append((slot, raw, factors))

    if selected_target and all(s.id != selected_target.id for s, _, _ in rows):
        cfg = load_yaml('warehouse.yaml').get('slotting', {})
        weights = cfg.get('weights', {'travel': 1.0, 'future': 0.7, 'congestion': 0.2, 'balance': 0.2, 'accessibility': 0.4})
        demand = forecaster.forecast(db, box.core_type_id)['demand_score']
        raw_base, factors = score_slot(selected_target, demand, weights)
        p_dist = route_distance(origin, selected_target) if origin else route_distance(None, selected_target)
        factors = dict(factors)
        raw = float(raw_base) + p_dist * 0.55
        factors['passage_distance'] = round(p_dist, 4)
        factors['weighted_total_cost'] = round(raw, 4)
        rows.append((selected_target, raw, factors))

    rows.sort(key=lambda x: (x[1], x[0].code))
    rows = rows[:limit]
    if not rows:
        return []
    best, worst = rows[0][1], max(r[1] for r in rows)
    spread = max(0.0001, worst - best)
    result = []
    for slot, raw, factors in rows:
        normalized = 100.0 if len(rows) == 1 else 100.0 - ((raw - best) / spread) * 35.0
        result.append({
            **_slot_payload(slot, normalized, factors, selected=bool(selected_target and slot.id == selected_target.id)),
            'rank': len(result) + 1,
            'raw_cost': round(raw, 4),
        })
    return result


def _fifo_candidate_payload(db: Session, task: RobotTask) -> list[dict]:
    if not task.request_id:
        return []
    plan = db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id == task.request_id).order_by(FulfillmentPlan.created_at.desc()))
    if not plan:
        return []
    rows = []
    for item in plan.items:
        box = db.get(Box, item.box_id)
        rows.append({
            'box_code': box.code if box else item.box_id[:8],
            'source_slot': item.source_slot,
            'fifo_rank': item.fifo_rank,
            'quantity_to_take': item.quantity_to_take,
            'selected_for_task': item.box_id == task.box_id,
            'reason': 'Oldest eligible READY box first' if item.box_id == task.box_id else 'Next FIFO candidate for this order',
        })
    return rows


def decision_for_task(db: Session, task: RobotTask | None) -> dict | None:
    if task is None:
        return None
    source = db.scalar(select(Slot).where(Slot.code == task.source_location)) if task.source_location else None
    target = db.scalar(select(Slot).where(Slot.code == task.target_location)) if task.target_location else None
    box = db.get(Box, task.box_id) if task.box_id else None
    approach_route = passage_route(None, source)
    route = passage_route(source, target)

    reasons: list[dict] = []
    candidates: list[dict] = []
    decision_type = 'ROUTE_SELECTION'
    confidence = 0.92

    if task.type == RobotTaskType.RETRIEVE_BOX.value:
        decision_type = 'FIFO_RETRIEVAL'
        item = None
        if task.request_id and task.box_id:
            plan = db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id == task.request_id).order_by(FulfillmentPlan.created_at.desc()))
            if plan:
                item = next((i for i in plan.items if i.box_id == task.box_id), None)
        reasons.extend([
            {'label': 'FIFO priority', 'value': f"Rank #{item.fifo_rank}" if item else 'Selected by FIFO plan', 'weight': 40},
            {'label': 'Drying eligibility', 'value': '24h rule passed before planning', 'weight': 25},
            {'label': 'Physical availability', 'value': source.code if source else 'Source available', 'weight': 20},
            {'label': 'Passage route', 'value': f"A* · {route['distance_units']} route units", 'weight': 15},
        ])
        candidates = _fifo_candidate_payload(db, task)
    elif task.type in {RobotTaskType.RETURN_BOX.value, RobotTaskType.STORE_BOX.value} and box:
        decision_type = 'INTELLIGENT_SLOT_SELECTION'
        candidates = destination_candidates(db, box, selected_target=target, origin=source, limit=8)
        selected = next((c for c in candidates if c['selected']), candidates[0] if candidates else None)
        reasons.extend([
            {'label': 'Travel efficiency', 'value': 'Minimizes route + rack travel cost', 'weight': 30},
            {'label': 'Future retrieval', 'value': 'Demand-weighted future access cost', 'weight': 25},
            {'label': 'Accessibility', 'value': 'Reachable enabled slot', 'weight': 20},
            {'label': 'Warehouse balance', 'value': 'Avoids over-concentrating one rack zone', 'weight': 15},
            {'label': 'Passage route', 'value': f"A* · {route['distance_units']} route units", 'weight': 10},
        ])
        if selected:
            confidence = min(0.99, max(0.70, selected['score'] / 100.0))
    elif task.type == RobotTaskType.RECOVERY.value:
        decision_type = 'ADMIN_NAVIGATION'
        reasons.extend([
            {'label': 'Command source', 'value': 'Admin Panel', 'weight': 100},
            {'label': 'Passage route', 'value': f"A* · {route['distance_units']} route units", 'weight': 0},
        ])
        confidence = 1.0
    else:
        reasons.extend([
            {'label': 'Safety', 'value': 'Source and target validated before dispatch', 'weight': 50},
            {'label': 'Passage route', 'value': f"A* · {route['distance_units']} route units", 'weight': 50},
        ])

    return {
        'task_id': task.id,
        'request_id': task.request_id,
        'task_type': task.type,
        'decision_type': decision_type,
        'chosen_source': task.source_location,
        'chosen_target': task.target_location,
        'box_id': task.box_id,
        'box_code': box.code if box else None,
        'confidence': round(confidence, 3),
        'reasons': reasons,
        'candidates': candidates,
        'approach_route': approach_route,
        'route': route,
        'status': task.status,
    }


def request_execution_trace(db: Session, request_id: str) -> dict:
    request = db.get(ProductionRequest, request_id)
    if not request:
        raise ValueError('request not found')
    core = db.get(CoreType, request.core_type_id)
    tasks = list(db.scalars(select(RobotTask).where(RobotTask.request_id == request_id).order_by(RobotTask.sequence_number, RobotTask.created_at)).all())
    return {
        'request': {
            'id': request.id,
            'core_type': core.code if core else request.core_type_id,
            'requested_quantity': request.requested_quantity,
            'status': request.status,
            'created_at': request.created_at,
            'completed_at': request.completed_at,
        },
        'tasks': [decision_for_task(db, task) for task in tasks],
        'completed_tasks': sum(1 for task in tasks if task.status == 'COMPLETED'),
        'total_tasks': len(tasks),
    }


def manual_route_from_robot(target: Slot, robot_x: float = 0.0, robot_z: float = 0.0) -> list[dict]:
    """Semantic movement path for an admin navigation command.

    Inventory is untouched; the mock embedded adapter simply ACKs the target
    position when this RECOVERY task completes.
    """
    return [
        {'action': 'RETRACT_Y', 'target': 0.0, 'label': 'Retract fork before travel'},
        {'action': 'NAVIGATE_PASSAGE', 'route': passage_route(None, target)['nodes'], 'label': 'Follow A* passage route'},
        {'action': 'MOVE_XZ', 'x': target.x_coordinate, 'z': target.z_coordinate, 'label': 'Align with destination'},
    ]

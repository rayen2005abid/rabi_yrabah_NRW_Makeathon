from __future__ import annotations

from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo.seed import seed_session, demo_summary
from app.catalog.service import get_by_code
from app.core.models import ProductionRequest, Slot
from app.core.enums import ProductionRequestStatus
from app.events.service import emit
from app.fulfillment.service import build_plan
from app.simulation.service import simulate_request
from app.robot.service import queue_for_plan
from app.intake.service import register_box
from app.autonomy.runtime import autonomy


SCENARIOS = [
    {
        'id': 'single_fifo',
        'title': 'Single production order',
        'subtitle': 'CORE-A × 55',
        'description': 'One complete FIFO order: three retrievals plus the partial-box intelligent return.',
        'kind': 'PRODUCTION',
    },
    {
        'id': 'multi_order_rush',
        'title': 'Multiple orders',
        'subtitle': '3 production requests',
        'description': 'Queues three independent customer orders so you can watch the robot schedule and execute them one after another.',
        'kind': 'MULTI_ORDER',
    },
    {
        'id': 'new_package',
        'title': 'New package arrival',
        'subtitle': 'ENTRY → intelligent rack slot',
        'description': 'Registers a new package at ENTRY. The slotting engine chooses a storage position and the robot carries it through the transfer lane into the rack.',
        'kind': 'INBOUND',
    },
    {
        'id': 'multiple_inbound',
        'title': 'Multiple package arrivals',
        'subtitle': '3 sequential incoming boxes',
        'description': 'Feeds three new packages through the single ENTRY station. The scenario waits for ENTRY to clear before registering the next package.',
        'kind': 'MULTI_INBOUND',
    },
    {
        'id': 'mixed_flow',
        'title': 'Inbound + production',
        'subtitle': 'Two different workflows together',
        'description': 'A new package arrives while a production order is waiting. Task priorities decide which physical movement happens first.',
        'kind': 'MIXED',
    },
    {
        'id': 'partial_return',
        'title': 'Partial pick + smart return',
        'subtitle': 'CORE-A × 55',
        'description': 'Highlights the third box being partially consumed, then returned to the storage slot selected by the intelligent scoring engine.',
        'kind': 'RETURN',
    },
    {
        'id': 'shortage',
        'title': 'Insufficient ready stock',
        'subtitle': 'Drying rule blocks stock',
        'description': 'Creates an order that cannot be fully fulfilled because some boxes are still drying. No unsafe execution is queued.',
        'kind': 'EDGE_CASE',
    },
]



@dataclass
class ScenarioRuntime:
    active_scenario_id: str | None = None
    pending_inbound: list[dict] = field(default_factory=list)
    launched_inbound: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.active_scenario_id = None
        self.pending_inbound = []
        self.launched_inbound = []

    def snapshot(self) -> dict:
        return {
            'active_scenario_id': self.active_scenario_id,
            'pending_inbound': list(self.pending_inbound),
            'launched_inbound': list(self.launched_inbound),
        }


scenario_runtime = ScenarioRuntime()


def advance_scenario(db: Session) -> dict | None:
    """Advance deferred scenario actions without bypassing real intake rules.

    Multiple incoming packages share one physical ENTRY station.  Instead of
    cheating and placing several boxes at ENTRY simultaneously, the scenario
    waits for the previous STORE_BOX task to physically clear ENTRY, then uses
    the normal intake service for the next package.
    """
    if not scenario_runtime.pending_inbound:
        return None
    entry = db.scalar(select(Slot).where(Slot.code == 'ENTRY'))
    if not entry or entry.box_id is not None or entry.status != 'FREE':
        return None
    spec = scenario_runtime.pending_inbound.pop(0)
    box = register_box(db, **spec)
    scenario_runtime.launched_inbound.append(box.code)
    return {'status': 'INBOUND_RELEASED', 'box_code': box.code, 'remaining': len(scenario_runtime.pending_inbound)}

def list_scenarios() -> list[dict]:
    return SCENARIOS


def _new_request(db: Session, core_code: str, quantity: int, priority: int = 50) -> tuple[ProductionRequest, dict, dict]:
    core = get_by_code(db, core_code)
    if not core:
        raise ValueError(f'unknown core type {core_code}')
    req = ProductionRequest(
        core_type_id=core.id,
        requested_quantity=quantity,
        status=ProductionRequestStatus.PENDING.value,
        priority=priority,
    )
    db.add(req)
    db.flush()
    emit(db, 'PRODUCTION_REQUEST_CREATED', 'production_request', req.id, {
        'quantity': quantity,
        'core_type': core.code,
        'scenario': True,
    })
    db.commit()
    plan = build_plan(db, req)
    sim = simulate_request(db, req)
    if sim.get('status') == 'PASS':
        queue_for_plan(db, plan)
    return req, {
        'plan_id': plan.id,
        'total_requested': plan.total_requested,
        'total_planned': plan.total_planned,
        'validation_state': plan.validation_state,
    }, sim


def run_scenario(db: Session, scenario_id: str) -> dict:
    if scenario_id not in {x['id'] for x in SCENARIOS}:
        raise ValueError('unknown scenario')

    # Every scenario starts from the exact same deterministic warehouse state.
    summary = seed_session(db, reset=True)
    autonomy.set_mode('AUTO')
    scenario_runtime.reset()
    scenario_runtime.active_scenario_id = scenario_id

    result: dict = {
        'scenario_id': scenario_id,
        'status': 'READY',
        'seed': summary,
        'orders': [],
        'inbound_boxes': [],
        'notes': [],
    }

    if scenario_id in {'single_fifo', 'partial_return'}:
        req, plan, sim = _new_request(db, 'CORE-A', 55, priority=30)
        result['orders'].append({'id': req.id, 'core_type': 'CORE-A', 'quantity': 55, 'plan': plan, 'simulation': sim})
        result['notes'].append('Expected FIFO: A01=10, A02=30, A03=15; A03 remainder returns to an intelligently ranked slot.')

    elif scenario_id == 'multi_order_rush':
        # Different core types avoid stale-plan overlap while still exercising the
        # real single-robot scheduler and queue priority ordering.
        for core, qty, priority in [
            ('CORE-A', 25, 20),
            ('CORE-B', 20, 30),
            ('CORE-C', 35, 40),
        ]:
            req, plan, sim = _new_request(db, core, qty, priority=priority)
            result['orders'].append({'id': req.id, 'core_type': core, 'quantity': qty, 'priority': priority, 'plan': plan, 'simulation': sim})
        result['notes'].append('Three real production orders are queued. The single robot executes lower priority-number work first.')

    elif scenario_id == 'new_package':
        box = register_box(db, core_type_code='CORE-D', quantity=24, box_code='NEW-D-24', vision_confidence=0.99)
        result['inbound_boxes'].append({'id': box.id, 'code': box.code, 'core_type': 'CORE-D', 'quantity': box.quantity})
        result['notes'].append('The package physically starts at ENTRY. Its selected rack slot is only reserved until the robot delivers it.')


    elif scenario_id == 'multiple_inbound':
        first = register_box(db, core_type_code='CORE-B', quantity=16, box_code='IN-B-16', vision_confidence=0.99)
        result['inbound_boxes'].append({'id': first.id, 'code': first.code, 'core_type': 'CORE-B', 'quantity': first.quantity})
        scenario_runtime.launched_inbound.append(first.code)
        scenario_runtime.pending_inbound = [
            {'core_type_code': 'CORE-C', 'quantity': 22, 'box_code': 'IN-C-22', 'vision_confidence': 0.99},
            {'core_type_code': 'CORE-E', 'quantity': 14, 'box_code': 'IN-E-14', 'vision_confidence': 0.99},
        ]
        result['notes'].append('Only one package can occupy ENTRY. The next packages are released automatically after the previous package reaches storage.')
        result['scenario_runtime'] = scenario_runtime.snapshot()

    elif scenario_id == 'mixed_flow':
        box = register_box(db, core_type_code='CORE-E', quantity=18, box_code='NEW-E-18', vision_confidence=0.99)
        result['inbound_boxes'].append({'id': box.id, 'code': box.code, 'core_type': 'CORE-E', 'quantity': box.quantity})
        req, plan, sim = _new_request(db, 'CORE-A', 25, priority=20)
        result['orders'].append({'id': req.id, 'core_type': 'CORE-A', 'quantity': 25, 'priority': 20, 'plan': plan, 'simulation': sim})
        result['notes'].append('Production has priority 20; incoming storage uses its configured priority. Watch the scheduler choose the next task.')

    elif scenario_id == 'shortage':
        req, plan, sim = _new_request(db, 'CORE-D', 50, priority=30)
        result['orders'].append({'id': req.id, 'core_type': 'CORE-D', 'quantity': 50, 'plan': plan, 'simulation': sim})
        result['status'] = 'SIMULATION_ONLY' if sim.get('status') != 'PASS' else 'READY'
        result['notes'].append('Only eligible READY boxes may be used. Drying stock is protected even when the request cannot be fully satisfied.')

    result['warehouse'] = demo_summary(db)
    result['scenario_runtime'] = scenario_runtime.snapshot()
    return result

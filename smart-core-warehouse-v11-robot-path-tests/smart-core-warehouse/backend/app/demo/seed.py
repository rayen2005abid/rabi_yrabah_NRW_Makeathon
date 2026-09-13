from __future__ import annotations

from datetime import timedelta
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.db import Base, engine, SessionLocal
from app.core.clock import clock, ClockMode
from app.core.models import CoreType, Box, Slot, ProductionRequest, RobotTask, DomainEvent
from app.core.enums import BoxStatus, ProductionRequestStatus, RobotTaskStatus
from app.warehouse.service import generate_slots, occupy_slot
from app.drying.service import ready_at_for
from app.robot.runtime import robot_runtime
from app.digital_twin.runtime import live_twin

CORE_TYPES = ['CORE-A', 'CORE-B', 'CORE-C', 'CORE-D', 'CORE-E']


def _reset_runtime_state() -> None:
    """Reset in-memory demo state that is intentionally not persisted."""
    live_twin.cancel()
    robot_runtime.x = 0.0
    robot_runtime.y = 0.0
    robot_runtime.z = 0.0
    robot_runtime.mode = 'HOME'
    robot_runtime.carrying_box = False
    robot_runtime.current_task_id = None
    robot_runtime.fault = None
    robot_runtime.estop = False
    clock.set_mode(ClockMode.REAL_TIME)


def seed_session(db: Session, reset: bool = True) -> dict:
    """Seed a deterministic, competition-ready warehouse demo dataset.

    The exact FIFO acceptance scenario is included as A01/A02/A03/A04.
    This function can be called by CLI, startup auto-seed, and the Demo UI reset.
    """
    Base.metadata.create_all(engine)
    _reset_runtime_state()

    if reset:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()

    # If data already exists and this is a non-destructive startup seed, leave it intact.
    if not reset and db.scalar(select(func.count(CoreType.id))) > 0:
        return demo_summary(db)

    generate_slots(db, force=False)

    cores: dict[str, CoreType] = {}
    for code in CORE_TYPES:
        existing = db.scalar(select(CoreType).where(CoreType.code == code))
        if existing:
            cores[code] = existing
            continue
        core = CoreType(
            code=code,
            name=code.replace('-', ' '),
            description=f'Demo foundry core {code}',
            active=True,
        )
        db.add(core)
        db.flush()
        cores[code] = core

    now = clock.now()
    # Meaningful mix: exact FIFO test, ready stock, drying stock and partial boxes.
    specs = [
        ('A01', 'CORE-A', 10, 10, 35),
        ('A02', 'CORE-A', 30, 30, 30),
        ('A03', 'CORE-A', 40, 40, 27),
        ('A04', 'CORE-A', 50, 50, 17),
        ('A17', 'CORE-A', 10, 30, 25),  # already partial, ready, and younger than A03 so FIFO acceptance test stays deterministic
        ('B01', 'CORE-B', 25, 25, 40),
        ('B02', 'CORE-B', 45, 45, 12),
        ('B03', 'CORE-B', 18, 30, 55),
        ('C01', 'CORE-C', 60, 60, 50),
        ('C02', 'CORE-C', 20, 20, 26),
        ('C03', 'CORE-C', 35, 35, 6),
        ('D01', 'CORE-D', 35, 35, 8),
        ('D02', 'CORE-D', 22, 22, 31),
        ('E01', 'CORE-E', 70, 70, 72),
        ('E02', 'CORE-E', 15, 15, 29),
        ('E03', 'CORE-E', 28, 28, 4),
    ]

    free_all = list(
        db.scalars(
            select(Slot)
            .where(Slot.type == 'STORAGE', Slot.status == 'FREE')
            .order_by(Slot.rack_face, Slot.column, Slot.level)
        ).all()
    )
    if len(free_all) < len(specs):
        raise RuntimeError('Configured warehouse does not contain enough free storage slots for demo seed')

    # Spread the seeded stock across all four racks so the Digital Twin is useful
    # immediately. The pattern is deterministic and keeps the exact FIFO ages intact.
    preferred_positions = [(1,1), (3,2), (5,3), (7,4), (2,6), (4,7), (6,8), (8,5)]
    by_rack = {r: [s for s in free_all if s.rack_face == r] for r in range(1, 5)}
    free = []
    for i in range(len(specs)):
        rack = (i % 4) + 1
        col, level = preferred_positions[(i // 4) % len(preferred_positions)]
        candidate = next((s for s in by_rack.get(rack, []) if s.column == col and s.level == level and s not in free), None)
        if candidate is None:
            candidate = next(s for s in by_rack.get(rack, []) if s not in free)
        free.append(candidate)

    for i, (code, core_code, qty, initial_qty, age_h) in enumerate(specs):
        entered = now - timedelta(hours=age_h)
        ready = ready_at_for(entered)
        status = BoxStatus.READY.value if now >= ready else BoxStatus.DRYING.value
        box = Box(
            code=code,
            core_type_id=cores[core_code].id,
            quantity=qty,
            initial_quantity=initial_qty,
            entered_at=entered,
            ready_at=ready,
            status=status,
        )
        db.add(box)
        db.flush()
        occupy_slot(db, free[i], box)
        db.add(DomainEvent(
            event_type='BOX_REGISTERED', aggregate_type='box', aggregate_id=box.id,
            payload={'box_code': code, 'core_type': core_code, 'quantity': initial_qty, 'demo_seed': True},
            occurred_at=entered,
        ))
        db.add(DomainEvent(
            event_type='BOX_STORED', aggregate_type='box', aggregate_id=box.id,
            payload={'slot': free[i].code, 'demo_seed': True},
            occurred_at=entered + timedelta(minutes=2),
        ))
        if status == BoxStatus.READY.value:
            db.add(DomainEvent(
                event_type='BOX_READY', aggregate_type='box', aggregate_id=box.id,
                payload={'demo_seed': True}, occurred_at=ready,
            ))

    # A little history makes dashboard/analytics useful immediately without changing active stock.
    for hours_ago, core_code, qty in [(18, 'CORE-B', 12), (8, 'CORE-C', 20), (3, 'CORE-E', 10)]:
        created = now - timedelta(hours=hours_ago)
        req = ProductionRequest(
            core_type_id=cores[core_code].id,
            requested_quantity=qty,
            status=ProductionRequestStatus.COMPLETED.value,
            priority=50,
            created_at=created,
            planned_at=created + timedelta(minutes=1),
            started_at=created + timedelta(minutes=2),
            completed_at=created + timedelta(minutes=7),
        )
        db.add(req)
        db.flush()
        db.add(DomainEvent(
            event_type='PRODUCTION_REQUEST_COMPLETED',
            aggregate_type='production_request', aggregate_id=req.id,
            payload={'core_type': core_code, 'quantity': qty, 'demo_seed': True},
            occurred_at=req.completed_at,
        ))

    # Completed robot history for utilization/failure-free dashboard context.
    hist_task = RobotTask(
        type='HOME', priority=90, status=RobotTaskStatus.COMPLETED.value,
        sequence_number=0, planned_path=[],
        created_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=2) + timedelta(seconds=18),
    )
    db.add(hist_task)

    db.commit()
    return demo_summary(db)


def demo_summary(db: Session) -> dict:
    boxes = list(db.scalars(select(Box)).all())
    slots = list(db.scalars(select(Slot)).all())
    return {
        'seeded': bool(boxes),
        'core_types': db.scalar(select(func.count(CoreType.id))) or 0,
        'boxes': len(boxes),
        'ready_boxes': sum(1 for b in boxes if b.status == BoxStatus.READY.value and b.quantity > 0),
        'drying_boxes': sum(1 for b in boxes if b.status == BoxStatus.DRYING.value and b.quantity > 0),
        'partial_boxes': sum(1 for b in boxes if 0 < b.quantity < b.initial_quantity),
        'storage_slots': sum(1 for s in slots if s.type == 'STORAGE'),
        'free_storage_slots': sum(1 for s in slots if s.type == 'STORAGE' and s.status == 'FREE'),
        'clock': {'mode': clock.snapshot().mode.value, 'now': clock.now().isoformat()},
        'recommended_test': {'core_type': 'CORE-A', 'quantity': 55},
    }


def seed_database(reset: bool = True) -> dict:
    db = SessionLocal()
    try:
        return seed_session(db, reset=reset)
    finally:
        db.close()


def ensure_seeded() -> dict:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        return seed_session(db, reset=False)
    finally:
        db.close()


if __name__ == '__main__':
    summary = seed_database(True)
    print(
        'Demo seed ready: '
        f"{summary['core_types']} core types, {summary['boxes']} boxes, "
        f"{summary['ready_boxes']} ready, {summary['drying_boxes']} drying."
    )

from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.clock import clock
from app.core.models import Box
from app.core.enums import BoxStatus
from app.events.service import emit

DRYING_HOURS = 24

def ready_at_for(entered_at: datetime) -> datetime:
    return entered_at + timedelta(hours=DRYING_HOURS)

def is_ready(entered_at: datetime, now: datetime | None = None) -> bool:
    return (now or clock.now()) >= ready_at_for(entered_at)

def refresh_readiness(db: Session) -> int:
    now = clock.now()
    boxes = db.scalars(select(Box).where(Box.status == BoxStatus.DRYING.value, Box.quantity > 0, Box.ready_at <= now)).all()
    for box in boxes:
        box.status = BoxStatus.READY.value
        emit(db, 'BOX_READY', 'box', box.id, {'box_code': box.code, 'ready_at': box.ready_at.isoformat()})
    if boxes:
        db.commit()
    return len(boxes)

def soon_to_be_ready(db: Session, hours: float = 24) -> list[Box]:
    now = clock.now()
    limit = now + timedelta(hours=hours)
    return list(db.scalars(select(Box).where(Box.status == BoxStatus.DRYING.value, Box.ready_at > now, Box.ready_at <= limit).order_by(Box.ready_at)).all())

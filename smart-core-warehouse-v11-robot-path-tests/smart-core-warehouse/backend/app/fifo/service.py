from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Box
from app.core.enums import BoxStatus
from app.drying.service import refresh_readiness


def eligible_boxes(db: Session, core_type_id: str):
    refresh_readiness(db)
    return list(db.scalars(select(Box).where(
        Box.core_type_id == core_type_id,
        Box.quantity > 0,
        Box.status == BoxStatus.READY.value,
        Box.current_slot_id.is_not(None),
    ).order_by(Box.entered_at.asc(), Box.code.asc())).all())

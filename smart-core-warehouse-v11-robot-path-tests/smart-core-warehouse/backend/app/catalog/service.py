from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import CoreType

def list_core_types(db: Session, include_inactive: bool = False):
    stmt = select(CoreType).order_by(CoreType.code)
    if not include_inactive:
        stmt = stmt.where(CoreType.active.is_(True))
    return list(db.scalars(stmt).all())

def get_by_code(db: Session, code: str) -> CoreType | None:
    return db.scalar(select(CoreType).where(CoreType.code == code))

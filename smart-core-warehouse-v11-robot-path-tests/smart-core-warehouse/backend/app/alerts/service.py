from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Alert

def active_alerts(db:Session):
    return list(db.scalars(select(Alert).where(Alert.active.is_(True)).order_by(Alert.created_at.desc())).all())

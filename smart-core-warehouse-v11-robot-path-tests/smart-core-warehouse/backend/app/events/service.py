from sqlalchemy.orm import Session
from app.core.models import DomainEvent
from app.realtime.manager import manager

def emit(db: Session, event_type: str, aggregate_type: str | None = None, aggregate_id: str | None = None, payload: dict | None = None) -> DomainEvent:
    ev = DomainEvent(event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id, payload=payload or {})
    db.add(ev)
    db.flush()
    manager.publish_sync({'type':'DOMAIN_EVENT','event_type':event_type,'aggregate_type':aggregate_type,'aggregate_id':aggregate_id,'payload':payload or {}})
    return ev

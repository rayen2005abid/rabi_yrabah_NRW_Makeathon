from sqlalchemy.orm import Session
from app.core.models import ProductionRequest
from app.core.enums import ProductionRequestStatus
from app.core.clock import clock

def mark_started(db:Session,req:ProductionRequest):
    req.status=ProductionRequestStatus.EXECUTING.value; req.started_at=clock.now()

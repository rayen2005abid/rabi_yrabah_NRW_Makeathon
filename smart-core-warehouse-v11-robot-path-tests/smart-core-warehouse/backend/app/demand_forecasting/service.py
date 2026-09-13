from __future__ import annotations
from datetime import timedelta
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.clock import clock
from app.core.models import ProductionRequest

class DemandForecastService:
    def forecast(self, db: Session, core_type_id: str) -> dict:
        raise NotImplementedError

class RuleBasedDemandForecaster(DemandForecastService):
    def forecast(self, db: Session, core_type_id: str) -> dict:
        since = clock.now() - timedelta(days=30)
        rows = db.scalars(select(ProductionRequest).where(ProductionRequest.core_type_id == core_type_id, ProductionRequest.created_at >= since)).all()
        total = sum(r.requested_quantity for r in rows)
        avg_daily = total / 30.0
        score = min(1.0, avg_daily / 100.0)
        return {'demand_score': score, 'expected_near_term_quantity': avg_daily * 3.0, 'method': 'RULE_BASED_30D'}

forecaster = RuleBasedDemandForecaster()

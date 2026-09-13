from __future__ import annotations
from sqlalchemy.orm import Session
from app.core.config import load_yaml
from app.core.models import Slot, Box
from app.warehouse.service import free_storage_slots
from app.demand_forecasting.service import forecaster
from app.slotting.rl_policy import placement_policy_value


def score_slot(slot: Slot, demand_score: float, weights: dict) -> tuple[float, dict]:
    future = slot.travel_cost * demand_score
    congestion = 0.0
    balance = abs((slot.rack_face or 1) - 1.5) * 0.1
    policy_value = placement_policy_value(slot, demand_score)
    score = (
        weights['travel'] * slot.travel_cost
        + weights['future'] * future
        + weights['congestion'] * congestion
        + weights['balance'] * balance
        - weights.get('accessibility', 0.0) * slot.accessibility_score
        - weights.get('rl_policy', 0.35) * policy_value
    )
    return score, {
        'travel': slot.travel_cost,
        'future_retrieval': future,
        'congestion': congestion,
        'balance': balance,
        'accessibility': slot.accessibility_score,
        'rl_policy_value': policy_value,
    }


def ranked_candidates(db: Session, box: Box, limit: int = 10):
    cfg = load_yaml('warehouse.yaml').get('slotting', {})
    weights = cfg.get('weights', {'travel': 1.0, 'future': 0.7, 'congestion': 0.2, 'balance': 0.2, 'accessibility': 0.4})
    demand = forecaster.forecast(db, box.core_type_id)['demand_score']
    ranked = []
    for slot in free_storage_slots(db):
        if not slot.metadata_json.get('reachable', True) or int(slot.metadata_json.get('capacity_boxes',1)) < 1:
            continue
        cost, explanation = score_slot(slot, demand, weights)
        ranked.append({'slot': slot, 'cost': cost, 'explanation': explanation})
    ranked.sort(key=lambda x: (x['cost'], x['slot'].code))
    return ranked[:limit]


def choose_best_slot(db: Session, box: Box) -> Slot | None:
    ranked = ranked_candidates(db, box, 1)
    return ranked[0]['slot'] if ranked else None


def choose_return_slot(db: Session, box: Box, fallback: Slot | None) -> Slot | None:
    ranked=ranked_candidates(db,box,limit=1)
    candidate=ranked[0] if ranked else None
    if fallback is None:
        return candidate['slot'] if candidate else None
    if not fallback.enabled or fallback.metadata_json.get('reachable',True) is False:
        return candidate['slot'] if candidate else None
    cfg=load_yaml('warehouse.yaml').get('slotting',{})
    weights=cfg.get('weights',{'travel':1.0,'future':0.7,'congestion':0.2,'balance':0.2,'accessibility':0.4})
    demand=forecaster.forecast(db,box.core_type_id)['demand_score']
    fallback_cost,_=score_slot(fallback,demand,weights)
    if candidate and candidate['cost'] < fallback_cost:
        return candidate['slot']
    return fallback

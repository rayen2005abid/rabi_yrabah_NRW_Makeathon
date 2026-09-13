from app.core.enums import SlotStatus
from app.predictive.service import current_predictions
from conftest import add_slot


def test_predicts_warehouse_near_capacity(db):
    for index in range(10):
        slot = add_slot(db, f"S{index}")
        if index < 9:
            slot.status = SlotStatus.OCCUPIED.value
    db.commit()

    risks = current_predictions(db)
    capacity = next(r for r in risks if r["code"] == "WAREHOUSE_NEAR_CAPACITY")
    assert capacity["kind"] == "PREDICTED_RISK"
    assert capacity["severity"] == "WARNING"
    assert capacity["probability_or_score"] == 0.9

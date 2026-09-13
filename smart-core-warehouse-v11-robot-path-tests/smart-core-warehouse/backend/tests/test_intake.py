import pytest
from app.intake.service import register_box
from app.core.models import Slot
from app.core.enums import SlotType, SlotStatus
from conftest import add_slot

def test_low_cv_confidence_is_rejected(db,core_a):
    add_slot(db,'ENTRY',typ=SlotType.ENTRY_PICKING.value); add_slot(db,'S1')
    with pytest.raises(ValueError,match='confidence'):
        register_box(db,'CORE-A',10,vision_confidence=.2)

def test_intake_selects_slot_without_user_choice(db,core_a):
    entry=add_slot(db,'ENTRY',typ=SlotType.ENTRY_PICKING.value); add_slot(db,'S-FAR',x=10,z=10); near=add_slot(db,'S-NEAR',x=.1,z=.1)
    box=register_box(db,'CORE-A',10,box_code='AUTO-SLOT',vision_confidence=.99)
    from app.core.models import RobotTask
    from sqlalchemy import select
    task=db.scalar(select(RobotTask).where(RobotTask.box_id==box.id))
    assert db.get(Slot,box.current_slot_id).code=='ENTRY'
    assert task.target_location=='S-NEAR' and near.status=='RESERVED'

def test_weight_based_quantity_estimation_uses_core_calibration():
    from app.capture_station.service import estimate_quantity
    # CORE-A demo calibration: tare 1.20 kg + 10 * 0.42 kg = 5.40 kg.
    result=estimate_quantity('CORE-A',5.40)
    assert result['quantity']==10
    assert result['count_confidence']==1.0
    assert result['method']=='WEIGHT_CALIBRATION'

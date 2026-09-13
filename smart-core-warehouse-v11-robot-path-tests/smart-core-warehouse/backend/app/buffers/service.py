from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Slot
from app.core.enums import SlotType

def list_buffers(db:Session): return list(db.scalars(select(Slot).where(Slot.type==SlotType.BUFFER.value)).all())

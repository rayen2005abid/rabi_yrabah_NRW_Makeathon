from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import Box

def active_inventory(db:Session):
    return list(db.scalars(select(Box).where(Box.quantity>0).order_by(Box.entered_at)).all())

def get_box_for_update(db:Session,box_id:str):
    return db.scalar(select(Box).where(Box.id==box_id).with_for_update())

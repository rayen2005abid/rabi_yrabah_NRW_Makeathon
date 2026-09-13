from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.db import Base
from app.core.clock import clock
from app.core.models import CoreType, Slot
from app.core.enums import SlotType, SlotStatus

@pytest.fixture
def db():
    engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    s=Session()
    clock.set_time(datetime(2026,9,12,12,0,tzinfo=timezone.utc))
    try: yield s
    finally: s.close(); Base.metadata.drop_all(engine)

@pytest.fixture
def core_a(db):
    c=CoreType(code='CORE-A',name='Core A',active=True); db.add(c); db.commit(); return c

def add_slot(db, code, x=0.0, z=0.0, typ=SlotType.STORAGE.value):
    s=Slot(code=code,type=typ,status=SlotStatus.FREE.value,enabled=True,x_coordinate=x,y_coordinate=0,z_coordinate=z,travel_cost=abs(x)+abs(z),accessibility_score=1.0)
    db.add(s); db.commit(); return s

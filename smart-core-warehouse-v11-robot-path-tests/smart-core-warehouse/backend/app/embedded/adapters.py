from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.models import RobotTask, RobotTelemetry, Slot, Box, Alert, FulfillmentPlan, ProductionRequest
from app.core.enums import RobotTaskStatus, RobotTaskType, BoxStatus, SlotStatus, PlanStatus, ProductionRequestStatus
from app.robot.runtime import robot_runtime
from app.safety.service import validate_dispatch, active_fault_types
from app.events.service import emit
from app.core.state_machine import transition


def _maybe_complete_request(db: Session, task: RobotTask) -> None:
    if not task.request_id:
        return
    plan=db.scalar(select(FulfillmentPlan).where(FulfillmentPlan.request_id==task.request_id).order_by(FulfillmentPlan.created_at.desc()))
    req=db.get(ProductionRequest,task.request_id)
    if not plan or not req:
        return
    items_done=all(i.actual_quantity_removed is not None for i in plan.items)
    other_pending=db.scalar(select(RobotTask.id).where(
        RobotTask.request_id==task.request_id,
        RobotTask.id!=task.id,
        RobotTask.status.in_([RobotTaskStatus.QUEUED.value,RobotTaskStatus.DISPATCHED.value,RobotTaskStatus.RUNNING.value]),
    ).limit(1))
    if items_done and not other_pending:
        plan.status=PlanStatus.COMPLETED.value
        req.status=ProductionRequestStatus.COMPLETED.value
        req.completed_at=datetime.now(timezone.utc)
        emit(db,'PRODUCTION_REQUEST_COMPLETED','production_request',req.id,{'final_robot_task_id':task.id})

class EmbeddedControllerAdapter(ABC):
    @abstractmethod
    def dispatch_task(self, db: Session, task: RobotTask) -> dict: ...
    @abstractmethod
    def get_status(self) -> dict: ...
    @abstractmethod
    def home(self) -> dict: ...
    @abstractmethod
    def emergency_stop(self) -> dict: ...
    @abstractmethod
    def reset_fault(self) -> dict: ...

class MockEmbeddedAdapter(EmbeddedControllerAdapter):
    def dispatch_task(self, db: Session, task: RobotTask) -> dict:
        source = db.scalar(select(Slot).where(Slot.code == task.source_location)) if task.source_location else None
        target = db.scalar(select(Slot).where(Slot.code == task.target_location)) if task.target_location else None
        safety = validate_dispatch(db, source, target, robot_runtime.carrying_box, allow_occupied_target=(task.type == RobotTaskType.RECOVERY.value))
        task.status = RobotTaskStatus.DISPATCHED.value
        task.started_at = datetime.now(timezone.utc)
        if not safety.ok:
            task.status = RobotTaskStatus.INTERRUPTED.value
            task.failure_reason = safety.reason
            robot_runtime.fault = safety.reason
            emit(db,'ROBOT_TASK_FAILED','robot_task',task.id,{'reason':safety.reason})
            db.commit(); return {'status':'FAILED','reason':safety.reason}
        task.status = RobotTaskStatus.RUNNING.value
        robot_runtime.current_task_id = task.id; robot_runtime.mode='RUNNING'
        emit(db,'ROBOT_TASK_STARTED','robot_task',task.id,{})
        # The mock acts as hardware ACK/telemetry source. Logical state is finalized only after this ACK path.
        box = db.get(Box, task.box_id) if task.box_id else None
        if target:
            robot_runtime.x, robot_runtime.y, robot_runtime.z = target.x_coordinate, 0.0, target.z_coordinate
        db.add(RobotTelemetry(task_id=task.id,state='ACK_COMPLETED',x=robot_runtime.x,y=robot_runtime.y,z=robot_runtime.z,carrying_box=False,fault=None))
        if task.type == RobotTaskType.RETRIEVE_BOX.value and box and source and target:
            source.box_id = None
            source.status = SlotStatus.RESERVED_FOR_RETURN.value
            db.flush()  # release UNIQUE slot.box_id before assigning the box to picking
            target.box_id = box.id
            target.status = SlotStatus.OCCUPIED.value
            box.current_slot_id = target.id
            box.reserved_return_slot_id = source.id
            box.status = transition(box.status,BoxStatus.IN_TRANSIT.value)
            box.status = transition(box.status,BoxStatus.AT_PICKING.value)
            emit(db,'BOX_AT_PICKING','box',box.id,{'source_slot':source.code,'picking_slot':target.code})
        elif task.type in {RobotTaskType.RETURN_BOX.value, RobotTaskType.STORE_BOX.value} and box and target:
            if target.box_id not in (None, box.id):
                task.status = RobotTaskStatus.FAILED.value; task.failure_reason='TARGET_OCCUPIED'; db.commit(); return {'status':'FAILED','reason':'TARGET_OCCUPIED'}
            if source and source.box_id == box.id:
                source.box_id = None
                source.status = SlotStatus.FREE.value if source.enabled else SlotStatus.DISABLED.value
                if source.code == 'PICKING':
                    for alert in db.scalars(select(Alert).where(Alert.code=='PICKING_STATION_BLOCKED',Alert.active.is_(True))).all(): alert.active=False
                db.flush()  # physical move: clear source before occupying target
            target.box_id = box.id; target.status = SlotStatus.OCCUPIED.value
            box.current_slot_id = target.id; box.reserved_return_slot_id = None
            if box.quantity > 0 and task.type == RobotTaskType.RETURN_BOX.value:
                box.status = transition(box.status,BoxStatus.READY.value)
            emit(db,'BOX_RETURNED' if task.type==RobotTaskType.RETURN_BOX.value else 'BOX_STORED','box',box.id,{'slot':target.code})
        task.status = RobotTaskStatus.COMPLETED.value
        task.completed_at = datetime.now(timezone.utc)
        robot_runtime.current_task_id=None; robot_runtime.mode='IDLE'; robot_runtime.carrying_box=False
        emit(db,'ROBOT_TASK_COMPLETED','robot_task',task.id,{})
        _maybe_complete_request(db,task)
        db.commit()
        return {'status':'COMPLETED','task_id':task.id}
    def get_status(self) -> dict: return robot_runtime.as_dict()
    def home(self) -> dict:
        robot_runtime.x=robot_runtime.y=robot_runtime.z=0.0; robot_runtime.mode='HOME'; return self.get_status()
    def emergency_stop(self) -> dict:
        robot_runtime.estop=True; robot_runtime.mode='ESTOP'; return self.get_status()
    def reset_fault(self) -> dict:
        robot_runtime.fault=None; robot_runtime.estop=False; robot_runtime.mode='IDLE'; return self.get_status()

class MQTTEmbeddedAdapter(EmbeddedControllerAdapter):
    def __init__(self, *args, **kwargs): self.reason='MQTT adapter skeleton: configure broker and client in deployment.'
    def dispatch_task(self, db: Session, task: RobotTask) -> dict: raise RuntimeError(self.reason)
    def get_status(self) -> dict: return {'mode':'UNCONFIGURED_MQTT'}
    def home(self) -> dict: raise RuntimeError(self.reason)
    def emergency_stop(self) -> dict: raise RuntimeError(self.reason)
    def reset_fault(self) -> dict: raise RuntimeError(self.reason)

mock_adapter = MockEmbeddedAdapter()

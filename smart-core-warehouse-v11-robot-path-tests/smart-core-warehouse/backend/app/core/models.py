from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base
from .enums import *


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class CoreType(Base):
    __tablename__='core_types'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Box(Base):
    __tablename__='boxes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    core_type_id: Mapped[str] = mapped_column(ForeignKey('core_types.id'), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    initial_quantity: Mapped[int] = mapped_column(Integer)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    current_slot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True, index=True)
    reserved_return_slot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    vision_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    vision_result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    core_type = relationship('CoreType')


class Slot(Base):
    __tablename__='slots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rack_face: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    x_coordinate: Mapped[float] = mapped_column(Float, default=0)
    y_coordinate: Mapped[float] = mapped_column(Float, default=0)
    z_coordinate: Mapped[float] = mapped_column(Float, default=0)
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    box_id: Mapped[str | None] = mapped_column(ForeignKey('boxes.id'), unique=True, nullable=True)
    accessibility_score: Mapped[float] = mapped_column(Float, default=1.0)
    travel_cost: Mapped[float] = mapped_column(Float, default=0.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    box = relationship('Box', foreign_keys=[box_id])


class VisionResult(Base):
    __tablename__='vision_results'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    core_type_code: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductionRequest(Base):
    __tablename__='production_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    core_type_id: Mapped[str] = mapped_column(ForeignKey('core_types.id'), index=True)
    requested_quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_type = relationship('CoreType')


class FulfillmentPlan(Base):
    __tablename__='fulfillment_plans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey('production_requests.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default=PlanStatus.DRAFT)
    total_requested: Mapped[int] = mapped_column(Integer)
    total_planned: Mapped[int] = mapped_column(Integer)
    simulated_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items = relationship('FulfillmentPlanItem', cascade='all, delete-orphan', order_by='FulfillmentPlanItem.fifo_rank')


class FulfillmentPlanItem(Base):
    __tablename__='fulfillment_plan_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(ForeignKey('fulfillment_plans.id'), index=True)
    box_id: Mapped[str] = mapped_column(ForeignKey('boxes.id'))
    fifo_rank: Mapped[int] = mapped_column(Integer)
    quantity_before: Mapped[int] = mapped_column(Integer)
    quantity_to_take: Mapped[int] = mapped_column(Integer)
    quantity_after: Mapped[int] = mapped_column(Integer)
    source_slot: Mapped[str] = mapped_column(String(64))
    return_required: Mapped[bool] = mapped_column(Boolean)
    proposed_return_slot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual_quantity_removed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    box = relationship('Box')


class RobotTask(Base):
    __tablename__='robot_tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    box_id: Mapped[str | None] = mapped_column(ForeignKey('boxes.id'), nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=RobotTaskStatus.QUEUED, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(ForeignKey('production_requests.id'), nullable=True)
    planned_path: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RobotTelemetry(Base):
    __tablename__='robot_telemetry'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('robot_tasks.id'), nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    z: Mapped[float] = mapped_column(Float, default=0)
    carrying_box: Mapped[bool] = mapped_column(Boolean, default=False)
    fault: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SimulationRun(Base):
    __tablename__='simulation_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fault(Base):
    __tablename__='faults'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Alert(Base):
    __tablename__='alerts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DomainEvent(Base):
    __tablename__='domain_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__='system_settings'
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class DemandForecast(Base):
    __tablename__='demand_forecasts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    core_type_id: Mapped[str] = mapped_column(ForeignKey('core_types.id'), index=True)
    demand_score: Mapped[float] = mapped_column(Float)
    expected_near_term_quantity: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class CoreTypeCreate(BaseModel):
    code: str; name: str; description: str | None = None; active: bool = True; metadata_json: dict = Field(default_factory=dict)
class CoreTypeOut(ORMModel):
    id: str; code: str; name: str; description: str | None; active: bool; metadata_json: dict; created_at: datetime

class BoxOut(ORMModel):
    id: str; code: str; core_type_id: str; quantity: int; initial_quantity: int; entered_at: datetime; ready_at: datetime; status: str; current_slot_id: str | None; reserved_return_slot_id: str | None; vision_confidence: float | None; created_at: datetime; updated_at: datetime

class SlotOut(ORMModel):
    id: str; code: str; rack_face: int | None; column: int | None; level: int | None; x_coordinate: float; y_coordinate: float; z_coordinate: float; type: str; status: str; box_id: str | None; accessibility_score: float; travel_cost: float; enabled: bool; metadata_json: dict

class IntakeRegister(BaseModel):
    core_type_code: str; quantity: int = Field(gt=0); box_code: str | None = None; entered_at: datetime | None = None; vision_confidence: float | None = None
class CVInput(BaseModel):
    core_type: str; quantity: int = Field(gt=0); confidence: float = Field(ge=0, le=1); status: str = 'ACCEPTED'

class ProductionRequestCreate(BaseModel):
    core_type_code: str; requested_quantity: int = Field(gt=0); priority: int = 50
class ProductionRequestOut(ORMModel):
    id: str; core_type_id: str; requested_quantity: int; status: str; priority: int; created_at: datetime; planned_at: datetime | None; started_at: datetime | None; completed_at: datetime | None; failure_reason: str | None

class ConfirmPick(BaseModel):
    actual_quantity_removed: int = Field(ge=0)

class TimeAdvance(BaseModel):
    hours: float
class TimeSet(BaseModel):
    timestamp: datetime

class FaultInject(BaseModel):
    type: str; details: dict = Field(default_factory=dict)

class WhatIfProduction(BaseModel):
    core_type_code: str; quantity: int = Field(gt=0)
class WhatIfIncoming(BaseModel):
    core_type_code: str; quantity: int = Field(gt=0); confidence: float = 0.99

class SlotBlock(BaseModel):
    slot_code: str; blocked: bool = True

class WhatIfTime(BaseModel):
    hours: float
class WhatIfBlockedSlot(BaseModel):
    slot_code: str
class WhatIfRobotFault(BaseModel):
    type: str
class WhatIfNearFull(BaseModel):
    incoming_boxes: int = Field(ge=0)

class TelemetryInput(BaseModel):
    task_id: str
    state: str
    x: float
    y: float = 0.0
    z: float
    carrying_box: bool = False
    fault: str | None = None

class TwinSpeed(BaseModel):
    multiplier: float

class AutonomyModeInput(BaseModel):
    mode: str

class ManualRobotGoTo(BaseModel):
    slot_code: str
    priority: int = 5

class ManualRobotPose(BaseModel):
    x: float = Field(ge=0)
    z: float = Field(ge=0)
    y: float = Field(default=0.0, ge=0)
    carrying_box: bool | None = None
    mode: str = 'MANUAL'

class TaskTargetOverride(BaseModel):
    slot_code: str

class CaptureAnalyzeInput(BaseModel):
    image_data_url: str | None = None
    gross_weight_kg: float = Field(gt=0)
    demo_core_type: str | None = None
    auto_register: bool = True

class CaptureClassifyInput(BaseModel):
    image_data_url: str | None = None
    demo_core_type: str | None = None

class DemoScaleInput(BaseModel):
    weight_kg: float = Field(ge=0)

class DemoCaptureArrival(BaseModel):
    core_type: str
    quantity: int = Field(gt=0)

class EmbeddedTelemetryInput(BaseModel):
    device_id: str = 'ESP32-ENTRY-01'
    timestamp: datetime | None = None
    entry_present: bool = False
    weight_kg: float = Field(ge=0)
    x_limit: bool = False
    z_limit: bool = False
    fork_extended: bool = False
    estop: bool = False

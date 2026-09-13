from pydantic import BaseModel

class TargetPosition(BaseModel):
    x: float; z: float; y: float = 0.0
class EmbeddedCommand(BaseModel):
    schema_version: str = '1.0'; command_id: str; task_id: str; command: str; target: TargetPosition | None = None
class EmbeddedTelemetry(BaseModel):
    schema_version: str = '1.0'; task_id: str | None = None; state: str; position: TargetPosition; carrying_box: bool = False; fault: str | None = None

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class EmbeddedStationState:
    device_id: str = "ESP32-ENTRY-01"
    online: bool = False
    timestamp: str | None = None
    entry_present: bool = False
    weight_kg: float = 0.0
    x_limit: bool = False
    z_limit: bool = False
    fork_extended: bool = False
    estop: bool = False

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self.device_id = str(payload.get("device_id") or self.device_id)
        self.timestamp = str(payload.get("timestamp") or now)
        self.entry_present = bool(payload.get("entry_present", False))
        self.weight_kg = round(float(payload.get("weight_kg", 0.0)), 3)
        self.x_limit = bool(payload.get("x_limit", False))
        self.z_limit = bool(payload.get("z_limit", False))
        self.fork_extended = bool(payload.get("fork_extended", False))
        self.estop = bool(payload.get("estop", False))
        self.online = True
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {"status": "ESP32 ONLINE" if self.online else "ESP32 OFFLINE", **asdict(self)}


embedded_station = EmbeddedStationState()

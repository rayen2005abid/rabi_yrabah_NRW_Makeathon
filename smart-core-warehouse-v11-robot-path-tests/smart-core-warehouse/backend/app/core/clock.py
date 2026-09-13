from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock


class ClockMode(StrEnum):
    REAL_TIME = 'REAL_TIME'
    SIMULATION_TIME = 'SIMULATION_TIME'


@dataclass
class ClockSnapshot:
    mode: ClockMode
    now: datetime


class ClockService:
    def __init__(self) -> None:
        self._mode = ClockMode.REAL_TIME
        self._sim_time = datetime.now(timezone.utc)
        self._lock = RLock()

    def now(self) -> datetime:
        with self._lock:
            return datetime.now(timezone.utc) if self._mode == ClockMode.REAL_TIME else self._sim_time

    def snapshot(self) -> ClockSnapshot:
        return ClockSnapshot(self._mode, self.now())

    def set_mode(self, mode: ClockMode) -> ClockSnapshot:
        with self._lock:
            self._mode = mode
            if mode == ClockMode.SIMULATION_TIME and self._sim_time.tzinfo is None:
                self._sim_time = self._sim_time.replace(tzinfo=timezone.utc)
            return self.snapshot()

    def set_time(self, value: datetime) -> ClockSnapshot:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        with self._lock:
            self._mode = ClockMode.SIMULATION_TIME
            self._sim_time = value
            return self.snapshot()

    def advance(self, hours: float) -> ClockSnapshot:
        with self._lock:
            if self._mode != ClockMode.SIMULATION_TIME:
                self._mode = ClockMode.SIMULATION_TIME
                self._sim_time = datetime.now(timezone.utc)
            self._sim_time += timedelta(hours=hours)
            return self.snapshot()


clock = ClockService()

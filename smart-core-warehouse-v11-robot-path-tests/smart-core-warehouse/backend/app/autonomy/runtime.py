from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class AutonomyController:
    """Small in-memory operating-mode controller for the demo WCS.

    AUTO        -> the backend auto-cycle may dispatch queued tasks and confirm
                   the planned picking quantity.
    SUPERVISED  -> decisions are still computed, but the admin must start tasks
                   and confirm/approve operational steps.
    MANUAL      -> no automatic task start/confirmation. Admin drives movement.

    This is deliberately runtime state rather than auth. Real deployments should
    protect admin endpoints with the platform identity/role layer.
    """

    mode: str = 'AUTO'

    def set_mode(self, mode: str) -> dict:
        mode = str(mode).upper().strip()
        if mode not in {'AUTO', 'SUPERVISED', 'MANUAL'}:
            raise ValueError('mode must be AUTO, SUPERVISED, or MANUAL')
        self.mode = mode
        return self.snapshot()

    def snapshot(self) -> dict:
        return asdict(self)

    @property
    def auto_enabled(self) -> bool:
        return self.mode == 'AUTO'


autonomy = AutonomyController()

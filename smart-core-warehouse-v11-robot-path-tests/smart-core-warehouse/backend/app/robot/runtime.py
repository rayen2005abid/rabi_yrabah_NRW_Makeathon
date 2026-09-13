from dataclasses import dataclass, asdict

@dataclass
class RobotRuntime:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    mode: str = 'HOME'
    carrying_box: bool = False
    current_task_id: str | None = None
    fault: str | None = None
    estop: bool = False

    def as_dict(self): return asdict(self)

robot_runtime = RobotRuntime()

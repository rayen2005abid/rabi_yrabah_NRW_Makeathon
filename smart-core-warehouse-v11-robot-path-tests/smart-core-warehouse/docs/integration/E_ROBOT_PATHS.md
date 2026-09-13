# E. Robot Paths

## Audit Status

The project has a backend robot path-planning and execution model:

- Explicit navigation graph in `backend/app/intelligence/service.py`.
- A* route search over transfer/spine/rack access nodes.
- Semantic robot routes in `backend/app/robot/planner.py`.
- Single-robot queue and runtime.
- Phase/keyframe movement in `backend/app/digital_twin/runtime.py`.

## Current Route Model

`semantic_path()` currently returns steps such as:

- `RETRACT_Y`
- `NAVIGATE_PASSAGE`
- `MOVE_XZ`
- `EXTEND_Y`
- `LOAD`
- `RETRACT_Y`
- `MOVE_XZ`
- `EXTEND_Y`
- `UNLOAD`
- `RETRACT_Y`

The navigation graph is normalized to a conceptual floor layout and separates floor travel from rack lift/fork movement.

## Current Execution Model

There are two execution paths:

- Instant mock execution via `/robot/process-next`.
- Visual execution via `/digital-twin/run-next`, `/digital-twin/tick`, and `/digital-twin/auto-cycle`.

The visual path starts `live_twin`, progresses through phases, records telemetry, and only applies final warehouse mutation after the visual movement completes and the mock adapter acknowledges the task.

## Gaps

- The navigation graph is hard-coded rather than loaded from versioned configuration.
- Dynamic obstacle-aware replanning is not implemented.
- The semantic route and Digital Twin phase list are related but separate, so they can drift.
- The instant path bypasses progressive visible motion.
- Real PLC/MCU protocol, acceleration limits, and collision zones are not modeled.

## Recommended Next Step

Expose a stable `RobotRoute` contract around the existing path data before changing visualization:

```json
{
  "task_id": "task-id",
  "source": "ENTRY",
  "target": "R1-C01-L01",
  "algorithm": "A*",
  "estimated_distance": 4.2,
  "estimated_time": 8.5,
  "nodes": []
}
```

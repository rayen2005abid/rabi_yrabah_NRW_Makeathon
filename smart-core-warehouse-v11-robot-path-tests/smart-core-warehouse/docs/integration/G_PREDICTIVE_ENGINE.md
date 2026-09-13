# G. Predictive Engine

## Goal

The project should claim innovation through an explainable predictive-risk engine, not an untrained fake ML model.

## Current Implementation

The backend now exposes:

- `GET /api/v1/predictive/risks`
- `backend/app/predictive/service.py`

The dashboard shows the highest active detected faults and predicted risks.

## Target Contract

```json
{
  "code": "ROBOT_TASK_TIMEOUT",
  "severity": "WARNING",
  "probability_or_score": 0.72,
  "explanation": "The current task is exceeding its expected travel time.",
  "affected_task_id": "task-id",
  "expected_time": "2026-09-13T10:00:00Z",
  "recommended_action": "Pause queue and inspect the active aisle."
}
```

## Required Risk Codes

- `LOW_CV_CONFIDENCE`
- `IMAGE_QUALITY_BAD`
- `QUANTITY_WEIGHT_VISION_MISMATCH`
- `SENSOR_WEIGHT_UNSTABLE`
- `DRYING_VIOLATION_ATTEMPT`
- `FIFO_VIOLATION_ATTEMPT`
- `SLOT_CONFLICT`
- `PATH_BLOCKED`
- `POSITION_DRIFT`
- `ROBOT_TASK_TIMEOUT`
- `WAREHOUSE_NEAR_CAPACITY`
- `PICKING_STATION_OCCUPIED`
- `ENTRY_STATION_BLOCKED`
- `RETURN_SLOT_UNAVAILABLE`
- `ETA_THRESHOLD_RISK`

## Rule

Each output must distinguish detected faults from predicted risks. A predicted risk should be shown before the failure condition occurs.

## Implemented Signals

- Active faults are reported as `DETECTED_FAULT`.
- Near-full storage becomes `WAREHOUSE_NEAR_CAPACITY`.
- Blocked/maintenance storage becomes `PATH_BLOCKED`.
- Long queues become `ETA_THRESHOLD_RISK`.
- Slow active movement can become `ROBOT_TASK_TIMEOUT`.
- Telemetry mismatch can become `POSITION_DRIFT`.
- Occupied picking station can become `PICKING_STATION_OCCUPIED`.
- Entry station conflict can become `ENTRY_STATION_BLOCKED`.
- Last capture can produce `LOW_CV_CONFIDENCE`, `IMAGE_QUALITY_BAD`, or `QUANTITY_WEIGHT_VISION_MISMATCH`.

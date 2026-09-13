# C. Quantity Strategy

## Strategy

Quantity is derived from weight, not faked from classification.

```text
net_weight = gross_weight_kg - tare_weight_kg
weight_quantity = round(net_weight / calibrated_unit_weight_kg)
```

The CV classifier identifies the core type. The calibrated unit weight for that core type determines quantity.

## Current Implementation

`backend/app/capture_station/service.py` already implements weight-based estimation using `config/core_weights.yaml`.

Current output includes:

- quantity
- count confidence
- gross weight
- tare weight
- net weight
- unit weight
- method `WEIGHT_CALIBRATION`

## Target Contract

```json
{
  "gross_weight_kg": 12.72,
  "tare_weight_kg": 0.42,
  "net_weight_kg": 12.3,
  "unit_weight_kg": 0.41,
  "weight_quantity": 30,
  "vision_quantity": null,
  "final_quantity": 30,
  "confidence": 0.98,
  "warnings": []
}
```

## Calibration

The shipped weights are demo calibration values. They must not be represented as final factory measurements. For real deployment, weigh multiple samples per core type, compute average unit weight, record tolerance, and update the calibration file.

## Optional Vision Count

If visual counting is later added, use it only as a second signal. When weight and vision disagree beyond tolerance, keep the weight-derived quantity as the safer default and emit `QUANTITY_WEIGHT_VISION_MISMATCH` for review.

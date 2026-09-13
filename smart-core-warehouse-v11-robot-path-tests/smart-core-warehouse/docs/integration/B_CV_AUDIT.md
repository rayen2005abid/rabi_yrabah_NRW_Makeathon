# B. CV Audit

## Audit Summary

Audited repositories:

- `C:\Users\user\Downloads\project NRW\cv_module_simple_v3\cv_module`
- `C:\Users\user\Downloads\project NRW\cv_module_simple_v4_phone_camera\cv_simple_v4`

The v4 phone-camera repository is the preferred integration target. It preserves the fixed-ROI classifier approach, adds phone/network camera support, and uses explicit multi-frame scan voting for live camera use. The deployed HTTP API loads the model once on FastAPI startup.

## Supported Classes

Current artifact class mapping:

| Index | Class |
|---:|---|
| 0 | `EMPTY` |
| 1 | `YOUR_REAL_TYPE_A` |
| 2 | `YOUR_REAL_TYPE_B` |
| 3 | `YOUR_REAL_TYPE_C` |
| 4 | `YOUR_REAL_TYPE_D` |
| 5 | `YOUR_REAL_TYPE_E` |

`EMPTY` is an operational no-piece class. The five real type placeholders must be mapped to final SOPAL/SOPALTEC core codes before a factory deployment claim.

## Dataset

Expected dataset structure:

```text
data/raw/
  EMPTY/
  YOUR_REAL_TYPE_A/
  YOUR_REAL_TYPE_B/
  YOUR_REAL_TYPE_C/
  YOUR_REAL_TYPE_D/
  YOUR_REAL_TYPE_E/
```

Images per class found in v4:

| Class | Images |
|---|---:|
| `EMPTY` | 57 |
| `YOUR_REAL_TYPE_A` | 64 |
| `YOUR_REAL_TYPE_B` | 49 |
| `YOUR_REAL_TYPE_C` | 55 |
| `YOUR_REAL_TYPE_D` | 60 |
| `YOUR_REAL_TYPE_E` | 53 |

The split policy in `configs/default.yaml` is 70% train, 15% validation, 15% test with seed 42.

## Preprocessing And Model

- Architecture: EfficientNet-B0.
- Input size: 224 x 224.
- Preprocessing: RGB conversion, aspect-ratio preserving square padding, resize, ImageNet normalization.
- Augmentation: moderate train-only affine, color, blur/noise, perspective, sharpness/autocontrast, and random erasing.
- Artifact: `artifacts/core_classifier_simple_v4/model.pt`.
- CPU compatibility: expected; EfficientNet-B0 was selected as a smaller CPU-friendly model.

## HTTP API

The CV service exposes:

- `GET /health`
- `GET /model-info`
- `POST /api/v1/classify`

The classify endpoint accepts multipart image upload field `image`.

Current response shape:

```json
{
  "prediction": {
    "core_type": "YOUR_REAL_TYPE_A",
    "confidence": 0.98
  },
  "alternatives": [
    {"core_type": "YOUR_REAL_TYPE_B", "confidence": 0.01}
  ],
  "status": "ACCEPTED",
  "model_version": "core_classifier_simple_v4",
  "quantity": null,
  "count_confidence": null
}
```

## Recommended Warehouse Contract

The warehouse backend should normalize all CV responses into:

```json
{
  "core_type_code": "YOUR_REAL_TYPE_A",
  "confidence": 0.98,
  "top_k": [
    {"core_type_code": "YOUR_REAL_TYPE_A", "confidence": 0.98}
  ],
  "model_version": "core_classifier_simple_v4",
  "inference_ms": 120.0,
  "image_quality_ok": true,
  "warnings": []
}
```

Rules:

- `EMPTY` must not register inventory.
- Low confidence and uncertain results must produce review-required behavior.
- Quantity remains a separate weight-calibration concern unless a reliable counting signal is added.

## Risks

- Class labels are placeholders and need final real core-code mapping.
- Small controlled test-set metrics should not be overstated as general factory robustness.
- The HTTP endpoint does single-image classification; the richer v4 scan voting lives in the camera UI path.
- `api/main.py` defaults to an older artifact path unless `CORE_CLASSIFIER_ARTIFACT` is set.

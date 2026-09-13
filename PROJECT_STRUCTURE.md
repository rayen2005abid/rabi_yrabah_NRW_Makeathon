# Project Structure

The workspace intentionally keeps the warehouse app and CV prototypes as separate folders. This avoids breaking the existing CV artifact paths while still giving the demo one clean root.

## Active App

`smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse`

Contains:

- `backend`: FastAPI, SQLAlchemy, warehouse rules, robot runtime, Digital Twin, predictive risks, embedded telemetry.
- `frontend`: React/Vite operator console, jury showcase, dashboard, inventory, production, Digital Twin.
- `config`: warehouse/robot/demo/calibration YAML files.
- `embedded/wokwi`: ESP32 simulation project.
- `docs`: audit, acceptance, and jury demo evidence.

## Active CV

`cv_module_simple_v4_phone_camera/cv_simple_v4`

Use this for real image classification. It contains the current trained artifact:

`artifacts/core_classifier_simple_v4/model.pt`

## Reference CV

`cv_module_simple_v3/cv_module`

Keep as reference/history. Do not use it for the final jury run unless v4 is unavailable.

## Launchers

Root launchers forward into the correct nested folders:

- `start_demo.bat`
- `start_backend.bat`
- `start_frontend.bat`
- `start_cv_v3.bat`
- `start_cv_v4.bat`
- `test_phone_camera.bat`
- `start_phone_camera.bat`

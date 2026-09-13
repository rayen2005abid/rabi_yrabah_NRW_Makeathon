# A. Architecture Audit

## Scope

Audit scope: `C:\Users\user\Downloads\project NRW`, focused on the main Smart Core Warehouse app and the two CV folders.

## Current Software Architecture

The main app lives under:

- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/backend`
- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/frontend`

The backend is a FastAPI modular monolith. `backend/app/api/routes.py` is the central integration boundary for catalog, intake, capture station, fulfillment, slotting, robot tasks, simulation, Digital Twin, events, alerts, analytics, embedded abstractions, admin controls, and demo scenarios.

The frontend is a React/Vite app. It calls backend APIs through `frontend/src/api/client.ts`, routes screens in `frontend/src/App.tsx`, and keeps business decisions in the backend.

## Current CV Architecture

There are two standalone CV folders:

- `cv_module_simple_v3/cv_module`
- `cv_module_simple_v4_phone_camera/cv_simple_v4`

The v4 repository is the preferred target. It provides fixed-ROI classification, a learned `EMPTY` class, multi-frame camera voting, phone-camera stream support, FastAPI inference, and a trained artifact under `artifacts/core_classifier_simple_v4`.

## Working Components

- FastAPI startup, CORS, schema creation, and demo seeding.
- SQLAlchemy domain model for boxes, slots, vision results, production requests, plans, tasks, telemetry, alerts, events, and faults.
- Strict FIFO planning and 24-hour drying rules.
- Intake registration with slot choice and store-task creation.
- Weight-based quantity estimation.
- Robot task queue and semantic path planning.
- Backend Digital Twin runtime with visible lift/fork/route phases.
- Frontend Factory Console, Demo Showcase, Admin Panel, Inventory, Production, and Digital Twin screens.
- WebSocket fanout for events and telemetry notifications.
- CV v4 FastAPI classifier and trained EfficientNet-B0 artifact.

## Broken Components

- Warehouse capture posts multipart upload field `file`; the CV API expects `image`.
- CV v4 API defaults to `artifacts/core_classifier_v2`, while the current artifact is `artifacts/core_classifier_simple_v4`.
- The main `docker-compose.yml` does not include the CV service.
- `backend/app/cv_gateway/service.py` still contains an older JSON `/classify` client, while capture station uses multipart `/api/v1/classify`.
- Embedded mode configuration exists, but routes/services still call the mock adapter directly.

## Missing Connections

- No single startup path launches backend, frontend, and CV together.
- No aggregate health endpoint checks CV, scale, model-loaded state, and embedded state together.
- No explicit CV-label to warehouse-core-code mapping.
- Browser camera capture sends a full image; the CV training workflow assumes a fixed ROI crop.
- No Wokwi ESP32 project was present before this integration pass.
- Predictive-risk functionality is not formalized as a dedicated backend contract.

## Proposed Final Architecture

Keep the backend as the single source of truth. External inputs enter through gateways:

- CV gateway normalizes classifier results into `CoreClassificationResult`.
- Quantity estimator combines gross weight, tare, calibrated unit weight, and optional vision count.
- Intake service registers only accepted, mapped, non-duplicate captures.
- Slotting service chooses storage locations and emits decision traces.
- Robot service owns tasks and planned routes.
- Digital Twin runtime owns authoritative robot phase/pose and publishes typed realtime updates.
- Embedded adapter accepts telemetry and gates final physical execution.
- Predictive-risk engine consumes current state and emits risk predictions before faults.

## Migration Strategy

1. Align CV HTTP field name and artifact default.
2. Add stable CV and quantity contracts without rewriting the trained CV pipeline.
3. Preserve existing FIFO/drying/slotting logic and add missing integration tests.
4. Add Wokwi demo and embedded telemetry endpoints.
5. Formalize predictive-risk outputs.
6. Improve realtime Digital Twin transport.
7. Upgrade 3D visualization while keeping backend authority.

## Files Expected To Change

- `backend/app/capture_station/service.py`
- `backend/app/cv_gateway/service.py`
- `backend/app/api/routes.py`
- `backend/app/core/schemas.py`
- `backend/app/embedded/*`
- `backend/app/robot/*`
- `backend/app/digital_twin/*`
- `frontend/src/features/FactoryConsole.tsx`
- `frontend/src/features/DigitalTwin.tsx`
- `frontend/src/features/DemoShowcase.tsx`
- `docker-compose.yml`
- `config/*`
- `embedded/wokwi/*`
- `docs/*`
- targeted tests

## Files That Should Not Be Rewritten

Do not rewrite these unless a narrow contract change requires it:

- `backend/app/fifo/service.py`
- `backend/app/drying/service.py`
- `backend/app/fulfillment/service.py`
- `backend/app/slotting/service.py`
- `backend/app/safety/service.py`
- `backend/app/warehouse/service.py`
- `backend/app/picking/service.py`
- `backend/app/core/models.py`
- `cv_module_simple_v4_phone_camera/cv_simple_v4/src/train.py`
- `cv_module_simple_v4_phone_camera/cv_simple_v4/src/dataset.py`
- `cv_module_simple_v4_phone_camera/cv_simple_v4/src/models.py`
- `cv_module_simple_v4_phone_camera/cv_simple_v4/src/inference.py`

## Technical Risks

- Silent mock CV fallback is useful for demos but dangerous if production config omits `CV_BASE_URL`.
- CV labels are placeholders and need final SOPAL/SOPALTEC mapping.
- Digital Twin currently relies on frequent HTTP refresh in the frontend, not typed state as the primary WebSocket transport.
- Existing simulation is operational and visual, not CAD-accurate physics.
- Real robot and scale integrations need hardware protocol details.
- The visible workspace root is not a git repository, so phase commits may be unavailable.

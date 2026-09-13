# SOPALTEC Smart Core Warehouse

Integrated warehouse-control demo for National Robotics Weekend 8.0.

This app demonstrates the full Smart Core Warehouse flow:

```text
box arrives
-> camera/CV identifies core type
-> weight estimates quantity
-> box is registered with entered_at and ready_at
-> smart slot is selected
-> robot task and route are planned
-> Digital Twin shows movement through racks and transfer lane
-> 24h drying rule protects stock
-> production requests use strict FIFO
-> partial returns preserve the original timestamp
-> predictive risks and embedded telemetry are shown live
```

## Quick Start

From this folder:

```bat
start_demo.bat
```

From the workspace root:

```bat
..\..\start_demo.bat
```

That root launcher starts CV v3, backend, frontend, the live site-camera CV loop, and the Digital Twin platform together.

Open:

- Factory Console: `http://localhost:5173`
- Demo Showcase: `http://localhost:5173/demo-showcase`
- Live Robot Path: `http://localhost:5173/digital-twin`
- Backend API docs: `http://localhost:8000/docs`

## Main Structure

```text
smart-core-warehouse/
  backend/
    app/
      api/                 REST and WebSocket routes
      capture_station/     automatic inbound capture and quantity analysis
      cv_gateway/          CV service boundary
      drying/              24-hour readiness rule
      fifo/                strict FIFO eligible-stock ordering
      fulfillment/         production allocation plans
      slotting/            intelligent slot ranking
      robot/               robot tasks, planner, runtime
      digital_twin/        authoritative visual execution runtime
      embedded/            ESP32/robot telemetry contracts
      predictive/          explainable risk predictions
      demo/                seeded presentation scenarios
  frontend/
    src/features/          Factory, demo, dashboard, inventory, Digital Twin
  config/                  warehouse, robot, demo, calibration YAML
  embedded/wokwi/          Wokwi-compatible ESP32 demo
  docs/
    integration/           architecture and subsystem audits
    acceptance/            NRW scoring matrix and final score gate
    presentation/          demo script
```

## Demo Screens

- **Factory Console**: operator view. The operator places boxes and requests production; the system chooses boxes, slots, routes, and robot tasks.
- **Demo Showcase**: fast one-click scoring scenarios.
- **Live Robot Path**: detailed robot movement, route, lift/fork action, carried box, and decision trace.
- **Operations Dashboard**: health, alerts, predictive risks, queue, and readiness summary.
- **Admin Panel**: advanced controls, reset, speed, fault injection, and recovery.

## Real CV Integration

The full demo uses the already-working CV v3 service outside this folder:

```text
../../cv_module_simple_v3/cv_module
```

The v4 service is also available for phone-camera scanner experiments:

```text
../../cv_module_simple_v4_phone_camera/cv_simple_v4
```

Start the full demo from the workspace root:

```bat
start_demo.bat
```

Set:

```env
CV_BASE_URL=http://localhost:8100
```

The warehouse sends multipart field `image` to `/api/v1/classify`.

## Phone Camera Scanner

From the workspace root, your old phone-camera stream is configured as the default:

```bat
test_phone_camera.bat
start_phone_camera.bat
```

Default stream:

```text
http://172.10.20.11:4747/video
```

If the phone app shows a different address, pass it explicitly:

```bat
start_phone_camera.bat "http://PHONE_IP:PORT/video"
```

## Site Camera CV

The Factory Console continuously classifies the camera/photo input through:

```text
POST /api/v1/capture/classify
```

That endpoint is read-only. It updates the live type display but does not create a box, reserve a slot, or move the robot. Box registration still uses `/api/v1/capture/analyze` after stable weight is available.

## Quantity Calibration

Demo values live in:

- `config/core_weights.yaml`
- `config/core_calibration.yaml`

They are demo calibration values, not final measured factory weights. Replace unit weight, tare weight, and tolerance with measured SOPALTEC values before presenting factory-accuracy claims.

## Embedded Simulation

Wokwi files are in:

```text
embedded/wokwi/
```

Backend endpoints:

- `POST /api/v1/embedded/telemetry`
- `GET /api/v1/embedded/state`

## Acceptance Evidence

- `docs/acceptance/NRW_ACCEPTANCE_MATRIX.md`
- `docs/acceptance/FINAL_SCORE_GATE.md`
- `docs/presentation/DEMO_SCRIPT.md`
- `docs/integration/A_ARCHITECTURE_AUDIT.md`

## Verification Status

Latest local checks:

- Frontend typecheck: pass.
- Frontend production build: pass.
- Backend Python compile check: pass.
- Backend pytest: blocked until `pytest` is installed in the backend Python environment.

The folder is not currently a git repository, so final commit hash generation is unavailable here.

# SOPALTEC Smart Core Warehouse

Final integration workspace for the National Robotics Weekend 8.0 demo.

## Start Here

Run the complete warehouse demo:

```bat
start_demo.bat
```

Then open:

- Factory Console: `http://localhost:5173`
- Jury Showcase: `http://localhost:5173/jury`
- Live Robot Path: `http://localhost:5173/digital-twin`
- Backend API docs: `http://localhost:8000/docs`

## Folder Structure

```text
project NRW/
  README.md                         this file
  start_demo.bat                    one-command Windows demo launcher
  start_backend.bat                 backend-only launcher
  start_frontend.bat                frontend-only launcher
  start_cv_v3.bat                   CV v3 API launcher used by full demo
  start_cv_v4.bat                   optional real CV service launcher
  test_phone_camera.bat             verify phone stream before ML loads
  start_phone_camera.bat            fixed-ROI phone-camera scanner

  smart-core-warehouse-v11-robot-path-tests/
    smart-core-warehouse/
      backend/                      FastAPI warehouse-control backend
      frontend/                     React operator, jury, dashboard, Digital Twin UI
      config/                       warehouse, robot, demo, calibration config
      embedded/wokwi/               ESP32 Wokwi simulation
      docs/integration/             integration audits and design notes
      docs/acceptance/              NRW score and acceptance evidence
      docs/jury/                    live demo script

  cv_module_simple_v4_phone_camera/
    cv_simple_v4/                   preferred CV classifier service
      api/                          FastAPI CV API
      src/                          training, inference, camera tools
      artifacts/core_classifier_simple_v4/
                                    trained EfficientNet-B0 classifier
      data/raw/                     fixed-ROI dataset

  cv_module_simple_v3/
    cv_module/                      older/reference CV module
```

## Recommended Demo Order

1. Run `start_demo.bat`.
2. Open **Jury Showcase**.
3. Click **Automatic entry**.
4. Open **Live Robot Path** and show robot route, rack lift, fork, and carried box.
5. Click **+24h drying**.
6. Click **FIFO CORE-A x55**.
7. Show the expected plan: A01 -> 10, A02 -> 30, A03 -> 15, A04 untouched.
8. Show **Predictive Risks** on the Operations Dashboard.
9. Open the Wokwi ESP32 simulation in `smart-core-warehouse.../embedded/wokwi`.

## One Command Full Demo

Use this for the jury run:

```bat
start_demo.bat
```

It starts:

- CV v3 API on `http://localhost:8100`
- warehouse backend on `http://localhost:8000`
- React platform on `http://localhost:5173`
- Factory Console live camera classification through the site camera
- Digital Twin and autonomous robot simulation inside the platform

The Factory Console camera sends frames to:

```text
site camera -> backend /api/v1/capture/classify -> CV v3 API /api/v1/classify
```

## CV Service

The full demo now defaults to the already-working CV v3 API:

```bat
start_cv_v3.bat
```

CV v4 is still available if you want to compare it:

```bat
start_cv_v4.bat
```

Then set the backend environment variable:

```env
CV_BASE_URL=http://localhost:8100
```

The warehouse backend sends multipart image field `image`, matching the CV APIs.

## Phone Camera

Your previous phone-camera address is wired as the default:

```text
http://172.10.20.11:4747/video
```

First test the stream:

```bat
test_phone_camera.bat
```

Then start the fixed-ROI scanner:

```bat
start_phone_camera.bat
```

To use a different phone/IP:

```bat
start_phone_camera.bat "http://PHONE_IP:PORT/video"
```

In the scanner window, put one core fully inside the green rectangle, hold it still, then press `SPACE`.

## Site Camera CV

The Factory Console camera now sends frames to the backend live classifier while the page is open:

```text
Factory Console camera -> /api/v1/capture/classify -> CV service -> live type on screen
```

This is separate from box registration. Live CV tells the current type; registration still waits for stable weight and accepted confidence.

If `CV_BASE_URL` is set and the CV service is reachable, the displayed type comes from the real classifier. If the CV service is unavailable during a demo, the app shows a demo fallback warning instead of leaving the type blank.

## Important Evidence Files

- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/docs/acceptance/FINAL_SCORE_GATE.md`
- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/docs/acceptance/NRW_ACCEPTANCE_MATRIX.md`
- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/docs/jury/JURY_DEMO_SCRIPT.md`
- `smart-core-warehouse-v11-robot-path-tests/smart-core-warehouse/docs/integration/A_ARCHITECTURE_AUDIT.md`

## What Is Preserved

- Existing warehouse domain logic.
- Existing FIFO and 24-hour drying tests.
- Existing CV v4 trained artifact.
- Existing operator/jury/admin frontend split.
- Existing robot task and Digital Twin runtime.

## Known Limits

- The original challenge PDF was not found in this workspace; scoring docs use the 160-point table from the pasted brief.
- The full 3D mechanical scene is still a pseudo-3D/SVG Digital Twin, not a Three.js CAD-accurate simulation.
- Backend pytest could not be run until `pytest` is installed in the backend Python environment.

# Smart Core Warehouse V8 Validation

## Verified in this environment

- Backend Python tests: **19/19 PASS**
- Existing warehouse business rules remain covered by the suite.
- Weight-based quantity calibration test: PASS.
- Backend import/startup: PASS.
- `GET /health`: HTTP 200.
- `GET /api/v1/capture/station`: PASS.
- `POST /api/v1/capture/demo-arrival`: PASS.
- `POST /api/v1/capture/analyze` with demo scale + automatic registration: PASS.
- Automatic registration created a real `STORE_BOX` robot task and reserved the destination: PASS.
- Demo state was reset after endpoint validation.
- TS/TSX syntax transpilation check: **25 files / 0 syntax errors**.

## Not verified here

- Full `npm install` / Vite production build: npm registry access is not available/reliable in this execution environment.
- Real MobileNetV3 model accuracy: the actual trained artifact/dataset is not mounted in this repository; no accuracy claim is made.
- Real physical scale integration: requires the team's scale/ESP/HTTP gateway.
- Browser camera permission: must be tested in the target browser on `localhost` or HTTPS.

## Important modeling boundary

The existing CV V1 specification classifies one of the known core types. V8 does **not** pretend that the classifier counts cores visually. Quantity is derived from the scale using calibrated per-core unit weight. This provides a working live quantity simulation while keeping visual counting as a future CV extension.

## V10 validation
- Backend regression: 19/19 pytest tests passed.
- Frontend TS/TSX syntax transpilation: 25 files passed.
- V10 UI changes are frontend-only over the validated V8/V9 backend autonomy, routing and capture workflows.

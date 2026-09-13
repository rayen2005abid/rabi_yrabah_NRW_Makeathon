# NRW Acceptance Matrix

| Criterion | Points | Implementation | Live demonstration | Automated test | Manual test | Current status | Evidence |
|---|---:|---|---|---|---|---|---|
| Understanding need | 10 | Operator/presentation/admin split, autonomous WMS flow | Factory Console and Demo Showcase | Frontend typecheck/build | Walk through 5-7 min demo | PARTIAL | `README.md`, `docs/integration/I_UX.md` |
| Core identification | 15 | CV v4 EfficientNet-B0 service, warehouse adapter contract | Upload/camera image through capture station | CV tests exist; not run here | Start CV API and classify sample | PARTIAL | `docs/integration/B_CV_AUDIT.md`, `cv_simple_v4/api/main.py` |
| Quantity | 15 | Weight calibration primary quantity estimate | Demo arrival or capture station weight | `test_weight_based_quantity_estimation_uses_core_calibration` | Change weight and verify quantity | IMPLEMENTED | `backend/app/capture_station/service.py` |
| 24h drying | 10 | `ready_at = entered_at + 24h` | Advance demo clock from 23h59 to 24h00 | `test_drying_rule_exact_24h` | Use drying scenario | IMPLEMENTED | `backend/app/drying/service.py` |
| FIFO | 15 | Strict ready-stock FIFO | CORE-A x55 scenario | `test_required_fifo_fulfillment_business_case` | Show A01/A02/A03 plan | IMPLEMENTED | `backend/tests/test_business_rules.py` |
| Automatic correct box | 15 | Backend slotting, reservation, robot task creation | Automatic entry scenario | Intake tests exist | Run `capture_auto` | PARTIAL | `backend/app/intake/service.py`, `backend/app/slotting/service.py` |
| 3D mechanical simulation | 25 | Backend phases and pseudo-3D/SVG visual twin | Live Robot Path page | Robot path tests exist | Watch lift/fork/carry/unload | PARTIAL | `backend/app/digital_twin/runtime.py`, `frontend/src/features/DigitalTwin.tsx` |
| Realtime dashboard | 15 | WebSocket fanout plus dashboard refresh | Live Warehouse/Factory Console | Frontend build | Observe updates during scenario | PARTIAL | `backend/app/realtime/manager.py` |
| Embedded simulation | 15 | Backend telemetry state plus Wokwi files | Open Wokwi, send telemetry JSON | `test_embedded_telemetry_state_contract` added; not run due missing pytest | POST telemetry and view state | PARTIAL | `embedded/wokwi/*`, `backend/app/embedded/state.py` |
| Innovation | 10 | Explainable decisions, what-if/fault foundation | Predicted issue scenario target | Existing simulation/fault tests | Show prediction before fault | PARTIAL | `docs/integration/G_PREDICTIVE_ENGINE.md` |
| Oral/demo readiness | 15 | Demo Showcase and script | 5-7 minute scripted demo | Frontend build | Reset and run script | PARTIAL | `docs/presentation/DEMO_SCRIPT.md` |
| TOTAL | 160 |  |  |  |  | PARTIAL | Final score gate required before PASS claims |

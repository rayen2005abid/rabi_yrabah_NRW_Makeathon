# Smart Core Warehouse — Implementation Analysis

## A. Architecture

The backend is a modular monolith. FastAPI is the command/query boundary, PostgreSQL is the authoritative logical state, and domain services own warehouse decisions. The execution chain is deliberately split into command → plan → simulation → validation → task scheduling → embedded adapter → telemetry/ACK → reconciliation → state/event persistence. The external CV system is represented only by a gateway. The frontend is a React operator console and never selects boxes, FIFO order, or storage slots.

A central persistence model is used to keep referential constraints explicit, while behavior remains separated by domain service modules. This avoids a microservice split that would introduce distributed transactions into a safety-sensitive POC.

## B. Module boundaries

- `catalog`: core-type lifecycle; history is preserved through deactivation.
- `cv_gateway`: external CV HTTP contract and deterministic mock.
- `intake`: CV validation, box creation and initial slot allocation.
- `inventory`: active box queries and row-lock helpers.
- `warehouse`: geometry generation, occupancy and slot facts.
- `drying`: exact 24-hour readiness rule using the Clock abstraction.
- `production`: production-request lifecycle helpers.
- `fifo`: strict per-core-type eligible-box ordering.
- `fulfillment`: non-mutating quantity allocation plan persistence.
- `slotting`: hard feasibility filters and deterministic weighted ranking.
- `partial_returns`: stable boundary over partial-return orchestration.
- `picking`: actual quantity confirmation and return/empty decisions.
- `buffers`: physical buffer queries.
- `robot`: semantic path planning, tasks and one-robot queue.
- `scheduling`: scheduler boundary.
- `safety`: deterministic software interlocks.
- `simulation`: cloned/snapshot state calculations, timeline and what-if queries.
- `digital_twin`: read model for slots, stations, buffers and robot state.
- `faults`: fault injection/clearing and coherent degraded mode.
- `embedded`: hardware-independent adapter contract, mock, MQTT skeleton and reconciliation.
- `events`: immutable append-only domain-event creation.
- `alerts`: operational alerts.
- `analytics`: KPI read model.
- `demand_forecasting`: swappable forecast interface with rule-based 30-day fallback.
- `realtime`: WebSocket fanout.
- `api`: versioned REST/WebSocket boundary.
- `system_configuration`: safe public configuration read model.

## C. Database model proposal

Core entities: `core_types`, `boxes`, `slots`, `vision_results`, `production_requests`, `fulfillment_plans`, `fulfillment_plan_items`, `robot_tasks`, `robot_telemetry`, `simulation_runs`, `faults`, `alerts`, `domain_events`, `system_settings`, `demand_forecasts`.

Uniqueness on `slots.box_id` enforces that a box cannot occupy two physical slots. Uniqueness on `boxes.current_slot_id` prevents two boxes from claiming the same current location in the logical read model. Execution uses row locking before reservation. Slot occupancy and box location are updated transactionally.

## D. State machines

Box state is explicit and validated by `core/state_machine.py`. Important execution paths are:

`REGISTERING → DRYING → READY → RESERVED → RETRIEVAL_PLANNED → IN_TRANSIT → AT_PICKING → RETURN_PLANNED → RETURNING → READY`

or `AT_PICKING → EMPTY`.

Robot tasks use `QUEUED → DISPATCHED → RUNNING → COMPLETED`, with `FAILED` / `INTERRUPTED` as explicit non-success states.

Production requests use `PENDING → PLANNING → SIMULATING/APPROVED → EXECUTING → COMPLETED`, with explicit partial/rejected/failed/cancelled alternatives.

## E. Event model

Important state changes append `domain_events`: box registration/storage/readiness, request creation, plan creation, simulation pass/fail, task creation/start/completion/failure, picking quantity update, return, emptying, and fault raise/clear. Events carry aggregate type/id, timestamp and structured payload and are also fanned out to connected WebSocket clients.

## F. Main API routes

Versioned under `/api/v1`: catalog, boxes/history, intake, warehouse state, production planning/simulation/execution, picking confirmation, robot tasks/state, pure what-if simulations, demo clock, faults, events, alerts, analytics, demand forecast, configuration, digital twin, health and WebSocket `/ws`.

## G. Repository tree

See `README.md` and the actual tree in the repository. Backend domain modules are under `backend/app`, frontend features under `frontend/src/features`, and physical/timing configuration under `config`.

## H. Implementation phases

Foundation → static domain → business rules → storage/returns → simulation → robot → embedded abstraction → faults → forecasting hooks → frontend → realtime → demo → QA. Tests are run after backend rule/execution changes. The final verification record is in `VALIDATION.md`.

## I. Assumptions

- One plastic box occupies one physical location at a time.
- A slot's effective dimensions are configured; current POC boxes use the shared 50×30×20 cm nominal format and one-box-per-cell capacity.
- Picking removes pieces only after `CONFIRM_PICK`; the individual picking mechanism is outside scope.
- The mock embedded adapter supplies the ACK/telemetry path in development; MQTT is intentionally non-operational until broker/topic details are provided.
- Authentication/roles were not specified, so the POC does not invent an identity scheme.

## J. Unresolved risks

- Real robot motion envelopes, acceleration limits, collision zones and PLC/MCU topic/protocol details require mechanical/embedded validation.
- Real CV image transport/authentication and its failure/retry contract are not yet defined.
- PostgreSQL row locks are used in the reservation path, but production deployment still needs load/concurrency testing under realistic request rates.
- The current simulation is operational/discrete-event, not physics/CAD simulation by design.
- The frontend dependency/build toolchain requires npm registry access at install time.

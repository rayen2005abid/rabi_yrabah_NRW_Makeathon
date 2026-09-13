# D. Domain Rules Audit

## Summary

The main warehouse rules are implemented in backend services rather than the frontend. FIFO, drying eligibility, production planning, simulation, robot queueing, slotting, and partial returns are separated into domain modules.

The canonical FIFO scenario is implemented and tested:

- Request: `CORE-A x 55`
- Picks: `A01=10`, `A02=30`, `A03=15`
- Remainder: `A03=25`
- Excluded: `A04`, because it is still drying

## Evidence

- `backend/app/fifo/service.py` refreshes readiness, filters ready boxes with positive quantity and a current slot, then orders by `entered_at ASC, code ASC`.
- `backend/app/drying/service.py` defines `ready_at = entered_at + 24h` and readiness as `now >= ready_at`.
- `backend/tests/test_business_rules.py` verifies the exact 24-hour boundary.
- `backend/tests/test_business_rules.py` verifies the canonical FIFO business case.
- `backend/app/fulfillment/service.py` builds non-mutating FIFO fulfillment plans and records quantity before/after each pick.
- `backend/app/api/routes.py` prevents production execution unless the latest simulation has passed.
- `backend/app/robot/service.py` re-checks readiness, quantity, source occupancy, and reservations at queue time.
- `backend/tests/test_partial_return.py` verifies partial returns preserve original `entered_at` and `ready_at`.
- `backend/tests/test_more_domain.py` verifies shortage handling does not use drying stock.

## Rules Status

| Rule | Status | Evidence |
|---|---|---|
| Box enters warehouse | Implemented | Intake and capture routes create boxes and storage tasks. |
| `entered_at` immutable | Implemented by convention | No update path found; partial return test protects timestamp. |
| `ready_at = entered_at + 24h` | Tested | Drying boundary test. |
| No use before 24h | Tested | FIFO filters ready stock only; shortage tests reject drying stock. |
| Strict FIFO among ready stock | Tested | Canonical CORE-A x55 test. |
| Partial picks preserve timestamp | Tested | Partial-return timestamp test. |
| Return does not reset drying | Tested | Partial-return timestamp test. |
| Software chooses box | Implemented | Fulfillment planner chooses boxes. |
| Software chooses storage location | Implemented | Slotting service chooses slot. |
| Software chooses robot tasks | Implemented | Robot queue is backend-created. |
| Operator requests type and quantity only | Implemented in main production flow | Frontend production request captures core type and quantity. |

## Risks

- Simulation validation flags rely on planner behavior rather than fully recomputing FIFO/drying independently.
- Existing plans can become stale and are caught later by simulation or queue-time checks.
- SQLite-style local tests do not fully prove PostgreSQL row-lock behavior under real concurrency.
- What-if production eligibility should stay aligned with canonical FIFO eligibility.

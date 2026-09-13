# Five-minute supervisor demo

The easiest path is the new **Demo Lab** page. The database is already seeded; no preparation step is required.

## 1 — Verify deterministic starting state

Open **Demo Lab**. You should see 5 core types, 16 boxes, READY + DRYING stock, free locations, and robot HOME/IDLE. If anything was changed earlier, click **Reset seeded demo**.

## 2 — Required FIFO scenario

Click **Run FIFO planning & simulation** for the preconfigured `CORE-A × 55` scenario.

Expected:

```text
A01: 10 -> take 10 -> 0
A02: 30 -> take 30 -> 0
A03: 40 -> take 15 -> 25
A04: untouched because it is still drying
```

The UI shows FIFO, 24h drying, safety and overall simulation validation.

## 3 — Queue and animate the real workflow

Click **Queue real execution**, then **Run next robot task**. The Digital Twin uses backend task state and telemetry to animate:

```text
MOVE_TO_SOURCE -> PICKING_UP -> MOVE_TO_TARGET -> UNLOADING -> ACK
```

When a box reaches PICKING, the UI shows the planned removal quantity. Click **Confirm planned pick**. Empty boxes are released; partial boxes create a safe return task while preserving their original timestamp.

## 4 — Drying rule

In Demo Lab or Configuration click **+24h**. Boxes whose exact `ready_at` has passed become READY.

## 5 — Intake / CV gateway

Open **New Box**. Submit a mock CV result such as `CORE-A`, 30 pieces, confidence `0.96`. The backend validates confidence, registers the box, chooses the storage location and creates the robot storage task automatically.

## 6 — Fault recovery

In Demo Lab click **Inject Z-axis fault**. Robot dispatch is blocked by backend safety. Clear the fault and continue. Fault history and alerts remain traceable.

## 7 — What-if

Open **What-If** and simulate production, incoming boxes, time advancement, blocked slots, robot faults and near-full capacity. These previews do not mutate real warehouse inventory.

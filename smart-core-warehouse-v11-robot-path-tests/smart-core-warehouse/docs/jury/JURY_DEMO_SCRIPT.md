# Presentation Demo Script

Target duration: 5-7 minutes.

## Setup

1. Start the demo with `start_demo.bat`.
2. Open the frontend.
3. Open **Demo Showcase**.
4. Click **Reset demo**.

## Flow

1. Click **Automatic entry**.
   - Expected: image/type simulation, stable weight, quantity, box registration, drying timer, slot reservation, robot task.

2. Open **Live Robot Path**.
   - Expected: robot follows source-to-target route, enters rack/station, lift moves, fork extends, box is carried, target is updated.

3. Return to **Demo Showcase** and click **+24h drying**.
   - Expected: 23h59 is not ready, 24h00 becomes ready.

4. Click **FIFO CORE-A x55**.
   - Expected: A01 gives 10, A02 gives 30, A03 gives 15, A03 remains 25, A04 is untouched.

5. Open **Live Robot Path** again.
   - Expected: retrieval tasks run through the same backend route and Digital Twin movement.

6. Click **Partial return**.
   - Expected: remaining A03 quantity returns without resetting `entered_at` or `ready_at`.

7. Click **Multiple orders**.
   - Expected: one robot processes queued tasks in order.

8. Click **Embedded sensor fault** or send telemetry manually:
   - `POST /api/v1/embedded/telemetry`
   - Expected: **ESP32 ONLINE**, weight, entry sensor, limits, fork, and E-stop values appear in backend state.

9. Click **Predicted issue** if available in the UI.
   - Expected: show a risk/alert before it becomes a hard fault. If not available, present the current decision trace as the implemented innovation foundation.

## Closing Line

This is not a manual robot dashboard. The operator only provides demand or places a box; the system identifies, counts, timestamps, applies drying/FIFO rules, chooses the physical slot and box, plans the route, dispatches the robot, and visualizes the same backend state in the Digital Twin.

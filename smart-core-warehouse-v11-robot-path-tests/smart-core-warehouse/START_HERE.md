# Smart Core Warehouse V6 — Start Here

## Fastest Windows demo

From the extracted project root, run:

```powershell
.\start_demo.bat
```

The package is pre-seeded. You do **not** need to seed manually.

Backend:
- `http://localhost:8000/health`
- `http://localhost:8000/docs`

Frontend:
- `http://localhost:5173`

## Recommended test

1. Open **Production**.
2. Keep `CORE-A` and `55`.
3. Click **Check availability & build plan**.
4. Verify PASS: FIFO + 24h drying + safety.
5. Click **Approve & run**.
6. Open **Live Warehouse**.
7. Watch the robot execute automatically.

The Live Warehouse now shows:
- the per-order robot movement sequence,
- the 6m × 6m conceptual passage map,
- the active A* path,
- the current source and destination,
- the active 8×8 rack face,
- why the intelligent system made the decision,
- candidate destinations and scores when relevant.

## Admin control

Open **Admin Panel** to switch between:
- `AUTO` — backend decides and executes automatically,
- `SUPERVISED` — backend decides; admin starts movement,
- `MANUAL` — admin can send the robot to a chosen location.

The Admin Panel can also:
- send the robot to a selected physical location,
- override a queued return/storage/manual target,
- inspect decision factors and candidate scores,
- start/stop/home the robot,
- change demo playback speed,
- inject/clear a robot fault.


## Best way to test V7

1. Run `start_demo.bat`.
2. Open **Scenario Lab** in the sidebar.
3. Start **New package arrival**, **Multiple orders**, or **Multiple package arrivals**.
4. Open **Live Simulation** to watch rack motion, passage movement and transfer-lane travel.
5. Use **Admin Panel** only for manual/supervised overrides.

## V8 quick demo

After the backend and frontend start:

- Factory/operator page: `http://localhost:5173/`
- Demo showcase: `http://localhost:5173/demo-showcase`
- Detailed robot movement: `http://localhost:5173/digital-twin`
- Admin/simulation controls: `http://localhost:5173/admin`

For a no-hardware demo, use **Demo Showcase**. It generates realistic capture-station events through the same backend registration and robot workflow.

For the factory capture page, allow browser camera permission. If camera permission is unavailable, use the Photo control. The scale is read automatically; in demo mode you can set a simulated scale value from the Admin Panel.

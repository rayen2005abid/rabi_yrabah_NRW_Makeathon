# F. Digital Twin

## Audit Status

The Digital Twin is backend-led. The backend owns warehouse state, robot runtime state, live execution phases, task decisions, telemetry, and final inventory mutation. The frontend renders snapshots and listens for WebSocket-triggered refreshes.

## Backend State

`backend/app/digital_twin/service.py` returns:

- warehouse geometry
- robot runtime state
- live execution snapshot
- picking station state
- slot and box state
- active task queue

`backend/app/digital_twin/runtime.py` separates:

- `floor_x/floor_y`: top-down floor movement
- `robot_runtime.x/y/z`: rack alignment, lift, and fork movement

## Current Frontend Behavior

`frontend/src/features/DigitalTwin.tsx` renders:

- top-down route
- moving robot marker
- route nodes
- active rack close-up
- lift and fork motion
- current decision explanation
- task queue

The frontend currently polls `GET /digital-twin` frequently and uses WebSocket messages mainly to invalidate cached queries.

## Gap Against Target

- WebSocket is not yet the primary transport for typed live state.
- Browser-side interpolation between 10-20 Hz backend updates is not formalized.
- The current display is pseudo-3D/SVG, not a full Three.js mechanical 3D scene.
- Live runtime is in-memory and resets on backend restart.
- Phase history is not persisted beyond sampled telemetry rows.

## Recommended Next Step

Keep the backend runtime as the source of truth, emit typed `robot.pose` and `robot.phase_changed` messages over the existing WebSocket, and add frontend interpolation on top of those messages. Then upgrade the visualization to a true 3D view without duplicating business logic in JavaScript.

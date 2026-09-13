# H. Embedded Simulation

## Goal

Provide a Wokwi-compatible ESP32 simulation for the live presentation demo and a backend telemetry contract for the dashboard.

## Required Telemetry

```json
{
  "device_id": "ESP32-ENTRY-01",
  "timestamp": "2026-09-13T10:00:00Z",
  "entry_present": true,
  "weight_kg": 12.72,
  "x_limit": false,
  "z_limit": false,
  "fork_extended": false,
  "estop": false
}
```

## Required Backend Endpoints

- `POST /api/v1/embedded/telemetry`
- `GET /api/v1/embedded/state`

## Demo Behavior

The Wokwi project should simulate:

- entry presence sensor
- weight/load-cell value
- camera trigger signal
- X limit/status
- Z limit/status
- fork status
- emergency stop
- task/status LEDs

If direct Wokwi-to-localhost networking is unreliable, use the Wokwi serial monitor values and the backend demo telemetry endpoint for the live demonstration.

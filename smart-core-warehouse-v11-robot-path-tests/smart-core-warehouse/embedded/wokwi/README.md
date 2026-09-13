# Wokwi ESP32 Simulation

This project simulates the Smart Core Warehouse entry/robot status signals for the jury demo.

## Fix: ESP32 platform not installed

If you see:

```text
Platform 'esp32:esp32' not found: platform not installed
```

install the ESP32 board package once:

```powershell
arduino-cli config init --overwrite
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

Then compile this sketch:

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32 ".\embedded\wokwi"
```

In Arduino IDE, open Board Manager, install `esp32 by Espressif Systems`, then select `ESP32 Dev Module`.

If you use Wokwi with PlatformIO instead, this folder also includes `platformio.ini`, and `wokwi.toml` points at the PlatformIO firmware output.

## Signals

- Entry presence switch
- Weight potentiometer, scaled to 0-25 kg
- X limit switch
- Z limit switch
- Fork extended switch
- Emergency stop button
- Online, task, and fault LEDs

## Backend Contract

Send the JSON printed in the Wokwi serial monitor to:

```text
POST http://localhost:8000/api/v1/embedded/telemetry
```

Example:

```json
{
  "device_id": "ESP32-ENTRY-01",
  "entry_present": true,
  "weight_kg": 12.72,
  "x_limit": false,
  "z_limit": false,
  "fork_extended": false,
  "estop": false
}
```

Then view:

```text
GET http://localhost:8000/api/v1/embedded/state
```

Wokwi browser networking to localhost can vary by environment, so the serial JSON is the reliable live-demo bridge.

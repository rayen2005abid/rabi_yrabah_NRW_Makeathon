def test_embedded_telemetry_state_contract(client):
    payload = {
        "device_id": "ESP32-ENTRY-01",
        "entry_present": True,
        "weight_kg": 12.72,
        "x_limit": False,
        "z_limit": True,
        "fork_extended": False,
        "estop": False,
    }
    response = client.post("/api/v1/embedded/telemetry", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ESP32 ONLINE"
    assert body["online"] is True
    assert body["entry_present"] is True
    assert body["weight_kg"] == 12.72
    assert body["z_limit"] is True

    state = client.get("/api/v1/embedded/state")
    assert state.status_code == 200
    assert state.json()["device_id"] == "ESP32-ENTRY-01"

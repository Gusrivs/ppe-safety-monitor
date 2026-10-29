import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.device.simulated import SimulatedDevice
from app.main import create_app


class FakeCamera:
    ok = False

    def start(self): ...
    def stop(self): ...

    def read(self):
        return None, 0


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.storage.data_dir = str(tmp_path)
    settings.device.simulate = True
    sim = SimulatedDevice(heartbeat_s=None, enroll_step_s=0.02)
    app = create_app(settings, device=sim, camera=FakeCamera())
    with TestClient(app) as c:
        c.sim = sim
        sim.flush()
        yield c


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def inject(client, **event):
    assert client.post("/api/sim/event", json={"event": event}).status_code == 200
    client.sim.flush()


def enroll(client, name="Ana Pérez"):
    worker = client.post("/api/workers", json={"name": name, "code": "T-1"}).json()
    assert client.post(f"/api/workers/{worker['id']}/fingerprint").status_code == 202
    assert wait_until(lambda: client.get(f"/api/workers/{worker['id']}").json()["has_fingerprint"])
    return client.get(f"/api/workers/{worker['id']}").json()


def test_health_and_status(client):
    assert client.get("/api/health").json()["ok"] is True
    status = client.get("/api/status").json()
    assert status["device_online"] is True and status["state"] == "IDLE"
    assert status["simulated_device"] is True


def test_worker_crud(client):
    worker = client.post("/api/workers", json={"name": "Luis", "code": "A-9", "role": "Albañil"}).json()
    assert worker["id"] and worker["has_fingerprint"] is False
    assert client.post("/api/workers", json={"name": "Otro", "code": "A-9"}).status_code == 409
    updated = client.put(f"/api/workers/{worker['id']}", json={"role": "Maestro de obra"}).json()
    assert updated["role"] == "Maestro de obra" and updated["name"] == "Luis"
    assert len(client.get("/api/workers").json()) == 1
    assert client.delete(f"/api/workers/{worker['id']}").status_code == 204
    assert client.get("/api/workers").json() == []
    assert client.get(f"/api/workers/{worker['id']}").status_code == 404


def test_full_entry_flow_through_api(client):
    worker = enroll(client)
    slot = worker["fingerprint_slot"]

    inject(client, evt="presence", sensor=1)
    assert client.get("/api/status").json()["state"] == "ENTRY_AUTH"
    assert client.get("/api/sim/state").json()["lcd"][0] == "Ponga su huella"

    inject(client, evt="finger", result="match", slot=slot)
    assert client.get("/api/status").json()["state"] == "ENTRY_WAIT_CROSS"
    assert client.get("/api/sim/state").json()["door_open"] is True

    inject(client, evt="presence", sensor=2)
    client.sim.flush()
    assert client.get("/api/workers").json()[0]["inside"] is True
    rows = client.get("/api/attendance").json()
    assert len(rows) == 1 and rows[0]["direction"] == "IN" and rows[0]["worker_name"] == "Ana Pérez"
    summary = client.get("/api/attendance/summary").json()
    assert summary[0]["inside"] is True and summary[0]["first_in"]

    csv = client.get("/api/reports/attendance.csv")
    assert csv.status_code == 200 and "Entrada" in csv.text and "Ana Pérez" in csv.text
    assert wait_until(lambda: client.get("/api/status").json()["state"] == "IDLE", timeout=3)


def test_intruder_flow_and_events(client):
    inject(client, evt="presence", sensor=1)
    for _ in range(3):
        inject(client, evt="finger", result="nomatch")
    assert client.get("/api/sim/state").json()["lcd"] == ["VETE!!", "Acceso denegado"]
    events = client.get("/api/events?level=alarm").json()
    assert any(e["type"] == "intruder_alert" for e in events)
    attempts = client.get("/api/access-attempts").json()
    assert [a["result"] for a in attempts].count("no_match") == 3


def test_assistance_button_and_attend(client):
    inject(client, evt="assist", where="entrance")
    open_requests = client.get("/api/assistance?status=open").json()
    assert len(open_requests) == 1 and open_requests[0]["source"] == "entrance"
    assert client.get("/api/status").json()["open_assistance"] == 1
    done = client.post(f"/api/assistance/{open_requests[0]['id']}/attend").json()
    assert done["status"] == "attended"
    assert client.get("/api/assistance?status=open").json() == []


def test_enroll_requires_idle(client):
    worker = client.post("/api/workers", json={"name": "Luis"}).json()
    inject(client, evt="presence", sensor=1)
    assert client.post(f"/api/workers/{worker['id']}/fingerprint").status_code == 409


def test_websocket_receives_status_and_events(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["kind"] == "status"
        inject(client, evt="assist", where="work_area")
        kinds = {ws.receive_json()["kind"] for _ in range(2)}
        assert "event" in kinds


def test_video_placeholder_and_snapshot(client):
    response = client.get("/api/snapshot.jpg")
    assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"


def test_violation_snapshot_is_confined_to_data_dir(client, tmp_path):
    outside = tmp_path.parent / "secret.jpg"
    outside.write_bytes(b"x")
    vid = client.app.state.ctx.db.record_violation(
        worker_id=None, track_id=1, missing=["helmet"], started_at=None, snapshot_path=str(outside))
    assert client.get(f"/api/violations/{vid}/snapshot").status_code == 404


def test_violations_report(client):
    ctx = client.app.state.ctx
    ctx.db.record_violation(worker_id=None, track_id=3, missing=["helmet", "vest"],
                            started_at=None, snapshot_path=None)
    csv = client.get("/api/reports/violations.csv").text
    assert "SIN ID" in csv and "casco y chaleco" in csv
    assert client.get("/api/violations").json()[0]["track_id"] == 3


def test_bad_date_is_rejected(client):
    assert client.get("/api/attendance?date_from=ayer").status_code == 422

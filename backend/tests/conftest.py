import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # raíz del proyecto (paquete ml)

from app.access.controller import AccessController  # noqa: E402
from app.config import AccessConfig  # noqa: E402
from app.db import Database  # noqa: E402
from app.events import EventBus  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeDevice:
    def __init__(self) -> None:
        self.connected = True
        self.listener = None
        self.commands: list[dict] = []

    def start(self): ...
    def stop(self): ...

    def send(self, command):
        self.commands.append(command)

    def sent(self, cmd: str) -> list[dict]:
        return [c for c in self.commands if c.get("cmd") == cmd]

    def last_lcd(self):
        lcds = self.sent("lcd")
        return (lcds[-1]["l1"], lcds[-1]["l2"]) if lcds else None


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def device():
    return FakeDevice()


@pytest.fixture
def callbacks():
    return {"entered": [], "exited": []}


@pytest.fixture
def controller(db, device, clock, callbacks):
    bus = EventBus(db)
    ctrl = AccessController(
        AccessConfig(), db, bus, device, clock=clock,
        on_entered=lambda wid, name: callbacks["entered"].append(wid),
        on_exited=lambda wid, name: callbacks["exited"].append(wid),
    )
    ctrl.handle_event({"evt": "hello"})   # el Arduino está en línea
    device.commands.clear()
    return ctrl


@pytest.fixture
def worker(db):
    w = db.create_worker("Ana Pérez", code="T-001")
    return db.update_worker(w["id"], fingerprint_slot=1)

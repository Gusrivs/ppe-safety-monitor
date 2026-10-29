import cv2
import numpy as np

from app.config import VisionConfig
from app.events import EventBus
from app.vision.ppe_association import Detection, PersonAssessment
from app.vision.worker import VisionWorker


class FakePipeline:
    """Devuelve una persona (track 1) con el estado que se le indique."""

    def __init__(self):
        self.status = "compliant"
        self.track_id = 1
        self.visible = True

    def process(self, frame):
        if not self.visible:
            return [], []
        missing = ("helmet",) if self.status == "not_detected" else ()
        a = PersonAssessment(1, self.track_id, (50, 300, 150, 650), 0.9, self.status == "compliant",
                             None, self.status == "compliant", None, self.status, (), missing)
        return [a], [Detection("reflective_jacket", 0.9, (60, 400, 140, 500))]


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def make_worker(db, tmp_path, pipeline, clock):
    cfg = VisionConfig(enabled=True, entry_zone=[0.0, 0.0, 0.4, 1.0])
    return VisionWorker(cfg, camera=None, db=db, bus=EventBus(db), captures_dir=tmp_path,
                        pipeline=pipeline, clock=clock)


def step(worker, clock, seconds, frame):
    for _ in range(int(seconds)):
        clock.now += 1
        worker.process_frame(cv2, frame)


def test_identified_worker_violation_is_recorded_with_snapshot(db, tmp_path):
    clock, pipeline = Clock(), FakePipeline()
    worker = make_worker(db, tmp_path, pipeline, clock)
    w = db.create_worker("Ana Pérez")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    worker.handle_entered(w["id"], w["name"])              # el sensor 2 confirmó el cruce
    step(worker, clock, 2, frame)
    assert worker.identity.worker_for(1) == w["id"]
    assert worker.tracks()[0]["name"] == "Ana Pérez"

    pipeline.status = "not_detected"
    step(worker, clock, 31, frame)
    rows = db.query("SELECT * FROM violations")
    assert len(rows) == 1
    assert rows[0]["worker_id"] == w["id"] and rows[0]["missing"] == "helmet"
    assert rows[0]["snapshot_path"] and (tmp_path / rows[0]["snapshot_path"].split(str(tmp_path) + "/")[-1]).exists()
    assert any(e["type"] == "ppe_violation" for e in db.query("SELECT type FROM events"))

    pipeline.status = "compliant"
    step(worker, clock, 5, frame)
    assert db.query("SELECT ended_at FROM violations")[0]["ended_at"] is not None


def test_unidentified_track_is_still_monitored(db, tmp_path):
    clock, pipeline = Clock(), FakePipeline()
    pipeline.status = "not_detected"
    worker = make_worker(db, tmp_path, pipeline, clock)
    step(worker, clock, 31, np.zeros((720, 1280, 3), dtype=np.uint8))
    rows = db.query("SELECT * FROM violations")
    assert len(rows) == 1 and rows[0]["worker_id"] is None and rows[0]["track_id"] == 1


def test_handoff_failure_is_reported_when_camera_sees_nobody(db, tmp_path):
    clock, pipeline = Clock(), FakePipeline()
    pipeline.visible = False
    worker = make_worker(db, tmp_path, pipeline, clock)
    w = db.create_worker("Luis")
    worker.handle_entered(w["id"], w["name"])
    step(worker, clock, 16, np.zeros((720, 1280, 3), dtype=np.uint8))
    assert any(e["type"] == "handoff_failed" for e in db.query("SELECT type FROM events"))


def test_exited_worker_is_no_longer_monitored(db, tmp_path):
    clock, pipeline = Clock(), FakePipeline()
    worker = make_worker(db, tmp_path, pipeline, clock)
    w = db.create_worker("Luis")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    worker.handle_entered(w["id"], w["name"])
    step(worker, clock, 2, frame)
    worker.handle_exited(w["id"], w["name"])
    pipeline.status = "not_detected"          # se quita el casco al salir
    step(worker, clock, 40, frame)
    assert db.query("SELECT * FROM violations") == []

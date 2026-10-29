"""Hilo de visión: cámara -> IA -> identidad -> infracciones -> video en vivo."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ..config import VisionConfig
from ..db import Database
from ..events import EventBus
from .drawing import draw_frame
from .identity import IdentityTracker
from .ppe_association import Detection, PersonAssessment
from .recorder import Recorder
from .violations import MonitorEvent, Observation, ViolationMonitor

log = logging.getLogger("epp.vision")


class Pipeline(Protocol):
    def process(self, frame: Any) -> tuple[list[PersonAssessment], list[Detection]]: ...


class VisionWorker:
    def __init__(
        self,
        cfg: VisionConfig,
        camera: Any,
        db: Database,
        bus: EventBus,
        captures_dir: Path,
        *,
        pipeline: Pipeline | None,
        recorder: Recorder | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.camera = camera
        self.db = db
        self.bus = bus
        self.captures_dir = captures_dir
        self.pipeline = pipeline
        self.recorder = recorder
        self.clock = clock
        zone = tuple(cfg.entry_zone)
        self.identity = IdentityTracker(zone, cfg.handoff_window_s, cfg.handoff_lookback_s)  # type: ignore[arg-type]
        self.monitor = ViolationMonitor(cfg.violation_seconds, cfg.cooldown_seconds,
                                        cfg.compliance_reset_seconds, cfg.track_lost_seconds)
        self.latest_jpeg: bytes | None = None
        self.jpeg_counter = 0
        self.fps = 0.0
        self._tracks_view: list[dict[str, Any]] = []
        self._open_violations: dict[str, int] = {}
        self._worker_names: dict[int, str] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self.recorder:
            self.recorder.close()

    # ------------------------------------------------- llamadas del control de acceso
    def handle_entered(self, worker_id: int, name: str) -> None:
        with self._lock:
            self._worker_names[worker_id] = name
            self.identity.request_handoff(worker_id, name, self.clock())

    def handle_exited(self, worker_id: int, name: str) -> None:
        with self._lock:
            self.identity.release_worker(worker_id)

    def assign_track(self, track_id: int, worker_id: int) -> bool:
        worker = self.db.get_worker(worker_id)
        if not worker:
            return False
        with self._lock:
            self._worker_names[worker_id] = worker["name"]
            self.identity.assign(track_id, worker_id)
        self.bus.publish("identity_assigned", f"{worker['name']} asignado manualmente al track {track_id}",
                         data={"track_id": track_id, "worker_id": worker_id, "manual": True})
        return True

    def tracks(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._tracks_view)

    # ---------------------------------------------------------------- bucle
    def _run(self) -> None:
        import cv2

        min_interval = 1.0 / self.cfg.max_fps if self.cfg.max_fps > 0 else 0.0
        last_counter = -1
        last_time = 0.0
        while not self._stop.is_set():
            frame, counter = self.camera.read()
            if frame is None or counter == last_counter:
                self._stop.wait(0.01)
                continue
            if min_interval and self.clock() - last_time < min_interval:
                self._stop.wait(0.005)
                continue
            last_counter = counter
            started = self.clock()
            try:
                annotated = self.process_frame(cv2, frame)
            except Exception:
                log.exception("Error procesando un fotograma")
                annotated = frame
            ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                self.latest_jpeg = buffer.tobytes()
                self.jpeg_counter += 1
            if self.recorder:
                self.recorder.write(frame)
            elapsed = self.clock() - started
            if elapsed > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / max(elapsed, 1e-3)) if self.fps else 1.0 / elapsed
            last_time = started

    def process_frame(self, cv2: Any, frame: Any) -> Any:
        """Procesa un fotograma y devuelve la imagen anotada (separado para poder probarlo)."""
        if self.pipeline is None:
            return frame
        now = self.clock()
        assessments, equipment = self.pipeline.process(frame)
        height, width = frame.shape[:2]
        with self._lock:
            tracked = [(a.track_id, a.box) for a in assessments if a.track_id is not None]
            new, expired = self.identity.update(now, tracked, (width, height))
            for track_id, worker_id, name in new:
                self.bus.publish("identity_assigned", f"{name} asociado al track {track_id} de la cámara",
                                 data={"track_id": track_id, "worker_id": worker_id})
            for pending in expired:
                self.bus.publish("handoff_failed",
                                 f"La cámara no vio entrar a {pending.name}; revisa el video",
                                 level="warning", data={"worker_id": pending.worker_id})

            observations: list[Observation] = []
            names: dict[int, str] = {}
            view: list[dict[str, Any]] = []
            for a in assessments:
                if a.track_id is None:
                    continue
                worker_id = self.identity.worker_for(a.track_id)
                if a.track_id in self.identity.ignored:
                    continue
                if worker_id is not None:
                    names[a.track_id] = self._worker_names.get(worker_id) or self._load_name(worker_id)
                observations.append(Observation(a.track_id, a.status, a.missing, worker_id))
                x1, y1, x2, y2 = a.box
                view.append({"track_id": a.track_id, "worker_id": worker_id,
                             "name": names.get(a.track_id), "status": a.status, "missing": list(a.missing),
                             "box": [x1 / width, y1 / height, x2 / width, y2 / height]})
            self._tracks_view = view
            events = self.monitor.update(now, observations)

        annotated = draw_frame(cv2, frame, assessments, equipment, names)
        for event in events:
            self._handle_monitor_event(cv2, event, annotated, names)
        return annotated

    # ------------------------------------------------------------ infracciones
    def _handle_monitor_event(self, cv2: Any, event: MonitorEvent, annotated: Any, names: dict[int, str]) -> None:
        if event.kind == "violation":
            path = self._save_snapshot(cv2, annotated, event)
            started = datetime.fromtimestamp(time.time() - event.duration_s).isoformat(timespec="seconds")
            violation_id = self.db.record_violation(
                worker_id=event.worker_id, track_id=event.track_id, missing=list(event.missing),
                started_at=started, snapshot_path=str(path) if path else None)
            self._open_violations[event.key] = violation_id
            who = names.get(event.track_id) or (self._load_name(event.worker_id) if event.worker_id else None)
            piezas = " y ".join({"helmet": "casco", "vest": "chaleco"}.get(m, m) for m in event.missing)
            subject = who or f"persona sin identificar (track {event.track_id})"
            self.bus.publish("ppe_violation", f"{subject}: sin {piezas} durante {int(event.duration_s)} s",
                             level="alarm", data={"violation_id": violation_id, "worker_id": event.worker_id,
                                                  "track_id": event.track_id, "missing": list(event.missing)})
        elif event.kind == "resolved":
            violation_id = self._open_violations.pop(event.key, None)
            if violation_id is not None:
                self.db.close_violation(violation_id, event.duration_s)
                self.bus.publish("ppe_resolved", "La persona volvió a cumplir con el EPP",
                                 data={"violation_id": violation_id, "worker_id": event.worker_id})

    def _save_snapshot(self, cv2: Any, image: Any, event: MonitorEvent) -> Path | None:
        folder = self.captures_dir / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        key = re.sub(r"[^A-Za-z0-9_-]", "_", event.key)
        path = folder / f"violation_{datetime.now().strftime('%H%M%S')}_{key}.jpg"
        return path if cv2.imwrite(str(path), image) else None

    def _load_name(self, worker_id: int) -> str:
        worker = self.db.get_worker(worker_id)
        name = worker["name"] if worker else f"Trabajador {worker_id}"
        self._worker_names[worker_id] = name
        return name

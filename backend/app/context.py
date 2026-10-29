"""Ensambla todas las piezas del sistema (base de datos, Arduino, cámara, IA, acceso)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .access.controller import AccessController
from .config import Settings
from .db import Database
from .device.serial_link import SerialLink
from .device.simulated import SimulatedDevice
from .events import EventBus
from .vision.camera import CameraReader
from .vision.recorder import Recorder
from .vision.worker import VisionWorker

log = logging.getLogger("epp.context")


class AppContext:
    def __init__(self, settings: Settings, *, device: Any = None, camera: Any = None,
                 pipeline: Any = None, db: Database | None = None) -> None:
        self.settings = settings
        data_dir = settings.data_dir
        self.db = db or Database(data_dir / "epp.db")
        self.bus = EventBus(self.db)

        if device is None:
            if settings.device.simulate:
                device = SimulatedDevice()
            else:
                device = SerialLink(settings.device.port, settings.device.baud)
        self.device = device
        self.camera = camera or CameraReader(settings.camera.url, settings.camera.reconnect_s)

        self.pipeline = pipeline
        if self.pipeline is None and settings.vision.enabled:
            self.pipeline = self._load_pipeline()

        recorder = Recorder(data_dir / "recordings", enabled=settings.recording.enabled,
                            segment_minutes=settings.recording.segment_minutes, fps=settings.recording.fps)
        self.vision = VisionWorker(settings.vision, self.camera, self.db, self.bus,
                                   data_dir / "captures", pipeline=self.pipeline, recorder=recorder)
        self.access = AccessController(
            settings.access, self.db, self.bus, self.device,
            fingerprint_capacity=settings.device.fingerprint_capacity,
            on_entered=self.vision.handle_entered, on_exited=self.vision.handle_exited,
        )
        self.device.listener = self.access.handle_event
        self._ticker: asyncio.Task[None] | None = None

    def _load_pipeline(self) -> Any:
        try:
            from .vision.pipeline import PpePipeline

            return PpePipeline(self.settings.vision, self.settings.resolve_path(self.settings.vision.ppe_model))
        except Exception as exc:  # falta el modelo, ultralytics, etc.
            log.error("No se pudo cargar la IA: %s", exc)
            self.bus.publish("vision_unavailable", f"IA desactivada: {exc}", level="warning")
            return None

    # ------------------------------------------------------------------ ciclo
    async def start(self) -> None:
        self.bus.bind_loop(asyncio.get_running_loop())
        self.camera.start()
        self.vision.start()
        self.device.start()
        self._ticker = asyncio.create_task(self._tick_forever())
        self.bus.publish("system_started", "Sistema iniciado", data={
            "simulated_device": isinstance(self.device, SimulatedDevice),
            "vision_enabled": self.pipeline is not None,
        })

    async def stop(self) -> None:
        if self._ticker:
            self._ticker.cancel()
        self.device.stop()
        self.vision.stop()
        self.camera.stop()
        self.db.close()

    async def _tick_forever(self) -> None:
        while True:
            try:
                self.access.tick()
            except Exception:
                log.exception("Error en el temporizador del control de acceso")
            await asyncio.sleep(0.1)

    def status(self) -> dict[str, Any]:
        data = self.access.status()
        data.update({
            "camera_online": bool(self.camera.ok),
            "vision_enabled": self.pipeline is not None,
            "vision_fps": round(self.vision.fps, 1),
            "simulated_device": isinstance(self.device, SimulatedDevice),
            "open_assistance": self.db.one(
                "SELECT COUNT(*) AS n FROM assistance_requests WHERE status = 'open'")["n"],  # type: ignore[index]
        })
        return data

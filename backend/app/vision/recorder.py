"""Grabación opcional de video crudo en segmentos, con la hora impresa en cada fotograma."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("epp.recorder")


class Recorder:
    def __init__(self, directory: Path, *, enabled: bool, segment_minutes: float = 5.0, fps: float = 10.0) -> None:
        self.directory = directory
        self.enabled = enabled
        self.segment_s = segment_minutes * 60
        self.fps = fps
        self._writer: Any = None
        self._segment_started = 0.0
        self._last_write = 0.0

    def write(self, frame: Any) -> None:
        if not self.enabled:
            return
        import cv2

        now = time.monotonic()
        if now - self._last_write < 1.0 / self.fps:
            return
        if self._writer is None or now - self._segment_started >= self.segment_s:
            self._open_segment(cv2, frame, now)
        if self._writer is None:
            return
        stamped = frame.copy()
        cv2.putText(stamped, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        self._writer.write(stamped)
        self._last_write = now

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def _open_segment(self, cv2: Any, frame: Any, now: float) -> None:
        self.close()
        height, width = frame.shape[:2]
        folder = self.directory / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now().strftime('%H%M%S')}.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height))
        if not writer.isOpened():
            log.warning("No se pudo crear el archivo de grabación %s", path)
            self.enabled = False
            return
        self._writer = writer
        self._segment_started = now
        log.info("Grabando segmento %s", path)

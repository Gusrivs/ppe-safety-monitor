"""Lectura de la cámara IP en un hilo aparte: siempre entrega el ÚLTIMO fotograma.

OpenCV acumula frames en un búfer; si la IA tarda más que el intervalo entre frames,
el video se atrasa. Con este hilo, la IA procesa siempre lo más reciente y se
reconecta sola si el celular o la red se caen.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("epp.camera")


class CameraReader:
    def __init__(self, url: str | int, reconnect_s: float = 2.0) -> None:
        self.url = url
        self.reconnect_s = reconnect_s
        self.ok = False
        self.frame_counter = 0
        self.last_frame_at = 0.0
        self._frame: Any = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def read(self) -> tuple[Any, int]:
        """Devuelve (frame, número de frame). frame es None si aún no hay imagen."""
        with self._lock:
            return (None if self._frame is None else self._frame.copy()), self.frame_counter

    def _run(self) -> None:
        import cv2

        while not self._stop.is_set():
            capture = cv2.VideoCapture(self.url)
            self.ok = bool(capture.isOpened())
            if not self.ok:
                log.warning("No se pudo abrir la cámara %s", self.url)
            while not self._stop.is_set() and capture.isOpened():
                ret, frame = capture.read()
                if not ret:
                    break
                with self._lock:
                    self._frame = frame
                    self.frame_counter += 1
                    self.last_frame_at = time.monotonic()
            capture.release()
            self.ok = False
            self._stop.wait(self.reconnect_s)

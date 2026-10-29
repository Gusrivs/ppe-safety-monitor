"""Enlace serial (USB) con el Arduino UNO, con reconexión automática."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from .protocol import EventListener

log = logging.getLogger("epp.serial")


class SerialLink:
    def __init__(self, port: str, baud: int = 115200) -> None:
        self.port = port
        self.baud = baud
        self.connected = False
        self.listener: EventListener | None = None
        self._serial: Any = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="serial-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._close()

    def send(self, command: dict[str, Any]) -> None:
        line = (json.dumps(command, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        with self._write_lock:
            if not self._serial:
                log.warning("Comando descartado (sin conexión serial): %s", command)
                return
            try:
                self._serial.write(line)
            except Exception as exc:  # puerto desconectado a media escritura
                log.warning("Error de escritura serial: %s", exc)
                self._close()

    # ---------------------------------------------------------------- internals
    def _close(self) -> None:
        self.connected = False
        serial_obj, self._serial = self._serial, None
        if serial_obj:
            try:
                serial_obj.close()
            except Exception:
                pass

    def _open(self) -> bool:
        import serial  # pyserial; se importa aquí para poder probar sin el paquete

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0.5)
        except Exception as exc:
            log.warning("No se pudo abrir %s: %s", self.port, exc)
            self._serial = None
            return False
        time.sleep(2.0)  # abrir el puerto reinicia al Arduino UNO
        self._serial.reset_input_buffer()
        self.connected = True
        log.info("Serial conectado en %s", self.port)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._serial and not self._open():
                self._stop.wait(2.0)
                continue
            try:
                raw = self._serial.readline()
            except Exception as exc:
                log.warning("Error de lectura serial: %s", exc)
                self._close()
                continue
            if not raw:
                continue
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text.startswith("{"):
                continue  # ruido o mensajes de depuración
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                log.debug("Línea serial inválida: %r", text)
                continue
            if isinstance(event, dict) and self.listener:
                try:
                    self.listener(event)
                except Exception:
                    log.exception("Error procesando evento %s", event)

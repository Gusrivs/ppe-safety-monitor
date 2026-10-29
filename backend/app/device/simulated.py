"""Arduino simulado: permite desarrollar la interfaz y probar el flujo sin hardware.

Responde a los comandos como lo haría el firmware real. Los eventos de sensores y
huellas se inyectan con `inject()` (el backend expone POST /api/sim/event).
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from .protocol import EventListener


class SimulatedDevice:
    def __init__(self, heartbeat_s: float | None = 2.0, enroll_step_s: float = 0.4) -> None:
        self.connected = False
        self.listener: EventListener | None = None
        self.lcd: tuple[str, str] = ("", "")
        self.door_open = False
        self.auth_active = False
        self.commands: list[dict[str, Any]] = []   # historial, útil en pruebas
        self._heartbeat_s = heartbeat_s
        self._enroll_step_s = enroll_step_s
        self._events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._timers: list[threading.Timer] = []

    def start(self) -> None:
        self._stop.clear()
        self.connected = True
        self._threads = [threading.Thread(target=self._deliver, name="sim-device", daemon=True)]
        if self._heartbeat_s:
            self._threads.append(threading.Thread(target=self._beat, name="sim-heartbeat", daemon=True))
        for thread in self._threads:
            thread.start()
        self.inject({"evt": "hello", "fw": "sim"})

    def stop(self) -> None:
        self._stop.set()
        self.connected = False
        for timer in self._timers:
            timer.cancel()
        self._events.put(None)

    def inject(self, event: dict[str, Any]) -> None:
        """Simula un evento que llega desde el Arduino."""
        self._events.put(event)

    def flush(self, timeout: float = 2.0) -> None:
        """Espera a que se entreguen los eventos pendientes (para pruebas)."""
        done = threading.Event()
        self._events.put({"__flush__": done})
        done.wait(timeout)

    def send(self, command: dict[str, Any]) -> None:
        self.commands.append(command)
        cmd = command.get("cmd")
        if cmd == "lcd":
            self.lcd = (str(command.get("l1", "")), str(command.get("l2", "")))
        elif cmd == "door":
            self.door_open = bool(command.get("open"))
            self.inject({"evt": "door", "open": self.door_open})
        elif cmd == "auth_start":
            self.auth_active = True
            self._later(command.get("timeout_ms", 15000) / 1000.0, self._auth_timeout)
        elif cmd == "auth_cancel":
            self.auth_active = False
        elif cmd == "enroll":
            self._simulate_enroll(int(command["slot"]))
        elif cmd == "delete":
            self.inject({"evt": "deleted", "slot": command.get("slot"), "ok": True})

    # ---------------------------------------------------------------- internals
    def _later(self, seconds: float, func: Any, *args: Any) -> None:
        timer = threading.Timer(seconds, func, args)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    def _auth_timeout(self) -> None:
        if self.auth_active and not self._stop.is_set():
            self.auth_active = False
            self.inject({"evt": "finger", "result": "timeout"})

    def _simulate_enroll(self, slot: int) -> None:
        steps = ["place1", "remove", "place2", "ok"]
        for index, step in enumerate(steps, start=1):
            self._later(self._enroll_step_s * index, self.inject,
                        {"evt": "enroll", "step": step, "slot": slot})

    def _beat(self) -> None:
        while not self._stop.wait(self._heartbeat_s or 2.0):
            self.inject({"evt": "hb"})

    def _deliver(self) -> None:
        while True:
            event = self._events.get()
            if event is None or self._stop.is_set():
                return
            flush = event.get("__flush__")
            if flush is not None:
                flush.set()
                continue
            if event.get("evt") == "finger":
                self.auth_active = False
            if self.listener:
                try:
                    self.listener(event)
                except Exception:  # un error de la lógica no debe matar al simulador
                    import logging
                    logging.getLogger("epp.sim").exception("Error en listener")

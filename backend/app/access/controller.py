"""Máquina de estados del control de acceso (entrada / salida con huella).

Toda la política vive aquí, en la PC (intentos, tiempos, reglas). El Arduino solo
ejecuta comandos y reporta lo que sienten sus sensores.

Entrada:  sensor 1 -> huella (hasta N intentos) -> puerta abre -> sensor 2 confirma el cruce
Salida:   sensor 2 -> huella (hasta N intentos) -> puerta abre -> sensor 1 confirma el cruce
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable

from ..config import AccessConfig
from ..db import Database
from ..device.protocol import Device, lcd_safe
from ..events import EventBus

log = logging.getLogger("epp.access")

IDLE_SCREEN = ("EPP Monitor", "Esperando...")


class State(str, Enum):
    IDLE = "IDLE"
    ENTRY_AUTH = "ENTRY_AUTH"
    ENTRY_WAIT_CROSS = "ENTRY_WAIT_CROSS"
    EXIT_AUTH = "EXIT_AUTH"
    EXIT_WAIT_CROSS = "EXIT_WAIT_CROSS"
    CLOSING = "CLOSING"        # puerta abierta, esperando a cerrarla; bloquea al siguiente
    DENIED = "DENIED"          # mostrando "VETE!!"
    ENROLLING = "ENROLLING"    # registrando una huella desde la interfaz


AUTH_STATES = {State.ENTRY_AUTH, State.EXIT_AUTH}
WAIT_STATES = {State.ENTRY_WAIT_CROSS, State.EXIT_WAIT_CROSS}


class AccessController:
    def __init__(
        self,
        config: AccessConfig,
        db: Database,
        bus: EventBus,
        device: Device,
        *,
        fingerprint_capacity: int = 127,
        clock: Callable[[], float] = time.monotonic,
        on_entered: Callable[[int, str], None] | None = None,
        on_exited: Callable[[int, str], None] | None = None,
    ) -> None:
        self.cfg = config
        self.db = db
        self.bus = bus
        self.device = device
        self.capacity = fingerprint_capacity
        self.clock = clock
        self.on_entered = on_entered
        self.on_exited = on_exited

        self._lock = threading.RLock()
        self.state = State.IDLE
        self.door_open = False
        self.device_online = False
        self._last_hb: float | None = None
        self._direction: str | None = None      # "IN" | "OUT" del flujo en curso
        self._attempts = 0
        self._worker: dict[str, Any] | None = None
        self._deadline = 0.0
        self._cooldown_until = {1: 0.0, 2: 0.0}
        self._enroll: dict[str, Any] | None = None
        self._manual_close_at: float | None = None

    # ------------------------------------------------------------------ entrada
    def handle_event(self, evt: dict[str, Any]) -> None:
        """Recibe un evento del Arduino (se llama desde el hilo serial)."""
        kind = evt.get("evt")
        with self._lock:
            if kind in ("hello", "hb"):
                self._heartbeat(kind == "hello")
            elif kind == "presence":
                self._heartbeat()
                self._on_presence(int(evt.get("sensor", 0)))
            elif kind == "finger":
                self._on_finger(evt)
            elif kind == "assist":
                self._on_assist(str(evt.get("where", "entrance")))
            elif kind == "enroll":
                self._on_enroll(evt)
            elif kind == "door":
                self.door_open = bool(evt.get("open"))
            elif kind == "deleted":
                self.bus.publish("fingerprint_deleted", f"Huella borrada del sensor (ranura {evt.get('slot')})",
                                 data={"slot": evt.get("slot"), "ok": evt.get("ok")})
            elif kind == "error":
                self.bus.publish("device_error", f"Error del Arduino: {evt.get('msg')}", level="warning",
                                 data={"msg": evt.get("msg")})

    def tick(self) -> None:
        """Revisa tiempos límite. Llamar unas 10 veces por segundo."""
        now = self.clock()
        with self._lock:
            self._check_device_online(now)
            if self._manual_close_at is not None and now >= self._manual_close_at:
                self._manual_close_at = None
                self._door(False)
            state = self.state
            if state in AUTH_STATES and now >= self._deadline:
                self.device.send({"cmd": "auth_cancel"})
                self._abort_auth("timeout", "Tiempo agotado sin huella")
            elif state in WAIT_STATES and now >= self._deadline:
                self._abort_crossing()
            elif state == State.CLOSING and now >= self._deadline:
                self._door(False)
                self._go_idle()
            elif state == State.DENIED and now >= self._deadline:
                self._cooldown(1 if self._direction == "IN" else 2)
                self._go_idle()
            elif state == State.ENROLLING and now >= self._deadline:
                self.device.send({"cmd": "enroll_cancel"})
                self._finish_enroll(False, "Tiempo agotado registrando la huella")

    # ----------------------------------------------------------- acciones de la GUI
    def start_enroll(self, worker_id: int) -> tuple[bool, str]:
        with self._lock:
            worker = self.db.get_worker(worker_id)
            if not worker:
                return False, "Trabajador no encontrado"
            if self.state != State.IDLE:
                return False, f"El sistema está ocupado ({self.state.value})"
            if not self.device_online:
                return False, "El Arduino no está conectado"
            slot = worker["fingerprint_slot"] or self.db.free_slot(self.capacity)
            if slot is None:
                return False, "No quedan ranuras libres en el sensor de huella"
            self._enroll = {"worker_id": worker_id, "slot": slot}
            self.state = State.ENROLLING
            self._deadline = self.clock() + 60.0
            self.device.send({"cmd": "enroll", "slot": slot})
            self.bus.publish("enroll_started", f"Registro de huella iniciado para {worker['name']}",
                             data={"worker_id": worker_id, "slot": slot})
            return True, f"Registro iniciado en la ranura {slot}"

    def cancel_enroll(self) -> None:
        with self._lock:
            if self.state == State.ENROLLING:
                self.device.send({"cmd": "enroll_cancel"})
                self._finish_enroll(False, "Registro cancelado")

    def delete_fingerprint(self, worker_id: int) -> tuple[bool, str]:
        with self._lock:
            worker = self.db.get_worker(worker_id)
            if not worker:
                return False, "Trabajador no encontrado"
            slot = worker["fingerprint_slot"]
            if slot is None:
                return True, "El trabajador no tenía huella"
            if self.state != State.IDLE:
                return False, f"El sistema está ocupado ({self.state.value})"
            self.device.send({"cmd": "delete", "slot": slot})
            self.db.update_worker(worker_id, fingerprint_slot=None)
            if not self.device_online:
                self.bus.publish("fingerprint_pending_delete",
                                 f"El Arduino estaba desconectado: la ranura {slot} puede seguir ocupada en el sensor",
                                 level="warning", data={"slot": slot})
            return True, f"Huella de la ranura {slot} eliminada"

    def set_door(self, open_: bool, source: str = "gui") -> None:
        """Apertura manual (anulación del administrador). Se cierra sola tras 8 s."""
        with self._lock:
            self._door(open_)
            self._manual_close_at = self.clock() + 8.0 if open_ else None
            self.bus.publish("door_manual", "Puerta abierta manualmente" if open_ else "Puerta cerrada manualmente",
                             level="warning", data={"open": open_, "source": source})

    def status(self) -> dict[str, Any]:
        with self._lock:
            inside = self.db.inside_worker_ids()
            return {
                "state": self.state.value,
                "device_online": self.device_online,
                "door_open": self.door_open,
                "inside_count": len(inside),
                "inside_worker_ids": sorted(inside),
            }

    # ---------------------------------------------------------------- internos
    def _heartbeat(self, hello: bool = False) -> None:
        self._last_hb = self.clock()
        if not self.device_online:
            self.device_online = True
            self.bus.publish("device_online", "Arduino conectado")
        if hello:
            self._idle_screen()

    def _check_device_online(self, now: float) -> None:
        if self.device_online and self._last_hb is not None and now - self._last_hb > self.cfg.device_timeout_s:
            self.device_online = False
            self.bus.publish("device_offline", "Arduino desconectado (sin latidos)", level="warning")

    def _lcd(self, line1: str, line2: str = "") -> None:
        self.device.send({"cmd": "lcd", "l1": lcd_safe(line1), "l2": lcd_safe(line2)})

    def _idle_screen(self) -> None:
        self._lcd(*IDLE_SCREEN)

    def _door(self, open_: bool) -> None:
        self.device.send({"cmd": "door", "open": open_})

    def _cooldown(self, sensor: int) -> None:
        self._cooldown_until[sensor] = self.clock() + self.cfg.retrigger_cooldown_s

    def _go_idle(self) -> None:
        self.state = State.IDLE
        self._direction = None
        self._worker = None
        self._attempts = 0
        self._idle_screen()

    # -- presencia ----------------------------------------------------------------
    def _on_presence(self, sensor: int) -> None:
        if sensor not in (1, 2):
            return
        now = self.clock()
        if self.state == State.IDLE:
            if now < self._cooldown_until[sensor]:
                return
            self._start_auth("IN" if sensor == 1 else "OUT")
        elif self.state == State.ENTRY_WAIT_CROSS and sensor == 2:
            self._complete_crossing("IN")
        elif self.state == State.EXIT_WAIT_CROSS and sensor == 1:
            self._complete_crossing("OUT")
        # En cualquier otro caso se ignora (p. ej. la fila sigue en el sensor 1,
        # o el sensor 2 detecta un objeto mientras no hay flujo activo).

    # -- autenticación ----------------------------------------------------------------
    def _start_auth(self, direction: str) -> None:
        self._direction = direction
        self._attempts = 0
        self.state = State.ENTRY_AUTH if direction == "IN" else State.EXIT_AUTH
        self.bus.publish("auth_started", "Entrada: esperando huella" if direction == "IN"
                         else "Salida: esperando huella", data={"direction": direction})
        self._begin_attempt()

    def _begin_attempt(self) -> None:
        number = self._attempts + 1
        title = "Ponga su huella" if self._direction == "IN" else "Salida: huella"
        self._lcd(title, f"Intento {number}/{self.cfg.max_attempts}")
        self.device.send({"cmd": "auth_start", "timeout_ms": int(self.cfg.auth_timeout_s * 1000)})
        self._deadline = self.clock() + self.cfg.auth_timeout_s + 3.0  # respaldo si el Arduino calla

    def _on_finger(self, evt: dict[str, Any]) -> None:
        if self.state not in AUTH_STATES:
            return
        result = evt.get("result")
        if result == "match":
            self._on_match(int(evt.get("slot", -1)))
        elif result == "nomatch":
            self._failed_attempt()
        elif result == "timeout":
            self._abort_auth("timeout", "Tiempo agotado sin huella")
        else:
            self._abort_auth("timeout", f"Resultado de huella inesperado: {result}")

    def _on_match(self, slot: int) -> None:
        direction = self._direction or "IN"
        worker = self.db.worker_by_slot(slot)
        if not worker or not worker["active"]:
            self._failed_attempt(detail=f"Ranura {slot} sin trabajador activo")
            return
        inside = worker["id"] in self.db.inside_worker_ids()
        if direction == "IN" and inside:
            self.db.record_attempt("IN", "already_inside", worker["id"])
            self.bus.publish("access_rejected", f"{worker['name']} ya está dentro", level="warning",
                             data={"worker_id": worker["id"], "reason": "already_inside"})
            self._lcd("Ya esta dentro", worker["name"])
            self._reject_and_cooldown(1)
            return
        if direction == "OUT" and not inside:
            self.db.record_attempt("OUT", "not_inside", worker["id"])
            self.bus.publish("access_rejected", f"{worker['name']} no figura dentro", level="warning",
                             data={"worker_id": worker["id"], "reason": "not_inside"})
            self._lcd("No esta adentro", worker["name"])
            self._reject_and_cooldown(2)
            return

        self.db.record_attempt(direction, "granted", worker["id"], self._attempts + 1)
        self._worker = worker
        self.state = State.ENTRY_WAIT_CROSS if direction == "IN" else State.EXIT_WAIT_CROSS
        self._deadline = self.clock() + self.cfg.crossing_timeout_s
        self._lcd("Bienvenido" if direction == "IN" else "Hasta luego", worker["name"])
        self._door(True)
        self.bus.publish("access_granted", f"{worker['name']} identificado ({'entrada' if direction == 'IN' else 'salida'})",
                         data={"worker_id": worker["id"], "name": worker["name"], "direction": direction})

    def _reject_and_cooldown(self, sensor: int) -> None:
        self.device.send({"cmd": "auth_cancel"})
        self._cooldown(sensor)
        self.state = State.DENIED
        self._deadline = self.clock() + 2.0

    def _failed_attempt(self, detail: str | None = None) -> None:
        direction = self._direction or "IN"
        self._attempts += 1
        self.db.record_attempt(direction, "no_match", None, self._attempts, detail)
        if self._attempts >= self.cfg.max_attempts:
            self.db.record_attempt(direction, "intruder", None, self._attempts)
            self.bus.publish("intruder_alert", "ALERTA: persona no reconocida tras varios intentos",
                             level="alarm", data={"direction": direction, "attempts": self._attempts})
            self.device.send({"cmd": "auth_cancel"})
            self._lcd("VETE!!", "Acceso denegado")
            self.state = State.DENIED
            self._deadline = self.clock() + self.cfg.denied_display_s
            return
        self.bus.publish("auth_failed", f"Huella no reconocida (intento {self._attempts}/{self.cfg.max_attempts})",
                         level="warning", data={"attempt": self._attempts})
        self._begin_attempt()

    def _abort_auth(self, result: str, message: str) -> None:
        direction = self._direction or "IN"
        self.db.record_attempt(direction, result, None, self._attempts + 1)
        self.bus.publish("auth_aborted", message, level="warning", data={"direction": direction})
        self._cooldown(1 if direction == "IN" else 2)
        self._go_idle()

    # -- cruce de la puerta ---------------------------------------------------------------
    def _complete_crossing(self, direction: str) -> None:
        worker = self._worker
        if not worker:
            self._go_idle()
            return
        self.db.record_attendance(worker["id"], direction)
        verb = "entró" if direction == "IN" else "salió"
        self.bus.publish("worker_entered" if direction == "IN" else "worker_exited",
                         f"{worker['name']} {verb}",
                         data={"worker_id": worker["id"], "name": worker["name"]})
        self._lcd("Acceso OK" if direction == "IN" else "Salida OK", worker["name"])
        callback = self.on_entered if direction == "IN" else self.on_exited
        if callback:
            try:
                callback(worker["id"], worker["name"])
            except Exception:
                log.exception("Error en el callback de %s", direction)
        self.state = State.CLOSING
        self._deadline = self.clock() + self.cfg.door_close_delay_s

    def _abort_crossing(self) -> None:
        """Verificado pero nadie cruzó a tiempo: se trata como si nunca se hubiera presentado."""
        direction = self._direction or "IN"
        worker = self._worker or {}
        self.db.record_attempt(direction, "no_crossing", worker.get("id"))
        self.bus.publish("crossing_timeout",
                         f"{worker.get('name', 'Trabajador')} no cruzó la puerta; se descarta el registro",
                         level="warning", data={"worker_id": worker.get("id"), "direction": direction})
        self._door(False)
        self._cooldown(1 if direction == "IN" else 2)
        self._go_idle()

    # -- asistencia técnica ---------------------------------------------------------------
    def _on_assist(self, where: str) -> None:
        request = self.db.create_assistance(where)
        label = "la entrada" if where == "entrance" else "el área de trabajo"
        self.bus.publish("assistance_request", f"Solicitud de asistencia técnica desde {label}",
                         level="warning", data={"request_id": request["id"], "source": where})

    # -- registro de huellas ----------------------------------------------------------------
    def _on_enroll(self, evt: dict[str, Any]) -> None:
        if self.state != State.ENROLLING or not self._enroll:
            return
        step = evt.get("step")
        if step == "ok":
            self._finish_enroll(True, "Huella registrada")
        elif step == "fail":
            self._finish_enroll(False, str(evt.get("msg") or "No se pudo registrar la huella"))
        else:
            self._deadline = self.clock() + 60.0
            self.bus.publish("enroll_step", f"Registro de huella: {step}",
                             data={"step": step, "slot": self._enroll["slot"]})

    def _finish_enroll(self, ok: bool, message: str) -> None:
        enroll, self._enroll = self._enroll, None
        if enroll and ok:
            self.db.update_worker(enroll["worker_id"], fingerprint_slot=enroll["slot"])
        self.bus.publish("enroll_ok" if ok else "enroll_failed", message,
                         level="info" if ok else "warning", data=enroll or {})
        self._go_idle()

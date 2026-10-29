"""Monitor temporal de infracciones (lógica pura: no usa cámara, IA ni base de datos).

Reglas (configurables):
  * Un trabajador "incumple" mientras su estado sea `not_detected` fotograma tras fotograma.
  * Los fotogramas `indeterminate` no suman ni reinician nada (no se puede concluir).
  * El contador solo se reinicia si cumple el EPP durante `compliance_reset_seconds` seguidos
    (evita que un solo fotograma bueno borre 29 s de incumplimiento).
  * Se advierte cuando la infracción lleva `violation_seconds` seguidos y respetando un
    enfriamiento de `cooldown_seconds` por trabajador (o por track, si no tiene ID).
"""

from __future__ import annotations

from dataclasses import dataclass, field

COMPLIANT = "compliant"
NOT_DETECTED = "not_detected"


@dataclass
class Observation:
    track_id: int
    status: str
    missing: tuple[str, ...] = ()
    worker_id: int | None = None


@dataclass
class MonitorEvent:
    kind: str                       # "violation" | "resolved"
    key: str
    track_id: int
    worker_id: int | None
    missing: tuple[str, ...]
    started_at: float               # reloj del monitor, al inicio del incumplimiento
    duration_s: float


@dataclass
class _TrackState:
    track_id: int
    worker_id: int | None
    last_seen: float
    bad_since: float | None = None
    good_since: float | None = None
    missing: tuple[str, ...] = ()
    last_warning: float | None = None
    warned: bool = False


@dataclass
class ViolationMonitor:
    violation_seconds: float = 30.0
    cooldown_seconds: float = 60.0
    compliance_reset_seconds: float = 3.0
    track_lost_seconds: float = 10.0
    _states: dict[int, _TrackState] = field(default_factory=dict)
    _last_warning_by_key: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def key_for(track_id: int, worker_id: int | None) -> str:
        return f"worker:{worker_id}" if worker_id is not None else f"track:{track_id}"

    def update(self, now: float, observations: list[Observation]) -> list[MonitorEvent]:
        events: list[MonitorEvent] = []
        seen: set[int] = set()
        for obs in observations:
            seen.add(obs.track_id)
            state = self._states.get(obs.track_id)
            if state is None:
                state = self._states[obs.track_id] = _TrackState(obs.track_id, obs.worker_id, now)
            state.last_seen = now
            state.worker_id = obs.worker_id
            key = self.key_for(obs.track_id, obs.worker_id)

            if obs.status == NOT_DETECTED:
                state.good_since = None
                if state.bad_since is None:
                    state.bad_since = now
                state.missing = tuple(obs.missing)      # lo que falta en el fotograma actual
                if self._should_warn(state, key, now):
                    self._last_warning_by_key[key] = now
                    state.warned = True
                    events.append(MonitorEvent("violation", key, obs.track_id, obs.worker_id,
                                               state.missing, state.bad_since, now - state.bad_since))
            elif obs.status == COMPLIANT:
                if state.bad_since is not None:
                    if state.good_since is None:
                        state.good_since = now
                    if now - state.good_since >= self.compliance_reset_seconds:
                        events.extend(self._resolve(state, key, now))
            # "indeterminate": no cambia nada

        for track_id in list(self._states):
            state = self._states[track_id]
            if track_id not in seen and now - state.last_seen >= self.track_lost_seconds:
                key = self.key_for(track_id, state.worker_id)
                events.extend(self._resolve(state, key, state.last_seen))
                del self._states[track_id]
        return events

    def forget_track(self, track_id: int) -> None:
        self._states.pop(track_id, None)

    # ---------------------------------------------------------------- internos
    def _should_warn(self, state: _TrackState, key: str, now: float) -> bool:
        if state.bad_since is None or now - state.bad_since < self.violation_seconds:
            return False
        last = self._last_warning_by_key.get(key)
        return last is None or now - last >= self.cooldown_seconds

    def _resolve(self, state: _TrackState, key: str, now: float) -> list[MonitorEvent]:
        events: list[MonitorEvent] = []
        if state.warned and state.bad_since is not None:
            events.append(MonitorEvent("resolved", key, state.track_id, state.worker_id,
                                       state.missing, state.bad_since, now - state.bad_since))
        state.bad_since = None
        state.good_since = None
        state.missing = ()
        state.warned = False
        return events

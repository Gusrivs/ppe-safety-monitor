"""Traspaso de identidad: huella -> track de la cámara.

Cuando el sensor 2 confirma que alguien cruzó, el controlador de acceso avisa con
`request_handoff(worker_id)`. El primer track NUEVO que aparece en la zona de entrada
(dentro de la ventana de tiempo) recibe ese ID de trabajador y lo conserva mientras la
cámara lo siga viendo. Si no aparece ningún track, se informa para revisar el video.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Pending:
    worker_id: int
    name: str
    requested_at: float


@dataclass
class _TrackInfo:
    first_seen: float
    first_center: tuple[float, float]       # coordenadas normalizadas 0..1


@dataclass
class IdentityTracker:
    entry_zone: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    window_s: float = 15.0
    lookback_s: float = 5.0
    assigned: dict[int, int] = field(default_factory=dict)      # track_id -> worker_id
    ignored: set[int] = field(default_factory=set)              # tracks de quien ya salió
    _pending: list[_Pending] = field(default_factory=list)
    _tracks: dict[int, _TrackInfo] = field(default_factory=dict)

    def request_handoff(self, worker_id: int, name: str, now: float) -> None:
        self.release_worker(worker_id)   # un trabajador solo puede tener un track
        self._pending.append(_Pending(worker_id, name, now))

    def release_worker(self, worker_id: int) -> None:
        """El trabajador salió (o se re-identificó): su track deja de contar."""
        self._pending = [p for p in self._pending if p.worker_id != worker_id]
        for track_id in [t for t, w in self.assigned.items() if w == worker_id]:
            del self.assigned[track_id]
            self.ignored.add(track_id)

    def assign(self, track_id: int, worker_id: int) -> None:
        """Asignación manual (desde la interfaz) a un track sin ID."""
        self._pending = [p for p in self._pending if p.worker_id != worker_id]
        for t in [t for t, w in self.assigned.items() if w == worker_id]:
            del self.assigned[t]
        self.ignored.discard(track_id)
        self.assigned[track_id] = worker_id

    def worker_for(self, track_id: int) -> int | None:
        return self.assigned.get(track_id)

    def update(self, now: float, tracks: list[tuple[int, tuple[float, float, float, float]]],
               frame_size: tuple[int, int]) -> tuple[list[tuple[int, int, str]], list[_Pending]]:
        """Procesa los tracks visibles. Devuelve (asignaciones nuevas, pendientes vencidos).

        `tracks`: lista de (track_id, caja en píxeles); `frame_size`: (ancho, alto).
        Cada asignación es (track_id, worker_id, nombre).
        """
        width, height = frame_size
        for track_id, (x1, y1, x2, y2) in tracks:
            if track_id not in self._tracks:
                center = (((x1 + x2) / 2) / max(width, 1), ((y1 + y2) / 2) / max(height, 1))
                self._tracks[track_id] = _TrackInfo(now, center)

        new_assignments: list[tuple[int, int, str]] = []
        visible = {track_id for track_id, _ in tracks}
        for pending in list(self._pending):
            candidates = [
                (info.first_seen, track_id)
                for track_id, info in self._tracks.items()
                if track_id in visible
                and track_id not in self.assigned
                and track_id not in self.ignored
                and self._in_zone(info.first_center)
                and info.first_seen >= pending.requested_at - self.lookback_s
            ]
            if candidates:
                _, track_id = min(candidates)
                self.assigned[track_id] = pending.worker_id
                self._pending.remove(pending)
                new_assignments.append((track_id, pending.worker_id, pending.name))

        expired = [p for p in self._pending if now - p.requested_at > self.window_s]
        self._pending = [p for p in self._pending if p not in expired]
        return new_assignments, expired

    def forget_old_tracks(self, visible_ids: set[int], keep: int = 200) -> None:
        """Evita que el diccionario crezca sin límite en sesiones largas."""
        if len(self._tracks) <= keep:
            return
        for track_id in [t for t in self._tracks if t not in visible_ids][: len(self._tracks) - keep]:
            self._tracks.pop(track_id, None)
            self.ignored.discard(track_id)

    def _in_zone(self, center: tuple[float, float]) -> bool:
        x1, y1, x2, y2 = self.entry_zone
        return x1 <= center[0] <= x2 and y1 <= center[1] <= y2

    def snapshot(self) -> dict:
        return {"assigned": dict(self.assigned),
                "pending": [{"worker_id": p.worker_id, "name": p.name} for p in self._pending]}

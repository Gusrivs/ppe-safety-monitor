"""Base de datos SQLite local (un solo archivo, sin servidor)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS workers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT UNIQUE,              -- carnet / código interno opcional
    name             TEXT NOT NULL,
    role             TEXT,
    fingerprint_slot INTEGER UNIQUE,           -- ranura en el R307S (NULL = sin huella)
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id  INTEGER NOT NULL REFERENCES workers(id),
    direction  TEXT NOT NULL CHECK (direction IN ('IN', 'OUT')),
    ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attendance_ts ON attendance(ts);
CREATE INDEX IF NOT EXISTS idx_attendance_worker ON attendance(worker_id, ts);

CREATE TABLE IF NOT EXISTS access_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    direction  TEXT NOT NULL CHECK (direction IN ('IN', 'OUT')),
    worker_id  INTEGER REFERENCES workers(id),
    result     TEXT NOT NULL,   -- granted, no_match, intruder, timeout, already_inside,
                                -- not_inside, no_crossing
    attempt_no INTEGER,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_ts ON access_attempts(ts);

CREATE TABLE IF NOT EXISTS violations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,            -- momento de la advertencia
    worker_id     INTEGER REFERENCES workers(id),   -- NULL = track sin ID
    track_id      INTEGER,
    missing       TEXT NOT NULL,            -- helmet, vest o helmet,vest
    started_at    TEXT,                     -- inicio estimado de la infracción continua
    ended_at      TEXT,
    duration_s    REAL,
    snapshot_path TEXT,
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_violations_ts ON violations(ts);

CREATE TABLE IF NOT EXISTS assistance_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    source      TEXT NOT NULL,              -- entrance, work_area, gui
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'attended')),
    attended_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    level   TEXT NOT NULL,                  -- info, warning, alarm
    type    TEXT NOT NULL,
    message TEXT NOT NULL,
    data    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def now_iso() -> str:
    """Marca de tiempo local con segundos (la PC es la fuente de verdad de la hora)."""
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Ejecuta una escritura y devuelve el id de la última fila insertada."""
        with self._lock:
            cursor = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cursor.lastrowid or 0

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ workers
    def create_worker(self, name: str, code: str | None = None, role: str | None = None) -> dict[str, Any]:
        ts = now_iso()
        worker_id = self.execute(
            "INSERT INTO workers (code, name, role, created_at, updated_at) VALUES (?,?,?,?,?)",
            (code or None, name, role, ts, ts),
        )
        return self.get_worker(worker_id)  # type: ignore[return-value]

    def get_worker(self, worker_id: int) -> dict[str, Any] | None:
        return self.one("SELECT * FROM workers WHERE id = ? AND deleted_at IS NULL", (worker_id,))

    def list_workers(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM workers WHERE deleted_at IS NULL ORDER BY name")

    def worker_by_slot(self, slot: int) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM workers WHERE fingerprint_slot = ? AND deleted_at IS NULL", (slot,)
        )

    def update_worker(self, worker_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"code", "name", "role", "active", "fingerprint_slot"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            columns = ", ".join(f"{key} = ?" for key in sets)
            self.execute(
                f"UPDATE workers SET {columns}, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (*sets.values(), now_iso(), worker_id),
            )
        return self.get_worker(worker_id)

    def soft_delete_worker(self, worker_id: int) -> None:
        """Elimina al trabajador pero conserva su historial (asistencia, infracciones)."""
        ts = now_iso()
        self.execute(
            "UPDATE workers SET deleted_at = ?, updated_at = ?, active = 0, "
            "fingerprint_slot = NULL, code = NULL WHERE id = ?",
            (ts, ts, worker_id),
        )

    def free_slot(self, capacity: int) -> int | None:
        used = {r["fingerprint_slot"] for r in self.query(
            "SELECT fingerprint_slot FROM workers WHERE fingerprint_slot IS NOT NULL")}
        for slot in range(1, capacity + 1):
            if slot not in used:
                return slot
        return None

    # --------------------------------------------------------------- attendance
    def inside_worker_ids(self) -> set[int]:
        """Trabajadores cuyo último registro de asistencia es una entrada."""
        rows = self.query(
            "SELECT a.worker_id, a.direction FROM attendance a "
            "JOIN (SELECT worker_id, MAX(id) AS last_id FROM attendance GROUP BY worker_id) l "
            "ON a.id = l.last_id"
        )
        return {r["worker_id"] for r in rows if r["direction"] == "IN"}

    def record_attendance(self, worker_id: int, direction: str) -> int:
        return self.execute(
            "INSERT INTO attendance (worker_id, direction, ts) VALUES (?,?,?)",
            (worker_id, direction, now_iso()),
        )

    def record_attempt(self, direction: str, result: str, worker_id: int | None = None,
                       attempt_no: int | None = None, detail: str | None = None) -> int:
        return self.execute(
            "INSERT INTO access_attempts (ts, direction, worker_id, result, attempt_no, detail) "
            "VALUES (?,?,?,?,?,?)",
            (now_iso(), direction, worker_id, result, attempt_no, detail),
        )

    # --------------------------------------------------------------- violations
    def record_violation(self, *, worker_id: int | None, track_id: int | None, missing: list[str],
                         started_at: str | None, snapshot_path: str | None) -> int:
        return self.execute(
            "INSERT INTO violations (ts, worker_id, track_id, missing, started_at, snapshot_path) "
            "VALUES (?,?,?,?,?,?)",
            (now_iso(), worker_id, track_id, ",".join(missing), started_at, snapshot_path),
        )

    def close_violation(self, violation_id: int, duration_s: float) -> None:
        self.execute(
            "UPDATE violations SET ended_at = ?, duration_s = ? WHERE id = ?",
            (now_iso(), round(duration_s, 1), violation_id),
        )

    # --------------------------------------------------------------- assistance
    def create_assistance(self, source: str) -> dict[str, Any]:
        request_id = self.execute(
            "INSERT INTO assistance_requests (ts, source) VALUES (?, ?)", (now_iso(), source)
        )
        return self.one("SELECT * FROM assistance_requests WHERE id = ?", (request_id,))  # type: ignore[return-value]

    def attend_assistance(self, request_id: int) -> dict[str, Any] | None:
        self.execute(
            "UPDATE assistance_requests SET status = 'attended', attended_at = ? "
            "WHERE id = ? AND status = 'open'",
            (now_iso(), request_id),
        )
        return self.one("SELECT * FROM assistance_requests WHERE id = ?", (request_id,))

    # ------------------------------------------------------------------- events
    def log_event(self, level: str, type_: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        ts = now_iso()
        payload = json.dumps(data, ensure_ascii=False) if data else None
        event_id = self.execute(
            "INSERT INTO events (ts, level, type, message, data) VALUES (?,?,?,?,?)",
            (ts, level, type_, message, payload),
        )
        return {"id": event_id, "ts": ts, "level": level, "type": type_,
                "message": message, "data": data or {}}

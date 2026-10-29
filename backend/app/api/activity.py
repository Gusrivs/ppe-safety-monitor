"""Consultas de asistencia, infracciones, intentos de acceso, asistencia técnica y reportes."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from ..context import AppContext
from .deps import get_ctx

router = APIRouter(tags=["registros"])


def _range(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Fechas ISO (AAAA-MM-DD). Por defecto, hoy. Devuelve límites [desde, hasta)."""
    today = date.today().isoformat()
    start = date_from or today
    end = date_to or start
    try:
        date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(422, "Las fechas deben tener el formato AAAA-MM-DD")
    return start, (end_date.fromordinal(end_date.toordinal() + 1)).isoformat()


@router.get("/attendance")
def attendance(date_from: str | None = None, date_to: str | None = None, worker_id: int | None = None,
               limit: int = Query(500, le=5000), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    start, end = _range(date_from, date_to)
    sql = ("SELECT a.id, a.worker_id, w.name AS worker_name, w.code AS worker_code, a.direction, a.ts "
           "FROM attendance a JOIN workers w ON w.id = a.worker_id WHERE a.ts >= ? AND a.ts < ?")
    params: list[Any] = [start, end]
    if worker_id is not None:
        sql += " AND a.worker_id = ?"
        params.append(worker_id)
    sql += " ORDER BY a.ts DESC, a.id DESC LIMIT ?"
    params.append(limit)
    return ctx.db.query(sql, params)


@router.get("/attendance/summary")
def attendance_summary(date_from: str | None = None, date_to: str | None = None,
                       ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    """Primera entrada, última salida y estado actual por trabajador en el rango."""
    start, end = _range(date_from, date_to)
    rows = ctx.db.query(
        "SELECT a.worker_id, w.name AS worker_name, w.code AS worker_code, a.direction, a.ts "
        "FROM attendance a JOIN workers w ON w.id = a.worker_id "
        "WHERE a.ts >= ? AND a.ts < ? ORDER BY a.ts, a.id", (start, end))
    summary: dict[int, dict[str, Any]] = {}
    for row in rows:
        item = summary.setdefault(row["worker_id"], {
            "worker_id": row["worker_id"], "worker_name": row["worker_name"],
            "worker_code": row["worker_code"], "first_in": None, "last_out": None, "inside": False})
        if row["direction"] == "IN":
            item["first_in"] = item["first_in"] or row["ts"]
            item["inside"] = True
        else:
            item["last_out"] = row["ts"]
            item["inside"] = False
    return list(summary.values())


@router.get("/access-attempts")
def access_attempts(date_from: str | None = None, date_to: str | None = None,
                    limit: int = Query(500, le=5000), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    start, end = _range(date_from, date_to)
    return ctx.db.query(
        "SELECT t.*, w.name AS worker_name FROM access_attempts t "
        "LEFT JOIN workers w ON w.id = t.worker_id WHERE t.ts >= ? AND t.ts < ? "
        "ORDER BY t.ts DESC, t.id DESC LIMIT ?", (start, end, limit))


def _violations(ctx: AppContext, date_from: str | None, date_to: str | None, worker_id: int | None,
                limit: int) -> list[dict[str, Any]]:
    start, end = _range(date_from, date_to)
    sql = ("SELECT v.*, w.name AS worker_name FROM violations v "
           "LEFT JOIN workers w ON w.id = v.worker_id WHERE v.ts >= ? AND v.ts < ?")
    params: list[Any] = [start, end]
    if worker_id is not None:
        sql += " AND v.worker_id = ?"
        params.append(worker_id)
    sql += " ORDER BY v.ts DESC, v.id DESC LIMIT ?"
    params.append(limit)
    rows = ctx.db.query(sql, params)
    for row in rows:
        row["has_snapshot"] = bool(row["snapshot_path"])
    return rows


@router.get("/violations")
def violations(date_from: str | None = None, date_to: str | None = None, worker_id: int | None = None,
               limit: int = Query(500, le=5000), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    return _violations(ctx, date_from, date_to, worker_id, limit)


@router.get("/violations/{violation_id}/snapshot")
def violation_snapshot(violation_id: int, ctx: AppContext = Depends(get_ctx)) -> FileResponse:
    row = ctx.db.one("SELECT snapshot_path FROM violations WHERE id = ?", (violation_id,))
    if not row or not row["snapshot_path"]:
        raise HTTPException(404, "Esta infracción no tiene captura")
    path = Path(row["snapshot_path"]).resolve()
    if ctx.settings.data_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "La captura ya no está en el disco")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/assistance")
def assistance(status: str | None = Query(None, pattern="^(open|attended)$"),
               ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    if status:
        return ctx.db.query("SELECT * FROM assistance_requests WHERE status = ? ORDER BY id DESC", (status,))
    return ctx.db.query("SELECT * FROM assistance_requests ORDER BY id DESC LIMIT 200")


@router.post("/assistance/{request_id}/attend")
def attend_assistance(request_id: int, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    request = ctx.db.attend_assistance(request_id)
    if not request:
        raise HTTPException(404, "Solicitud no encontrada")
    ctx.bus.publish("assistance_attended", f"Solicitud de asistencia #{request_id} atendida",
                    data={"request_id": request_id})
    return request


@router.get("/events")
def events(limit: int = Query(100, le=1000), level: str | None = Query(None, pattern="^(info|warning|alarm)$"),
           ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM events", []
    if level:
        sql += " WHERE level = ?"
        params.append(level)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return ctx.db.query(sql, params)


# --------------------------------------------------------------------------- reportes CSV
def _csv_response(filename: str, header: list[str], rows: list[list[Any]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    body = "\ufeff" + buffer.getvalue()      # BOM: Excel abre bien las tildes
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/attendance.csv")
def report_attendance(date_from: str | None = None, date_to: str | None = None,
                      ctx: AppContext = Depends(get_ctx)) -> Response:
    rows = attendance(date_from, date_to, None, 5000, ctx)
    return _csv_response("asistencia.csv", ["Fecha y hora", "Código", "Trabajador", "Movimiento"],
                         [[r["ts"], r["worker_code"] or "", r["worker_name"],
                           "Entrada" if r["direction"] == "IN" else "Salida"] for r in reversed(rows)])


@router.get("/reports/violations.csv")
def report_violations(date_from: str | None = None, date_to: str | None = None,
                      ctx: AppContext = Depends(get_ctx)) -> Response:
    rows = _violations(ctx, date_from, date_to, None, 5000)
    names = {"helmet": "casco", "vest": "chaleco"}
    return _csv_response("infracciones.csv",
                         ["Fecha y hora", "Trabajador", "Track", "Faltó", "Duración (s)", "Captura"],
                         [[r["ts"], r["worker_name"] or "SIN ID", r["track_id"] or "",
                           " y ".join(names.get(m, m) for m in r["missing"].split(",")),
                           r["duration_s"] if r["duration_s"] is not None else "",
                           "sí" if r["has_snapshot"] else "no"] for r in reversed(rows)])

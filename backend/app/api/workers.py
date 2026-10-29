"""CRUD de trabajadores y registro de huellas."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..context import AppContext
from .deps import get_ctx

router = APIRouter(tags=["trabajadores"])


class WorkerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=80)


class WorkerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=80)
    active: bool | None = None


def _view(worker: dict[str, Any], inside: set[int]) -> dict[str, Any]:
    return {
        "id": worker["id"], "code": worker["code"], "name": worker["name"], "role": worker["role"],
        "active": bool(worker["active"]), "fingerprint_slot": worker["fingerprint_slot"],
        "has_fingerprint": worker["fingerprint_slot"] is not None,
        "inside": worker["id"] in inside,
        "created_at": worker["created_at"], "updated_at": worker["updated_at"],
    }


@router.get("/workers")
def list_workers(ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    inside = ctx.db.inside_worker_ids()
    return [_view(w, inside) for w in ctx.db.list_workers()]


@router.post("/workers", status_code=201)
def create_worker(body: WorkerIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    try:
        worker = ctx.db.create_worker(body.name.strip(), body.code, body.role)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Ya existe un trabajador con ese código")
    return _view(worker, set())


@router.get("/workers/{worker_id}")
def get_worker(worker_id: int, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    worker = ctx.db.get_worker(worker_id)
    if not worker:
        raise HTTPException(404, "Trabajador no encontrado")
    return _view(worker, ctx.db.inside_worker_ids())


@router.put("/workers/{worker_id}")
def update_worker(worker_id: int, body: WorkerUpdate, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.db.get_worker(worker_id):
        raise HTTPException(404, "Trabajador no encontrado")
    changes = body.model_dump(exclude_unset=True)
    if "active" in changes:
        changes["active"] = int(bool(changes["active"]))
    try:
        worker = ctx.db.update_worker(worker_id, **changes)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Ya existe un trabajador con ese código")
    return _view(worker, ctx.db.inside_worker_ids())  # type: ignore[arg-type]


@router.delete("/workers/{worker_id}", status_code=204)
def delete_worker(worker_id: int, ctx: AppContext = Depends(get_ctx)) -> None:
    """Elimina al trabajador (y su huella del sensor). El historial se conserva."""
    if not ctx.db.get_worker(worker_id):
        raise HTTPException(404, "Trabajador no encontrado")
    ok, message = ctx.access.delete_fingerprint(worker_id)
    if not ok:
        raise HTTPException(409, message)
    ctx.vision.handle_exited(worker_id, "")
    ctx.db.soft_delete_worker(worker_id)
    ctx.bus.publish("worker_deleted", f"Trabajador {worker_id} eliminado", data={"worker_id": worker_id})


@router.post("/workers/{worker_id}/fingerprint", status_code=202)
def enroll_fingerprint(worker_id: int, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Inicia el registro de la huella. El progreso llega por WebSocket (enroll_step/enroll_ok)."""
    ok, message = ctx.access.start_enroll(worker_id)
    if not ok:
        raise HTTPException(409, message)
    return {"ok": True, "message": message}


@router.delete("/workers/{worker_id}/fingerprint", status_code=200)
def delete_fingerprint(worker_id: int, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ok, message = ctx.access.delete_fingerprint(worker_id)
    if not ok:
        raise HTTPException(409, message)
    return {"ok": True, "message": message}


@router.post("/enroll/cancel")
def cancel_enroll(ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    ctx.access.cancel_enroll()
    return {"ok": True}

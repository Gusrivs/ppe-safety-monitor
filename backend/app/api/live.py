"""Estado en vivo: video MJPEG, WebSocket de eventos, puerta, tracks y simulador."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..context import AppContext
from ..device.simulated import SimulatedDevice
from .deps import get_ctx

router = APIRouter()
_PLACEHOLDER: bytes | None = None


def _placeholder_jpeg() -> bytes:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        import cv2
        import numpy as np

        image = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(image, "Sin senal de camara", (150, 185), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (200, 200, 200), 2)
        _PLACEHOLDER = cv2.imencode(".jpg", image)[1].tobytes()
    return _PLACEHOLDER


@router.get("/api/health", tags=["sistema"])
def health() -> dict[str, Any]:
    return {"ok": True, "service": "epp-monitor"}


@router.get("/api/status", tags=["sistema"])
def status(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.status()


@router.get("/api/snapshot.jpg", tags=["video"])
def snapshot(ctx: AppContext = Depends(get_ctx)) -> Response:
    return Response(ctx.vision.latest_jpeg or _placeholder_jpeg(), media_type="image/jpeg")


@router.get("/video", tags=["video"])
async def video(ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    """Video en vivo (MJPEG): <img src="http://localhost:8000/video">."""

    async def frames() -> AsyncIterator[bytes]:
        last = -1
        while True:
            counter = ctx.vision.jpeg_counter
            if counter != last or ctx.vision.latest_jpeg is None:
                jpeg = ctx.vision.latest_jpeg or _placeholder_jpeg()
                last = counter
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() \
                    + b"\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    """Emite {"kind":"event"|"status","data":...}. El estado se reenvía tras cada evento y cada 2 s."""
    ctx: AppContext = websocket.app.state.ctx
    await websocket.accept()
    queue = ctx.bus.subscribe()
    try:
        await websocket.send_json({"kind": "status", "data": ctx.status()})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                await websocket.send_json({"kind": "event", "data": event})
            except asyncio.TimeoutError:
                pass
            await websocket.send_json({"kind": "status", "data": ctx.status()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        ctx.bus.unsubscribe(queue)


class DoorIn(BaseModel):
    open: bool


@router.post("/api/door", tags=["acceso"])
def door(body: DoorIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    """Anulación manual del administrador (se cierra sola a los 8 s)."""
    ctx.access.set_door(body.open)
    return {"ok": True}


@router.get("/api/tracks", tags=["video"])
def tracks(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"tracks": ctx.vision.tracks(), "identity": ctx.vision.identity.snapshot()}


class AssignIn(BaseModel):
    track_id: int
    worker_id: int


@router.post("/api/tracks/assign", tags=["video"])
def assign_track(body: AssignIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    """Asigna a mano un trabajador a un track sin ID (corrige un cambio de ID del tracker)."""
    if not ctx.vision.assign_track(body.track_id, body.worker_id):
        raise HTTPException(404, "Trabajador no encontrado")
    return {"ok": True}


# ------------------------------------------------------------------ simulador (sin Arduino)
class SimEventIn(BaseModel):
    event: dict[str, Any]


def _sim(ctx: AppContext) -> SimulatedDevice:
    if not isinstance(ctx.device, SimulatedDevice):
        raise HTTPException(404, "El simulador solo existe con device.simulate: true")
    return ctx.device


@router.post("/api/sim/event", tags=["simulador"])
def sim_event(body: SimEventIn, ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    """Inyecta un evento como si lo enviara el Arduino. Ej: {"event":{"evt":"presence","sensor":1}}"""
    _sim(ctx).inject(body.event)
    return {"ok": True}


@router.get("/api/sim/state", tags=["simulador"])
def sim_state(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    sim = _sim(ctx)
    return {"lcd": list(sim.lcd), "door_open": sim.door_open, "auth_active": sim.auth_active}

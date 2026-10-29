"""Punto de entrada del backend.

    cd backend
    python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import activity, live, workers
from .config import PROJECT_ROOT, Settings, load_settings
from .context import AppContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, **overrides: Any) -> FastAPI:
    """`overrides` (device, camera, pipeline, db) permite inyectar piezas falsas en pruebas."""
    settings = settings or load_settings()
    ctx = AppContext(settings, **overrides)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ctx.start()
        yield
        await ctx.stop()

    app = FastAPI(title="Monitoreo automatizado de EPP", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],   # servidor de desarrollo de Vue
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(workers.router, prefix="/api")
    app.include_router(activity.router, prefix="/api")
    app.include_router(live.router)

    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.is_dir():  # interfaz de Vue ya compilada: se sirve desde el mismo backend
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


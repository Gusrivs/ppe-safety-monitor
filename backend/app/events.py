"""Bus de eventos: guarda en la base de datos y reenvía por WebSocket a la interfaz."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .db import Database


class EventBus:
    """Se puede llamar a `publish` desde cualquier hilo (serial, visión, API)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, message: str, *, level: str = "info",
                data: dict[str, Any] | None = None) -> dict[str, Any]:
        event = self.db.log_event(level, type_, message, data)
        with self._lock:
            subscribers = list(self._subscribers)
        loop = self._loop
        if loop is not None and subscribers and not loop.is_closed():
            for queue in subscribers:
                loop.call_soon_threadsafe(self._offer, queue, event)
        return event

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():  # un cliente lento no debe bloquear al sistema
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

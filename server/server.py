#!/usr/bin/env python3
"""Minimal HTTP/JSON receiver for the NodeMCU communication prototype."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


HOST = "0.0.0.0"
PORT = 8080
MAX_BODY_BYTES = 16 * 1024
SUPPORTED_EVENTS = {"ping", "worker_identified", "crossing"}


class EventHandler(BaseHTTPRequestHandler):
    server_version = "EPPPrototype/0.1"

    def do_POST(self) -> None:
        if self.path != "/api/event":
            self._respond(404, {"ok": False, "error": "Ruta no encontrada"})
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._respond(411, {"ok": False, "error": "Content-Length inválido"})
            return

        if length <= 0:
            self._respond(400, {"ok": False, "error": "El cuerpo JSON está vacío"})
            return
        if length > MAX_BODY_BYTES:
            self._respond(413, {"ok": False, "error": "El cuerpo excede el límite de 16 KiB"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._respond(400, {"ok": False, "error": "El cuerpo debe ser JSON UTF-8 válido"})
            return

        error = validate_event(payload)
        if error:
            self._respond(422, {"ok": False, "error": error})
            return

        print(f"Evento recibido: {json.dumps(payload, ensure_ascii=False)}", flush=True)
        self._respond(200, {"ok": True, "message": "Evento recibido", "event": payload["event"]})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"ok": True, "service": "epp-prototype"})
            return
        self._respond(404, {"ok": False, "error": "Ruta no encontrada"})

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def validate_event(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "El cuerpo debe ser un objeto JSON"

    event = payload.get("event")
    if not isinstance(event, str) or event not in SUPPORTED_EVENTS:
        return "event debe ser ping, worker_identified o crossing"

    if event == "worker_identified":
        worker_id = payload.get("worker_id")
        if isinstance(worker_id, bool) or not isinstance(worker_id, int) or worker_id < 0:
            return "worker_identified requiere worker_id entero no negativo"

    if event == "crossing":
        direction = payload.get("direction")
        if not isinstance(direction, str) or direction not in {"IN", "OUT"}:
            return "crossing requiere direction igual a IN u OUT"

    return None


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), EventHandler)
    print(f"Servidor EPP escuchando en http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

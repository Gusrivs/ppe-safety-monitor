"""Protocolo PC <-> Arduino UNO: una línea JSON por mensaje, terminada en '\\n'.

Arduino -> PC (eventos, clave "evt"):
    {"evt":"hello","fw":"0.1"}                         al arrancar
    {"evt":"hb"}                                       latido cada ~2 s
    {"evt":"presence","sensor":1|2}                    HC-SR04 detecta a alguien
                                                       (se repite cada ~3 s mientras siga ahí)
    {"evt":"finger","result":"match","slot":3,"score":120}
    {"evt":"finger","result":"nomatch"}
    {"evt":"finger","result":"timeout"}
    {"evt":"enroll","step":"place1|remove|place2|ok|fail","slot":3,"msg":"..."}
    {"evt":"deleted","slot":3,"ok":true}
    {"evt":"door","open":true|false}
    {"evt":"assist","where":"entrance"|"work_area"}    botones de Asistencia Técnica
    {"evt":"error","msg":"..."}

PC -> Arduino (comandos, clave "cmd"):
    {"cmd":"lcd","l1":"Hola","l2":"mundo"}             16 caracteres ASCII por línea
    {"cmd":"door","open":true|false}                   servo SG90 (cerradura)
    {"cmd":"auth_start","timeout_ms":15000}            empieza a esperar un dedo
    {"cmd":"auth_cancel"}
    {"cmd":"enroll","slot":3}                          registra una huella nueva en esa ranura
    {"cmd":"enroll_cancel"}
    {"cmd":"delete","slot":3}                          borra la plantilla de esa ranura
    {"cmd":"cfg","th1":80,"th2":80}                    umbrales de los HC-SR04 en cm (opcional)
"""

from __future__ import annotations

import unicodedata
from typing import Any, Callable, Protocol

LCD_WIDTH = 16


def lcd_safe(text: str) -> str:
    """Convierte a ASCII y recorta a 16 caracteres (el LCD 16x2 no soporta tildes)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ascii_text = "".join(ch for ch in ascii_text if ch.isprintable() and ch not in '"\\')
    return ascii_text[:LCD_WIDTH]


EventListener = Callable[[dict[str, Any]], None]


class Device(Protocol):
    """Interfaz común del Arduino real y del simulado."""

    connected: bool
    listener: EventListener | None

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def send(self, command: dict[str, Any]) -> None: ...

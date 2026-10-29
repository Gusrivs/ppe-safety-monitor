"""Dibuja cajas y etiquetas sobre el fotograma (OpenCV solo soporta texto ASCII)."""

from __future__ import annotations

import unicodedata
from typing import Any

from .ppe_association import Detection, PersonAssessment

GREEN = (0, 170, 0)
ORANGE = (0, 140, 255)
GRAY = (150, 150, 150)
BLUE = (255, 120, 0)


def ascii_text(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def draw_frame(cv2: Any, frame: Any, assessments: list[PersonAssessment], equipment: list[Detection],
               names: dict[int, str]) -> Any:
    """`names`: track_id -> nombre del trabajador identificado."""
    out = frame.copy()
    for a in assessments:
        color = GREEN if a.status == "compliant" else ORANGE if a.status == "not_detected" else GRAY
        x1, y1, x2, y2 = (int(v) for v in a.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        who = names.get(a.track_id) if a.track_id is not None else None
        title = ascii_text(who) if who else (f"SIN ID (track {a.track_id})" if a.track_id is not None else "SIN ID")
        detail = f"casco {'SI' if a.helmet_detected else 'NO'} | chaleco {'SI' if a.vest_detected else 'NO'}"
        cv2.putText(out, title, (x1, max(18, y1 - 24)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        cv2.putText(out, detail, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    for item in equipment:
        x1, y1, x2, y2 = (int(v) for v in item.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), BLUE, 1)
    return out

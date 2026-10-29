"""Asociación de casco/chaleco con cada persona (reglas geométricas, sin IA extra).

Un casco debe quedar en la zona de la cabeza de la persona y un chaleco en la zona del
torso. Estados por persona y por fotograma:

  compliant      casco y chaleco detectados y asociados sin ambigüedad
  not_detected   persona de tamaño fiable y falta alguna pieza en ESTE fotograma
  indeterminate  persona muy pequeña o detección ambigua (no se puede concluir nada)

"not_detected" NO es una infracción por sí solo: el ViolationMonitor exige que persista
(30 s por defecto) antes de advertir, porque un detector falla en fotogramas sueltos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]
    track_id: int | None = None


@dataclass(frozen=True)
class PersonAssessment:
    person_id: int                      # índice dentro del fotograma
    track_id: int | None                # id del tracker (estable entre fotogramas)
    box: tuple[float, float, float, float]
    person_confidence: float
    helmet_detected: bool
    helmet_confidence: float | None
    vest_detected: bool
    vest_confidence: float | None
    status: str
    reasons: tuple[str, ...]
    missing: tuple[str, ...] = ()       # piezas que faltan si status == "not_detected"


def normalise_label(label: str) -> str | None:
    value = "".join(ch for ch in label.lower() if ch.isalnum())
    if value.startswith("no") or value.startswith("without"):
        return None
    if "helmet" in value or "hardhat" in value:
        return "helmet"
    if "vest" in value or "jacket" in value or "reflective" in value:
        return "vest"
    return None


def _inside(point: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def associate_equipment(
    people: Iterable[Detection],
    equipment: Iterable[Detection],
    *,
    min_person_height: float = 80,
) -> list[PersonAssessment]:
    people = list(people)
    equipment = [d for d in equipment if normalise_label(d.label) is not None]
    matches: list[dict] = [
        {"person": p, "helmet": None, "vest": None, "helmet_ambiguous": False,
         "vest_ambiguous": False, "low_resolution": False}
        for p in people
    ]

    for item in matches:
        _, y1, _, y2 = item["person"].box
        item["low_resolution"] = max(0.0, y2 - y1) < min_person_height

    for item in equipment:
        kind = normalise_label(item.label)
        assert kind in {"helmet", "vest"}
        x1, y1, x2, y2 = item.box
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        candidates: list[int] = []
        for index, record in enumerate(matches):
            px1, py1, px2, py2 = record["person"].box
            width, height = max(0.0, px2 - px1), max(0.0, py2 - py1)
            if kind == "helmet":
                zone = (px1 + width * 0.08, py1, px2 - width * 0.08, py1 + height * 0.38)
            else:
                zone = (px1 + width * 0.08, py1 + height * 0.20,
                        px2 - width * 0.08, py1 + height * 0.82)
            if _inside(center, zone):
                candidates.append(index)

        if len(candidates) == 1:
            current = matches[candidates[0]][kind]
            if current is None or item.confidence > current.confidence:
                matches[candidates[0]][kind] = item
        elif len(candidates) > 1:
            for index in candidates:
                matches[index][f"{kind}_ambiguous"] = True

    assessments: list[PersonAssessment] = []
    for person_id, record in enumerate(matches, start=1):
        person, helmet, vest = record["person"], record["helmet"], record["vest"]
        reasons: list[str] = []
        missing: list[str] = []
        if helmet is None:
            reasons.append("helmet_ambiguous" if record["helmet_ambiguous"] else "helmet_not_detected")
            missing.append("helmet")
        if vest is None:
            reasons.append("vest_ambiguous" if record["vest_ambiguous"] else "vest_not_detected")
            missing.append("vest")
        ambiguous = record["helmet_ambiguous"] or record["vest_ambiguous"]
        if record["low_resolution"]:
            reasons.append("person_too_small_for_reliable_assessment")

        if helmet is not None and vest is not None and not record["low_resolution"]:
            status = "compliant"
        elif record["low_resolution"] or ambiguous:
            status = "indeterminate"
        else:
            status = "not_detected"

        assessments.append(PersonAssessment(
            person_id=person_id,
            track_id=person.track_id,
            box=person.box,
            person_confidence=person.confidence,
            helmet_detected=helmet is not None,
            helmet_confidence=helmet.confidence if helmet else None,
            vest_detected=vest is not None,
            vest_confidence=vest.confidence if vest else None,
            status=status,
            reasons=tuple(reasons),
            missing=tuple(missing) if status == "not_detected" else (),
        ))
    return assessments

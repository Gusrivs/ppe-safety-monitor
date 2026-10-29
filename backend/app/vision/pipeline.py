"""Detección con YOLO: personas (con tracker) + casco/chaleco (modelo entrenado)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import VisionConfig
from .ppe_association import Detection, PersonAssessment, associate_equipment, normalise_label


def _validate_model_class_names(names: Any) -> None:
    labels = list(names.values()) if isinstance(names, dict) else list(names)
    canonical = {normalise_label(str(label)) for label in labels}
    if not {"helmet", "vest"}.issubset(canonical):
        raise ValueError(
            "El modelo EPP debe declarar clases reconocibles de casco y chaleco. "
            f"Clases del modelo: {labels}"
        )


def _detections(result: Any, track: bool = False) -> list[Detection]:
    output: list[Detection] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return output
    names = result.names
    ids = getattr(boxes, "id", None) if track else None
    id_list = [int(v) for v in ids.tolist()] if ids is not None else None
    for index, box in enumerate(boxes):
        class_id = int(box.cls[0].item())
        coords = tuple(float(v) for v in box.xyxy[0].tolist())
        track_id = id_list[index] if id_list is not None and index < len(id_list) else None
        output.append(Detection(str(names[class_id]), float(box.conf[0].item()), coords, track_id))  # type: ignore[arg-type]
    return output


class PpePipeline:
    """Carga los dos modelos y evalúa un fotograma -> (personas evaluadas, piezas de EPP)."""

    def __init__(self, cfg: VisionConfig, ppe_model_path: Path) -> None:
        from ultralytics import YOLO  # importación tardía: el backend arranca sin IA instalada

        if not ppe_model_path.is_file():
            raise FileNotFoundError(
                f"No existe el modelo EPP: {ppe_model_path}. Entrénalo primero (ver ml/README.md) "
                "o desactiva la visión con vision.enabled: false."
            )
        self.cfg = cfg
        self.person_model = YOLO(cfg.person_model)
        self.ppe_model = YOLO(str(ppe_model_path))
        _validate_model_class_names(self.ppe_model.names)

    def process(self, frame: Any) -> tuple[list[PersonAssessment], list[Detection]]:
        people_result = self.person_model.track(
            source=frame, persist=True, classes=[0], conf=self.cfg.confidence,
            tracker=self.cfg.tracker, device=self.cfg.device, imgsz=self.cfg.imgsz, verbose=False,
        )[0]
        ppe_result = self.ppe_model.predict(
            source=frame, conf=self.cfg.confidence, device=self.cfg.device,
            imgsz=self.cfg.imgsz, verbose=False,
        )[0]
        people = [d for d in _detections(people_result, track=True) if d.label.lower() == "person"]
        equipment = _detections(ppe_result)
        assessments = associate_equipment(people, equipment, min_person_height=self.cfg.min_person_height)
        return assessments, equipment

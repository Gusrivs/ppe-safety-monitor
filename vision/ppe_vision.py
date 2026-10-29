#!/usr/bin/env python3
"""Run per-person helmet/vest detection on still images or a webcam."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_PERSON_MODEL = "yolo26n.pt"
DEFAULT_PPE_MODEL = Path("models/ppe/best.pt")


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class PersonAssessment:
    person_id: int
    box: tuple[float, float, float, float]
    person_confidence: float
    helmet_detected: bool
    helmet_confidence: float | None
    vest_detected: bool
    vest_confidence: float | None
    status: str
    reasons: tuple[str, ...]


def _normalise_label(label: str) -> str | None:
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
    """Associate PPE centers with a person's head or torso region.

    A person is marked compliant only when both items are detected and
    unambiguously associated. Missing or ambiguous detections stay
    indeterminate; detection absence alone is not proof of non-compliance.
    """
    people = list(people)
    equipment = [d for d in equipment if _normalise_label(d.label) is not None]
    matches: list[dict[str, Detection | float | bool | list[str]]] = [
        {"person": p, "helmet": None, "vest": None, "helmet_ambiguous": False,
         "vest_ambiguous": False, "low_resolution": False}
        for p in people
    ]

    for item in matches:
        person = item["person"]
        assert isinstance(person, Detection)
        x1, y1, x2, y2 = person.box
        height = max(0.0, y2 - y1)
        item["low_resolution"] = height < min_person_height

    for item in equipment:
        kind = _normalise_label(item.label)
        assert kind in {"helmet", "vest"}
        x1, y1, x2, y2 = item.box
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        candidates: list[int] = []

        for index, record in enumerate(matches):
            person = record["person"]
            assert isinstance(person, Detection)
            px1, py1, px2, py2 = person.box
            width, height = max(0.0, px2 - px1), max(0.0, py2 - py1)
            if kind == "helmet":
                zone = (px1 + width * 0.08, py1, px2 - width * 0.08, py1 + height * 0.38)
            else:
                zone = (px1 + width * 0.08, py1 + height * 0.20,
                        px2 - width * 0.08, py1 + height * 0.82)
            if _inside(center, zone):
                candidates.append(index)

        if len(candidates) == 1:
            slot = kind
            current = matches[candidates[0]][slot]
            if current is None or item.confidence > current.confidence:  # type: ignore[union-attr]
                matches[candidates[0]][slot] = item
        elif len(candidates) > 1:
            for index in candidates:
                matches[index][f"{kind}_ambiguous"] = True

    assessments: list[PersonAssessment] = []
    for person_id, record in enumerate(matches, start=1):
        person = record["person"]
        helmet = record["helmet"]
        vest = record["vest"]
        assert isinstance(person, Detection)
        assert helmet is None or isinstance(helmet, Detection)
        assert vest is None or isinstance(vest, Detection)
        reasons: list[str] = []
        if helmet is None:
            reasons.append("helmet_ambiguous" if record["helmet_ambiguous"] else "helmet_not_detected")
        if vest is None:
            reasons.append("vest_ambiguous" if record["vest_ambiguous"] else "vest_not_detected")
        if record["low_resolution"]:
            reasons.append("person_too_small_for_reliable_assessment")
        complete = helmet is not None and vest is not None and not record["low_resolution"]
        assessments.append(
            PersonAssessment(
                person_id=person_id,
                box=person.box,
                person_confidence=person.confidence,
                helmet_detected=helmet is not None,
                helmet_confidence=helmet.confidence if helmet else None,
                vest_detected=vest is not None,
                vest_confidence=vest.confidence if vest else None,
                status="compliant" if complete else "indeterminate",
                reasons=tuple(reasons),
            )
        )
    return assessments


def _import_runtime() -> tuple[Any, Any]:
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Faltan dependencias de visión. Instálalas con: "
            "python3 -m pip install -r vision/requirements.txt"
        ) from exc
    return cv2, YOLO


def _model_detections(result: Any, names: Any) -> list[Detection]:
    output: list[Detection] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return output
    for box in boxes:
        class_id = int(box.cls[0].item())
        label = str(names[class_id])
        coords = tuple(float(v) for v in box.xyxy[0].tolist())
        output.append(Detection(label, float(box.conf[0].item()), coords))
    return output


class VisionPipeline:
    def __init__(
        self,
        person_model_path: str,
        ppe_model_path: str,
        *,
        device: str = "cpu",
        confidence: float = 0.25,
        min_person_height: int = 80,
    ) -> None:
        cv2, yolo_class = _import_runtime()
        self.cv2 = cv2
        ppe_path = Path(ppe_model_path)
        if not ppe_path.is_file():
            raise FileNotFoundError(
                f"No existe el modelo EPP: {ppe_path}. Entrénalo primero; "
                "consulta vision/README.md."
            )
        self.person_model = yolo_class(person_model_path)
        self.ppe_model = yolo_class(str(ppe_path))
        _validate_model_class_names(self.ppe_model.names)
        self.device = device
        self.confidence = confidence
        self.min_person_height = min_person_height

    def process_frame(self, frame: Any) -> tuple[Any, dict[str, Any]]:
        people_result = self.person_model.predict(
            source=frame, classes=[0], conf=self.confidence,
            device=self.device, verbose=False,
        )[0]
        ppe_result = self.ppe_model.predict(
            source=frame, conf=self.confidence, device=self.device, verbose=False,
        )[0]

        people = [d for d in _model_detections(people_result, people_result.names)
                  if d.label.lower() == "person"]
        equipment = _model_detections(ppe_result, ppe_result.names)
        assessments = associate_equipment(
            people, equipment, min_person_height=self.min_person_height
        )
        annotated = frame.copy()
        for assessment in assessments:
            color = (0, 170, 0) if assessment.status == "compliant" else (0, 190, 255)
            x1, y1, x2, y2 = (int(v) for v in assessment.box)
            self.cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = (f"Persona {assessment.person_id}: "
                     f"casco={'SI' if assessment.helmet_detected else '?'} "
                     f"chaleco={'SI' if assessment.vest_detected else '?'} "
                     f"{assessment.status}")
            self.cv2.putText(annotated, label, (x1, max(20, y1 - 8)),
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2)
        for item in equipment:
            x1, y1, x2, y2 = (int(v) for v in item.box)
            self.cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 120, 0), 2)
            self.cv2.putText(annotated, f"{item.label} {item.confidence:.2f}",
                             (x1, min(annotated.shape[0] - 4, y2 + 18)),
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 120, 0), 1)

        return annotated, {
            "people": [asdict(assessment) for assessment in assessments],
            "equipment_detections": [asdict(item) for item in equipment],
        }


def _validate_model_class_names(names: Any) -> None:
    labels = list(names.values()) if isinstance(names, dict) else list(names)
    canonical = {_normalise_label(str(label)) for label in labels}
    if not {"helmet", "vest"}.issubset(canonical):
        raise ValueError(
            "El modelo EPP debe declarar clases reconocibles de casco y chaleco. "
            f"Clases del modelo: {labels}"
        )


def _load_models(args: argparse.Namespace) -> VisionPipeline:
    return VisionPipeline(
        args.person_model,
        str(args.ppe_model),
        device=args.device,
        confidence=args.confidence,
        min_person_height=args.min_person_height,
    )


def run_images(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"No existe la entrada: {input_path}", file=sys.stderr)
        return 2
    if input_path.is_file():
        image_paths = [input_path] if input_path.suffix.lower() in IMAGE_SUFFIXES else []
        root = input_path.parent
    else:
        image_paths = sorted(p for p in input_path.rglob("*")
                             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
        root = input_path
    if not image_paths:
        print(f"No se encontraron imágenes compatibles en: {input_path}", file=sys.stderr)
        return 2

    pipeline = _load_models(args)
    output_dir = Path(args.output).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures = 0
    for source in image_paths:
        relative = Path(source.name) if input_path.is_file() else source.relative_to(root)
        destination = (output_dir / relative).with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame = pipeline.cv2.imread(str(source))
        if frame is None:
            failures += 1
            records.append({"source": str(source), "error": "No se pudo leer la imagen"})
            continue
        annotated, result = pipeline.process_frame(frame)
        if not pipeline.cv2.imwrite(str(destination), annotated):
            failures += 1
            records.append({"source": str(source), "error": "No se pudo guardar la salida"})
            continue
        records.append({"source": str(source), "output": str(destination), **result})
        print(f"{source} -> {destination}: {len(result['people'])} persona(s)")

    summary = {
        "input": str(input_path),
        "device": args.device,
        "person_model": args.person_model,
        "ppe_model": str(args.ppe_model),
        "images_processed": len(image_paths) - failures,
        "errors": failures,
        "results": records,
    }
    (output_dir / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Resultados y anotaciones guardados en: {output_dir}")
    return 1 if failures else 0


def run_camera(args: argparse.Namespace) -> int:
    pipeline = _load_models(args)
    capture = pipeline.cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        print(f"No se pudo abrir la cámara {args.camera}.", file=sys.stderr)
        return 2
    print("Webcam activa; pulsa q para salir.")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("No se pudo leer un fotograma de la cámara.", file=sys.stderr)
                return 1
            annotated, _ = pipeline.process_frame(frame)
            pipeline.cv2.imshow("Monitoreo EPP (q para salir)", annotated)
            if pipeline.cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        pipeline.cv2.destroyAllWindows()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("images", "camera"))
    parser.add_argument("--input", default="assets", help="Imagen o carpeta de entrada")
    parser.add_argument("--output", default="output/vision", help="Directorio de resultados")
    parser.add_argument("--person-model", default=DEFAULT_PERSON_MODEL,
                        help="Pesos YOLO con clase COCO person; default descarga yolo26n.pt")
    parser.add_argument("--ppe-model", type=Path, default=DEFAULT_PPE_MODEL,
                        help="Pesos YOLO ajustados para safety_helmet y reflective_jacket")
    parser.add_argument("--device", default="cpu", help="Dispositivo Ultralytics: cpu, 0, etc.")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--min-person-height", type=int, default=80,
                        help="Altura mínima de persona en píxeles para declarar cumplimiento")
    parser.add_argument("--camera", type=int, default=0, help="Índice de cámara para modo camera")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0.0 <= args.confidence <= 1.0:
        print("--confidence debe estar entre 0 y 1", file=sys.stderr)
        return 2
    if args.min_person_height < 1:
        print("--min-person-height debe ser mayor que cero", file=sys.stderr)
        return 2
    try:
        return run_images(args) if args.mode == "images" else run_camera(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

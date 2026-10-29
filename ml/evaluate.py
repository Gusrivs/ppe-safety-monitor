#!/usr/bin/env python3
"""Evalúa un modelo en la partición de prueba (test) y guarda las métricas.

    python -m ml.evaluate --data ml/datasets/combined/data.yaml --model models/ppe/best.pt

Compara modelos ejecutándolo dos veces con --model y --output distintos (p. ej. el modelo
base y el ajustado) SOBRE EL MISMO test propio: así ves cuánto mejoró con tus imágenes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ml.dataset_tools import validate_dataset, write_normalized_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="YAML del dataset")
    parser.add_argument("--model", type=Path, default=Path("models/ppe/best.pt"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=Path("output/ml/metrics.json"))
    args = parser.parse_args()

    try:
        data = validate_dataset(args.data)
        if not args.model.is_file():
            raise FileNotFoundError(f"No existe el modelo entrenado: {args.model}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Falta Ultralytics. Instálalo con ml/requirements.txt") from exc

        model = YOLO(str(args.model))
        normalized = write_normalized_yaml(data, args.output.parent / "dataset.yaml")
        metrics = model.val(data=str(normalized), split="test", device=args.device)
        names: Any = model.names
        class_names = list(names.values()) if isinstance(names, dict) else list(names)
        per_class_ap = [float(value) for value in metrics.box.maps]
        report = {
            "dataset_yaml": str(args.data),
            "model": str(args.model),
            "split": "test",
            "device": args.device,
            "precision_mean": float(metrics.box.mp),
            "recall_mean": float(metrics.box.mr),
            "map50": float(metrics.box.map50),
            "map50_95": float(metrics.box.map),
            "per_class_map50_95": [
                {"class": str(class_names[i]), "map50_95": score}
                for i, score in enumerate(per_class_ap) if i < len(class_names)
            ],
            "note": "Mide cajas de EPP, no cumplimiento individual ni identidad.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

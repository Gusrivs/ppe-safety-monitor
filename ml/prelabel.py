#!/usr/bin/env python3
"""Pre-etiqueta tus imágenes con un modelo existente para que solo tengas que CORREGIR.

    python -m ml.prelabel --model models/ppe/base.pt \\
        --images ml/datasets/own/frames --out ml/datasets/own/prelabels

Crea un .txt por imagen (formato YOLO) con las cajas que el modelo cree ver. Súbelos junto
con las imágenes a la herramienta de etiquetado (Roboflow, CVAT o Label Studio), corrige
cajas equivocadas/faltantes y exporta en formato YOLO. Es mucho más rápido que dibujar todo.

Una imagen sin detecciones genera un .txt vacío: sigue siendo válida (fondo / persona sin EPP).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ml.dataset_tools import CLASS_NAMES

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def canonical(label: str) -> int | None:
    value = "".join(ch for ch in label.lower() if ch.isalnum())
    if value.startswith("no") or value.startswith("without"):
        return None
    if "helmet" in value or "hardhat" in value:
        return 0
    if "vest" in value or "jacket" in value or "reflective" in value:
        return 1
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, required=True, help="Pesos YOLO con casco y chaleco")
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("ml/datasets/own/prelabels"))
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    images = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        print(f"No hay imágenes en {args.images}", file=sys.stderr)
        return 2
    if not args.model.is_file():
        print(f"No existe el modelo {args.model}", file=sys.stderr)
        return 2

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    mapping = {int(i): canonical(str(n)) for i, n in model.names.items()}
    if {0, 1} - {v for v in mapping.values() if v is not None}:
        print(f"El modelo no tiene clases de casco y chaleco: {model.names}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    boxes_written = 0
    for path in images:
        result = model.predict(source=str(path), conf=args.conf, device=args.device, verbose=False)[0]
        lines = []
        for box in result.boxes:
            cls = mapping.get(int(box.cls[0].item()))
            if cls is None:
                continue
            x, y, w, h = (float(v) for v in box.xywhn[0].tolist())
            lines.append(f"{cls} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
        (args.out / f"{path.stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        boxes_written += len(lines)
    (args.out / "classes.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")
    print(f"{len(images)} imágenes, {boxes_written} cajas pre-etiquetadas en {args.out}")
    print(f"Clases (en este orden): {CLASS_NAMES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

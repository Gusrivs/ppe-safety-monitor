#!/usr/bin/env python3
"""Entrena (o ajusta) el detector de casco y chaleco.

Dos etapas recomendadas (ver ml/README.md):

  A) Modelo base con el dataset público, RÁPIDO (muestra pequeña, imagen menor, GPU de Colab si puedes):
     python -m ml.train --data datasets/ppe/.../data.yaml --fraction 0.25 --imgsz 512 --epochs 30 \\
            --name base --export models/ppe/base.pt

  B) Ajuste fino con tus imágenes (y una muestra pública para no olvidar lo aprendido):
     python -m ml.train --data ml/datasets/combined/data.yaml --model models/ppe/base.pt \\
            --epochs 40 --freeze 10 --name finetune --export models/ppe/best.pt
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ml.dataset_tools import validate_dataset, write_normalized_yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="data.yaml del dataset")
    parser.add_argument("--model", default="yolo26n.pt",
                        help="Pesos de partida: preentrenados (yolo26n.pt) o tu modelo base (.pt)")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cpu", help="cpu, 0 (primera GPU), ...")
    parser.add_argument("--fraction", type=float, default=1.0,
                        help="Fracción del conjunto de entrenamiento a usar (0-1). Útil para entrenar rápido")
    parser.add_argument("--cache", default="false", choices=["false", "ram", "disk"],
                        help="'ram' acelera las épocas si cabe en memoria")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--patience", type=int, default=15, help="Épocas sin mejora antes de parar")
    parser.add_argument("--freeze", type=int, default=0,
                        help="Congela las primeras N capas (ajuste fino con pocas imágenes: 10)")
    parser.add_argument("--lr0", type=float, default=None, help="Tasa de aprendizaje inicial (ajuste fino: 0.002)")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Retoma un entrenamiento interrumpido desde su last.pt")
    parser.add_argument("--project", default="runs/ppe")
    parser.add_argument("--name", default="helmet-vest")
    parser.add_argument("--export", type=Path, default=None,
                        help="Copia best.pt a esta ruta al terminar (p. ej. models/ppe/best.pt)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.epochs < 1 or args.imgsz < 32 or args.batch < 1 or not 0 < args.fraction <= 1:
        print("epochs/batch deben ser positivos, imgsz >= 32 y fraction en (0, 1]", file=sys.stderr)
        return 2
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Falta Ultralytics. Instálalo con: pip install -r ml/requirements.txt", file=sys.stderr)
        return 2

    try:
        if args.resume:
            model = YOLO(str(args.resume))
            model.train(resume=True)
        else:
            data = validate_dataset(args.data)
            print(f"Clases verificadas: {data['_class_names']}")
            for split, stats in data["_annotation_stats"].items():
                print(f"{split}: {stats}")
            model = YOLO(args.model)
            normalized = write_normalized_yaml(data, Path(args.project) / args.name / "dataset.yaml")
            options = dict(
                data=str(normalized), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, project=args.project, name=args.name, fraction=args.fraction,
                cache=False if args.cache == "false" else args.cache, workers=args.workers,
                patience=args.patience, freeze=args.freeze or None, verbose=True,
            )
            if args.lr0 is not None:
                options["lr0"] = args.lr0
            model.train(**{k: v for k, v in options.items() if v is not None})
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    best = Path(model.trainer.save_dir) / "weights" / "best.pt"
    print(f"Entrenamiento finalizado. Mejores pesos: {best}")
    if args.export and best.is_file():
        args.export.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, args.export)
        print(f"Copiado a {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

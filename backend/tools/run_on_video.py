#!/usr/bin/env python3
"""Corre la IA (personas + casco/chaleco + reglas) sobre un VIDEO y guarda el resultado anotado.

Sirve para probar el modelo con tus videos SIN levantar todo el sistema, y para ver cuántos
fotogramas salen 'compliant', 'not_detected' o 'indeterminate'.

    cd backend
    python tools/run_on_video.py --video ../ml/datasets/own/videos/prueba1.mp4 \\
        --ppe-model ../models/ppe/best.pt --out ../output/prueba1_anotado.mp4
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.config import VisionConfig  # noqa: E402
from app.vision.drawing import draw_frame  # noqa: E402
from app.vision.pipeline import PpePipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--ppe-model", type=Path, default=Path("../models/ppe/best.pt"))
    parser.add_argument("--person-model", default="yolo26n.pt")
    parser.add_argument("--out", type=Path, default=Path("../output/anotado.mp4"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--min-person-height", type=int, default=80)
    parser.add_argument("--skip", type=int, default=1, help="Procesa 1 de cada N fotogramas")
    args = parser.parse_args()

    cfg = VisionConfig(enabled=True, person_model=args.person_model, device=args.device,
                       confidence=args.confidence, min_person_height=args.min_person_height)
    pipeline = PpePipeline(cfg, args.ppe_model)

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        print(f"No se pudo abrir {args.video}", file=sys.stderr)
        return 2
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.out), cv2.VideoWriter_fourcc(*"mp4v"), fps / args.skip, (width, height))

    counts: Counter[str] = Counter()
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index += 1
        if (index - 1) % args.skip:
            continue
        assessments, equipment = pipeline.process(frame)
        counts.update(a.status for a in assessments)
        writer.write(draw_frame(cv2, frame, assessments, equipment, {}))
        if index % 50 == 0:
            print(f"{index} fotogramas...", flush=True)
    capture.release()
    writer.release()
    total = sum(counts.values()) or 1
    print(f"Guardado en {args.out}")
    for status in ("compliant", "not_detected", "indeterminate"):
        print(f"  {status}: {counts[status]} ({100 * counts[status] / total:.0f} % de las personas-fotograma)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Saca fotogramas de tus videos para etiquetarlos.

    python -m ml.extract_frames --videos-dir ml/datasets/own/videos --out ml/datasets/own/frames

Los archivos se llaman <video>_<número>.jpg. Ese prefijo es importante: más adelante
prepare_dataset separa train/val/test POR VIDEO, para que las métricas sean honestas
(fotogramas casi idénticos del mismo video no deben caer en train y en test a la vez).

Se descartan fotogramas borrosos y casi repetidos.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}


def safe_stem(path: Path) -> str:
    """Nombre sin espacios ni símbolos (el patrón <video>_<000123> debe ser limpio)."""
    stem = re.sub(r"[^A-Za-z0-9-]+", "-", path.stem).strip("-")
    return stem or "video"


def extract(video: Path, out_dir: Path, *, per_second: float, blur_threshold: float,
            min_change: float, max_side: int, max_frames: int | None) -> tuple[int, int]:
    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        print(f"No se pudo abrir {video}", file=sys.stderr)
        return 0, 0
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / per_second)))
    stem = safe_stem(video)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = skipped = index = 0
    previous = None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            small = cv2.resize(gray, (64, 36))
            changed = previous is None or float(np.mean(cv2.absdiff(small, previous))) >= min_change
            if sharpness >= blur_threshold and changed:
                height, width = frame.shape[:2]
                scale = max_side / max(height, width)
                if scale < 1:
                    frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
                cv2.imwrite(str(out_dir / f"{stem}_{index:06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                previous = small
                saved += 1
                if max_frames and saved >= max_frames:
                    break
            else:
                skipped += 1
        index += 1
    capture.release()
    return saved, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path, help="Un video")
    source.add_argument("--videos-dir", type=Path, help="Carpeta con videos")
    parser.add_argument("--out", type=Path, default=Path("ml/datasets/own/frames"))
    parser.add_argument("--per-second", type=float, default=2.0, help="Fotogramas candidatos por segundo")
    parser.add_argument("--blur-threshold", type=float, default=60.0,
                        help="Varianza del Laplaciano mínima (más alto = más estricto con el desenfoque)")
    parser.add_argument("--min-change", type=float, default=4.0,
                        help="Diferencia media mínima respecto al fotograma guardado anterior")
    parser.add_argument("--max-side", type=int, default=1280, help="Lado mayor máximo en píxeles")
    parser.add_argument("--max-frames", type=int, default=None, help="Máximo por video")
    args = parser.parse_args()

    videos = [args.video] if args.video else sorted(
        p for p in args.videos_dir.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        print("No se encontraron videos.", file=sys.stderr)
        return 2
    total = 0
    for video in videos:
        saved, skipped = extract(video, args.out, per_second=args.per_second,
                                 blur_threshold=args.blur_threshold, min_change=args.min_change,
                                 max_side=args.max_side, max_frames=args.max_frames)
        total += saved
        print(f"{video.name}: {saved} guardados, {skipped} descartados (borrosos o repetidos)")
    print(f"Total: {total} imágenes en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

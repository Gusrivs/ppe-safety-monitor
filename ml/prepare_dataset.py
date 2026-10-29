#!/usr/bin/env python3
"""Arma el dataset final (train/val/test) con tus imágenes etiquetadas y, opcionalmente,
una muestra del dataset público.

    python -m ml.prepare_dataset --own ml/datasets/own/labeled \\
        --public datasets/ppe/safety-Helmet-Reflective-Jacket/data.yaml --public-fraction 0.15

Entrada (--own): carpeta que contiene imágenes con sus etiquetas YOLO. Acepta tanto
`labeled/images + labeled/labels` como la exportación de Roboflow (train/valid/test, cada
uno con images/ y labels/): se ignora la partición que traiga y se vuelve a dividir.

División HONESTA: se reparte por VIDEO (nombre antes del número de fotograma). Así los
fotogramas casi idénticos de un mismo video nunca quedan en train y en test a la vez. Con menos
de 3 videos se divide cada video en bloques consecutivos (70/15/15 %) y se avisa.

El conjunto de prueba (test) es SOLO tuyo: mide cómo rinde el modelo en tu entorno real.
Del dataset público solo entra una muestra en train y val.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from ml.dataset_tools import CLASS_NAMES, validate_dataset

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FRAME_PATTERN = re.compile(r"^(?P<video>.+?)_(?P<frame>\d{6})")


def find_pairs(root: Path) -> list[tuple[Path, Path | None]]:
    """(imagen, etiqueta o None). Busca imágenes en cualquier carpeta 'images'."""
    pairs = []
    for image in sorted(root.rglob("*")):
        if image.suffix.lower() not in IMAGE_SUFFIXES or "images" not in image.parent.parts:
            continue
        parts = list(image.parts)
        index = max(i for i, part in enumerate(parts) if part == "images")
        parts[index] = "labels"
        label = Path(*parts).with_suffix(".txt")
        pairs.append((image, label if label.is_file() else None))
    return pairs


def video_and_frame(path: Path) -> tuple[str, int]:
    match = FRAME_PATTERN.match(path.stem)
    if match:
        return match["video"], int(match["frame"])
    return path.stem, 0


def split_by_video(pairs: list[tuple[Path, Path | None]], seed: int, val_videos: set[str],
                   test_videos: set[str]) -> dict[str, list[tuple[Path, Path | None]]]:
    groups: dict[str, list[tuple[Path, Path | None]]] = defaultdict(list)
    for pair in pairs:
        groups[video_and_frame(pair[0])[0]].append(pair)
    videos = sorted(groups)
    splits: dict[str, list[tuple[Path, Path | None]]] = {"train": [], "val": [], "test": []}

    if len(videos) < 3 and not (val_videos or test_videos):
        print(f"AVISO: solo hay {len(videos)} video(s); se divide cada uno en bloques consecutivos "
              "70/15/15 %. Con más videos distintos las métricas serán más fiables.", file=sys.stderr)
        for video in videos:
            ordered = sorted(groups[video], key=lambda p: video_and_frame(p[0])[1])
            n = len(ordered)
            a, b = int(n * 0.70), int(n * 0.85)
            splits["train"] += ordered[:a]
            splits["val"] += ordered[a:b]
            splits["test"] += ordered[b:]
        return splits

    rng = random.Random(seed)
    free = [v for v in videos if v not in val_videos | test_videos]
    rng.shuffle(free)
    n_val = len(val_videos) or max(1, round(len(videos) * 0.15))
    n_test = len(test_videos) or max(1, round(len(videos) * 0.15))
    chosen_val = set(val_videos) or set(free[:n_val])
    free = [v for v in free if v not in chosen_val]
    chosen_test = set(test_videos) or set(free[:n_test])
    for video in videos:
        target = "val" if video in chosen_val else "test" if video in chosen_test else "train"
        splits[target] += groups[video]
    print(f"Videos -> val: {sorted(chosen_val)} | test: {sorted(chosen_test)} | "
          f"train: {sorted(set(videos) - chosen_val - chosen_test)}")
    return splits


def public_sample(data_yaml: Path, fraction: float, seed: int) -> dict[str, list[tuple[Path, Path | None]]]:
    data = validate_dataset(data_yaml)
    rng = random.Random(seed)
    sample: dict[str, list[tuple[Path, Path | None]]] = {"train": [], "val": []}
    for split in ("train", "val"):
        sources = data[split] if isinstance(data[split], list) else [data[split]]
        pairs = [p for source in sources for p in find_pairs(Path(source))]
        rng.shuffle(pairs)
        sample[split] = pairs[: max(1, int(len(pairs) * fraction))]
    return sample


def copy_split(pairs: list[tuple[Path, Path | None]], out: Path, split: str, prefix: str, link: bool) -> int:
    images_dir, labels_dir = out / "images" / split, out / "labels" / split
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    for image, label in pairs:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{prefix}{image.name}")
        destination = images_dir / name
        if link:
            destination.unlink(missing_ok=True)
            destination.symlink_to(image.resolve())
        else:
            shutil.copy2(image, destination)
        target_label = labels_dir / Path(name).with_suffix(".txt")
        if label is not None:
            shutil.copy2(label, target_label)
        else:
            target_label.write_text("", encoding="utf-8")   # sin etiqueta = imagen de fondo
    return len(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--own", type=Path, default=Path("ml/datasets/own/labeled"))
    parser.add_argument("--out", type=Path, default=Path("ml/datasets/combined"))
    parser.add_argument("--public", type=Path, default=None, help="data.yaml del dataset público (opcional)")
    parser.add_argument("--public-fraction", type=float, default=0.15,
                        help="Fracción del dataset público que entra en train y val")
    parser.add_argument("--val-videos", default="", help="Videos para validación, separados por coma")
    parser.add_argument("--test-videos", default="", help="Videos para prueba, separados por coma")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--link", action="store_true", help="Enlaces simbólicos en vez de copiar (ahorra disco)")
    args = parser.parse_args()

    own_pairs = find_pairs(args.own)
    if not own_pairs:
        print(f"No se encontraron imágenes en {args.own} (se esperan carpetas 'images' y 'labels').",
              file=sys.stderr)
        return 2
    unlabeled = sum(1 for _, label in own_pairs if label is None)
    print(f"{len(own_pairs)} imágenes propias ({unlabeled} sin archivo de etiquetas = fondo).")

    splits = split_by_video(own_pairs, args.seed,
                            {v for v in args.val_videos.split(",") if v},
                            {v for v in args.test_videos.split(",") if v})
    if args.out.exists():
        shutil.rmtree(args.out)
    for split, pairs in splits.items():
        print(f"{split}: {copy_split(pairs, args.out, split, '', args.link)} imágenes propias")

    if args.public:
        for split, pairs in public_sample(args.public, args.public_fraction, args.seed).items():
            print(f"{split}: +{copy_split(pairs, args.out, split, 'pub_', args.link)} imágenes públicas")

    data_yaml = args.out / "data.yaml"
    data_yaml.write_text(yaml.safe_dump({
        "path": str(args.out.resolve()), "train": "images/train", "val": "images/val",
        "test": "images/test", "names": {i: n for i, n in enumerate(CLASS_NAMES)},
    }, sort_keys=False), encoding="utf-8")

    try:
        data = validate_dataset(data_yaml)
    except (ValueError, FileNotFoundError) as exc:
        print(f"\nEl dataset se creó pero NO es válido todavía: {exc}", file=sys.stderr)
        print("Normalmente significa que alguna partición no tiene ejemplos de las dos clases; "
              "etiqueta más imágenes o ajusta --val-videos/--test-videos.", file=sys.stderr)
        return 1
    for split, stats in data["_annotation_stats"].items():
        print(f"  {split}: {stats['images']} imágenes, objetos {stats['objects_per_class']}")
    print(f"\nListo: {data_yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fine-tune a small YOLO detector for helmet and reflective-jacket boxes."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path
from typing import Any


def _normalise(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def validate_dataset(data_path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Instala PyYAML con vision/requirements.txt") from exc
    if not data_path.is_file():
        raise FileNotFoundError(f"No se encontró el YAML del dataset: {data_path}")
    with data_path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("El YAML del dataset debe contener un objeto")

    names = data.get("names")
    if isinstance(names, list):
        labels = [str(name) for name in names]
    elif isinstance(names, dict):
        labels = [str(names[key]) for key in sorted(names, key=lambda key: int(key))]
    else:
        raise ValueError("El YAML debe declarar `names` como lista o mapa")

    normalized = [_normalise(label) for label in labels]
    has_helmet = any("helmet" in name or "hardhat" in name for name in normalized)
    has_vest = any(any(part in name for part in ("vest", "jacket", "reflective"))
                   for name in normalized)
    if not has_helmet or not has_vest:
        raise ValueError(
            "El dataset debe etiquetar safety_helmet y reflective_jacket; "
            f"se encontraron: {labels}"
        )

    configured_root = data.get("path")
    if configured_root:
        dataset_root = Path(configured_root)
        if not dataset_root.is_absolute():
            dataset_root = data_path.parent / dataset_root
    else:
        dataset_root = data_path.parent
    dataset_root = dataset_root.resolve()
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    annotation_stats: dict[str, Any] = {}
    for split in ("train", "val", "test"):
        split_value = data.get(split)
        if split_value is None:
            raise ValueError(f"El YAML debe declarar la partición `{split}`")
        split_values = split_value if isinstance(split_value, list) else [split_value]
        images: list[Path] = []
        normalized_values: list[str] = []
        for value in split_values:
            source = Path(str(value))
            if not source.is_absolute():
                source = dataset_root / source
            if not source.exists() and not Path(str(value)).is_absolute():
                relative = Path(str(value))
                while relative.parts and relative.parts[0] == "..":
                    relative = Path(*relative.parts[1:])
                corrected = dataset_root / relative
                if corrected.exists():
                    source = corrected
            source_text = str(source)
            if any(token in source_text for token in ("*", "?", "[")):
                matches = glob.glob(source_text, recursive=True)
                if not matches:
                    raise FileNotFoundError(f"No coincide la ruta de imágenes {split}: {source}")
                normalized_values.extend(str(Path(match).resolve()) for match in matches)
                for match in matches:
                    path = Path(match)
                    if path.is_dir():
                        images.extend(p for p in path.rglob("*") if p.suffix.lower() in image_extensions)
                    elif path.suffix.lower() in image_extensions:
                        images.append(path)
            elif source.is_dir():
                normalized_values.append(str(source.resolve()))
                images.extend(p for p in source.rglob("*") if p.suffix.lower() in image_extensions)
            elif source.is_file() and source.suffix.lower() in image_extensions:
                normalized_values.append(str(source.resolve()))
                images.append(source)
            elif source.is_file():
                normalized_values.append(str(source.resolve()))
                for line in source.read_text(encoding="utf-8").splitlines():
                    item = Path(line.strip())
                    if not line.strip():
                        continue
                    if not item.is_absolute():
                        item = source.parent / item
                    if item.is_file() and item.suffix.lower() in image_extensions:
                        images.append(item)
            else:
                raise FileNotFoundError(f"No existe la ruta de imágenes {split}: {source}")
        if not images:
            raise ValueError(f"La partición `{split}` no contiene imágenes")

        label_files = 0
        class_counts = [0] * len(labels)
        for image_path in images:
            parts = list(image_path.parts)
            image_dirs = [i for i, part in enumerate(parts) if part.lower() == "images"]
            if image_dirs:
                parts[image_dirs[-1]] = "labels"
                label_path = Path(*parts).with_suffix(".txt")
            else:
                label_path = image_path.with_suffix(".txt")
            if not label_path.is_file():
                continue
            label_files += 1
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                fields = line.split()
                if len(fields) != 5:
                    raise ValueError(f"Etiqueta inválida {label_path}:{line_number}; se esperan 5 campos")
                try:
                    class_id = int(fields[0])
                    coords = [float(field) for field in fields[1:]]
                except ValueError as exc:
                    raise ValueError(f"Etiqueta no numérica {label_path}:{line_number}") from exc
                if class_id < 0 or class_id >= len(labels):
                    raise ValueError(f"ID de clase fuera de rango en {label_path}:{line_number}")
                if not all(0 <= value <= 1 for value in coords) or coords[2] <= 0 or coords[3] <= 0:
                    raise ValueError(f"Caja YOLO fuera de rango en {label_path}:{line_number}")
                class_counts[class_id] += 1
        if not all(class_counts):
            raise ValueError(f"La partición `{split}` no tiene etiquetas para todas las clases: {class_counts}")
        data[split] = normalized_values[0] if len(normalized_values) == 1 else normalized_values
        annotation_stats[split] = {
            "images": len(images),
            "label_files": label_files,
            "images_without_label_file": len(images) - label_files,
            "objects_per_class": {labels[i]: count for i, count in enumerate(class_counts)},
        }

    data["path"] = str(dataset_root)
    data["_class_names"] = labels
    data["_annotation_stats"] = annotation_stats
    return data


def write_normalized_yaml(data: dict[str, Any], destination: Path) -> Path:
    """Write resolved absolute split paths without changing the source YAML."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Instala PyYAML con vision/requirements.txt") from exc
    public_data = {key: value for key, value in data.items() if not key.startswith("_")}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(public_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True,
                        help="Ruta al data.yaml exportado del dataset")
    parser.add_argument("--model", default="yolo26n.pt",
                        help="Pesos preentrenados para transfer learning")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--project", default="runs/ppe")
    parser.add_argument("--name", default="helmet-vest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.epochs < 1 or args.imgsz < 32 or args.batch < 1:
        print("epochs/batch deben ser positivos e imgsz debe ser >= 32", file=sys.stderr)
        return 2
    try:
        data = validate_dataset(args.data)
        print(f"Clases verificadas: {data['_class_names']}")
        for split, stats in data["_annotation_stats"].items():
            print(f"{split}: {stats}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Falta Ultralytics. Instálalo con: "
                "python3 -m pip install -r vision/requirements.txt"
            ) from exc
        model = YOLO(args.model)
        normalized_data = write_normalized_yaml(
            data, Path(args.project) / args.name / "dataset.yaml"
        )
        model.train(
            data=str(normalized_data),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            project=args.project,
            name=args.name,
            verbose=True,
        )
        print(f"Entrenamiento finalizado; busca weights/best.pt en {args.project}/{args.name}.")
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

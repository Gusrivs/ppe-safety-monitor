#!/usr/bin/env python3
"""Inspecciona un data.yaml de YOLO: particiones, etiquetas y objetos por clase.

    python -m ml.check_dataset --data ml/datasets/combined/data.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ml.dataset_tools import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Ruta al data.yaml")
    args = parser.parse_args()
    try:
        data = validate_dataset(args.data)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"Dataset no válido: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "dataset_yaml": str(args.data),
        "classes": data["_class_names"],
        "splits": data["_annotation_stats"],
        "resolved_paths": {split: data[split] for split in ("train", "val", "test")},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import tempfile
import unittest
from pathlib import Path

import yaml

from vision.train_ppe import validate_dataset


class DatasetValidationTests(unittest.TestCase):
    def _make_dataset(self, root: Path, *, bad_box: bool = False) -> Path:
        for split in ("train", "val", "test"):
            folder = "valid" if split == "val" else split
            (root / folder / "images").mkdir(parents=True)
            (root / folder / "labels").mkdir(parents=True)
            (root / folder / "images" / "sample.jpg").write_bytes(b"image-placeholder")
            helmet_x = 1.5 if bad_box else 0.5
            (root / folder / "labels" / "sample.txt").write_text(
                f"0 {helmet_x} 0.5 0.2 0.2\n1 0.5 0.5 0.3 0.4\n",
                encoding="utf-8",
            )
        config = {
            "path": str(root),
            # Mirrors the Kaggle YAML, whose ../ paths point outside the extracted folder.
            "train": "../train/images",
            "val": "../valid/images",
            "test": "../test/images",
            "names": {0: "safety_helmet", 1: "reflective_jacket"},
        }
        data_path = root / "data.yaml"
        data_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return data_path

    def test_accepts_complete_dataset_and_counts_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            data = validate_dataset(self._make_dataset(Path(directory)))
        self.assertEqual(data["_class_names"], ["safety_helmet", "reflective_jacket"])
        self.assertEqual(data["_annotation_stats"]["train"]["images"], 1)
        self.assertEqual(data["_annotation_stats"]["test"]["objects_per_class"]["safety_helmet"], 1)

    def test_rejects_out_of_range_bbox(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Caja YOLO fuera de rango"):
                validate_dataset(self._make_dataset(Path(directory), bad_box=True))

    def test_rejects_missing_split(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = self._make_dataset(Path(directory))
            config = yaml.safe_load(data_path.read_text(encoding="utf-8"))
            config.pop("test")
            data_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "partición `test`"):
                validate_dataset(data_path)


if __name__ == "__main__":
    unittest.main()

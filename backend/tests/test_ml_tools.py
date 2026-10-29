"""Pruebas del flujo de datos propios: video -> fotogramas -> dataset train/val/test."""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from ml import extract_frames, prepare_dataset
from ml.check_dataset import main as check_main


def make_video(path: Path, seconds=4, fps=10, seed=0):
    rng = np.random.default_rng(seed)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    assert writer.isOpened()
    for i in range(seconds * fps):
        frame = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (10 + i * 5, 50), (60 + i * 5, 150), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()


def label_all(frames_dir: Path, labeled: Path):
    (labeled / "images").mkdir(parents=True)
    (labeled / "labels").mkdir(parents=True)
    for image in frames_dir.glob("*.jpg"):
        (labeled / "images" / image.name).write_bytes(image.read_bytes())
        (labeled / "labels" / f"{image.stem}.txt").write_text(
            "0 0.3 0.2 0.1 0.1\n1 0.3 0.5 0.2 0.3\n")


def test_extract_names_frames_by_video(tmp_path):
    video = tmp_path / "Mi Video 1.mp4"
    make_video(video)
    saved, _ = extract_frames.extract(video, tmp_path / "frames", per_second=2, blur_threshold=0,
                                      min_change=0, max_side=1280, max_frames=None)
    names = sorted(p.name for p in (tmp_path / "frames").glob("*.jpg"))
    assert saved == len(names) > 0
    assert names[0].startswith("Mi-Video-1_") and names[0].endswith(".jpg")


@pytest.mark.parametrize("n_videos", [4, 2])
def test_prepare_dataset_splits_by_video_and_validates(tmp_path, monkeypatch, n_videos, capsys):
    frames = tmp_path / "frames"
    for i in range(n_videos):
        video = tmp_path / f"video{i}.mp4"
        make_video(video, seconds=6, seed=i)
        extract_frames.extract(video, frames, per_second=3, blur_threshold=0, min_change=0,
                               max_side=1280, max_frames=None)
    labeled = tmp_path / "labeled"
    label_all(frames, labeled)
    out = tmp_path / "combined"
    monkeypatch.setattr(sys, "argv", ["prepare", "--own", str(labeled), "--out", str(out)])
    assert prepare_dataset.main() == 0

    data = out / "data.yaml"
    assert check_main.__module__ == "ml.check_dataset"
    monkeypatch.setattr(sys, "argv", ["check", "--data", str(data)])
    assert check_main() == 0

    if n_videos >= 3:   # ningún video aparece en dos particiones
        seen = {}
        for split in ("train", "val", "test"):
            for image in (out / "images" / split).glob("*.jpg"):
                video = image.stem.rsplit("_", 1)[0]
                assert seen.setdefault(video, split) == split


def test_prepare_dataset_mixes_public_sample_only_in_train_and_val(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    for i in range(3):
        make_video(tmp_path / f"v{i}.mp4", seconds=6, seed=i)
        extract_frames.extract(tmp_path / f"v{i}.mp4", frames, per_second=3, blur_threshold=0,
                               min_change=0, max_side=1280, max_frames=None)
    labeled = tmp_path / "labeled"
    label_all(frames, labeled)

    # dataset público con el diseño del original: train/images, train/labels, valid/..., test/...
    public = tmp_path / "public"
    for split in ("train", "valid", "test"):
        (public / split / "images").mkdir(parents=True)
        (public / split / "labels").mkdir(parents=True)
        for k in range(10):
            img = np.full((64, 64, 3), 40 + k, dtype=np.uint8)
            cv2.imwrite(str(public / split / "images" / f"p{k}.jpg"), img)
            (public / split / "labels" / f"p{k}.txt").write_text("0 0.5 0.5 0.2 0.2\n1 0.5 0.6 0.3 0.3\n")
    (public / "data.yaml").write_text(
        "train: ../train/images\nval: ../valid/images\ntest: ../test/images\n"
        "names: [safety_helmet, reflective_jacket]\n")

    out = tmp_path / "combined"
    monkeypatch.setattr(sys, "argv", ["prepare", "--own", str(labeled), "--out", str(out),
                                      "--public", str(public / "data.yaml"), "--public-fraction", "0.5"])
    assert prepare_dataset.main() == 0
    assert list((out / "images" / "train").glob("pub_*.jpg"))
    assert list((out / "images" / "val").glob("pub_*.jpg"))
    assert not list((out / "images" / "test").glob("pub_*.jpg"))   # test = solo tus imágenes

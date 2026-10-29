"""Configuración del backend: se lee de config/config.yaml (o config.example.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class StorageConfig:
    data_dir: str = "data"


@dataclass
class DeviceConfig:
    simulate: bool = True
    port: str = "/dev/ttyACM0"
    baud: int = 115200
    fingerprint_capacity: int = 127


@dataclass
class AccessConfig:
    max_attempts: int = 3
    auth_timeout_s: float = 15.0
    crossing_timeout_s: float = 10.0
    door_close_delay_s: float = 1.0
    denied_display_s: float = 5.0
    retrigger_cooldown_s: float = 5.0
    device_timeout_s: float = 6.0


@dataclass
class CameraConfig:
    url: str = "http://192.168.0.7:8080/video"
    reconnect_s: float = 2.0


@dataclass
class VisionConfig:
    enabled: bool = False
    person_model: str = "yolo26n.pt"
    ppe_model: str = "models/ppe/best.pt"
    tracker: str = "bytetrack.yaml"
    device: str = "cpu"
    confidence: float = 0.25
    imgsz: int = 640
    max_fps: float = 8.0
    min_person_height: int = 80
    violation_seconds: float = 30.0
    cooldown_seconds: float = 60.0
    compliance_reset_seconds: float = 3.0
    track_lost_seconds: float = 10.0
    entry_zone: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    handoff_window_s: float = 15.0
    handoff_lookback_s: float = 5.0


@dataclass
class RecordingConfig:
    enabled: bool = False
    segment_minutes: float = 5.0
    fps: float = 10.0


@dataclass
class Settings:
    storage: StorageConfig = field(default_factory=StorageConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)

    @property
    def data_dir(self) -> Path:
        path = Path(self.storage.data_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path


def _fill(instance: Any, values: dict[str, Any]) -> None:
    known = {f.name: f for f in fields(instance)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"Opción desconocida en la configuración: {key!r}")
        current = getattr(instance, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"La sección {key!r} debe ser un mapa")
            _fill(current, value)
        else:
            setattr(instance, key, value)


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    """Carga la configuración. Prioridad: argumento, $EPP_CONFIG, config.yaml, example."""
    candidates = [
        path,
        os.environ.get("EPP_CONFIG"),
        PROJECT_ROOT / "config" / "config.yaml",
        PROJECT_ROOT / "config" / "config.example.yaml",
    ]
    settings = Settings()
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            with Path(candidate).open(encoding="utf-8") as stream:
                data = yaml.safe_load(stream) or {}
            if not isinstance(data, dict):
                raise ValueError("El archivo de configuración debe ser un mapa YAML")
            _fill(settings, data)
            break
    return settings

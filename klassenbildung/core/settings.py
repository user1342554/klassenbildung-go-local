from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from klassenbildung.core.constants import DEFAULT_WEIGHTS
from klassenbildung.core.models import ClassConfig, OptimizationSettings
from klassenbildung.core.normalization import normalize_class_id, normalize_language, normalize_music_profile

CONFIG_DIR = Path("config")
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.default.json"
USER_SETTINGS_PATH = CONFIG_DIR / "settings.json"
DEFAULT_CLASS_PROFILES_PATH = CONFIG_DIR / "class_profiles.default.json"
USER_CLASS_PROFILES_PATH = CONFIG_DIR / "class_profiles.json"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_settings() -> OptimizationSettings:
    path = USER_SETTINGS_PATH if USER_SETTINGS_PATH.exists() else DEFAULT_SETTINGS_PATH
    data = _read_json(path) if path.exists() else {}
    payload = {
        "enforce_music_profile": bool(data.get("enforce_music_profile", True)),
        "enforce_language_profile": bool(data.get("enforce_language_profile", True)),
        "solver_time_limit_seconds": int(data.get("solver_time_limit_seconds", 30)),
    }
    for key, default in DEFAULT_WEIGHTS.items():
        payload[key] = int(data.get(key, default))
    return OptimizationSettings(**payload)


def save_settings(settings: OptimizationSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with USER_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)


def _class_config_from_dict(class_id: str, payload: dict[str, Any]) -> ClassConfig:
    return ClassConfig(
        class_id=normalize_class_id(class_id) or class_id,
        label=str(payload.get("label") or class_id),
        size_min=int(payload.get("size_min", 0)),
        size_max=int(payload.get("size_max", 30)),
        music_allowed=[
            value
            for value in (normalize_music_profile(item) for item in payload.get("music_allowed", []))
            if value
        ],
        languages_allowed=[
            value
            for value in (normalize_language(item) for item in payload.get("languages_allowed", []))
            if value
        ],
    )


def load_class_configs() -> list[ClassConfig]:
    path = USER_CLASS_PROFILES_PATH if USER_CLASS_PROFILES_PATH.exists() else DEFAULT_CLASS_PROFILES_PATH
    data = _read_json(path) if path.exists() else {}
    configs = [_class_config_from_dict(class_id, payload) for class_id, payload in data.items()]
    return sorted(configs, key=lambda cfg: cfg.class_id)


def save_class_configs(class_configs: list[ClassConfig]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        config.class_id: {
            "label": config.label,
            "music_allowed": config.music_allowed,
            "languages_allowed": config.languages_allowed,
            "size_min": config.size_min,
            "size_max": config.size_max,
        }
        for config in class_configs
    }
    with USER_CLASS_PROFILES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def generate_class_configs(
    total_students: int,
    class_count: int = 7,
    year: int = 5,
    max_size: int = 30,
    existing_profiles: list[ClassConfig] | None = None,
) -> list[ClassConfig]:
    existing_by_id = {config.class_id: config for config in existing_profiles or []}
    basis = total_students // class_count if class_count else 0
    rest = total_students % class_count if class_count else 0
    configs: list[ClassConfig] = []

    for index in range(class_count):
        class_id = f"{year}{chr(ord('a') + index)}"
        target_size = basis + (1 if index < rest else 0)
        profile = existing_by_id.get(class_id)
        configs.append(
            ClassConfig(
                class_id=class_id,
                label=profile.label if profile else class_id,
                size_min=target_size,
                size_max=max(max_size, target_size),
                music_allowed=profile.music_allowed if profile else [],
                languages_allowed=profile.languages_allowed if profile else [],
            )
        )

    if configs and sum(config.size_max for config in configs) < total_students:
        needed = math.ceil(total_students / len(configs))
        configs = [
            ClassConfig(
                class_id=config.class_id,
                label=config.label,
                size_min=config.size_min,
                size_max=max(config.size_max, needed),
                music_allowed=config.music_allowed,
                languages_allowed=config.languages_allowed,
            )
            for config in configs
        ]
    return configs


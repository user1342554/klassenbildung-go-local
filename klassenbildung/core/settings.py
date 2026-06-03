from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from klassenbildung.core.constants import DEFAULT_WEIGHTS
from klassenbildung.core.models import ClassConfig, ClassSizePolicy, OptimizationSettings
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
    return settings_from_mapping(data)


def settings_from_mapping(data: Mapping[str, Any]) -> OptimizationSettings:
    payload = {
        "enforce_music_profile": bool(data.get("enforce_music_profile", False)),
        "enforce_language_profile": bool(data.get("enforce_language_profile", False)),
        "solver_time_limit_seconds": int(data.get("solver_time_limit_seconds", 30)),
    }
    for key, default in DEFAULT_WEIGHTS.items():
        payload[key] = int(data.get(key, default))
    return OptimizationSettings(**payload)


def coerce_settings(value: object | None) -> OptimizationSettings:
    if value is None:
        return load_settings()
    if isinstance(value, Mapping):
        return settings_from_mapping(value)

    base = load_settings()
    payload = {
        field_name: getattr(value, field_name, getattr(base, field_name))
        for field_name in OptimizationSettings.__dataclass_fields__
    }
    return OptimizationSettings(**payload)


def save_settings(settings: OptimizationSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with USER_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)


def _class_config_from_dict(class_id: str, payload: dict[str, Any]) -> ClassConfig:
    size_policy_payload = payload.get("size_policy") or {}
    size_policy = (
        ClassSizePolicy(
            target_size=int(size_policy_payload.get("target_size", payload.get("size_max", 30))),
            comfort_tolerance=int(size_policy_payload.get("comfort_tolerance", 0)),
            hard_tolerance=int(size_policy_payload.get("hard_tolerance", 0)),
            soft_weight=int(size_policy_payload.get("soft_weight", 0)),
        )
        if size_policy_payload
        else None
    )
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
        size_policy=size_policy,
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
            "size_policy": asdict(getattr(config, "size_policy", None)) if getattr(config, "size_policy", None) else None,
        }
        for config in class_configs
    }
    with USER_CLASS_PROFILES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def generate_class_configs(
    total_students: int,
    class_count: int = 7,
    year: int = 5,
    target_size: int | None = None,
    comfort_tolerance: int = 0,
    hard_tolerance: int = 0,
    class_size_soft_weight: int = 500,
    existing_profiles: list[ClassConfig] | None = None,
) -> list[ClassConfig]:
    existing_by_id = {config.class_id: config for config in existing_profiles or []}
    target = target_size if target_size is not None else math.ceil(total_students / class_count) if class_count else 0
    hard_tolerance = max(0, hard_tolerance)
    comfort_tolerance = max(0, min(comfort_tolerance, hard_tolerance))
    size_policy = ClassSizePolicy(
        target_size=target,
        comfort_tolerance=comfort_tolerance,
        hard_tolerance=hard_tolerance,
        soft_weight=max(0, class_size_soft_weight),
    )
    hard_min = max(0, target - hard_tolerance)
    hard_max = max(target, target + hard_tolerance)
    configs: list[ClassConfig] = []

    for index in range(class_count):
        class_id = f"{year}{chr(ord('a') + index)}"
        profile = existing_by_id.get(class_id)
        configs.append(
            ClassConfig(
                class_id=class_id,
                label=profile.label if profile else class_id,
                size_min=hard_min,
                size_max=hard_max,
                music_allowed=profile.music_allowed if profile else [],
                languages_allowed=profile.languages_allowed if profile else [],
                size_policy=size_policy,
            )
        )

    if configs and sum(config.size_min for config in configs) > total_students:
        overage = sum(config.size_min for config in configs) - total_students
        adjusted: list[ClassConfig] = []
        for config in reversed(configs):
            reduce_by = min(overage, config.size_min)
            overage -= reduce_by
            adjusted.append(
                ClassConfig(
                    class_id=config.class_id,
                    label=config.label,
                    size_min=config.size_min - reduce_by,
                    size_max=config.size_max,
                    music_allowed=config.music_allowed,
                    languages_allowed=config.languages_allowed,
                    size_policy=getattr(config, "size_policy", None),
                )
            )
        configs = list(reversed(adjusted))

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
                size_policy=getattr(config, "size_policy", None),
            )
            for config in configs
        ]
    return configs

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def normalize_class_id(value: Any) -> str | None:
    text = normalize_string(value)
    if not text:
        return None
    match = re.match(r"^\s*(\d+)\s*([a-zA-Z])", text)
    if not match:
        return text.lower()
    return f"{match.group(1)}{match.group(2).lower()}"


def normalize_gender(value: Any) -> str | None:
    text = normalize_string(value)
    return text.lower() if text else None


def normalize_language(value: Any) -> str | None:
    text = normalize_string(value)
    return text.upper() if text else None


def normalize_eligibility(value: Any) -> str | None:
    text = normalize_string(value)
    return text.upper() if text else None


def normalize_music_profile(value: Any) -> str | None:
    text = normalize_string(value)
    if not text:
        return None
    upper = text.upper().replace(".", "")
    if upper in {"REG", "REGULAER", "REGULAR"}:
        return "Reg"
    return upper


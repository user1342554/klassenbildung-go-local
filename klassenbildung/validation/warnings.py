from __future__ import annotations

import re

from klassenbildung.core.normalization import normalize_primary_class


def primary_class_looks_irregular(value: str | None) -> bool:
    if not value:
        return False
    compact = re.sub(r"\s+", "", value).upper()
    if value.upper() != compact:
        return True
    if compact.startswith("0"):
        return True
    return re.fullmatch(r"4[A-Z]", compact) is None


def primary_class_normalization_label(value: str | None) -> str | None:
    normalized = normalize_primary_class(value)
    if not value or not normalized:
        return None
    return f"{value} -> {normalized}"

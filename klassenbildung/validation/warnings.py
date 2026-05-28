from __future__ import annotations

import re


def primary_class_looks_irregular(value: str | None) -> bool:
    if not value:
        return False
    compact = re.sub(r"\s+", "", value).upper()
    if value.upper() != compact:
        return True
    if compact.startswith("0"):
        return True
    return re.fullmatch(r"4[A-Z]", compact) is None


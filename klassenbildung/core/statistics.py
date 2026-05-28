from __future__ import annotations

from collections import Counter
from typing import Callable

from klassenbildung.core.models import Student


def count_values(students: list[Student], getter: Callable[[Student], str | None]) -> dict[str, int]:
    counts = Counter(getter(student) or "leer" for student in students)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_import_statistics(students: list[Student]) -> dict[str, object]:
    return {
        "student_count": len(students),
        "classes": count_values(students, lambda student: student.original_class),
        "languages": count_values(students, lambda student: student.second_language),
        "gender": count_values(students, lambda student: student.gender),
        "music": count_values(students, lambda student: student.music_profile),
        "support_count": sum(1 for student in students if student.is_support),
        "comment_count": sum(1 for student in students if student.comment),
    }


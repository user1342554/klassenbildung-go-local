from __future__ import annotations

from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student
from klassenbildung.validation.validator import validate_students


def _student(index: int, language: str, music: str) -> Student:
    return Student(
        internal_id=f"s{index}",
        row_number=index,
        original_class=None,
        nr=str(index),
        school="Grundschule",
        last_name=f"N{index}",
        first_name=f"V{index}",
        eligibility="GYM",
        gender="w",
        birthdate=None,
        nationality="DE",
        religion="ev",
        second_language=language,
        music_profile=music,
        primary_class="4a",
        friend1=None,
        friend2=None,
        comment=None,
        is_support=False,
    )


def test_validator_detects_profile_capacity_conflict_before_solver() -> None:
    students = [
        _student(1, "F", "Reg"),
        _student(2, "F", "Reg"),
        _student(3, "F", "G"),
    ]
    classes = [
        ClassConfig("5a", "5a Reg", 1, 1, ["Reg"], ["F"]),
        ClassConfig("5b", "5b G", 1, 2, ["G"], ["F"]),
    ]

    validation = validate_students(students, classes, OptimizationSettings())

    assert any(
        "Harte Profilregeln sind mit den Klassengrößen unvereinbar" in message.message
        for message in validation.errors
    )


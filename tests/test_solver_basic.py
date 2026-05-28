from __future__ import annotations

from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student
from klassenbildung.optimization.solver import solve_assignments


def _student(index: int, language: str, music: str = "Reg") -> Student:
    return Student(
        internal_id=f"s{index}",
        row_number=index,
        original_class=None,
        nr=str(index),
        school="Grundschule",
        last_name=f"N{index}",
        first_name=f"V{index}",
        eligibility="GYM",
        gender="w" if index % 2 else "m",
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


def test_solver_respects_hard_language_profiles() -> None:
    students = [_student(1, "F"), _student(2, "F"), _student(3, "L"), _student(4, "L")]
    classes = [
        ClassConfig("5a", "5a F", 2, 2, ["Reg"], ["F"]),
        ClassConfig("5b", "5b L", 2, 2, ["Reg"], ["L"]),
    ]
    result = solve_assignments(students, classes, OptimizationSettings())

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert {result.assignments["s1"], result.assignments["s2"]} == {"5a"}
    assert {result.assignments["s3"], result.assignments["s4"]} == {"5b"}


def test_solver_reports_impossible_capacity() -> None:
    students = [_student(1, "F"), _student(2, "F")]
    classes = [ClassConfig("5a", "5a", 0, 1, ["Reg"], ["F"])]
    result = solve_assignments(students, classes, OptimizationSettings())

    assert result.status == "INFEASIBLE"


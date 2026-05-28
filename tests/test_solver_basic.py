from __future__ import annotations

import pytest

from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student
from klassenbildung.optimization.scoring import score_solution
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


def test_soft_language_profile_adds_score_penalty() -> None:
    students = [_student(1, "F")]
    classes = [ClassConfig("5a", "5a L", 0, 1, ["Reg"], ["L"])]
    settings = OptimizationSettings(
        enforce_language_profile=False,
        weight_language_profile=800,
    )
    assignments = {"s1": "5a"}

    score = score_solution(students, assignments, settings, classes)

    assert score.total_score >= 800
    assert not score.hard_violations


def test_solver_prefers_soft_language_match_when_not_hard() -> None:
    pytest.importorskip("ortools")
    students = [_student(1, "F"), _student(2, "L")]
    classes = [
        ClassConfig("5a", "5a F", 1, 1, ["Reg"], ["F"]),
        ClassConfig("5b", "5b L", 1, 1, ["Reg"], ["L"]),
    ]
    settings = OptimizationSettings(
        enforce_language_profile=False,
        weight_language_profile=1000,
        weight_gender_balance=0,
        weight_support_distribution=0,
        weight_primary_school=0,
        weight_primary_class=0,
        weight_nationality=0,
        weight_religion=0,
    )

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.assignments["s1"] == "5a"
    assert result.assignments["s2"] == "5b"

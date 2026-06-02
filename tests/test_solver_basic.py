from __future__ import annotations

from dataclasses import replace

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


def test_solver_can_still_respect_explicit_hard_language_profiles() -> None:
    students = [_student(1, "F"), _student(2, "F"), _student(3, "L"), _student(4, "L")]
    classes = [
        ClassConfig("5a", "5a F", 2, 2, ["Reg"], ["F"]),
        ClassConfig("5b", "5b L", 2, 2, ["Reg"], ["L"]),
    ]
    result = solve_assignments(students, classes, OptimizationSettings(enforce_language_profile=True))

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert {result.assignments["s1"], result.assignments["s2"]} == {"5a"}
    assert {result.assignments["s3"], result.assignments["s4"]} == {"5b"}


def test_solver_reports_impossible_capacity() -> None:
    students = [_student(1, "F"), _student(2, "F")]
    classes = [ClassConfig("5a", "5a", 0, 1, ["Reg"], ["F"])]
    result = solve_assignments(students, classes, OptimizationSettings())

    assert result.status == "INFEASIBLE"


def test_mixed_language_class_adds_score_penalty() -> None:
    students = [_student(1, "F"), _student(2, "L")]
    classes = [ClassConfig("5a", "5a", 0, 2, ["Reg"], ["F"])]
    settings = OptimizationSettings(weight_mixed_language_class=5000)
    assignments = {"s1": "5a", "s2": "5a"}

    score = score_solution(students, assignments, settings, classes)

    assert score.mixed_language_class_count == 1
    assert score.total_score >= 5000
    assert not score.hard_violations


def test_solver_prefers_pure_language_classes_when_possible() -> None:
    pytest.importorskip("ortools")
    students = [_student(1, "F"), _student(2, "F"), _student(3, "L"), _student(4, "L")]
    classes = [
        ClassConfig("5a", "5a", 2, 2, ["Reg"], []),
        ClassConfig("5b", "5b", 2, 2, ["Reg"], []),
    ]
    settings = OptimizationSettings(
        weight_mixed_language_class=5000,
        weight_gender_balance=0,
        weight_support_distribution=0,
        weight_primary_school=0,
        weight_primary_class=0,
        weight_nationality=0,
        weight_religion=0,
    )

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.score_report
    assert result.score_report.mixed_language_class_count == 0


def test_mutual_friend_pair_adds_extra_score_penalty() -> None:
    students = [
        replace(_student(1, "F"), friend1="2"),
        replace(_student(2, "F"), friend1="1"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 1, ["Reg"], []),
        ClassConfig("5b", "5b", 0, 1, ["Reg"], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    settings = OptimizationSettings(
        weight_friend1=1000,
        weight_mutual_friend=2500,
        weight_mixed_language_class=0,
    )

    score = score_solution(students, assignments, settings, classes)

    assert score.friend1_total == 2
    assert score.mutual_friend_total == 1
    assert score.mutual_friend_fulfilled == 0
    assert score.total_score >= 4500

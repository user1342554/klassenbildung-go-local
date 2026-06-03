from __future__ import annotations

import importlib

import pytest

import klassenbildung.core.models as core_models
from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.services.note_rule_conversion import (
    NoteRuleConversionError,
    convert_note_to_manual_rule,
    keep_note_as_hint,
)


def test_note_can_be_converted_to_separate_rule() -> None:
    students = [_student(1, note_text="nicht mit Max"), _student(2)]

    result = convert_note_to_manual_rule(
        students,
        "s1",
        "SEPARATE",
        selected_student_id="s2",
        confirmed=True,
    )

    assert result.rule
    assert result.rule.type == "SEPARATE"
    assert result.rule.student_a == "s1"
    assert result.rule.student_b == "s2"


def test_note_can_be_converted_to_together_rule() -> None:
    students = [_student(1, note_text="mit Ben"), _student(2)]

    result = convert_note_to_manual_rule(
        students,
        "s1",
        "TOGETHER",
        selected_student_id="s2",
        confirmed=True,
    )

    assert result.rule
    assert result.rule.type == "TOGETHER"
    assert result.rule.student_a == "s1"
    assert result.rule.student_b == "s2"


def test_note_can_be_converted_to_fixed_class_rule() -> None:
    students = [_student(1, note_text="bitte 5b")]

    result = convert_note_to_manual_rule(
        students,
        "s1",
        "FIX_CLASS",
        class_id="5b",
        confirmed=True,
    )

    assert result.rule
    assert result.rule.type == "FIX_CLASS"
    assert result.rule.student_a == "s1"
    assert result.rule.class_id == "5b"


def test_note_conversion_requires_explicit_user_selection() -> None:
    students = [_student(1, note_text="nicht mit Max"), _student(2)]

    with pytest.raises(NoteRuleConversionError, match="zweiter Schüler"):
        convert_note_to_manual_rule(students, "s1", "SEPARATE", confirmed=True)


def test_converted_separate_rule_rejects_same_student() -> None:
    students = [_student(1, note_text="nicht allein")]

    with pytest.raises(NoteRuleConversionError, match="unterschiedliche Schüler"):
        convert_note_to_manual_rule(
            students,
            "s1",
            "SEPARATE",
            selected_student_id="s1",
            confirmed=True,
        )


def test_converted_together_rule_rejects_unknown_student() -> None:
    students = [_student(1, note_text="mit unbekannt")]

    with pytest.raises(NoteRuleConversionError, match="nicht gefunden"):
        convert_note_to_manual_rule(
            students,
            "s1",
            "TOGETHER",
            selected_student_id="s999",
            confirmed=True,
        )


def test_converted_fix_rule_rejects_unknown_class() -> None:
    students = [_student(1, note_text="bitte 5x")]

    with pytest.raises(NoteRuleConversionError, match="nicht bekannt"):
        convert_note_to_manual_rule(
            students,
            "s1",
            "FIX_CLASS",
            class_id="5x",
            available_class_ids=["5a", "5b"],
            confirmed=True,
        )


def test_note_conversion_requires_user_confirmation() -> None:
    students = [_student(1, note_text="nicht mit Max"), _student(2)]

    with pytest.raises(NoteRuleConversionError, match="Bestätigung"):
        convert_note_to_manual_rule(students, "s1", "SEPARATE", selected_student_id="s2")


def test_note_conversion_does_not_parse_note_text_automatically() -> None:
    students = [
        _student(1, note_text="nicht mit 2"),
        _student(2),
        _student(3),
    ]

    result = convert_note_to_manual_rule(
        students,
        "s1",
        "SEPARATE",
        selected_student_id="s3",
        confirmed=True,
    )

    assert result.rule
    assert result.rule.student_b == "s3"


def test_note_can_be_kept_as_hint_without_rule() -> None:
    students = [_student(1, note_text="nur lesen")]

    result = keep_note_as_hint(students, "s1", confirmed=True)

    assert result.rule is None
    assert result.kept_as_hint is True


def test_converted_note_rule_is_used_in_next_solver_run() -> None:
    students = [
        _student(1, note_text="nicht zusammen"),
        _student(2),
        _student(3),
        _student(4),
    ]
    classes = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    conversion = convert_note_to_manual_rule(
        students,
        "s1",
        "SEPARATE",
        selected_student_id="s2",
        confirmed=True,
    )
    assert conversion.rule

    result = solve_assignments(students, classes, OptimizationSettings(), manual_rules=[conversion.rule])

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.assignments["s1"] != result.assignments["s2"]
    assert result.score_report
    assert not result.score_report.hard_violations


def test_note_rule_service_imports_when_core_note_helpers_are_stale() -> None:
    effective_note_helper = getattr(core_models, "student_effective_note_text")
    has_note_helper = getattr(core_models, "student_has_manual_note")
    try:
        delattr(core_models, "student_effective_note_text")
        delattr(core_models, "student_has_manual_note")
        import klassenbildung.services.note_rule_conversion as module

        reloaded = importlib.reload(module)
        students = [_student(1, note_text="nicht mit 2"), _student(2)]
        result = reloaded.convert_note_to_manual_rule(
            students,
            "s1",
            "SEPARATE",
            selected_student_id="s2",
            confirmed=True,
        )
    finally:
        core_models.student_effective_note_text = effective_note_helper
        core_models.student_has_manual_note = has_note_helper
        import klassenbildung.services.note_rule_conversion as module

        importlib.reload(module)

    assert result.rule
    assert result.rule.type == "SEPARATE"


def _student(index: int, note_text: str | None = None) -> Student:
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
        second_language="F" if index % 2 else "L",
        music_profile="Reg",
        primary_class="4a",
        friend1=None,
        friend2=None,
        comment=note_text,
        note_text=note_text,
        is_support=False,
    )

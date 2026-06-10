from __future__ import annotations

from types import SimpleNamespace

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, Student
from klassenbildung.services.manual_rules import (
    NoteReviewStatus,
    active_manual_rules,
    add_manual_rule_entry,
    create_manual_rule_entry,
    delete_manual_rule_entry,
    manual_rule_entry_records,
    note_review_status_by_student,
    student_data_hash,
    update_manual_rule_entry,
    validation_errors_for_new_rule,
)


def test_active_manual_rule_records_show_source_and_status() -> None:
    students = [_student(1), _student(2)]
    entry = create_manual_rule_entry(ManualRule("SEPARATE", "s1", "s2"), source="note", note_student_id="s1")

    records = manual_rule_entry_records([entry], students)

    assert records == [
        {
            "id": entry.id,
            "Typ": "Trennen",
            "Schüler": "1 - V1 N1",
            "Ziel / Partner": "2 - V2 N2",
            "Quelle": "aus Notiz",
            "Status": "aktiv",
        }
    ]


def test_allowed_classes_rule_records_show_target_classes() -> None:
    students = [_student(1)]
    entry = create_manual_rule_entry(
        ManualRule("ALLOW_CLASSES", "s1", class_ids=("5a", "5c", "5e")),
        source="note",
        note_student_id="s1",
    )

    records = manual_rule_entry_records([entry], students)

    assert records[0]["Typ"] == "Erlaubte Klassen"
    assert records[0]["Ziel / Partner"] == "5a, 5c, 5e"


def test_manual_rule_entry_can_be_deactivated_and_deleted() -> None:
    entry = create_manual_rule_entry(ManualRule("SEPARATE", "s1", "s2"), source="note")

    deactivated = update_manual_rule_entry([entry], entry.id, active=False)

    assert active_manual_rules(deactivated) == []
    assert delete_manual_rule_entry(deactivated, entry.id) == []


def test_converted_rule_conflict_with_existing_fix_is_reported() -> None:
    students = [_student(1), _student(2)]
    classes = [ClassConfig("5a", "5a", 0, 2, [], []), ClassConfig("5b", "5b", 0, 2, [], [])]
    entries = [
        create_manual_rule_entry(ManualRule("FIX_CLASS", "s1", class_id="5a"), source="note"),
        create_manual_rule_entry(ManualRule("FIX_CLASS", "s2", class_id="5b"), source="note"),
    ]

    errors = validation_errors_for_new_rule(
        students,
        classes,
        OptimizationSettings(),
        entries,
        ManualRule("TOGETHER", "s1", "s2"),
    )

    assert any("Zusammenregel widerspricht Fixierung" in error.message for error in errors)


def test_converted_rule_conflict_with_existing_together_rule_is_reported() -> None:
    students = [_student(1), _student(2)]
    classes = [ClassConfig("5a", "5a", 0, 2, [], []), ClassConfig("5b", "5b", 0, 2, [], [])]
    entries = [create_manual_rule_entry(ManualRule("TOGETHER", "s1", "s2"), source="note")]

    errors = validation_errors_for_new_rule(
        students,
        classes,
        OptimizationSettings(),
        entries,
        ManualRule("SEPARATE", "s1", "s2"),
    )

    assert any("Zusammen- und Trennen-Regel widersprechen sich" in error.message for error in errors)


def test_add_manual_rule_entry_reactivates_duplicate() -> None:
    rule = ManualRule("SEPARATE", "s1", "s2")
    entry = create_manual_rule_entry(rule, source="note", active=False)

    entries, changed = add_manual_rule_entry([entry], rule, source="note")

    assert changed is True
    assert active_manual_rules(entries) == [rule]


def test_note_review_status_counts_kept_and_converted_notes() -> None:
    converted = create_manual_rule_entry(
        ManualRule("SEPARATE", "s1", "s2"),
        source="note",
        note_student_id="s1",
    )

    statuses = note_review_status_by_student([converted], {"s2"})

    assert statuses == {
        "s1": NoteReviewStatus.CONVERTED_TO_RULE,
        "s2": NoteReviewStatus.KEPT_AS_NOTE,
    }


def test_note_review_status_tracks_deactivated_and_unresolved_notes() -> None:
    deactivated = create_manual_rule_entry(
        ManualRule("SEPARATE", "s1", "s2"),
        source="note",
        note_student_id="s1",
        active=False,
    )

    statuses = note_review_status_by_student([deactivated], set(), {"s2"})

    assert statuses == {
        "s1": NoteReviewStatus.DEACTIVATED_RULE,
        "s2": NoteReviewStatus.UNRESOLVED_BLOCKER,
    }


def test_student_data_hash_changes_only_when_student_data_changes() -> None:
    students = [_student(1), _student(2)]
    same_students = [_student(1), _student(2)]
    changed_students = [_student(1), _student(2, note_text="neue Notiz")]

    assert student_data_hash(same_students) == student_data_hash(students)
    assert student_data_hash(changed_students) != student_data_hash(students)


def test_student_data_hash_accepts_legacy_student_without_note_text() -> None:
    legacy_student = SimpleNamespace(
        internal_id="s1",
        row_number=1,
        nr="1",
        school="Grundschule",
        last_name="N1",
        first_name="V1",
        eligibility="GYM",
        gender="w",
        second_language="F",
        music_profile="Reg",
        primary_class="4a",
        friend1=None,
        friend2=None,
        comment="alte Bemerkung",
        is_support=False,
    )

    current_student = _student(1, note_text="alte Bemerkung")

    assert student_data_hash([legacy_student]) == student_data_hash([current_student])


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

from __future__ import annotations

from klassenbildung.core.models import ClassConfig, Student
from klassenbildung.presentation.assignment_overview import (
    assignment_board_columns,
    assignment_profile_conflicts,
    assignments_from_board_value,
    student_drag_labels,
)


def test_duplicate_student_names_get_unique_drag_labels() -> None:
    students = [
        _student("s1", "Alex", "Meier", "1"),
        _student("s2", "Alex", "Meier", "2"),
    ]

    labels = student_drag_labels(students)

    assert labels == {
        "s1": "Alex Meier (Nr 1)",
        "s2": "Alex Meier (Nr 2)",
    }


def test_assignment_board_value_roundtrip_moved_student() -> None:
    students = [
        _student("s1", "Anna", "Alpha", "1"),
        _student("s2", "Ben", "Beta", "2"),
        _student("s3", "Gina", "Gamma", "3"),
    ]
    class_configs = [ClassConfig("5a", "5a", 0, 3), ClassConfig("5b", "5b", 0, 3)]
    assignments = {"s1": "5a", "s2": "5b", "s3": "5b"}

    columns = assignment_board_columns(students, assignments, class_configs)

    assert [column["class_id"] for column in columns] == ["5a", "5b"]
    assert [student["id"] for student in columns[0]["students"]] == ["s1"]
    assert [student["id"] for student in columns[1]["students"]] == ["s2", "s3"]
    assert columns[0]["students"][0]["label"] == "Anna Alpha"

    edited = assignments_from_board_value(
        {
            "columns": [
                {
                    "class_id": "5a",
                    "students": [
                        {"id": "s1", "label": "Anna Alpha"},
                        {"id": "s2", "label": "Ben Beta"},
                    ],
                },
                {"class_id": "5b", "students": [{"id": "s3", "label": "Gina Gamma"}]},
            ]
        },
        assignments,
    )

    assert edited == {"s1": "5a", "s2": "5a", "s3": "5b"}


def test_assignment_board_marks_notes_and_includes_click_details_and_friend_wishes() -> None:
    anna = _student("s1", "Anna", "Alpha", "1", language="F", friend1="2", note="Asthma")
    ben = _student("s2", "Ben", "Beta", "2", language="F")
    columns = assignment_board_columns(
        [anna, ben],
        {"s1": "5a", "s2": "5a"},
        [ClassConfig("5a", "5a", 0, 3)],
    )

    card = columns[0]["students"][0]

    assert card["has_note"] is True
    assert card["note"] == "Asthma"
    assert {field["label"]: field["value"] for field in card["details"]}["Fremdsprache"] == "F"
    assert card["friend_wishes"] == [
        {
            "priority": 1,
            "reference": "2",
            "friend_id": "s2",
            "label": "2 - Ben Beta",
        }
    ]


def test_profile_conflict_uses_configured_language_profile() -> None:
    student = _student("s1", "Anna", "Alpha", "1", language="F")
    configs = [ClassConfig("5a", "5a", 0, 3, languages_allowed=["L"])]

    conflicts = assignment_profile_conflicts([student], {"s1": "5a"}, configs)

    assert [conflict["kind"] for conflict in conflicts] == ["Sprache"]
    assert "Sprache F passt nicht zu 5a (erlaubt: L)" in conflicts[0]["message"]


def test_assignment_board_only_marks_verified_profile_conflicts() -> None:
    student = _student("s1", "Anna", "Alpha", "1", language="F")
    configs = [ClassConfig("5a", "5a", 0, 3, languages_allowed=["L"])]

    unchecked = assignment_board_columns([student], {"s1": "5a"}, configs)
    checked = assignment_board_columns(
        [student],
        {"s1": "5a"},
        configs,
        verified_profile_conflict_student_ids={"s1"},
    )

    assert unchecked[0]["students"][0]["profile_conflict_verified"] is False
    assert checked[0]["students"][0]["profile_conflict_verified"] is True


def test_manual_move_warns_against_inferred_reference_language_profile() -> None:
    french = _student("s1", "Fran", "Zösisch", "1", language="F")
    latin = _student("s2", "Lara", "Latein", "2", language="L")
    configs = [ClassConfig("5a", "5a", 0, 3), ClassConfig("5b", "5b", 0, 3)]
    reference = {"s1": "5a", "s2": "5b"}
    edited = {"s1": "5b", "s2": "5b"}

    conflicts = assignment_profile_conflicts(
        [french, latin],
        edited,
        configs,
        reference_assignments=reference,
        student_ids={"s1"},
    )

    assert len(conflicts) == 1
    assert "bisheriges Sprachprofil: L" in conflicts[0]["message"]


def _student(
    student_id: str,
    first_name: str,
    last_name: str,
    number: str,
    *,
    language: str | None = None,
    friend1: str | None = None,
    note: str | None = None,
) -> Student:
    return Student(
        internal_id=student_id,
        row_number=int(number) + 1,
        original_class=None,
        nr=number,
        school=None,
        last_name=last_name,
        first_name=first_name,
        eligibility=None,
        gender=None,
        birthdate=None,
        nationality=None,
        religion=None,
        second_language=language,
        music_profile=None,
        primary_class=None,
        friend1=friend1,
        friend2=None,
        comment=note,
        note_text=note,
    )

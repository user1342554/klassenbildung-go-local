from __future__ import annotations

from klassenbildung.core.models import ClassConfig, Student
from klassenbildung.presentation.assignment_overview import (
    assignment_board_columns,
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

    assert columns == [
        {
            "class_id": "5a",
            "class_type": "Regelklasse",
            "students": [{"id": "s1", "label": "Anna Alpha"}],
        },
        {
            "class_id": "5b",
            "class_type": "Regelklasse",
            "students": [
                {"id": "s2", "label": "Ben Beta"},
                {"id": "s3", "label": "Gina Gamma"},
            ],
        },
    ]

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


def _student(student_id: str, first_name: str, last_name: str, number: str) -> Student:
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
        second_language=None,
        music_profile=None,
        primary_class=None,
        friend1=None,
        friend2=None,
        comment=None,
    )

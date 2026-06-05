from __future__ import annotations

import pytest

from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.presentation.optimization_progress import (
    plain_status_label,
    progress_event_message,
)
from klassenbildung.presentation.standard_result_view import STANDARD_MODE_FORBIDDEN_SOLVER_JARGON


def test_progress_texts_stay_plain_language_for_standard_users() -> None:
    visible_text = "\n".join(
        [
            plain_status_label("UNKNOWN"),
            progress_event_message(
                {
                    "event": "finished",
                    "phase_name": "1 F/L-Mischklassen minimieren",
                    "phase_index": 1,
                    "phase_total": 9,
                    "status": "OPTIMAL",
                }
            ),
        ]
    )

    forbidden = [term for term in STANDARD_MODE_FORBIDDEN_SOLVER_JARGON if term in visible_text]
    assert forbidden == []


def test_solver_emits_progress_events_for_streamlit() -> None:
    pytest.importorskip("ortools")
    students = [
        _student(1, "F", "B", friend1="2"),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S", friend1="4"),
        _student(4, "L", "S", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    events: list[dict[str, object]] = []

    result = solve_assignments(
        students,
        class_configs,
        OptimizationSettings(solver_time_limit_seconds=1),
        progress_callback=events.append,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert events[0]["event"] == "started"
    assert events[0]["phase_index"] == 1
    assert any(event["event"] == "finished" and event["phase_index"] == 9 for event in events)


def _student(number: int, language: str, music: str, friend1: str | None = None) -> Student:
    return Student(
        internal_id=str(number),
        row_number=number,
        original_class=None,
        nr=str(number),
        school=None,
        last_name=f"Kind{number}",
        first_name=None,
        eligibility=None,
        gender=None,
        birthdate=None,
        nationality=None,
        religion=None,
        second_language=language,
        music_profile=music,
        primary_class=None,
        friend1=friend1,
        friend2=None,
        comment=None,
    )

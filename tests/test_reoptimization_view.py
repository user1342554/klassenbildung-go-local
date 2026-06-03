from __future__ import annotations

import importlib

import pytest

import klassenbildung.services.reoptimization as reoptimization_module
from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, SolverResult, Student
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.reoptimization_view import (
    STANDARD_REOPTIMIZATION_FORBIDDEN_JARGON,
    reoptimization_action_hints,
    reoptimization_state_text,
    reoptimization_summary_text,
    reoptimization_visible_text,
)
from klassenbildung.presentation.result_view_model import CandidateRole, CandidateSource, CandidateSummary
from klassenbildung.services.assignment_draft import ManualMove, apply_move, create_assignment_draft
from klassenbildung.services.reoptimization import (
    ReoptimizationFlowState,
    ReoptimizationReport,
    draft_reoptimization_state,
    reoptimization_rules,
    reoptimize_with_manual_fixations,
)


def test_reoptimization_view_shows_base_and_result_metrics() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)
    fixed = apply_move(draft, ManualMove("s1", "5a", "5b", lock_after_move=True), students=students, class_configs=classes)
    report = reoptimize_with_manual_fixations(fixed, students, classes, settings, base_candidate_name="E: E beide +1")

    text = reoptimization_visible_text(report)

    assert "Ausgang: E: E beide +1" in text
    assert "Fixierungen: 1" in text
    assert "weitere aktive Regeln: 0" in text
    assert "Neu optimierte" in text
    assert "Kinder ohne Wunschfreund" in text
    assert "Freund 1 erfüllt" in text
    assert "F/L-Mischklassen" in text
    assert "Musik-Mischklassen" in text
    assert "harte Regelverletzungen" in text
    assert report.base_candidate_name == "E: E beide +1"


def test_reoptimization_view_import_tolerates_stale_service_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(reoptimization_module, "ReoptimizationFlowState")
    import klassenbildung.presentation.reoptimization_view as reoptimization_view

    importlib.reload(reoptimization_view)

    assert hasattr(reoptimization_view, "reoptimization_summary_text")
    importlib.reload(reoptimization_module)
    importlib.reload(reoptimization_view)


def test_reoptimization_view_hides_solver_jargon_in_standard_mode() -> None:
    summary, students, classes, settings = _fixture()
    report = _failed_report("UNKNOWN", create_assignment_draft(summary), students, classes, settings)

    text = reoptimization_visible_text(report)

    for forbidden in STANDARD_REOPTIMIZATION_FORBIDDEN_JARGON:
        assert forbidden not in text


def test_reoptimization_blocked_state_disables_run_button() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary, manual_rules=[ManualRule("SEPARATE", "s1", "s3")])
    invalid_draft = apply_move(draft, ManualMove("s3", "5b", "5a"), students=students, class_configs=classes)
    score = score_solution(students, invalid_draft.current_assignments, settings, classes, invalid_draft.manual_rules)

    state = draft_reoptimization_state(invalid_draft, score)

    assert state == ReoptimizationFlowState.DRAFT_HAS_CONFLICTS
    assert "Regelkonflikt" in reoptimization_state_text(state)
    assert reoptimization_action_hints(state)


def test_reoptimization_unknown_state_keeps_previous_solution_message() -> None:
    summary, students, classes, settings = _fixture()
    report = _failed_report("UNKNOWN", create_assignment_draft(summary), students, classes, settings)

    assert "bisherige Entwurf bleibt erhalten" in reoptimization_summary_text(report)
    assert "Suchzeit erhöhen" in " ".join(reoptimization_action_hints(report.flow_state))


def test_reoptimization_infeasible_state_shows_actionable_conflict_message() -> None:
    summary, students, classes, settings = _fixture()
    report = _failed_report("INFEASIBLE", create_assignment_draft(summary), students, classes, settings)
    hints = " ".join(reoptimization_action_hints(report.flow_state))

    assert "nicht lösbar" in reoptimization_summary_text(report)
    assert "Fixierungen" in hints
    assert "Regeln" in hints


def _failed_report(status: str, draft, students, classes, settings) -> ReoptimizationReport:
    before_score = score_solution(students, draft.current_assignments, settings, classes, draft.manual_rules)
    return ReoptimizationReport(
        solver_result=SolverResult(status, {}),
        before_score=before_score,
        after_score=None,
        changed_student_count=0,
        fixed_student_ids=set(),
        applied_rules=reoptimization_rules(draft),
        base_candidate_key=draft.base_candidate_key,
        base_candidate_name=draft.base_candidate_key,
        manual_moves=list(draft.moves),
        manual_move_impacts=[],
    )


def _fixture():
    students = [
        _student(1, "F", "B", friend1="2"),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S", friend1="4"),
        _student(4, "L", "S", friend1="3"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5b", "s4": "5b"}
    settings = OptimizationSettings(solver_time_limit_seconds=2)
    score = score_solution(students, assignments, settings, classes)
    return _summary(assignments, score, len(students)), students, classes, settings


def _summary(assignments: dict[str, str], score, student_count: int) -> CandidateSummary:
    return CandidateSummary(
        key="E",
        name="E beide +1",
        role=CandidateRole.REVIEW,
        recommendation_role="Ausgewogenster Vorschlag",
        assignments=assignments,
        fl_mixed_actual=score.mixed_language_class_count,
        fl_mixed_allowed=2,
        music_mixed_actual=score.mixed_music_class_count,
        music_mixed_allowed=2,
        fl_minority=score.language_minority_student_count,
        music_minority=score.music_minority_student_count,
        without_wishfriend=score.isolated_friend_request_count,
        without_wishfriend_rate=score.isolated_friend_request_count / max(student_count, 1),
        friend1_satisfied=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        mutual_satisfied=score.mutual_friend_fulfilled,
        mutual_total=score.mutual_friend_total,
        friend2_satisfied=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
        social_threshold_met=True,
        candidate_for_review=True,
        automatically_approvable=False,
        gap=None,
        gap_reliable=False,
        displayed_source=CandidateSource.SLACK_SEARCH,
        refinement_attempted=False,
        refinement_status=None,
        refinement_result=None,
    )


def _student(index: int, language: str, music: str, *, friend1: str | None = None) -> Student:
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
        friend1=friend1,
        friend2=None,
        comment=None,
        note_text=None,
        is_support=False,
    )

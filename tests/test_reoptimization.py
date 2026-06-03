from __future__ import annotations

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, Student
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.result_view_model import CandidateRole, CandidateSource, CandidateSummary
from klassenbildung.services.assignment_draft import ManualMove, apply_move, create_assignment_draft
from klassenbildung.services.reoptimization import (
    draft_fixation_rules,
    reoptimization_comparison_rows,
    reoptimization_rules,
    reoptimize_with_manual_fixations,
)


def test_reoptimize_keeps_manual_fixations() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)
    fixed = apply_move(draft, ManualMove("s1", "5a", "5b", lock_after_move=True), students=students, class_configs=classes)

    report = reoptimize_with_manual_fixations(fixed, students, classes, settings)

    assert report.succeeded
    assert report.solver_result.assignments["s1"] == "5b"
    assert not report.after_score.hard_violations


def test_reoptimize_keeps_active_manual_rules() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary, manual_rules=[ManualRule("SEPARATE", "s1", "s3")])

    report = reoptimize_with_manual_fixations(draft, students, classes, settings)

    assert report.succeeded
    assert report.solver_result.assignments["s1"] != report.solver_result.assignments["s3"]


def test_reoptimize_does_not_keep_temporary_moves_unless_fixed() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)
    temporary = apply_move(draft, ManualMove("s1", "5a", "5b"), students=students, class_configs=classes)

    assert draft_fixation_rules(temporary) == []
    assert ManualRule("FIX_CLASS", "s1", class_id="5b") not in reoptimization_rules(temporary)


def test_reoptimize_reports_number_of_changed_students() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)
    fixed = apply_move(draft, ManualMove("s1", "5a", "5b", lock_after_move=True), students=students, class_configs=classes)

    report = reoptimize_with_manual_fixations(fixed, students, classes, settings)
    expected = sum(
        1
        for student_id, before_class in fixed.current_assignments.items()
        if report.solver_result.assignments.get(student_id) != before_class
    )

    assert report.changed_student_count == expected


def test_reoptimize_compares_before_after_metrics() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)
    fixed = apply_move(draft, ManualMove("s1", "5a", "5b", lock_after_move=True), students=students, class_configs=classes)

    report = reoptimize_with_manual_fixations(fixed, students, classes, settings)
    rows = reoptimization_comparison_rows(report)

    assert {row["Kennzahl"] for row in rows} >= {
        "Kinder ohne Wunschfreund",
        "Freund 1 erfüllt",
        "Musik-Minderheits-Schüler",
        "Verschobene Schüler gegenüber Entwurf",
        "Fixierungen verletzt",
    }


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
    assignments = {
        "s1": "5a",
        "s2": "5a",
        "s3": "5b",
        "s4": "5b",
    }
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

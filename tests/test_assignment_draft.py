from __future__ import annotations

import pytest

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, Student
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.result_view_model import CandidateRole, CandidateSource, CandidateSummary
from klassenbildung.services.assignment_draft import (
    AssignmentDraftError,
    ManualMove,
    apply_move,
    build_candidate_review_for_draft,
    create_assignment_draft,
    move_delta_rows,
    move_impact,
    revert_last_move,
    score_assignment,
)
from klassenbildung.services.manual_rules import NoteReviewStatus
from klassenbildung.services.manual_rules import create_manual_rule_entry


def test_assignment_draft_applies_move() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    moved = apply_move(draft, ManualMove("s1", "5a", "5b"))

    assert moved.current_assignments["s1"] == "5b"
    assert moved.moves[-1].student_id == "s1"


def test_assignment_draft_has_exactly_one_class_per_student_after_move() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)

    moved = apply_move(draft, ManualMove("s1", "5a", "5b"), students=students, class_configs=classes)

    assert set(moved.current_assignments) == {student.internal_id for student in students}
    assert all(moved.current_assignments[student.internal_id] for student in students)


def test_assignment_draft_base_assignment_is_immutable() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)

    moved = apply_move(draft, ManualMove("s1", "5a", "5b"), students=students, class_configs=classes)

    assert draft.base_assignments == summary.assignments
    assert moved.base_assignments == summary.assignments


def test_assignment_draft_reverts_move() -> None:
    summary, _students, _classes, _settings = _fixture()
    draft = create_assignment_draft(summary)
    moved = apply_move(draft, ManualMove("s1", "5a", "5b"))

    reverted = revert_last_move(moved)

    assert reverted.current_assignments == summary.assignments
    assert reverted.moves == []


def test_assignment_draft_undo_restores_previous_assignment() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)
    first = apply_move(draft, ManualMove("s1", "5a", "5b"), students=students, class_configs=classes)
    second = apply_move(first, ManualMove("s2", "5a", "5b"), students=students, class_configs=classes)

    reverted = revert_last_move(second)

    assert reverted.current_assignments["s1"] == "5b"
    assert reverted.current_assignments["s2"] == "5a"
    assert [move.student_id for move in reverted.moves] == ["s1"]


def test_assignment_draft_recomputes_without_wishfriend() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s2", "5a", "5b"), summary, students, classes, settings)

    assert impact.before_summary.without_wishfriend == 0
    assert impact.after_summary.without_wishfriend > 0
    assert impact.delta_without_wishfriend > 0


def test_assignment_draft_recomputes_friendship_counts() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s2", "5a", "5b"), summary, students, classes, settings)

    assert impact.delta_friend1 < 0
    assert impact.delta_mutual < 0


def test_assignment_draft_recomputes_profile_minorities() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s3", "5b", "5a"), summary, students, classes, settings)

    assert impact.after_summary.fl_minority != impact.before_summary.fl_minority
    assert impact.after_summary.music_minority != impact.before_summary.music_minority


def test_assignment_draft_warns_when_student_has_manual_note() -> None:
    summary, students, classes, settings = _fixture(note_for_s1=True)
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s1", "5a", "5b"), summary, students, classes, settings)

    assert any("manuelle Notiz" in warning.message for warning in impact.warnings)


def test_assignment_draft_detects_converted_manual_rule_violation() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary, manual_rules=[ManualRule("SEPARATE", "s1", "s3")])

    impact = move_impact(draft, ManualMove("s3", "5b", "5a"), summary, students, classes, settings)

    assert impact.hard_violations
    assert any(warning.level == "blocker" for warning in impact.warnings)


def test_move_impact_with_blockers_is_not_applyable() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary, manual_rules=[ManualRule("SEPARATE", "s1", "s3")])

    impact = move_impact(draft, ManualMove("s3", "5b", "5a"), summary, students, classes, settings)

    assert not impact.applyable


def test_assignment_draft_blocks_move_that_violates_active_rule() -> None:
    summary, students, classes, settings = _fixture()
    active_rule = create_manual_rule_entry(ManualRule("SEPARATE", "s1", "s3"), source="manual")
    draft = create_assignment_draft(summary, manual_rule_entries=[active_rule])

    impact = move_impact(draft, ManualMove("s3", "5b", "5a"), summary, students, classes, settings)

    assert not impact.applyable
    assert impact.hard_violations


def test_assignment_draft_disabled_rule_is_not_enforced() -> None:
    summary, students, classes, settings = _fixture()
    disabled_rule = create_manual_rule_entry(
        ManualRule("SEPARATE", "s1", "s3"),
        source="manual",
        active=False,
    )
    draft = create_assignment_draft(summary, manual_rule_entries=[disabled_rule])
    moved = apply_move(draft, ManualMove("s3", "5b", "5a"), students=students, class_configs=classes)

    score = score_assignment(moved, students, classes, settings)

    assert not score.hard_violations


def test_assignment_draft_ignores_disabled_rule() -> None:
    summary, students, classes, settings = _fixture()
    disabled_rule = create_manual_rule_entry(
        ManualRule("SEPARATE", "s1", "s3"),
        source="manual",
        active=False,
    )
    draft = create_assignment_draft(summary, manual_rule_entries=[disabled_rule])

    impact = move_impact(draft, ManualMove("s3", "5b", "5a"), summary, students, classes, settings)

    assert impact.applyable
    assert not impact.hard_violations


def test_assignment_draft_active_rule_is_enforced() -> None:
    summary, students, classes, settings = _fixture()
    active_rule = create_manual_rule_entry(ManualRule("SEPARATE", "s1", "s3"), source="manual")
    draft = create_assignment_draft(summary, manual_rule_entries=[active_rule])
    moved = apply_move(draft, ManualMove("s3", "5b", "5a"), students=students, class_configs=classes)

    score = score_assignment(moved, students, classes, settings)

    assert score.hard_violations


def test_assignment_draft_fixed_student_cannot_be_moved_without_override() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary, manual_rules=[ManualRule("FIX_CLASS", "s1", class_id="5a")])

    with pytest.raises(AssignmentDraftError, match="Fixierter Schüler"):
        apply_move(draft, ManualMove("s1", "5a", "5b"), students=students, class_configs=classes)


def test_assignment_draft_move_to_unknown_class_is_rejected() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)

    with pytest.raises(AssignmentDraftError, match="Unbekannte Zielklasse"):
        apply_move(draft, ManualMove("s1", "5a", "5x"), students=students, class_configs=classes)


def test_assignment_draft_move_unknown_student_is_rejected() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)

    with pytest.raises(AssignmentDraftError, match="Unbekannter Schüler"):
        apply_move(draft, ManualMove("s999", "5a", "5b"), students=students, class_configs=classes)


def test_assignment_draft_lock_creates_fix_rule() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    moved = apply_move(draft, ManualMove("s1", "5a", "5b", lock_after_move=True))
    score = score_assignment(moved, students, classes, settings)

    assert moved.locked_students == {"s1"}
    assert ManualRule("FIX_CLASS", "s1", class_id="5b") in moved.manual_rules
    assert not score.hard_violations


def test_assignment_draft_fix_move_creates_draft_fixation() -> None:
    summary, students, classes, _settings = _fixture()
    draft = create_assignment_draft(summary)

    moved = apply_move(
        draft,
        ManualMove("s1", "5a", "5b", lock_after_move=True),
        students=students,
        class_configs=classes,
    )

    assert "s1" in moved.locked_students
    assert ManualRule("FIX_CLASS", "s1", class_id="5b") in moved.manual_rules


def test_assignment_draft_fixation_affects_draft_score() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)
    fixed = apply_move(
        draft,
        ManualMove("s1", "5a", "5b", lock_after_move=True),
        students=students,
        class_configs=classes,
    )
    moved_again = apply_move(
        fixed,
        ManualMove("s1", "5b", "5a", override_locked=True),
        students=students,
        class_configs=classes,
    )

    score = score_assignment(moved_again, students, classes, settings)

    assert score.hard_violations


def test_move_delta_without_wishfriend_increase_is_bad() -> None:
    summary, students, classes, settings = _fixture()
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s2", "5a", "5b"), summary, students, classes, settings)
    without_wishfriend = _delta_by_key(impact, "without_wishfriend")

    assert without_wishfriend.delta > 0
    assert without_wishfriend.assessment == "schlechter"


def test_move_delta_friend1_increase_is_good() -> None:
    summary, students, classes, settings = _fixture(
        assignments={"s1": "5a", "s2": "5b", "s3": "5b", "s4": "5b"}
    )
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s2", "5b", "5a"), summary, students, classes, settings)
    friend1 = _delta_by_key(impact, "friend1")

    assert friend1.delta > 0
    assert friend1.assessment == "besser"


def test_move_delta_music_minority_decrease_is_good() -> None:
    summary, students, classes, settings = _fixture(
        assignments={"s1": "5a", "s2": "5a", "s3": "5a", "s4": "5b"}
    )
    draft = create_assignment_draft(summary)

    impact = move_impact(draft, ManualMove("s3", "5a", "5b"), summary, students, classes, settings)
    music_minority = _delta_by_key(impact, "music_minority")

    assert music_minority.delta < 0
    assert music_minority.assessment == "besser"


def test_assignment_draft_builds_review_model_from_current_assignments() -> None:
    summary, students, classes, settings = _fixture(note_for_s1=True)
    draft = create_assignment_draft(summary)
    moved = apply_move(draft, ManualMove("s2", "5a", "5b"), students=students, class_configs=classes)

    review = build_candidate_review_for_draft(
        moved,
        summary,
        students,
        classes,
        settings,
        note_review_status_by_student={"s1": NoteReviewStatus.KEPT_AS_NOTE},
    )

    assert review.summary.assignments == moved.current_assignments
    assert len(review.students_without_wishfriend) == review.summary.without_wishfriend
    assert review.students_with_manual_notes[0].review_status == NoteReviewStatus.KEPT_AS_NOTE


def _fixture(note_for_s1: bool = False, assignments: dict[str, str] | None = None):
    students = [
        _student(1, "F", "B", friend1="2", note_text="prüfen" if note_for_s1 else None),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S", friend1="4"),
        _student(4, "L", "S", friend1="3"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    assignments = assignments or {
        "s1": "5a",
        "s2": "5a",
        "s3": "5b",
        "s4": "5b",
    }
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, classes)
    summary = _summary(assignments, score, len(students))
    return summary, students, classes, settings


def _delta_by_key(impact, key: str):
    return next(row for row in move_delta_rows(impact) if row.key == key)


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


def _student(
    index: int,
    language: str,
    music: str,
    *,
    friend1: str | None = None,
    note_text: str | None = None,
) -> Student:
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
        comment=note_text,
        note_text=note_text,
        is_support=False,
    )

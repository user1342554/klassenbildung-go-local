from __future__ import annotations

from klassenbildung.core.models import (
    ClassConfig,
    ClassSizePolicy,
    OptimizationSettings,
    ProfileSlackReport,
    SolverResult,
    Student,
)
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.candidate_review import (
    ReviewReadiness,
    ReviewWarningLevel,
    build_candidate_review_model,
    build_candidate_review_models,
    candidate_review_records,
    group_reviews_by_readiness,
    review_readiness_text,
    review_warning_messages,
)
from klassenbildung.services.manual_rules import NoteReviewStatus
from klassenbildung.presentation.wording import STANDARD_MODE_FORBIDDEN_SOLVER_JARGON
from klassenbildung.services.candidate_selection import review_candidates


def test_candidate_review_without_wishfriend_rows_match_summary() -> None:
    review = _review()

    assert len(review.students_without_wishfriend) == review.summary.without_wishfriend


def test_candidate_review_mutual_friendship_rows_match_summary() -> None:
    review = _review()

    assert len(review.separated_mutual_friendships) == review.summary.mutual_total - review.summary.mutual_satisfied


def test_candidate_review_fl_minority_rows_match_summary() -> None:
    review = _review()

    assert sum(row.minority_count for row in review.fl_mixed_classes) == review.summary.fl_minority


def test_candidate_review_music_minority_rows_match_summary() -> None:
    review = _review()

    assert sum(row.minority_count for row in review.music_mixed_classes) == review.summary.music_minority


def test_candidate_review_includes_manual_note_students() -> None:
    review = _review()

    assert [row.display_name for row in review.students_with_manual_notes] == ["1 - V1 N1"]
    assert review.students_with_manual_notes[0].automatically_evaluated is False
    assert review.students_with_manual_notes[0].review_status == NoteReviewStatus.UNREVIEWED


def test_candidate_review_marks_converted_and_kept_note_statuses() -> None:
    review = _review(
        note_review_status_by_student={
            "s1": NoteReviewStatus.CONVERTED_TO_RULE,
        }
    )

    assert review.students_with_manual_notes[0].review_status == NoteReviewStatus.CONVERTED_TO_RULE
    assert not any("ungeprüfte Notizen" in warning.message for warning in review.warnings)
    assert not any("Notiz" in warning.message for warning in review.warnings)


def test_candidate_review_has_no_solver_jargon() -> None:
    review = _review()
    text = review.visible_text()

    for term in STANDARD_MODE_FORBIDDEN_SOLVER_JARGON:
        assert term not in text


def test_candidate_review_model_matches_summary_for_all_review_candidates() -> None:
    solver_result, students, class_configs, settings = _multi_candidate_fixture()

    reviews = build_candidate_review_models(solver_result, students, class_configs, settings)

    assert {review.summary.key for review in reviews} == {"C", "E", "F"}
    for review in reviews:
        assert len(review.students_without_wishfriend) == review.summary.without_wishfriend
        assert sum(row.minority_count for row in review.fl_mixed_classes) == review.summary.fl_minority
        assert sum(row.minority_count for row in review.music_mixed_classes) == review.summary.music_minority
        assert len(review.separated_mutual_friendships) == (
            review.summary.mutual_total - review.summary.mutual_satisfied
        )


def test_candidate_review_records_are_json_ready_for_all_review_candidates() -> None:
    solver_result, students, class_configs, settings = _multi_candidate_fixture()

    records = candidate_review_records(solver_result, students, class_configs, settings)

    assert {record["key"] for record in records} == {"C", "E", "F"}
    assert all("without_wishfriend" in record for record in records)
    assert all("blockers" in record for record in records)


def test_candidate_review_warning_levels_and_readiness() -> None:
    review = _review()

    assert review.readiness == ReviewReadiness.NEEDS_ATTENTION
    assert not any(warning.level == ReviewWarningLevel.BLOCKER for warning in review.warnings)
    assert any(warning.level == ReviewWarningLevel.WARNING for warning in review.warnings)
    assert any(warning.level == ReviewWarningLevel.INFO for warning in review.warnings)
    assert review.blocker_count == 0


def test_candidate_review_with_hard_violation_is_blocked() -> None:
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [ClassConfig("5a", "5a", 0, 1, [], [])]
    assignments = {"s1": "5a", "s2": "5a"}
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = _candidate_from_score("E beide +1", assignments, score)
    solver_result = SolverResult("FEASIBLE", assignments, profile_slack_reports=[candidate])
    summary = review_candidates(solver_result, len(students))[0]

    review = build_candidate_review_model(summary, students, class_configs, settings)

    assert review.readiness == ReviewReadiness.BLOCKED
    assert review.blocker_count >= 1
    assert review_warning_messages(review, ReviewWarningLevel.BLOCKER)


def test_blocked_reviews_are_grouped_away_from_reviewable_candidates() -> None:
    ready = _review_without_warning_but_unreliable_gap()
    blocked = _blocked_review()

    groups = group_reviews_by_readiness([ready, blocked])

    assert groups.reviewable == [ready]
    assert groups.blocked == [blocked]


def test_review_readiness_texts_are_user_facing() -> None:
    assert review_readiness_text(ReviewReadiness.READY_FOR_REVIEW) == "Bereit zur pädagogischen Prüfung"
    assert review_readiness_text(ReviewReadiness.NEEDS_ATTENTION) == "Prüfen, enthält Warnungen"
    assert review_readiness_text(ReviewReadiness.BLOCKED) == "Nicht verwendbar, Blocker vorhanden"


def test_review_warning_levels_classify_gap_as_info_not_blocker() -> None:
    review = _review_without_warning_but_unreliable_gap()

    assert review.readiness == ReviewReadiness.READY_FOR_REVIEW
    assert review.info_count >= 1
    assert review.warning_count == 0
    assert review.blocker_count == 0


def test_review_warning_levels_classify_comfort_size_deviation_as_warning() -> None:
    students = [_student(1, "F", "B"), _student(2, "F", "B"), _student(3, "F", "B")]
    class_configs = [
        ClassConfig(
            "5a",
            "5a",
            1,
            4,
            [],
            [],
            size_policy=ClassSizePolicy(target_size=2, comfort_tolerance=0, hard_tolerance=1, soft_weight=1),
        )
    ]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5a"}
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = _candidate_from_score("E beide +1", assignments, score, gap_reliable=True)
    solver_result = SolverResult("FEASIBLE", assignments, profile_slack_reports=[candidate])
    summary = review_candidates(solver_result, len(students))[0]

    review = build_candidate_review_model(summary, students, class_configs, settings)

    assert review.readiness == ReviewReadiness.NEEDS_ATTENTION
    assert any("Komfortbereich" in warning.message for warning in review.warnings)
    assert review.blocker_count == 0


def _review(note_review_status_by_student: dict[str, NoteReviewStatus] | None = None):
    students = [
        _student(1, "F", "B", friend1="2", note_text="nicht neben Max setzen"),
        _student(2, "F", "S", friend1="1"),
        _student(3, "L", "G", friend1="4"),
        _student(4, "L", "S", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    assignments = {
        "s1": "5a",
        "s2": "5b",
        "s3": "5a",
        "s4": "5b",
    }
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = ProfileSlackReport(
        **_candidate_kwargs("E beide +1", assignments, score)
    )
    solver_result = SolverResult("FEASIBLE", assignments, profile_slack_reports=[candidate])
    summary = review_candidates(solver_result, len(students))[0]
    return build_candidate_review_model(
        summary,
        students,
        class_configs,
        settings,
        note_review_status_by_student=note_review_status_by_student,
    )


def _review_without_warning_but_unreliable_gap():
    students = [_student(1, "F", "B"), _student(2, "F", "B")]
    class_configs = [ClassConfig("5a", "5a", 0, 2, [], [])]
    assignments = {"s1": "5a", "s2": "5a"}
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = _candidate_from_score("E beide +1", assignments, score, gap_reliable=False)
    solver_result = SolverResult("FEASIBLE", assignments, profile_slack_reports=[candidate])
    summary = review_candidates(solver_result, len(students))[0]
    return build_candidate_review_model(summary, students, class_configs, settings)


def _blocked_review():
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [ClassConfig("5a", "5a", 0, 1, [], [])]
    assignments = {"s1": "5a", "s2": "5a"}
    settings = OptimizationSettings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = _candidate_from_score("E beide +1", assignments, score)
    solver_result = SolverResult("FEASIBLE", assignments, profile_slack_reports=[candidate])
    summary = review_candidates(solver_result, len(students))[0]
    return build_candidate_review_model(summary, students, class_configs, settings)


def _multi_candidate_fixture():
    students = [
        _student(1, "F", "B", friend1="2", note_text="nicht neben Max setzen"),
        _student(2, "F", "S", friend1="1"),
        _student(3, "L", "G", friend1="4"),
        _student(4, "L", "S", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    settings = OptimizationSettings()
    assignments_by_variant = {
        "C Musik +2": {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"},
        "E beide +1": {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"},
        "F mehr Profil-Slack": {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"},
    }
    reports = [
        _candidate_from_score(
            variant,
            assignments,
            score_solution(students, assignments, settings, class_configs),
        )
        for variant, assignments in assignments_by_variant.items()
    ]
    solver_result = SolverResult("FEASIBLE", {}, profile_slack_reports=reports)
    return solver_result, students, class_configs, settings


def _candidate_from_score(
    variant: str,
    assignments: dict[str, str],
    score,
    *,
    gap_reliable: bool | None = None,
) -> ProfileSlackReport:
    return ProfileSlackReport(**_candidate_kwargs(variant, assignments, score, gap_reliable=gap_reliable))


def _candidate_kwargs(
    variant: str,
    assignments: dict[str, str],
    score,
    *,
    gap_reliable: bool | None = None,
) -> dict:
    return {
        "variant": variant,
        "language_mixed_limit": 2,
        "music_mixed_limit": 2,
        "status": "FEASIBLE",
        "mixed_language_class_count": score.mixed_language_class_count,
        "mixed_music_class_count": score.mixed_music_class_count,
        "language_minority_student_count": score.language_minority_student_count,
        "music_minority_student_count": score.music_minority_student_count,
        "isolated_friend_request_count": score.isolated_friend_request_count,
        "friend1_fulfilled": score.friend1_fulfilled,
        "friend1_total": score.friend1_total,
        "friend2_fulfilled": score.friend2_fulfilled,
        "friend2_total": score.friend2_total,
        "mutual_friend_fulfilled": score.mutual_friend_fulfilled,
        "mutual_friend_total": score.mutual_friend_total,
        "review_candidate": True,
        "social_limit_met": True,
        "gap_reliable": gap_reliable,
        "assignments": assignments,
    }


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
        row_number=index + 1,
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

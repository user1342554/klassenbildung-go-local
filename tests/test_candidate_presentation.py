from __future__ import annotations

from klassenbildung.core.models import ClassConfig, OptimizationSettings, ProfileSlackReport, SolverResult, Student
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.presentation.optimization_progress import calculation_result_summary
from klassenbildung.presentation.wording import candidate_tradeoff_text
from klassenbildung.services.candidate_selection import decision_candidate_cards, review_candidates


def test_candidate_cards_show_only_best_candidate() -> None:
    solver_result = SolverResult(
        "FEASIBLE",
        {},
        profile_slack_reports=[
            _report("C Musik +2", isolated=26, fl_actual=1, music_actual=3, fl_allowed=1, music_allowed=3),
            _report("E beide +1", isolated=28, fl_actual=2, music_actual=2, fl_allowed=2, music_allowed=2),
            _report("F mehr Profil-Slack", isolated=21, fl_actual=2, music_actual=3, fl_allowed=2, music_allowed=3),
        ],
    )

    cards = decision_candidate_cards(solver_result, 210)

    assert [summary.key for _, summary, _ in cards] == ["F"]
    assert cards[0][0] == "F - beste Lösung"


def test_calculation_summary_is_short_wishfriend_count() -> None:
    solver_result = SolverResult(
        "FEASIBLE",
        {},
        profile_slack_reports=[
            _report("A streng", isolated=58, fl_actual=1, music_actual=1, fl_allowed=1, music_allowed=1),
            _report("E beide +1", isolated=28, fl_actual=2, music_actual=2, fl_allowed=2, music_allowed=2),
            _report("F mehr Profil-Slack", isolated=21, fl_actual=2, music_actual=3, fl_allowed=2, music_allowed=3),
        ],
    )
    score = type("Score", (), {"hard_violations": [], "isolated_friend_request_count": 58})()
    solver_result = SolverResult(
        solver_result.status,
        solver_result.assignments,
        score_report=score,
        profile_slack_reports=solver_result.profile_slack_reports,
    )

    text = calculation_result_summary(solver_result, 210)

    assert text == "Lösung gefunden: 189 von 210 Kindern haben mindestens einen Wunschfreund in der Klasse."
    assert "strenge Profilvariante" not in text
    assert "Profil-Lockerung" not in text


def test_e_wording_does_not_claim_socially_better_than_c_when_c_has_less_isolation() -> None:
    solver_result = SolverResult(
        "FEASIBLE",
        {},
        profile_slack_reports=[
            _report("C Musik +2", isolated=26, fl_actual=1, music_actual=3, fl_allowed=1, music_allowed=3),
            _report("E beide +1", isolated=28, fl_actual=2, music_actual=2, fl_allowed=2, music_allowed=2),
        ],
    )
    summaries = review_candidates(solver_result, 210)
    e_summary = next(summary for summary in summaries if summary.key == "E")

    text = candidate_tradeoff_text(e_summary, summaries)

    assert "Sozial liegt E knapp hinter C" in text
    assert "besser sozial" not in text


def test_debug_payload_uses_explicit_candidate_roles() -> None:
    payload = _debug_payload()

    assert payload["default_review_candidate"] == "E beide +1"
    assert payload["social_strongest_candidate"] == "F mehr Profil-Slack"
    assert payload["fl_preserving_candidate"] == "C Musik +2"
    assert "candidate_summaries" in payload
    assert "candidate_reviews" in payload


def test_debug_payload_does_not_emit_primary_recommendation() -> None:
    payload = _debug_payload()

    assert "primary_recommendation" not in payload


def test_debug_payload_does_not_emit_balanced_recommendation() -> None:
    payload = _debug_payload()

    assert "balanced_recommendation" not in payload


def test_debug_payload_does_not_emit_slack_candidates() -> None:
    payload = _debug_payload()

    assert "slack_candidates" not in payload


def test_current_debug_payload_does_not_emit_legacy_recommendation_keys_from_solver_run() -> None:
    import app

    students = [
        _student(1, "F", "B", friend1="2"),
        _student(2, "L", "S", friend1="1"),
        _student(3, "F", "G", friend1="4"),
        _student(4, "L", "B", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    settings = OptimizationSettings(solver_time_limit_seconds=2)
    solver_result = solve_assignments(students, class_configs, settings)
    assert solver_result.score_report

    payload = app._solver_debug_payload(
        solver_result,
        students,
        class_configs,
        settings,
        solver_result.score_report,
    )
    keys = _nested_keys(payload)

    assert "primary_recommendation" not in keys
    assert "balanced_recommendation" not in keys
    assert "slack_candidates" not in keys
    assert "candidate_summaries" in payload
    assert "candidate_reviews" in payload
    assert "default_review_candidate" in payload
    assert "social_strongest_candidate" in payload
    assert "fl_preserving_candidate" in payload
    assert "overall_status" in payload


def test_current_candidate_payload_uses_explicit_role_names() -> None:
    payload = _debug_payload()

    for candidate in payload["candidate_summaries"]:
        keys = set(candidate)
        assert "role" in keys
        assert "recommendation_role" in keys
        assert "primary_recommendation" not in keys
        assert "balanced_recommendation" not in keys


def _debug_payload() -> dict[str, object]:
    import app

    solver_result = SolverResult(
        "FEASIBLE",
        {},
        profile_slack_reports=[
            _report("C Musik +2", isolated=26, fl_actual=1, music_actual=3, fl_allowed=1, music_allowed=3),
            _report("E beide +1", isolated=28, fl_actual=2, music_actual=2, fl_allowed=2, music_allowed=2),
            _report("F mehr Profil-Slack", isolated=21, fl_actual=2, music_actual=3, fl_allowed=2, music_allowed=3),
        ],
    )
    score = type("Score", (), {"total_score": 0, "hard_violations": [], "isolated_friend_request_count": 0})()

    return app._solver_debug_payload(solver_result, [], [], OptimizationSettings(), score)


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_nested_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_nested_keys(item))
        return keys
    return set()


def _report(
    variant: str,
    *,
    isolated: int,
    fl_actual: int,
    music_actual: int,
    fl_allowed: int,
    music_allowed: int,
    fl_minority: int = 0,
    music_minority: int = 0,
    role: str | None = None,
) -> ProfileSlackReport:
    return ProfileSlackReport(
        variant=variant,
        language_mixed_limit=fl_allowed,
        music_mixed_limit=music_allowed,
        status="FEASIBLE",
        mixed_language_class_count=fl_actual,
        mixed_music_class_count=music_actual,
        language_minority_student_count=fl_minority,
        music_minority_student_count=music_minority,
        isolated_friend_request_count=isolated,
        friend1_fulfilled=160,
        friend1_total=210,
        friend2_fulfilled=120,
        friend2_total=180,
        mutual_friend_fulfilled=80,
        mutual_friend_total=105,
        review_candidate=variant != "A streng",
        social_limit_met=True,
        recommendation_role=role,
        assignments={f"s{index}": f"{variant}-5a" for index in range(210)},
    )


def _student(index: int, language: str, music: str = "Reg", *, friend1: str | None = None) -> Student:
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

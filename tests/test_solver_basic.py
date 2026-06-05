from __future__ import annotations

from dataclasses import replace
from itertools import chain, repeat

import pytest

import klassenbildung.optimization.solver as solver_module
from klassenbildung.core.models import ClassConfig, ClassSizePolicy, ManualRule, OptimizationSettings, ScoreReport, Student
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.optimization.solver import (
    _build_phase_report,
    _apply_dominance_to_candidates,
    _phase_objective_limit,
    _ProfileVariantCandidate,
    _target_ladder,
    _PhaseResult,
    solve_assignments,
)


def _student(index: int, language: str, music: str = "Reg") -> Student:
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
        friend1=None,
        friend2=None,
        comment=None,
        is_support=False,
    )


def _zero_settings(**overrides: int | bool) -> OptimizationSettings:
    settings = OptimizationSettings(
        enforce_music_profile=False,
        enforce_language_profile=False,
        weight_music_profile=0,
        weight_language_profile=0,
        weight_mixed_language_class=0,
        weight_language_minority_student=0,
        weight_mixed_music_class=0,
        weight_music_minority_student=0,
        weight_music_focus_shortfall=0,
        weight_friend1=0,
        weight_friend2=0,
        weight_mutual_friend=0,
        weight_no_friend=0,
        weight_support_distribution=0,
        weight_gender_balance=0,
        weight_primary_school=0,
        weight_primary_class=0,
        weight_nationality=0,
        weight_religion=0,
        weight_keep_existing=0,
    )
    return replace(settings, **overrides)


def _score_report_for_candidate(
    *,
    isolated: int,
    mutual: int,
    friend1: int,
    language_mixed: int,
    music_mixed: int,
    friend2: int = 0,
    language_minority: int = 0,
    music_minority: int = 0,
) -> ScoreReport:
    return ScoreReport(
        total_score=isolated,
        hard_violations=[],
        friend1_total=100,
        friend1_fulfilled=friend1,
        friend2_total=100,
        friend2_fulfilled=friend2,
        mutual_friend_total=100,
        mutual_friend_fulfilled=mutual,
        mixed_language_class_count=language_mixed,
        mixed_music_class_count=music_mixed,
        language_minority_student_count=language_minority,
        music_minority_student_count=music_minority,
        music_focus_shortfall_count=0,
        isolated_friend_request_count=isolated,
        class_reports=[],
    )


def _cache_fixture() -> tuple[list[Student], list[ClassConfig], OptimizationSettings]:
    students = [_student(1, "F"), _student(2, "L")]
    classes = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    return students, classes, _zero_settings(weight_friend1=1)


def _seed_incumbent_cache(cache_key: str, assignments: dict[str, str]) -> None:
    solver_module._PROFILE_INCUMBENT_CACHE.clear()
    solver_module._PROFILE_INCUMBENT_CACHE_LOADED = True
    solver_module._PROFILE_INCUMBENT_CACHE[cache_key] = {"1:1": dict(assignments)}


def test_solver_can_still_respect_explicit_hard_language_profiles() -> None:
    students = [_student(1, "F"), _student(2, "F"), _student(3, "L"), _student(4, "L")]
    classes = [
        ClassConfig("5a", "5a F", 2, 2, ["Reg"], ["F"]),
        ClassConfig("5b", "5b L", 2, 2, ["Reg"], ["L"]),
    ]
    result = solve_assignments(students, classes, OptimizationSettings(enforce_language_profile=True))

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert {result.assignments["s1"], result.assignments["s2"]} == {"5a"}
    assert {result.assignments["s3"], result.assignments["s4"]} == {"5b"}


def test_solver_allows_mixed_music_classes_by_default() -> None:
    students = [_student(1, "F", "B"), _student(2, "F", "S")]
    classes = [ClassConfig("5a", "5a", 2, 2, ["B", "S"], [])]

    result = solve_assignments(students, classes, OptimizationSettings())

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.score_report
    assert not result.score_report.hard_violations
    assert result.score_report.mixed_music_class_count == 1


def test_solver_reports_impossible_capacity() -> None:
    students = [_student(1, "F"), _student(2, "F")]
    classes = [ClassConfig("5a", "5a", 0, 1, ["Reg"], ["F"])]
    result = solve_assignments(students, classes, OptimizationSettings())

    assert result.status == "INFEASIBLE"


def test_mixed_language_class_adds_score_penalty() -> None:
    students = [_student(1, "F"), _student(2, "L")]
    classes = [ClassConfig("5a", "5a", 0, 2, ["Reg"], ["F", "L"])]
    settings = OptimizationSettings(weight_mixed_language_class=5000)
    assignments = {"s1": "5a", "s2": "5a"}

    score = score_solution(students, assignments, settings, classes)

    assert score.mixed_language_class_count == 1
    assert score.total_score >= 5000
    assert not score.hard_violations


def test_mixed_music_class_adds_score_penalty() -> None:
    students = [_student(1, "F", "B"), _student(2, "F", "S")]
    classes = [ClassConfig("5a", "5a", 0, 2, [], [])]
    settings = OptimizationSettings(weight_mixed_music_class=5000)
    assignments = {"s1": "5a", "s2": "5a"}

    score = score_solution(students, assignments, settings, classes)

    assert score.mixed_music_class_count == 1
    assert score.total_score >= 5000
    assert not score.hard_violations


def test_solver_prefers_pure_language_classes_when_possible() -> None:
    pytest.importorskip("ortools")
    students = [_student(1, "F"), _student(2, "F"), _student(3, "L"), _student(4, "L")]
    classes = [
        ClassConfig("5a", "5a", 2, 2, ["Reg"], []),
        ClassConfig("5b", "5b", 2, 2, ["Reg"], []),
    ]
    settings = OptimizationSettings(
        weight_mixed_language_class=5000,
        weight_gender_balance=0,
        weight_support_distribution=0,
        weight_primary_school=0,
        weight_primary_class=0,
        weight_nationality=0,
        weight_religion=0,
    )

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.score_report
    assert result.score_report.mixed_language_class_count == 0


def test_lexicographic_solver_keeps_profiles_before_cross_language_friendships() -> None:
    pytest.importorskip("ortools")
    students = [
        replace(_student(1, "F"), friend1="3"),
        replace(_student(2, "F"), friend1="4"),
        replace(_student(3, "L"), friend1="1"),
        replace(_student(4, "L"), friend1="2"),
    ]
    classes = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    settings = _zero_settings(
        weight_mixed_language_class=100,
        weight_language_minority_student=10,
        weight_friend1=50000,
        weight_mutual_friend=100000,
        weight_no_friend=100000,
    )

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.profile_status == "OPTIMAL"
    assert result.profile_baseline_report
    assert result.score_report
    assert result.profile_baseline_report.mixed_language_class_count == 0
    assert result.score_report.mixed_language_class_count == 0
    assert result.score_report.friend1_fulfilled == 0
    assert result.score_report.friend_profile_conflicts["Freund 1 F/L-Konflikt"] == 4
    assert result.score_report.friend_profile_conflicts["Gegenseitig F/L-Konflikt"] == 2


def test_profile_baseline_reports_unavoidable_language_mixing() -> None:
    pytest.importorskip("ortools")
    students = [_student(1, "F"), _student(2, "L")]
    classes = [ClassConfig("5a", "5a", 2, 2, [], [])]
    settings = _zero_settings(weight_mixed_language_class=100, weight_language_minority_student=10)

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.profile_status == "OPTIMAL"
    assert result.profile_baseline_report
    assert result.profile_baseline_report.mixed_language_class_count == 1
    assert result.score_report
    assert result.score_report.mixed_language_class_count == 1


def test_social_minimum_comes_before_language_minority_depth() -> None:
    pytest.importorskip("ortools")
    students = [
        replace(_student(1, "F"), friend1="6"),
        replace(_student(2, "F"), friend1="7"),
        _student(3, "F"),
        _student(4, "F"),
        _student(5, "F"),
        replace(_student(6, "L"), friend1="1"),
        replace(_student(7, "L"), friend1="2"),
    ]
    classes = [
        ClassConfig("5a", "5a", 3, 4, [], []),
        ClassConfig("5b", "5b", 3, 4, [], []),
    ]
    settings = _zero_settings(
        weight_mixed_language_class=100,
        weight_language_minority_student=10,
        weight_friend1=5000,
        weight_mutual_friend=10000,
        weight_no_friend=10000,
    )

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.score_report
    assert result.score_report.mixed_language_class_count == 1
    assert result.score_report.isolated_friend_request_count == 0
    assert result.score_report.language_minority_student_count == 2
    phase_by_name = {phase.name: phase for phase in result.phase_reports}
    assert "3 Freigabegrenze testen: ohne Wunschfreund <= 1" in phase_by_name
    assert phase_by_name["4 Bestes Ergebnis ohne Wunschfreund suchen"].isolated_friend_request_count == 0
    assert result.displayed_solution_source
    assert result.last_accepted_phase


def test_unknown_phase_report_does_not_report_zero_values() -> None:
    report = _build_phase_report(
        "UNKNOWN-Test",
        _PhaseResult("UNKNOWN", object(), None, None, None),
        None,
        [],
        [],
        OptimizationSettings(),
        [],
    )

    assert report.status == "UNKNOWN"
    assert report.objective_value is None
    assert report.best_objective_bound is None
    assert report.mixed_language_class_count is None


def test_phase_limit_uses_found_objective_not_best_bound() -> None:
    phase = _PhaseResult("FEASIBLE", object(), objective_value=58, best_bound=18, relative_gap=0.69)

    assert _phase_objective_limit(phase) == 58


def test_target_ladder_uses_progressive_steps() -> None:
    assert _target_ladder(59, 31) == [55, 50, 45, 40, 35, 31]
    assert _target_ladder(31, 31) == []


class _FakeSolver:
    def __init__(self, class_by_student_index: dict[int, int]):
        self.class_by_student_index = class_by_student_index

    def BooleanValue(self, variable) -> bool:  # noqa: N802 - OR-Tools uses this method name.
        name = variable.Name()
        parts = name.split("_")
        student_index = int(parts[-2])
        class_index = int(parts[-1])
        return self.class_by_student_index.get(student_index) == class_index


def test_unknown_followup_phase_keeps_last_feasible_solution(monkeypatch: pytest.MonkeyPatch) -> None:
    students = [
        replace(_student(1, "F"), friend1="2"),
        replace(_student(2, "F"), friend1="1"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    fake_solver = _FakeSolver({0: 0, 1: 0})
    scripted_phases = chain(
        [
            _PhaseResult("OPTIMAL", fake_solver, 0, 0, 0.0),
            _PhaseResult("OPTIMAL", fake_solver, 0, 0, 0.0),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("FEASIBLE", fake_solver, 0, 0, 0.0),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
        ]
    )

    monkeypatch.setattr(
        "klassenbildung.optimization.solver._solve_phase",
        lambda *_args, **_kwargs: next(scripted_phases),
    )

    result = solve_assignments(
        students,
        classes,
        _zero_settings(weight_friend1=1000, weight_mutual_friend=5000, weight_no_friend=10000),
    )

    assert result.status == "FEASIBLE"
    assert result.assignments == {"s1": "5a", "s2": "5a"}
    assert result.last_accepted_phase == "4 Bestes Ergebnis ohne Wunschfreund suchen"
    assert result.last_accepted_phase_gap == 0.0
    assert result.failed_phase == "5 Gegenseitige Freunde retten"
    assert result.failed_phase_status == "UNKNOWN"
    assert result.displayed_solution_source == "4 Bestes Ergebnis ohne Wunschfreund suchen"
    assert result.phase_reports[-1].objective_value is None
    assert result.phase_reports[-1].best_objective_bound is None


def test_bad_social_phase_skips_later_friendship_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    students = [replace(_student(index, "F"), friend1=str((index % 10) + 1)) for index in range(1, 11)]
    classes = [ClassConfig(f"5{index}", f"5{index}", 0, 1, [], []) for index in range(10)]
    fake_solver = _FakeSolver({index: index for index in range(10)})
    scripted_phases = chain(
        [
            _PhaseResult("OPTIMAL", fake_solver, 0, 0, 0.0),
            _PhaseResult("OPTIMAL", fake_solver, 0, 0, 0.0),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("FEASIBLE", fake_solver, 10, 0, 1.0),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
            _PhaseResult("UNKNOWN", fake_solver, None, None, None),
        ],
        repeat(_PhaseResult("UNKNOWN", fake_solver, None, None, None)),
    )
    monkeypatch.setattr(
        "klassenbildung.optimization.solver._solve_phase",
        lambda *_args, **_kwargs: next(scripted_phases),
    )

    result = solve_assignments(students, classes, _zero_settings(weight_no_friend=10000))

    assert result.status == "FEASIBLE"
    assert result.score_report
    assert result.score_report.isolated_friend_request_count == 10
    assert result.failed_phase is None
    assert result.skipped_phase == "5 Gegenseitige Freunde retten"
    assert result.skipped_phase_status == "SKIPPED"
    assert result.skipped_phase_reason == "social_quality_not_approved_and_gap_too_high"
    assert result.phase_reports[-1].status == "SKIPPED"
    assert any(phase.name.startswith("4a Zieltreppe") for phase in result.phase_reports)
    assert result.approval_test_status == "UNKNOWN"
    assert result.approval_possible_but_unproven is True
    assert result.profile_slack_reports


def test_profile_slack_dominance_carries_better_incumbent() -> None:
    e_candidate = _ProfileVariantCandidate(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        objective_value=34,
        best_objective_bound=0,
        relative_gap=1.0,
        score=_score_report_for_candidate(
            isolated=34,
            mutual=68,
            friend1=68,
            language_mixed=2,
            music_mixed=2,
        ),
        assignments={"s1": "5a"},
        solution_source="slack_search",
        optimization_attempted=True,
    )
    f_candidate = _ProfileVariantCandidate(
        variant="F mehr Profil-Slack",
        language_mixed_limit=2,
        music_mixed_limit=3,
        status="FEASIBLE",
        objective_value=37,
        best_objective_bound=0,
        relative_gap=1.0,
        score=_score_report_for_candidate(
            isolated=37,
            mutual=81,
            friend1=81,
            language_mixed=2,
            music_mixed=3,
        ),
        assignments={"s1": "5a"},
        solution_source="slack_search",
        optimization_attempted=True,
    )

    updated = _apply_dominance_to_candidates(
        {
            "E beide +1": e_candidate,
            "F mehr Profil-Slack": f_candidate,
        }
    )

    assert updated["F mehr Profil-Slack"].score
    assert updated["F mehr Profil-Slack"].score.isolated_friend_request_count == 34
    assert updated["F mehr Profil-Slack"].dominance_source == "E beide +1"


def test_profile_slack_dominance_never_self_sources() -> None:
    d_candidate = _ProfileVariantCandidate(
        variant="D F/L +1",
        language_mixed_limit=2,
        music_mixed_limit=1,
        status="FEASIBLE",
        objective_value=40,
        best_objective_bound=0,
        relative_gap=1.0,
        score=_score_report_for_candidate(
            isolated=40,
            mutual=65,
            friend1=65,
            language_mixed=2,
            music_mixed=1,
        ),
        assignments={"s1": "5a"},
        solution_source="carried_from:D F/L +1",
        optimization_attempted=True,
        dominance_source="D F/L +1",
    )

    updated = _apply_dominance_to_candidates({"D F/L +1": d_candidate})

    assert updated["D F/L +1"].dominance_source is None
    assert updated["D F/L +1"].solution_source != "carried_from:D F/L +1"


def test_incumbent_cache_key_changes_when_manual_rule_added() -> None:
    students, classes, settings = _cache_fixture()
    base_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [])
    rule_key = solver_module._profile_incumbent_cache_key(
        students,
        classes,
        settings,
        [ManualRule("SEPARATE", "s1", "s2")],
    )

    assert rule_key != base_key


def test_incumbent_cache_key_changes_when_settings_change() -> None:
    students, classes, settings = _cache_fixture()
    base_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [])
    changed_key = solver_module._profile_incumbent_cache_key(
        students,
        classes,
        replace(settings, weight_friend1=settings.weight_friend1 + 1),
        [],
    )

    assert changed_key != base_key


def test_cached_candidate_is_not_used_after_manual_rule_change() -> None:
    students, classes, settings = _cache_fixture()
    assignments = {"s1": "5a", "s2": "5a"}
    base_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [])
    rule = ManualRule("SEPARATE", "s1", "s2")
    changed_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [rule])

    _seed_incumbent_cache(base_key, assignments)

    cached = solver_module._cached_profile_candidate(
        changed_key,
        "E beide +1",
        1,
        1,
        students,
        classes,
        settings,
        [rule],
    )

    assert cached is None


def test_cached_candidate_is_not_used_after_class_size_policy_change() -> None:
    students, classes, settings = _cache_fixture()
    assignments = {"s1": "5a", "s2": "5a"}
    base_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [])
    policy = ClassSizePolicy(target_size=1, comfort_tolerance=0, hard_tolerance=1, soft_weight=10)
    changed_classes = [
        replace(config, size_policy=policy)
        for config in classes
    ]
    changed_key = solver_module._profile_incumbent_cache_key(students, changed_classes, settings, [])

    _seed_incumbent_cache(base_key, assignments)

    cached = solver_module._cached_profile_candidate(
        changed_key,
        "E beide +1",
        1,
        1,
        students,
        changed_classes,
        settings,
        [],
    )

    assert cached is None


def test_seeded_incumbent_preserves_lower_score_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(solver_module, "_PROFILE_INCUMBENT_CACHE_PATH", tmp_path / "incumbents.json")
    solver_module._PROFILE_INCUMBENT_CACHE.clear()
    solver_module._PROFILE_INCUMBENT_CACHE_LOADED = False
    students = [
        replace(_student(1, "F"), original_class="5a"),
        replace(_student(2, "F"), original_class="5a"),
        replace(_student(3, "F"), original_class="5b"),
        replace(_student(4, "F"), original_class="5b"),
    ]
    classes = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    settings = _zero_settings(weight_keep_existing=50)
    better_assignments = {"s1": "5a", "s2": "5a", "s3": "5b", "s4": "5b"}
    worse_assignments = {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"}
    cache_key = solver_module._profile_incumbent_cache_key(students, classes, settings, [])

    better_score = solver_module.seed_profile_incumbent_assignments(
        students,
        classes,
        settings,
        better_assignments,
    )
    worse_score = solver_module.seed_profile_incumbent_assignments(
        students,
        classes,
        settings,
        worse_assignments,
    )

    assert better_score.total_score == 0
    assert worse_score.total_score > better_score.total_score
    assert solver_module._PROFILE_INCUMBENT_CACHE[cache_key]["0:0"] == better_assignments


def test_phase_reports_keep_fixed_metrics_monotonic() -> None:
    pytest.importorskip("ortools")
    students = [
        replace(_student(1, "F"), friend1="6"),
        replace(_student(2, "F"), friend1="7"),
        _student(3, "F"),
        _student(4, "F"),
        _student(5, "F"),
        replace(_student(6, "L"), friend1="1"),
        replace(_student(7, "L"), friend1="2"),
    ]
    classes = [
        ClassConfig("5a", "5a", 3, 4, [], []),
        ClassConfig("5b", "5b", 3, 4, [], []),
    ]
    settings = _zero_settings(
        weight_mixed_language_class=100,
        weight_language_minority_student=10,
        weight_friend1=5000,
        weight_mutual_friend=10000,
        weight_no_friend=10000,
    )

    result = solve_assignments(students, classes, settings)
    feasible_phases = [
        phase
        for phase in result.phase_reports
        if phase.status in {"OPTIMAL", "FEASIBLE"} and phase.mixed_language_class_count is not None
    ]
    language_limit = feasible_phases[0].mixed_language_class_count
    music_limit = feasible_phases[1].mixed_music_class_count
    no_friend_phase = next(phase for phase in feasible_phases if phase.name.startswith("4 "))

    assert all(phase.mixed_language_class_count <= language_limit for phase in feasible_phases[1:])
    assert all(phase.mixed_music_class_count <= music_limit for phase in feasible_phases[2:])
    assert all(
        phase.isolated_friend_request_count <= no_friend_phase.isolated_friend_request_count
        for phase in feasible_phases
        if phase.name > no_friend_phase.name
    )


def test_solver_objective_matches_score_report() -> None:
    pytest.importorskip("ortools")
    students = [
        replace(_student(1, "F", "B"), friend1="2", is_support=True),
        replace(_student(2, "L", "S"), friend1="1", is_support=True),
        _student(3, "F", "Reg"),
        _student(4, "L", "Reg"),
    ]
    classes = [
        ClassConfig("5a", "5a", 2, 2, [], []),
        ClassConfig("5b", "5b", 2, 2, [], []),
    ]
    settings = OptimizationSettings(solver_time_limit_seconds=10)

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.score_report
    assert result.objective_value == result.score_report.total_score


def test_mutual_friend_pair_uses_pair_score_instead_of_double_counting() -> None:
    students = [
        replace(_student(1, "F"), friend1="2"),
        replace(_student(2, "F"), friend1="1"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 1, ["Reg"], []),
        ClassConfig("5b", "5b", 0, 1, ["Reg"], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    settings = _zero_settings(
        weight_friend1=1000,
        weight_mutual_friend=2500,
    )

    score = score_solution(students, assignments, settings, classes)

    assert score.friend1_total == 2
    assert score.mutual_friend_total == 1
    assert score.mutual_friend_fulfilled == 0
    assert score.total_score == 2500


def test_language_minority_penalty_distinguishes_small_and_large_mixes() -> None:
    classes = [ClassConfig("5a", "5a", 0, 30, [], [])]
    settings = _zero_settings(
        weight_mixed_language_class=10000,
        weight_language_minority_student=1500,
    )
    small_mix_students = [_student(index, "F") for index in range(1, 30)] + [_student(30, "L")]
    large_mix_students = [_student(index, "F") for index in range(1, 16)] + [
        _student(index, "L") for index in range(16, 31)
    ]

    small_score = score_solution(
        small_mix_students,
        {student.internal_id: "5a" for student in small_mix_students},
        settings,
        classes,
    )
    large_score = score_solution(
        large_mix_students,
        {student.internal_id: "5a" for student in large_mix_students},
        settings,
        classes,
    )

    assert small_score.language_minority_student_count == 1
    assert large_score.language_minority_student_count == 15
    assert small_score.total_score == 11500
    assert large_score.total_score == 32500
    assert small_score.total_score < large_score.total_score


def test_friend_relationship_is_counted_once_per_pair() -> None:
    students = [
        replace(_student(1, "F"), friend1="2"),
        replace(_student(2, "F"), friend1="1"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 1, [], []),
        ClassConfig("5b", "5b", 0, 1, [], []),
    ]
    settings = _zero_settings(weight_friend1=2500, weight_mutual_friend=10000)
    assignments = {"s1": "5a", "s2": "5b"}

    score = score_solution(students, assignments, settings, classes)

    assert score.friend1_total == 2
    assert score.mutual_friend_total == 1
    assert score.total_score == 10000
    assert score.category_scores["Freundschaften getrennt"] == 10000


def test_child_without_any_requested_friend_gets_own_penalty() -> None:
    students = [
        replace(_student(1, "F"), friend1="2"),
        _student(2, "F"),
    ]
    classes = [
        ClassConfig("5a", "5a", 0, 1, [], []),
        ClassConfig("5b", "5b", 0, 1, [], []),
    ]
    settings = _zero_settings(weight_friend1=0, weight_no_friend=12000)
    assignments = {"s1": "5a", "s2": "5b"}

    score = score_solution(students, assignments, settings, classes)

    assert score.isolated_friend_request_count == 1
    assert score.total_score == 12000


def test_support_distribution_penalty_is_nonlinear_after_tolerance() -> None:
    students = [replace(_student(index, "F"), is_support=True) for index in range(1, 7)]
    classes = [
        ClassConfig("5a", "5a", 0, 6, [], []),
        ClassConfig("5b", "5b", 0, 6, [], []),
        ClassConfig("5c", "5c", 0, 6, [], []),
    ]
    settings = _zero_settings(weight_support_distribution=1200)
    assignments = {student.internal_id: "5a" for student in students}

    score = score_solution(students, assignments, settings, classes)

    assert score.category_scores["R-Ballung"] == 10800
    assert score.total_score == 10800


def test_music_focus_shortfall_penalizes_reg_majority_in_focus_class() -> None:
    students = [_student(index, "F", "B") for index in range(1, 7)] + [
        _student(index, "F", "Reg") for index in range(7, 27)
    ]
    classes = [ClassConfig("5a", "5a", 0, 30, [], [])]
    settings = _zero_settings(weight_music_focus_shortfall=500)
    assignments = {student.internal_id: "5a" for student in students}

    score = score_solution(students, assignments, settings, classes)

    assert score.music_focus_shortfall_count == 14
    assert score.total_score == 7000


def test_nationality_weight_is_ignored_as_deactivated_criterion() -> None:
    students = [_student(index, "F") for index in range(1, 5)]
    classes = [ClassConfig("5a", "5a", 0, 4, [], [])]
    settings = _zero_settings(weight_nationality=999999)
    assignments = {student.internal_id: "5a" for student in students}

    score = score_solution(students, assignments, settings, classes)

    assert score.total_score == 0


def test_class_size_policy_scores_comfort_and_hard_ranges() -> None:
    students = [_student(index, "F") for index in range(60)]
    settings = _zero_settings()
    policy = ClassSizePolicy(target_size=30, comfort_tolerance=2, hard_tolerance=5, soft_weight=100)
    classes = [
        ClassConfig("5a", "5a", 25, 35, [], [], policy),
        ClassConfig("5b", "5b", 25, 35, [], [], policy),
    ]

    comfort_score = score_solution(
        students,
        {student.internal_id: "5a" if index < 32 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )
    slight_score = score_solution(
        students,
        {student.internal_id: "5a" if index < 33 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )
    large_score = score_solution(
        students,
        {student.internal_id: "5a" if index < 35 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )
    hard_violation_score = score_solution(
        students,
        {student.internal_id: "5a" if index < 36 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )

    assert "Klassengröße Komfortbereich" not in comfort_score.category_scores
    assert slight_score.category_scores["Klassengröße Komfortbereich"] == 200
    assert large_score.category_scores["Klassengröße Komfortbereich"] == 1800
    assert any("5a: zu groß" in violation for violation in hard_violation_score.hard_violations)


def test_class_size_comfort_zone_has_zero_penalty() -> None:
    students = [_student(index, "F") for index in range(64)]
    settings = _zero_settings()
    policy = ClassSizePolicy(target_size=30, comfort_tolerance=2, hard_tolerance=5, soft_weight=100)
    classes = [
        ClassConfig("5a", "5a", 25, 35, [], [], policy),
        ClassConfig("5b", "5b", 25, 35, [], [], policy),
    ]

    score = score_solution(
        students,
        {student.internal_id: "5a" if index < 32 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )

    assert "Klassengröße Komfortbereich" not in score.category_scores


def test_class_size_outside_comfort_inside_hard_limit_has_penalty() -> None:
    students = [_student(index, "F") for index in range(60)]
    settings = _zero_settings()
    policy = ClassSizePolicy(target_size=30, comfort_tolerance=2, hard_tolerance=5, soft_weight=100)
    classes = [
        ClassConfig("5a", "5a", 25, 35, [], [], policy),
        ClassConfig("5b", "5b", 25, 35, [], [], policy),
    ]

    score = score_solution(
        students,
        {student.internal_id: "5a" if index < 33 else "5b" for index, student in enumerate(students)},
        settings,
        classes,
    )

    assert score.hard_violations == []
    assert score.category_scores["Klassengröße Komfortbereich"] == 200


def test_class_size_soft_penalty_does_not_change_profile_minimum() -> None:
    students = [_student(index, "F") for index in range(1, 4)] + [
        _student(index, "L") for index in range(4, 7)
    ]
    settings = _zero_settings(solver_time_limit_seconds=10)
    policy = ClassSizePolicy(target_size=2, comfort_tolerance=0, hard_tolerance=2, soft_weight=999999)
    classes = [
        ClassConfig("5a", "5a", 0, 4, [], [], policy),
        ClassConfig("5b", "5b", 0, 4, [], [], policy),
        ClassConfig("5c", "5c", 0, 4, [], [], policy),
    ]

    result = solve_assignments(students, classes, settings)

    assert result.profile_min_fl_mixed_classes == 0


def test_class_size_hard_limits_apply_in_all_solver_phases() -> None:
    students = [_student(index, "F") for index in range(1, 4)] + [
        _student(index, "L") for index in range(4, 7)
    ]
    settings = _zero_settings(solver_time_limit_seconds=10)
    policy = ClassSizePolicy(target_size=3, comfort_tolerance=0, hard_tolerance=0, soft_weight=999999)
    classes = [
        ClassConfig("5a", "5a", 3, 3, [], [], policy),
        ClassConfig("5b", "5b", 3, 3, [], [], policy),
    ]

    result = solve_assignments(students, classes, settings)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    for assignments in [result.assignments] + [
        report.assignments or {}
        for report in result.profile_slack_reports
        if report.assignments
    ]:
        sizes = {
            class_id: sum(1 for assigned_class in assignments.values() if assigned_class == class_id)
            for class_id in ("5a", "5b")
        }
        assert sizes == {"5a": 3, "5b": 3}

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from klassenbildung.core.models import (
    ClassConfig,
    ManualRule,
    OptimizationSettings,
    ProfileSlackReport,
    ScoreReport,
    SolverResult,
    SolverPhaseReport,
    Student,
)
from klassenbildung.optimization.scoring import (
    build_friend_relationships,
    friend_relationship_weight,
    resolve_student_ref,
    score_solution,
    support_upper_bound,
)


@dataclass(frozen=True)
class _PhaseResult:
    status_name: str
    solver: object
    objective_value: int | None
    best_bound: int | None
    relative_gap: float | None


@dataclass(frozen=True)
class _ProfileVariantCandidate:
    variant: str
    language_mixed_limit: int
    music_mixed_limit: int
    status: str
    objective_value: int | None
    best_objective_bound: int | None
    relative_gap: float | None
    score: ScoreReport | None
    assignments: dict[str, str] | None
    solution_source: str
    optimization_attempted: bool = False
    target_test_status: str | None = None
    refinement_attempted: bool = False
    refinement_status: str | None = None
    dominance_source: str | None = None


_PROFILE_INCUMBENT_CACHE_PATH = Path("config/profile_incumbents.json")
_PROFILE_INCUMBENT_CACHE: dict[str, dict[str, dict[str, str]]] = {}
_PROFILE_INCUMBENT_CACHE_LOADED = False


def solve_assignments(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule] | None = None,
) -> SolverResult:
    manual_rules = manual_rules or []
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return _solve_greedy_fallback(students, class_configs, settings, manual_rules)

    if not students or not class_configs:
        return SolverResult("INFEASIBLE", {}, message="Keine Schüler oder Klassen vorhanden.")

    model = cp_model.CpModel()
    student_indexes = range(len(students))
    class_indexes = range(len(class_configs))
    x = {
        (i, c): model.NewBoolVar(f"x_{i}_{c}")
        for i in student_indexes
        for c in class_indexes
    }

    for i in student_indexes:
        model.Add(sum(x[(i, c)] for c in class_indexes) == 1)

    for c, config in enumerate(class_configs):
        class_size = sum(x[(i, c)] for i in student_indexes)
        model.Add(class_size >= config.size_min)
        model.Add(class_size <= config.size_max)

    for i, student in enumerate(students):
        for c, config in enumerate(class_configs):
            if not _student_allowed(student, config, settings):
                model.Add(x[(i, c)] == 0)

    _add_manual_rule_constraints(model, x, students, class_configs, manual_rules)

    phase_reports: list[SolverPhaseReport] = []
    profile_statuses: list[str] = []

    language_mixed_terms: list = []
    _add_mixed_language_terms(
        model,
        x,
        students,
        class_configs,
        1,
        0,
        language_mixed_terms,
        "profile_language_count",
    )
    profile_phase = _solve_phase(cp_model, model, language_mixed_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "1 F/L-Mischklassen minimieren",
            profile_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    language_profile_report = phase_reports[-1]
    if profile_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        return SolverResult(
            profile_phase.status_name,
            {},
            phase_reports=phase_reports,
            message="Solver hat keine gültige Sprache-Profillösung gefunden.",
        )
    profile_statuses.append(profile_phase.status_name)
    language_mixed_limit = _phase_objective_limit(profile_phase)
    if language_mixed_terms:
        model.Add(sum(language_mixed_terms) <= language_mixed_limit)

    music_mixed_terms: list = []
    _add_mixed_music_terms(
        model,
        x,
        students,
        class_configs,
        1,
        0,
        0,
        music_mixed_terms,
        "profile_music_count",
    )
    profile_phase = _solve_phase(cp_model, model, music_mixed_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "2 Musik-Mischklassen minimieren",
            profile_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    music_profile_report = phase_reports[-1]
    if profile_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        return SolverResult(
            profile_phase.status_name,
            {},
            phase_reports=phase_reports,
            message="Solver hat keine gültige Musik-Profillösung gefunden.",
        )
    profile_statuses.append(profile_phase.status_name)
    music_mixed_limit = _phase_objective_limit(profile_phase)
    if music_mixed_terms:
        model.Add(sum(music_mixed_terms) <= music_mixed_limit)

    profile_count_assignments = _extract_assignments(profile_phase.solver, x, students, class_configs)
    profile_count_score = score_solution(students, profile_count_assignments, settings, class_configs, manual_rules)
    last_assignments = profile_count_assignments
    last_score = profile_count_score
    last_phase_report = phase_reports[-1]
    failed_phase_report: SolverPhaseReport | None = None
    _add_assignment_hints(model, x, students, class_configs, profile_count_assignments)

    no_friend_terms: list = []
    _add_no_friend_terms(
        model,
        x,
        students,
        class_configs,
        1,
        no_friend_terms,
        "phase_no_friend",
        hint_assignments=last_assignments,
    )

    target_no_friend_limit = int(len(students) * 0.15)
    target_phase, target_assignments = _solve_no_friend_target_phase(
        cp_model,
        students,
        class_configs,
        settings,
        manual_rules,
        language_mixed_limit,
        music_mixed_limit,
        target_no_friend_limit,
        last_assignments,
    )
    phase_reports.append(target_phase)
    approval_phase_report = target_phase
    profile_slack_reports: list[ProfileSlackReport] = []
    profile_refinement_reports: list[ProfileSlackReport] = []
    slack_candidates: list[dict[str, object]] = []
    profile_metadata = _profile_metadata(language_profile_report, music_profile_report)
    if target_assignments:
        last_assignments = target_assignments
        last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
        last_phase_report = target_phase
        _add_assignment_hints(model, x, students, class_configs, last_assignments)
        if no_friend_terms:
            model.Add(sum(no_friend_terms) <= target_no_friend_limit)

    social_phase = _solve_phase(cp_model, model, no_friend_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "4 Bestes Ergebnis ohne Wunschfreund suchen",
            social_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    if social_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Profilminimum gefunden; Sozialphase fand keine gültige Lösung.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                None,
            ),
        )
    no_friend_limit = _phase_objective_limit(social_phase)
    if no_friend_terms:
        model.Add(sum(no_friend_terms) <= no_friend_limit)
    last_assignments = _extract_assignments(social_phase.solver, x, students, class_configs)
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    last_phase_report = phase_reports[-1]
    _add_assignment_hints(model, x, students, class_configs, last_assignments)
    strict_social_assignments = dict(last_assignments)
    strict_social_score = last_score

    if _needs_social_diagnostics(last_score, social_phase, target_no_friend_limit):
        for ladder_limit in _target_ladder(no_friend_limit, target_no_friend_limit):
            ladder_phase, ladder_assignments = _solve_no_friend_target_phase(
                cp_model,
                students,
                class_configs,
                settings,
                manual_rules,
                language_mixed_limit,
                music_mixed_limit,
                ladder_limit,
                last_assignments,
                phase_name=f"4a Zieltreppe testen: ohne Wunschfreund <= {ladder_limit}",
                time_limit_seconds=_diagnostic_time_limit(settings),
            )
            phase_reports.append(ladder_phase)
            if not ladder_assignments:
                break
            last_assignments = ladder_assignments
            last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
            last_phase_report = ladder_phase
            _add_assignment_hints(model, x, students, class_configs, last_assignments)
            if no_friend_terms:
                model.Add(sum(no_friend_terms) <= ladder_limit)
            no_friend_limit = ladder_limit
            if ladder_limit <= target_no_friend_limit:
                break

        profile_slack_reports, profile_refinement_reports, slack_candidates = _build_profile_slack_reports(
            cp_model,
            students,
            class_configs,
            settings,
            manual_rules,
            language_mixed_limit,
            music_mixed_limit,
            target_no_friend_limit,
            last_assignments,
            strict_phase=social_phase,
            strict_score=strict_social_score,
            strict_assignments=strict_social_assignments,
        )

    if _needs_social_diagnostics(last_score, social_phase, target_no_friend_limit):
        skipped_phase = _build_skipped_phase_report("5 Gegenseitige Freunde retten")
        phase_reports.append(skipped_phase)
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            skipped_phase=skipped_phase.name,
            skipped_phase_status=skipped_phase.status,
            skipped_phase_reason="social_quality_not_approved_and_gap_too_high",
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message=(
                "Strenges Profilminimum gefunden; unter strengen Profilgrenzen ist die soziale Mindestqualität "
                "nicht freigabefähig. Mit Profil-Slack wurden soziale Prüfkandidaten gesucht."
            ),
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )

    incumbent_violations = _incumbent_limit_violations(
        last_score,
        language_mixed_limit=language_mixed_limit,
        music_mixed_limit=music_mixed_limit,
        no_friend_limit=no_friend_limit,
    )
    if incumbent_violations:
        failed_phase_report = _build_skipped_phase_report("5 Gegenseitige Freunde retten")
        phase_reports.append(failed_phase_report)
        return SolverResult(
            "ERROR",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Interner Phasenfehler: letzte gültige Lösung verletzt neue Constraints: "
            + "; ".join(incumbent_violations),
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )

    mutual_terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        mutual_terms,
        label_prefix="phase_mutual",
        relationship_filter=_is_mutual_relationship,
        unit_weight=True,
        hint_assignments=last_assignments,
    )
    social_phase = _solve_phase(cp_model, model, mutual_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "5 Gegenseitige Freunde retten",
            social_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    if social_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Profilminimum gefunden; gegenseitige Freundschaftsphase fand keine gültige Lösung.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )
    mutual_limit = _phase_objective_limit(social_phase)
    if mutual_terms:
        model.Add(sum(mutual_terms) <= mutual_limit)
    last_assignments = _extract_assignments(social_phase.solver, x, students, class_configs)
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    last_phase_report = phase_reports[-1]
    _add_assignment_hints(model, x, students, class_configs, last_assignments)

    friend1_terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        friend1_terms,
        label_prefix="phase_friend1",
        relationship_filter=_has_friend1_priority,
        unit_weight=True,
        hint_assignments=last_assignments,
    )
    social_phase = _solve_phase(cp_model, model, friend1_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "6 Freund 1 retten",
            social_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    if social_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Profilminimum gefunden; Freund-1-Phase fand keine gültige Lösung.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )
    friend1_limit = _phase_objective_limit(social_phase)
    if friend1_terms:
        model.Add(sum(friend1_terms) <= friend1_limit)
    last_assignments = _extract_assignments(social_phase.solver, x, students, class_configs)
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    last_phase_report = phase_reports[-1]
    _add_assignment_hints(model, x, students, class_configs, last_assignments)

    profile_depth_terms: list = []
    _add_mixed_language_terms(
        model,
        x,
        students,
        class_configs,
        0,
        1,
        profile_depth_terms,
        "profile_language_depth",
    )
    _add_mixed_music_terms(
        model,
        x,
        students,
        class_configs,
        0,
        1,
        1,
        profile_depth_terms,
        "profile_music_depth",
    )
    profile_phase = _solve_phase(cp_model, model, profile_depth_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "7 Minderheiten in Mischklassen minimieren",
            profile_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    if profile_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Solver hat keine gültige Profil-Tiefenlösung gefunden.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )
    profile_depth_limit = _phase_objective_limit(profile_phase)
    if profile_depth_terms:
        model.Add(sum(profile_depth_terms) <= profile_depth_limit)
    last_assignments = _extract_assignments(profile_phase.solver, x, students, class_configs)
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    last_phase_report = phase_reports[-1]
    _add_assignment_hints(model, x, students, class_configs, last_assignments)

    friend2_terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        friend2_terms,
        label_prefix="phase_friend2",
        relationship_filter=_has_friend2_priority,
        unit_weight=True,
        hint_assignments=last_assignments,
    )
    social_phase = _solve_phase(cp_model, model, friend2_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "8 Freund 2 retten",
            social_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    if social_phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            phase_reports=phase_reports,
            profile_status=_combined_profile_status(profile_statuses),
            profile_baseline_report=profile_count_score,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Profilminimum gefunden; Freund-2-Phase fand keine gültige Lösung.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                social_phase,
            ),
        )
    friend2_limit = _phase_objective_limit(social_phase)
    if friend2_terms:
        model.Add(sum(friend2_terms) <= friend2_limit)
    last_assignments = _extract_assignments(social_phase.solver, x, students, class_configs)
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    last_phase_report = phase_reports[-1]
    _add_assignment_hints(model, x, students, class_configs, last_assignments)

    objective_terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        objective_terms,
        hint_assignments=last_assignments,
    )
    _add_no_friend_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_no_friend,
        objective_terms,
        hint_assignments=last_assignments,
    )
    _add_mixed_language_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_mixed_language_class,
        settings.weight_language_minority_student,
        objective_terms,
        "final_language",
    )
    _add_mixed_music_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_mixed_music_class,
        settings.weight_music_minority_student,
        settings.weight_music_focus_shortfall,
        objective_terms,
        "final_music",
    )
    _add_class_size_policy_terms(model, x, students, class_configs, objective_terms)
    _add_soft_profile_terms(
        x,
        students,
        class_configs,
        settings.enforce_music_profile,
        settings.weight_music_profile,
        lambda student: student.music_profile,
        lambda config: config.music_allowed,
        objective_terms,
    )
    _add_soft_profile_terms(
        x,
        students,
        class_configs,
        settings.enforce_language_profile,
        settings.weight_language_profile,
        lambda student: student.second_language,
        lambda config: config.languages_allowed,
        objective_terms,
    )
    _add_support_distribution_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_support_distribution,
        objective_terms,
    )
    _add_gender_balance_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_gender_balance,
        objective_terms,
    )
    _add_concentration_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: student.school,
        settings.weight_primary_school,
        objective_terms,
        "school",
        free_count=3,
    )
    _add_concentration_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: student.primary_class,
        settings.weight_primary_class,
        objective_terms,
        "primary_class",
        free_count=2,
    )
    _add_keep_existing_terms(x, students, class_configs, settings.weight_keep_existing, objective_terms)

    final_phase = _solve_phase(cp_model, model, objective_terms, settings.solver_time_limit_seconds)
    phase_reports.append(
        _build_phase_report(
            "9 Restqualität optimieren",
            final_phase,
            x,
            students,
            class_configs,
            settings,
            manual_rules,
        )
    )
    status_name = final_phase.status_name

    if status_name not in {"OPTIMAL", "FEASIBLE"}:
        failed_phase_report = phase_reports[-1]
        return SolverResult(
            "FEASIBLE",
            last_assignments,
            score_report=last_score,
            objective_value=last_score.total_score,
            best_objective_bound=None,
            relative_gap=None,
            profile_status=_combined_profile_status(profile_statuses),
            profile_objective_value=profile_count_score.mixed_language_class_count
            + profile_count_score.mixed_music_class_count,
            profile_best_objective_bound=None,
            profile_relative_gap=None,
            profile_baseline_report=profile_count_score,
            phase_reports=phase_reports,
            last_accepted_phase=last_phase_report.name,
            last_accepted_phase_status=last_phase_report.status,
            last_accepted_phase_gap=last_phase_report.relative_gap,
            failed_phase=failed_phase_report.name,
            failed_phase_status=failed_phase_report.status,
            displayed_solution_source=last_phase_report.name,
            profile_slack_reports=profile_slack_reports,
            profile_refinement_reports=profile_refinement_reports,
            slack_candidates=slack_candidates,
            message="Profil- und Sozialphasen gefunden; Restoptimierung fand im Zeitlimit keine eigene Lösung.",
            **profile_metadata,
            **_solution_metadata(
                last_phase_report,
                last_score,
                approval_phase_report,
                target_no_friend_limit,
                final_phase,
            ),
        )

    assignments = _extract_assignments(final_phase.solver, x, students, class_configs)
    score = score_solution(students, assignments, settings, class_configs, manual_rules)
    return SolverResult(
        status_name,
        assignments,
        score_report=score,
        objective_value=final_phase.objective_value,
        best_objective_bound=final_phase.best_bound,
        relative_gap=final_phase.relative_gap,
        profile_status=_combined_profile_status(profile_statuses),
        profile_objective_value=profile_count_score.mixed_language_class_count
        + profile_count_score.mixed_music_class_count,
        profile_best_objective_bound=None,
        profile_relative_gap=None,
        profile_baseline_report=profile_count_score,
        phase_reports=phase_reports,
        last_accepted_phase=phase_reports[-1].name,
        last_accepted_phase_status=phase_reports[-1].status,
        last_accepted_phase_gap=phase_reports[-1].relative_gap,
        displayed_solution_source=phase_reports[-1].name,
        profile_slack_reports=profile_slack_reports,
        profile_refinement_reports=profile_refinement_reports,
        slack_candidates=slack_candidates,
        **profile_metadata,
        **_solution_metadata(
            phase_reports[-1],
            score,
            approval_phase_report,
            target_no_friend_limit,
            final_phase,
        ),
    )


def _solve_phase(cp_model, model, objective_terms: list, time_limit_seconds: int) -> _PhaseResult:
    model.Minimize(sum(objective_terms) if objective_terms else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_name = _status_name(cp_model, status)
    objective_value = int(solver.ObjectiveValue()) if status_name in {"OPTIMAL", "FEASIBLE"} else None
    best_bound = int(solver.BestObjectiveBound()) if status_name in {"OPTIMAL", "FEASIBLE"} else None
    relative_gap = (
        abs(objective_value - best_bound) / max(abs(objective_value), 1)
        if objective_value is not None and best_bound is not None
        else None
    )
    return _PhaseResult(status_name, solver, objective_value, best_bound, relative_gap)


def _phase_objective_limit(phase: _PhaseResult) -> int:
    if phase.status_name not in {"OPTIMAL", "FEASIBLE"} or phase.objective_value is None:
        raise ValueError("Nur akzeptierte Phasen mit gefundener Lösung können fixiert werden.")
    return phase.objective_value


def _solve_no_friend_target_phase(
    cp_model,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
    language_mixed_limit: int,
    music_mixed_limit: int,
    target_no_friend_limit: int,
    hint_assignments: dict[str, str],
    *,
    phase_name: str | None = None,
    time_limit_seconds: int | None = None,
) -> tuple[SolverPhaseReport, dict[str, str] | None]:
    target_model = cp_model.CpModel()
    x = {
        (i, c): target_model.NewBoolVar(f"target_x_{i}_{c}")
        for i in range(len(students))
        for c in range(len(class_configs))
    }

    for i in range(len(students)):
        target_model.Add(sum(x[(i, c)] for c in range(len(class_configs))) == 1)

    for c, config in enumerate(class_configs):
        class_size = sum(x[(i, c)] for i in range(len(students)))
        target_model.Add(class_size >= config.size_min)
        target_model.Add(class_size <= config.size_max)

    for i, student in enumerate(students):
        for c, config in enumerate(class_configs):
            if not _student_allowed(student, config, settings):
                target_model.Add(x[(i, c)] == 0)

    _add_manual_rule_constraints(target_model, x, students, class_configs, manual_rules)

    language_terms: list = []
    _add_mixed_language_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        0,
        language_terms,
        "target_language",
    )
    if language_terms:
        target_model.Add(sum(language_terms) <= language_mixed_limit)

    music_terms: list = []
    _add_mixed_music_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        0,
        0,
        music_terms,
        "target_music",
    )
    if music_terms:
        target_model.Add(sum(music_terms) <= music_mixed_limit)

    no_friend_terms: list = []
    _add_no_friend_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        no_friend_terms,
        "target_no_friend",
        hint_assignments=hint_assignments,
    )
    if no_friend_terms:
        target_model.Add(sum(no_friend_terms) <= target_no_friend_limit)

    _add_assignment_hints(target_model, x, students, class_configs, hint_assignments, clear_existing=False)
    phase = _solve_phase(cp_model, target_model, [], time_limit_seconds or settings.solver_time_limit_seconds)
    phase_name = phase_name or f"3 Freigabegrenze testen: ohne Wunschfreund <= {target_no_friend_limit}"
    report = _build_phase_report(
        phase_name,
        phase,
        x,
        students,
        class_configs,
        settings,
        manual_rules,
    )
    if phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        return report, None
    return report, _extract_assignments(phase.solver, x, students, class_configs)


def _solve_no_friend_min_phase(
    cp_model,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
    language_mixed_limit: int,
    music_mixed_limit: int,
    hint_assignments: dict[str, str],
    *,
    phase_name: str,
    time_limit_seconds: int,
) -> tuple[SolverPhaseReport, _PhaseResult, dict[str, str] | None]:
    target_model = cp_model.CpModel()
    x = {
        (i, c): target_model.NewBoolVar(f"slack_x_{i}_{c}")
        for i in range(len(students))
        for c in range(len(class_configs))
    }

    for i in range(len(students)):
        target_model.Add(sum(x[(i, c)] for c in range(len(class_configs))) == 1)

    for c, config in enumerate(class_configs):
        class_size = sum(x[(i, c)] for i in range(len(students)))
        target_model.Add(class_size >= config.size_min)
        target_model.Add(class_size <= config.size_max)

    for i, student in enumerate(students):
        for c, config in enumerate(class_configs):
            if not _student_allowed(student, config, settings):
                target_model.Add(x[(i, c)] == 0)

    _add_manual_rule_constraints(target_model, x, students, class_configs, manual_rules)

    language_terms: list = []
    _add_mixed_language_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        0,
        language_terms,
        "slack_language",
    )
    if language_terms:
        target_model.Add(sum(language_terms) <= language_mixed_limit)

    music_terms: list = []
    _add_mixed_music_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        0,
        0,
        music_terms,
        "slack_music",
    )
    if music_terms:
        target_model.Add(sum(music_terms) <= music_mixed_limit)

    no_friend_terms: list = []
    _add_no_friend_terms(
        target_model,
        x,
        students,
        class_configs,
        1,
        no_friend_terms,
        "slack_no_friend",
        hint_assignments=hint_assignments,
    )

    _add_assignment_hints(target_model, x, students, class_configs, hint_assignments, clear_existing=False)
    phase = _solve_phase(cp_model, target_model, no_friend_terms, time_limit_seconds)
    report = _build_phase_report(phase_name, phase, x, students, class_configs, settings, manual_rules)
    if phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        return report, phase, None
    return report, phase, _extract_assignments(phase.solver, x, students, class_configs)


def _build_profile_slack_reports(
    cp_model,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
    language_mixed_limit: int,
    music_mixed_limit: int,
    approval_limit: int,
    hint_assignments: dict[str, str],
    *,
    strict_phase: _PhaseResult,
    strict_score,
    strict_assignments: dict[str, str],
) -> tuple[list[ProfileSlackReport], list[ProfileSlackReport], list[dict[str, object]]]:
    candidates: list[_ProfileVariantCandidate] = [
        _profile_candidate_from_score(
            "A streng",
            language_mixed_limit,
            music_mixed_limit,
            strict_phase.status_name,
            strict_phase.objective_value,
            strict_phase.best_bound,
            strict_phase.relative_gap,
            strict_score,
            strict_assignments,
            solution_source="strict_profile",
        )
    ]
    candidate_by_variant = {candidates[0].variant: candidates[0]}
    cache_key = _profile_incumbent_cache_key(students, class_configs, manual_rules)
    refinement_reports: list[ProfileSlackReport] = []
    variants = [
        ("B Musik +1", language_mixed_limit, music_mixed_limit + 1),
        ("C Musik +2", language_mixed_limit, music_mixed_limit + 2),
        ("D F/L +1", language_mixed_limit + 1, music_mixed_limit),
        ("E beide +1", language_mixed_limit + 1, music_mixed_limit + 1),
        ("F mehr Profil-Slack", language_mixed_limit + 1, music_mixed_limit + 2),
    ]
    max_classes = len(class_configs)
    for variant, language_limit, music_limit in variants:
        language_limit = min(language_limit, max_classes)
        music_limit = min(music_limit, max_classes)
        cached = _cached_profile_candidate(
            cache_key,
            variant,
            language_limit,
            music_limit,
            students,
            class_configs,
            settings,
            manual_rules,
        )
        if cached:
            candidates.append(cached)
        carried = _best_dominating_candidate(candidates, language_limit, music_limit)
        phase_hint = carried.assignments if carried and carried.assignments else hint_assignments
        report, phase, assignments = _solve_no_friend_min_phase(
            cp_model,
            students,
            class_configs,
            settings,
            manual_rules,
            language_limit,
            music_limit,
            phase_hint,
            phase_name=f"Profil-Slack {variant}",
            time_limit_seconds=_diagnostic_time_limit(settings),
        )
        score = score_solution(students, assignments, settings, class_configs, manual_rules) if assignments else None
        raw_candidate = _profile_candidate_from_score(
            variant,
            language_limit,
            music_limit,
            phase.status_name,
            phase.objective_value,
            phase.best_bound,
            phase.relative_gap,
            score,
            assignments,
            solution_source="slack_search",
        )
        best_candidate = _best_display_candidate(
            variant,
            language_limit,
            music_limit,
            raw_candidate,
            carried,
            optimization_attempted=True,
        )
        candidates.append(best_candidate)
        candidate_by_variant[variant] = best_candidate

    target_variants = _target_test_variants(candidate_by_variant, approval_limit)
    for variant in target_variants:
        candidate = candidate_by_variant[variant]
        if not candidate.assignments:
            continue
        target_phase, target_assignments = _solve_no_friend_target_phase(
            cp_model,
            students,
            class_configs,
            settings,
            manual_rules,
            candidate.language_mixed_limit,
            candidate.music_mixed_limit,
            approval_limit,
            candidate.assignments,
            phase_name=f"{variant} Zieltest <= {approval_limit}",
            time_limit_seconds=_diagnostic_time_limit(settings),
        )
        target_score = (
            score_solution(students, target_assignments, settings, class_configs, manual_rules)
            if target_assignments
            else None
        )
        target_candidate = _profile_candidate_from_score(
            variant,
            candidate.language_mixed_limit,
            candidate.music_mixed_limit,
            target_phase.status,
            target_phase.objective_value,
            target_phase.best_objective_bound,
            target_phase.relative_gap,
            target_score,
            target_assignments,
            solution_source="target_test",
            optimization_attempted=False,
            target_test_status=target_phase.status,
        )
        refinement_reports.append(
            _profile_slack_report_from_candidate(
                replace(target_candidate, variant=f"{variant} Zieltest <= {approval_limit}"),
                approval_limit,
                strict_language_limit=language_mixed_limit,
                strict_music_limit=music_mixed_limit,
            )
        )
        if _is_candidate_better(target_candidate, candidate):
            candidate_by_variant[variant] = target_candidate
            candidates.append(target_candidate)
        else:
            candidate_by_variant[variant] = replace(
                candidate,
                target_test_status=target_phase.status,
            )

    candidate_by_variant = _apply_dominance_to_candidates(candidate_by_variant)
    candidates = list(candidate_by_variant.values())

    for variant in _refinement_variants(candidate_by_variant, approval_limit):
        candidate = candidate_by_variant[variant]
        if not candidate.score or not candidate.assignments:
            continue
        refined_candidate = _solve_refined_profile_variant(
                cp_model,
                students,
                class_configs,
                settings,
                manual_rules,
                candidate.language_mixed_limit,
                candidate.music_mixed_limit,
                candidate.score.isolated_friend_request_count,
                candidate.assignments,
                variant=variant,
                approval_limit=approval_limit,
                strict_language_limit=language_mixed_limit,
                strict_music_limit=music_mixed_limit,
            )
        if not refined_candidate:
            continue
        refinement_reports.append(
            _profile_slack_report_from_candidate(
                replace(refined_candidate, variant=f"{variant} Vertiefung"),
                approval_limit,
                strict_language_limit=language_mixed_limit,
                strict_music_limit=music_mixed_limit,
                recommendation_role=(
                    _recommendation_role_for_candidate(refined_candidate, candidate_by_variant, approval_limit)
                    or variant
                )
                + " - Vertiefung",
            )
        )
        if _is_candidate_better(refined_candidate, candidate_by_variant[variant]):
            candidate_by_variant[variant] = refined_candidate
        else:
            candidate_by_variant[variant] = replace(
                candidate_by_variant[variant],
                refinement_attempted=True,
                refinement_status=refined_candidate.refinement_status,
            )

    candidate_by_variant = _apply_dominance_to_candidates(candidate_by_variant)
    reports = [
        _profile_slack_report_from_candidate(
            candidate_by_variant[variant],
            approval_limit,
            strict_language_limit=language_mixed_limit,
            strict_music_limit=music_mixed_limit,
            recommendation_role=_recommendation_role_for_candidate(
                candidate_by_variant[variant],
                candidate_by_variant,
                approval_limit,
            ),
        )
        for variant in ["A streng", "B Musik +1", "C Musik +2", "D F/L +1", "E beide +1", "F mehr Profil-Slack"]
        if variant in candidate_by_variant
    ]
    _save_profile_incumbents(cache_key, candidate_by_variant, students, class_configs, settings, manual_rules)
    return reports, refinement_reports, _slack_candidates_payload(reports, approval_limit, len(students))


def _profile_candidate_from_score(
    variant: str,
    language_limit: int,
    music_limit: int,
    status: str,
    objective_value: int | None,
    best_bound: int | None,
    relative_gap: float | None,
    score,
    assignments: dict[str, str] | None,
    *,
    solution_source: str,
    optimization_attempted: bool = False,
    target_test_status: str | None = None,
    refinement_attempted: bool = False,
    refinement_status: str | None = None,
    dominance_source: str | None = None,
) -> _ProfileVariantCandidate:
    return _ProfileVariantCandidate(
        variant=variant,
        language_mixed_limit=language_limit,
        music_mixed_limit=music_limit,
        status=status,
        objective_value=objective_value,
        best_objective_bound=best_bound,
        relative_gap=relative_gap,
        score=score,
        assignments=assignments,
        solution_source=solution_source,
        optimization_attempted=optimization_attempted,
        target_test_status=target_test_status,
        refinement_attempted=refinement_attempted,
        refinement_status=refinement_status,
        dominance_source=dominance_source,
    )


def _best_display_candidate(
    variant: str,
    language_limit: int,
    music_limit: int,
    raw_candidate: _ProfileVariantCandidate,
    carried: _ProfileVariantCandidate | None,
    *,
    optimization_attempted: bool,
) -> _ProfileVariantCandidate:
    if carried and _is_candidate_better(carried, raw_candidate):
        if carried.variant == variant:
            return replace(
                carried,
                variant=variant,
                language_mixed_limit=language_limit,
                music_mixed_limit=music_limit,
                optimization_attempted=optimization_attempted,
                dominance_source=None,
            )
        return replace(
            carried,
            variant=variant,
            language_mixed_limit=language_limit,
            music_mixed_limit=music_limit,
            solution_source=f"carried_from:{carried.variant}",
            optimization_attempted=optimization_attempted,
            dominance_source=carried.variant,
        )
    return replace(raw_candidate, optimization_attempted=optimization_attempted, solution_source="slack_search")


def _best_dominating_candidate(
    candidates: list[_ProfileVariantCandidate],
    language_limit: int,
    music_limit: int,
) -> _ProfileVariantCandidate | None:
    valid = [
        candidate
        for candidate in candidates
        if _candidate_fits_limits(candidate, language_limit, music_limit)
    ]
    return min(valid, key=_candidate_rank_key, default=None)


def _apply_dominance_to_candidates(
    candidate_by_variant: dict[str, _ProfileVariantCandidate],
) -> dict[str, _ProfileVariantCandidate]:
    ordered = ["A streng", "B Musik +1", "C Musik +2", "D F/L +1", "E beide +1", "F mehr Profil-Slack"]
    updated = dict(candidate_by_variant)
    for variant in ordered:
        candidate = updated.get(variant)
        if not candidate:
            continue
        if candidate.dominance_source == variant or candidate.solution_source == f"carried_from:{variant}":
            candidate = replace(
                candidate,
                solution_source="slack_search" if candidate.solution_source == f"carried_from:{variant}" else candidate.solution_source,
                dominance_source=None,
            )
            updated[variant] = candidate
        carried = _best_dominating_candidate(
            [other for key, other in updated.items() if key != variant and other.variant != variant],
            candidate.language_mixed_limit,
            candidate.music_mixed_limit,
        )
        if carried and _is_candidate_better(carried, candidate):
            updated[variant] = replace(
                carried,
                variant=variant,
                language_mixed_limit=candidate.language_mixed_limit,
                music_mixed_limit=candidate.music_mixed_limit,
                solution_source=f"carried_from:{carried.variant}",
                optimization_attempted=candidate.optimization_attempted,
                target_test_status=candidate.target_test_status,
                refinement_attempted=candidate.refinement_attempted,
                refinement_status=candidate.refinement_status,
                dominance_source=carried.variant,
            )
    return updated


def _profile_incumbent_cache_key(
    students: list[Student],
    class_configs: list[ClassConfig],
    manual_rules: list[ManualRule],
) -> str:
    payload = {
        "students": [
            {
                "id": student.internal_id,
                "school": student.school,
                "primary_class": student.primary_class,
                "gender": student.gender,
                "language": student.second_language,
                "music": student.music_profile,
                "friend1": student.friend1,
                "friend2": student.friend2,
                "support": student.is_support,
            }
            for student in students
        ],
        "classes": [
            {
                "id": config.class_id,
                "min": config.size_min,
                "max": config.size_max,
                "music": sorted(config.music_allowed),
                "language": sorted(config.languages_allowed),
            }
            for config in class_configs
        ],
        "rules": [
            {
                "type": rule.type,
                "a": rule.student_a,
                "b": rule.student_b,
                "class": rule.class_id,
            }
            for rule in manual_rules
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cached_profile_candidate(
    cache_key: str,
    variant: str,
    language_limit: int,
    music_limit: int,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
) -> _ProfileVariantCandidate | None:
    _ensure_profile_incumbent_cache_loaded()
    assignments = _PROFILE_INCUMBENT_CACHE.get(cache_key, {}).get(_limit_cache_key(language_limit, music_limit))
    if not assignments:
        return None
    score = score_solution(students, assignments, settings, class_configs, manual_rules)
    candidate = _profile_candidate_from_score(
        variant,
        language_limit,
        music_limit,
        "FEASIBLE",
        None,
        None,
        None,
        score,
        assignments,
        solution_source="cached_incumbent",
    )
    if not _candidate_fits_limits(candidate, language_limit, music_limit):
        return None
    return candidate


def _save_profile_incumbents(
    cache_key: str,
    candidate_by_variant: dict[str, _ProfileVariantCandidate],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
) -> None:
    _ensure_profile_incumbent_cache_loaded()
    cache = _PROFILE_INCUMBENT_CACHE.setdefault(cache_key, {})
    for candidate in candidate_by_variant.values():
        if not candidate.assignments or not candidate.score:
            continue
        key = _limit_cache_key(candidate.language_mixed_limit, candidate.music_mixed_limit)
        existing_assignments = cache.get(key)
        if existing_assignments:
            existing_score = score_solution(students, existing_assignments, settings, class_configs, manual_rules)
            existing_candidate = replace(
                candidate,
                score=existing_score,
                assignments=existing_assignments,
                solution_source="cached_incumbent",
            )
            if not _candidate_fits_limits(existing_candidate, candidate.language_mixed_limit, candidate.music_mixed_limit):
                cache[key] = dict(candidate.assignments)
                continue
            if not _is_candidate_better(candidate, existing_candidate):
                continue
        cache[key] = dict(candidate.assignments)
    _write_profile_incumbent_cache()


def _limit_cache_key(language_limit: int, music_limit: int) -> str:
    return f"{language_limit}:{music_limit}"


def _ensure_profile_incumbent_cache_loaded() -> None:
    global _PROFILE_INCUMBENT_CACHE_LOADED
    if _PROFILE_INCUMBENT_CACHE_LOADED:
        return
    _PROFILE_INCUMBENT_CACHE_LOADED = True
    if not _PROFILE_INCUMBENT_CACHE_PATH.exists():
        return
    try:
        loaded = json.loads(_PROFILE_INCUMBENT_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(loaded, dict):
        _PROFILE_INCUMBENT_CACHE.clear()
        for dataset_key, by_limit in loaded.items():
            if not isinstance(dataset_key, str) or not isinstance(by_limit, dict):
                continue
            assignments_by_limit = {
                str(limit_key): assignments
                for limit_key, assignments in by_limit.items()
                if isinstance(assignments, dict)
            }
            _PROFILE_INCUMBENT_CACHE[dataset_key] = assignments_by_limit


def _write_profile_incumbent_cache() -> None:
    try:
        _PROFILE_INCUMBENT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_INCUMBENT_CACHE_PATH.write_text(
            json.dumps(_PROFILE_INCUMBENT_CACHE, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(_PROFILE_INCUMBENT_CACHE_PATH, 0o600)
    except Exception:
        return


def clear_profile_incumbent_cache() -> None:
    _PROFILE_INCUMBENT_CACHE.clear()
    global _PROFILE_INCUMBENT_CACHE_LOADED
    _PROFILE_INCUMBENT_CACHE_LOADED = True
    try:
        _PROFILE_INCUMBENT_CACHE_PATH.unlink(missing_ok=True)
    except Exception:
        return


def _profile_slack_report_from_candidate(
    candidate: _ProfileVariantCandidate,
    approval_limit: int,
    *,
    strict_language_limit: int,
    strict_music_limit: int,
    recommendation_role: str | None = None,
) -> ProfileSlackReport:
    score = candidate.score
    social_limit_met = score.isolated_friend_request_count <= approval_limit if score else None
    gap_reliable = _is_gap_reliable(candidate.status, candidate.relative_gap) if score else None
    profile_slack_needed = (
        candidate.language_mixed_limit > strict_language_limit
        or candidate.music_mixed_limit > strict_music_limit
    )
    review_candidate = bool(score and candidate.status in {"OPTIMAL", "FEASIBLE"} and social_limit_met)
    return ProfileSlackReport(
        variant=candidate.variant,
        language_mixed_limit=candidate.language_mixed_limit,
        music_mixed_limit=candidate.music_mixed_limit,
        status=candidate.status,
        objective_value=candidate.objective_value,
        best_objective_bound=candidate.best_objective_bound,
        relative_gap=candidate.relative_gap,
        mixed_language_class_count=score.mixed_language_class_count if score else None,
        mixed_music_class_count=score.mixed_music_class_count if score else None,
        language_minority_student_count=score.language_minority_student_count if score else None,
        music_minority_student_count=score.music_minority_student_count if score else None,
        isolated_friend_request_count=score.isolated_friend_request_count if score else None,
        friend1_fulfilled=score.friend1_fulfilled if score else None,
        friend1_total=score.friend1_total if score else None,
        friend2_fulfilled=score.friend2_fulfilled if score else None,
        friend2_total=score.friend2_total if score else None,
        mutual_friend_fulfilled=score.mutual_friend_fulfilled if score else None,
        mutual_friend_total=score.mutual_friend_total if score else None,
        approvable=bool(score and social_limit_met and gap_reliable),
        social_limit_met=social_limit_met,
        gap_reliable=gap_reliable,
        profile_slack_needed=profile_slack_needed,
        review_candidate=review_candidate,
        recommendation_role=recommendation_role,
        near_miss=_is_near_miss(score, approval_limit),
        candidate_for_target_test=bool(candidate.target_test_status or _is_near_miss(score, approval_limit)),
        optimization_attempted=candidate.optimization_attempted,
        solution_source=candidate.solution_source,
        displayed_source=candidate.solution_source,
        displayed_gap=candidate.relative_gap,
        target_test_status=candidate.target_test_status,
        refinement_attempted=candidate.refinement_attempted,
        refinement_status=candidate.refinement_status,
        dominance_source=candidate.dominance_source,
        assignments=candidate.assignments,
    )


def _candidate_fits_limits(
    candidate: _ProfileVariantCandidate,
    language_limit: int,
    music_limit: int,
) -> bool:
    score = candidate.score
    return bool(
        score
        and candidate.assignments
        and not score.hard_violations
        and score.mixed_language_class_count <= language_limit
        and score.mixed_music_class_count <= music_limit
    )


def _candidate_rank_key(candidate: _ProfileVariantCandidate) -> tuple:
    score = candidate.score
    if not score:
        return (1, float("inf"), float("inf"), float("inf"), float("inf"), float("inf"), float("inf"))
    return (
        0,
        score.isolated_friend_request_count,
        -score.mutual_friend_fulfilled,
        -score.friend1_fulfilled,
        -score.friend2_fulfilled,
        score.language_minority_student_count + score.music_minority_student_count,
        score.total_score,
    )


def _is_candidate_better(
    candidate: _ProfileVariantCandidate,
    incumbent: _ProfileVariantCandidate | None,
) -> bool:
    if incumbent is None:
        return candidate.score is not None
    return _candidate_rank_key(candidate) < _candidate_rank_key(incumbent)


def _is_near_miss(score, approval_limit: int, *, margin: int = 3) -> bool:
    if not score:
        return False
    distance = score.isolated_friend_request_count - approval_limit
    return 0 < distance <= margin


def _target_test_variants(
    candidate_by_variant: dict[str, _ProfileVariantCandidate],
    approval_limit: int,
) -> list[str]:
    variants = [candidate for name, candidate in candidate_by_variant.items() if name != "A streng" and candidate.score]
    targets = {candidate.variant for candidate in variants if _is_near_miss(candidate.score, approval_limit)}
    social_limit_found = any(
        candidate.score and candidate.score.isolated_friend_request_count <= approval_limit
        for candidate in variants
    )
    over_limit = [
        candidate
        for candidate in variants
        if candidate.score and candidate.score.isolated_friend_request_count > approval_limit
    ]
    if not social_limit_found and over_limit:
        best_over_limit = min(over_limit, key=_candidate_rank_key)
        targets.add(best_over_limit.variant)
        for candidate in variants:
            if (
                candidate.variant != best_over_limit.variant
                and candidate.language_mixed_limit >= best_over_limit.language_mixed_limit
                and candidate.music_mixed_limit >= best_over_limit.music_mixed_limit
            ):
                targets.add(candidate.variant)
    order = ["B Musik +1", "C Musik +2", "D F/L +1", "E beide +1", "F mehr Profil-Slack"]
    return [variant for variant in order if variant in targets]


def _refinement_variants(
    candidate_by_variant: dict[str, _ProfileVariantCandidate],
    approval_limit: int,
) -> list[str]:
    selected: set[str] = set()
    for variant in ("E beide +1", "F mehr Profil-Slack"):
        if variant in candidate_by_variant:
            selected.add(variant)
    for variant in ("C Musik +2", "E beide +1", "F mehr Profil-Slack"):
        candidate = candidate_by_variant.get(variant)
        if not candidate or not candidate.score:
            continue
        if (
            candidate.score.isolated_friend_request_count <= approval_limit
            or _is_near_miss(candidate.score, approval_limit)
        ):
            selected.add(variant)
    order = ["C Musik +2", "E beide +1", "F mehr Profil-Slack"]
    return [variant for variant in order if variant in selected]


def _recommendation_role_for_candidate(
    candidate: _ProfileVariantCandidate,
    candidate_by_variant: dict[str, _ProfileVariantCandidate],
    approval_limit: int,
) -> str | None:
    score = candidate.score
    if candidate.variant == "A streng":
        return "Strenges Profilminimum"
    if not score:
        return None
    social_limit_met = score.isolated_friend_request_count <= approval_limit
    slack_candidates = [
        other
        for name, other in candidate_by_variant.items()
        if name != "A streng" and other.score
    ]
    min_isolated = min(
        (other.score.isolated_friend_request_count for other in slack_candidates if other.score),
        default=None,
    )
    social_limit_found = any(
        other.score and other.score.isolated_friend_request_count <= approval_limit
        for other in slack_candidates
    )
    best_over_limit = (
        min(
            [
                other
                for other in slack_candidates
                if other.score and other.score.isolated_friend_request_count > approval_limit
            ],
            key=_candidate_rank_key,
            default=None,
        )
        if not social_limit_found
        else None
    )
    if candidate.variant == "C Musik +2":
        if social_limit_met:
            return "F/L-schonender Prüfkandidat"
        if _is_near_miss(score, approval_limit):
            return "F/L-schonender Near-Miss"
        return "F/L streng, Musik gelockert"
    if candidate.variant == "E beide +1":
        if social_limit_met:
            return "Balancierter Prüfkandidat"
        if best_over_limit and best_over_limit.variant == candidate.variant:
            return "Bester aktueller Suchkandidat"
        return None
    if candidate.variant == "F mehr Profil-Slack":
        if candidate.dominance_source:
            return "Mehr Profil-Slack, übernimmt besseren Incumbent"
        if min_isolated is not None and score.isolated_friend_request_count == min_isolated:
            return "Sozial stärkste Alternative"
        return "Mehr Profil-Slack, hohe Freundschaftsquote"
    return None


def _slack_candidates_payload(
    reports: list[ProfileSlackReport],
    approval_limit: int,
    student_count: int,
) -> list[dict[str, object]]:
    social_strongest = _social_strongest_recommendation(reports)
    default_review = _default_review_recommendation(reports)
    fl_preserving = next((report.variant for report in reports if report.variant == "C Musik +2" and report.review_candidate), None)
    payload = [
        {
            "name": report.variant,
            "fl_mixed_actual": report.mixed_language_class_count,
            "fl_mixed_allowed": report.language_mixed_limit,
            "music_mixed_actual": report.mixed_music_class_count,
            "music_mixed_allowed": report.music_mixed_limit,
            "without_wishfriend": report.isolated_friend_request_count,
            "without_wishfriend_rate": (
                report.isolated_friend_request_count / max(student_count, 1)
                if report.isolated_friend_request_count is not None
                else None
            ),
            "approval_threshold_without_wishfriend": approval_limit,
            "social_threshold_met": report.social_limit_met,
            "gap": report.relative_gap,
            "gap_reliable": report.gap_reliable,
            "near_miss": report.near_miss,
            "candidate_for_target_test": report.candidate_for_target_test,
            "candidate_for_review": report.review_candidate,
            "recommendation_role": report.recommendation_role,
            "displayed_source": report.displayed_source or report.solution_source,
            "dominance_source": report.dominance_source,
            "profile_cost_summary": {
                "fl_mixed_actual": report.mixed_language_class_count,
                "fl_mixed_allowed": report.language_mixed_limit,
                "music_mixed_actual": report.mixed_music_class_count,
                "music_mixed_allowed": report.music_mixed_limit,
                "fl_minority": report.language_minority_student_count,
                "music_minority": report.music_minority_student_count,
                "display": {
                    "fl_mixed": f"{report.mixed_language_class_count}/{report.language_mixed_limit}",
                    "music_mixed": f"{report.mixed_music_class_count}/{report.music_mixed_limit}",
                },
            },
            "variant_role": _variant_role(report),
            "default_review_candidate": report.variant == default_review,
            "social_strongest_candidate": report.variant == social_strongest,
            "fl_preserving_candidate": report.variant == fl_preserving,
        }
        for report in reports
    ]
    return payload


def _variant_role(report: ProfileSlackReport) -> str:
    if report.variant == "A streng":
        return "strict_diagnostic"
    if report.review_candidate:
        return "review_candidate"
    if report.social_limit_met:
        return "social_candidate"
    return "discarded_candidate"


def _social_strongest_recommendation(reports: list[ProfileSlackReport]) -> str | None:
    candidates = [report for report in reports if report.review_candidate and report.isolated_friend_request_count is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda report: (
            report.isolated_friend_request_count,
            -(report.mutual_friend_fulfilled or 0),
            -(report.friend1_fulfilled or 0),
        ),
    ).variant


def _default_review_recommendation(reports: list[ProfileSlackReport]) -> str | None:
    candidates = [report for report in reports if report.review_candidate and report.isolated_friend_request_count is not None]
    if not candidates:
        return None
    e_report = next((report for report in candidates if report.variant == "E beide +1"), None)
    if e_report:
        return e_report.variant
    return min(
        candidates,
        key=lambda report: (
            report.language_mixed_limit + report.music_mixed_limit,
            report.isolated_friend_request_count,
        ),
    ).variant


def _is_gap_reliable(status: str, relative_gap: float | None) -> bool:
    if status == "OPTIMAL":
        return True
    return status == "FEASIBLE" and relative_gap is not None and relative_gap <= 0.20


def _solve_refined_profile_variant(
    cp_model,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
    language_mixed_limit: int,
    music_mixed_limit: int,
    no_friend_limit: int,
    hint_assignments: dict[str, str],
    *,
    variant: str,
    approval_limit: int,
    strict_language_limit: int,
    strict_music_limit: int,
) -> _ProfileVariantCandidate | None:
    model = cp_model.CpModel()
    x = {
        (i, c): model.NewBoolVar(f"refine_x_{i}_{c}")
        for i in range(len(students))
        for c in range(len(class_configs))
    }

    for i in range(len(students)):
        model.Add(sum(x[(i, c)] for c in range(len(class_configs))) == 1)

    for c, config in enumerate(class_configs):
        class_size = sum(x[(i, c)] for i in range(len(students)))
        model.Add(class_size >= config.size_min)
        model.Add(class_size <= config.size_max)

    for i, student in enumerate(students):
        for c, config in enumerate(class_configs):
            if not _student_allowed(student, config, settings):
                model.Add(x[(i, c)] == 0)

    _add_manual_rule_constraints(model, x, students, class_configs, manual_rules)

    language_terms: list = []
    _add_mixed_language_terms(model, x, students, class_configs, 1, 0, language_terms, "refine_language_count")
    if language_terms:
        model.Add(sum(language_terms) <= language_mixed_limit)

    music_terms: list = []
    _add_mixed_music_terms(model, x, students, class_configs, 1, 0, 0, music_terms, "refine_music_count")
    if music_terms:
        model.Add(sum(music_terms) <= music_mixed_limit)

    no_friend_terms: list = []
    _add_no_friend_terms(
        model,
        x,
        students,
        class_configs,
        1,
        no_friend_terms,
        "refine_no_friend",
        hint_assignments=hint_assignments,
    )
    if no_friend_terms:
        model.Add(sum(no_friend_terms) <= no_friend_limit)

    last_assignments = hint_assignments
    last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
    baseline_candidate = _profile_candidate_from_score(
        variant,
        language_mixed_limit,
        music_mixed_limit,
        "FEASIBLE",
        None,
        None,
        None,
        last_score,
        last_assignments,
        solution_source="carried_candidate",
        optimization_attempted=True,
        refinement_attempted=True,
    )
    last_phase: _PhaseResult | None = None
    failed_status: str | None = None
    time_limit = _refinement_time_limit(settings)

    phase_builders = [
        lambda prefix, assignments: _refinement_mutual_terms(model, x, students, class_configs, settings, prefix, assignments),
        lambda prefix, assignments: _refinement_friend1_terms(model, x, students, class_configs, settings, prefix, assignments),
        lambda prefix, assignments: _refinement_profile_depth_terms(
            model,
            x,
            students,
            class_configs,
            language_mixed_limit,
            strict_language_limit,
            prefix,
        ),
        lambda prefix, assignments: _refinement_friend2_terms(model, x, students, class_configs, settings, prefix, assignments),
        lambda prefix, assignments: _refinement_final_terms(model, x, students, class_configs, settings, prefix, assignments),
    ]

    for index, build_terms in enumerate(phase_builders, start=1):
        terms = build_terms(f"refine_{variant.replace(' ', '_')}_{index}", last_assignments)
        phase = _solve_phase(cp_model, model, terms, time_limit)
        if phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
            failed_status = phase.status_name
            break
        if terms:
            model.Add(sum(terms) <= _phase_objective_limit(phase))
        last_assignments = _extract_assignments(phase.solver, x, students, class_configs)
        last_score = score_solution(students, last_assignments, settings, class_configs, manual_rules)
        last_phase = phase
        _add_assignment_hints(model, x, students, class_configs, last_assignments)

    status = last_phase.status_name if last_phase else "FEASIBLE"
    objective_value = last_phase.objective_value if last_phase else None
    best_bound = last_phase.best_bound if last_phase else None
    relative_gap = last_phase.relative_gap if last_phase else None
    refined_candidate = _profile_candidate_from_score(
        variant,
        language_mixed_limit,
        music_mixed_limit,
        status,
        objective_value,
        best_bound,
        relative_gap,
        last_score,
        last_assignments,
        solution_source="refinement",
        optimization_attempted=True,
        refinement_attempted=True,
        refinement_status=status if last_phase else failed_status,
    )
    if _is_candidate_better(refined_candidate, baseline_candidate):
        return refined_candidate
    return replace(
        baseline_candidate,
        refinement_status=status if last_phase else failed_status,
    )


def _refinement_time_limit(settings: OptimizationSettings) -> int:
    return max(1, min(settings.solver_time_limit_seconds, 3))


def _refinement_mutual_terms(model, x, students, class_configs, settings, prefix: str, assignments: dict[str, str]) -> list:
    terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        terms,
        label_prefix=f"{prefix}_mutual",
        relationship_filter=_is_mutual_relationship,
        unit_weight=True,
        hint_assignments=assignments,
    )
    return terms


def _refinement_friend1_terms(model, x, students, class_configs, settings, prefix: str, assignments: dict[str, str]) -> list:
    terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        terms,
        label_prefix=f"{prefix}_friend1",
        relationship_filter=_has_friend1_priority,
        unit_weight=True,
        hint_assignments=assignments,
    )
    return terms


def _refinement_friend2_terms(model, x, students, class_configs, settings, prefix: str, assignments: dict[str, str]) -> list:
    terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        terms,
        label_prefix=f"{prefix}_friend2",
        relationship_filter=_has_friend2_priority,
        unit_weight=True,
        hint_assignments=assignments,
    )
    return terms


def _refinement_profile_depth_terms(
    model,
    x,
    students,
    class_configs,
    language_mixed_limit: int,
    strict_language_limit: int,
    prefix: str,
) -> list:
    terms: list = []
    language_minority_weight = 1 if language_mixed_limit > strict_language_limit else 0
    _add_mixed_language_terms(model, x, students, class_configs, 0, language_minority_weight, terms, f"{prefix}_language_depth")
    _add_mixed_music_terms(model, x, students, class_configs, 0, 1, 1, terms, f"{prefix}_music_depth")
    return terms


def _refinement_final_terms(model, x, students, class_configs, settings, prefix: str, assignments: dict[str, str]) -> list:
    terms: list = []
    _add_friend_relationship_terms(
        model,
        x,
        students,
        class_configs,
        settings,
        terms,
        label_prefix=f"{prefix}_friend",
        hint_assignments=assignments,
    )
    _add_no_friend_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_no_friend,
        terms,
        f"{prefix}_no_friend",
        hint_assignments=assignments,
    )
    _add_mixed_language_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_mixed_language_class,
        settings.weight_language_minority_student,
        terms,
        f"{prefix}_language",
    )
    _add_mixed_music_terms(
        model,
        x,
        students,
        class_configs,
        settings.weight_mixed_music_class,
        settings.weight_music_minority_student,
        settings.weight_music_focus_shortfall,
        terms,
        f"{prefix}_music",
    )
    _add_support_distribution_terms(model, x, students, class_configs, settings.weight_support_distribution, terms)
    _add_gender_balance_terms(model, x, students, class_configs, settings.weight_gender_balance, terms)
    _add_concentration_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: student.school,
        settings.weight_primary_school,
        terms,
        f"{prefix}_school",
        free_count=3,
    )
    _add_concentration_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: student.primary_class,
        settings.weight_primary_class,
        terms,
        f"{prefix}_primary_class",
        free_count=2,
    )
    _add_keep_existing_terms(x, students, class_configs, settings.weight_keep_existing, terms)
    return terms


def _needs_social_diagnostics(score, phase: _PhaseResult, approval_limit: int) -> bool:
    if score.isolated_friend_request_count <= approval_limit:
        return False
    return phase.relative_gap is None or phase.relative_gap > 0.20


def _target_ladder(current_value: int, target_value: int) -> list[int]:
    if current_value <= target_value:
        return []
    next_value = (current_value // 5) * 5
    if next_value >= current_value:
        next_value -= 5
    steps: list[int] = []
    while next_value > target_value:
        steps.append(next_value)
        next_value -= 5
    if target_value not in steps:
        steps.append(target_value)
    return [step for step in steps if step >= 0]


def _diagnostic_time_limit(settings: OptimizationSettings) -> int:
    return max(1, min(settings.solver_time_limit_seconds, 5))


def _build_skipped_phase_report(name: str) -> SolverPhaseReport:
    return SolverPhaseReport(name=name, status="SKIPPED")


def _solution_metadata(
    displayed_phase: SolverPhaseReport,
    displayed_score,
    approval_phase: SolverPhaseReport,
    approval_limit: int,
    bound_phase: _PhaseResult | None,
) -> dict[str, object]:
    found_without_friend = displayed_score.isolated_friend_request_count if displayed_score else None
    approval_metric_value = (
        approval_phase.isolated_friend_request_count
        if approval_phase.status in {"OPTIMAL", "FEASIBLE"}
        else None
    )
    approval_possible_but_unproven = (
        found_without_friend is not None
        and found_without_friend > approval_limit
        and approval_phase.status == "UNKNOWN"
        and bound_phase is not None
        and bound_phase.best_bound is not None
        and bound_phase.best_bound <= approval_limit
    )
    return {
        "displayed_solution_gap": displayed_phase.relative_gap,
        "displayed_solution_gap_source": "last_accepted_phase" if displayed_phase.relative_gap is not None else None,
        "approval_test_status": approval_phase.status,
        "approval_test_limit_without_wishfriend": approval_limit,
        "approval_test_metric_value": approval_metric_value,
        "found_without_wishfriend": found_without_friend,
        "approval_threshold_without_wishfriend": approval_limit,
        "approval_possible_but_unproven": approval_possible_but_unproven,
    }


def _profile_metadata(language_phase: SolverPhaseReport, music_phase: SolverPhaseReport) -> dict[str, object]:
    return {
        "profile_min_fl_mixed_classes": language_phase.objective_value,
        "profile_min_music_mixed_classes": music_phase.objective_value,
        "profile_status_fl": language_phase.status,
        "profile_status_music": music_phase.status,
        "profile_gap_fl": language_phase.relative_gap,
        "profile_gap_music": music_phase.relative_gap,
    }


def _incumbent_limit_violations(
    score,
    *,
    language_mixed_limit: int,
    music_mixed_limit: int,
    no_friend_limit: int,
) -> list[str]:
    violations = []
    if score.mixed_language_class_count > language_mixed_limit:
        violations.append(f"F/L-Mischklassen {score.mixed_language_class_count} > {language_mixed_limit}")
    if score.mixed_music_class_count > music_mixed_limit:
        violations.append(f"Musik-Mischklassen {score.mixed_music_class_count} > {music_mixed_limit}")
    if score.isolated_friend_request_count > no_friend_limit:
        violations.append(f"Ohne Wunschfreund {score.isolated_friend_request_count} > {no_friend_limit}")
    return violations


def _build_phase_report(
    name: str,
    phase: _PhaseResult,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
) -> SolverPhaseReport:
    if phase.status_name not in {"OPTIMAL", "FEASIBLE"}:
        return SolverPhaseReport(
            name=name,
            status=phase.status_name,
            objective_value=phase.objective_value,
            best_objective_bound=phase.best_bound,
            relative_gap=phase.relative_gap,
        )

    assignments = _extract_assignments(phase.solver, x, students, class_configs)
    score = score_solution(students, assignments, settings, class_configs, manual_rules)
    return SolverPhaseReport(
        name=name,
        status=phase.status_name,
        objective_value=phase.objective_value,
        best_objective_bound=phase.best_bound,
        relative_gap=phase.relative_gap,
        mixed_language_class_count=score.mixed_language_class_count,
        mixed_music_class_count=score.mixed_music_class_count,
        language_minority_student_count=score.language_minority_student_count,
        music_minority_student_count=score.music_minority_student_count,
        isolated_friend_request_count=score.isolated_friend_request_count,
        friend1_fulfilled=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        friend2_fulfilled=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
        mutual_friend_fulfilled=score.mutual_friend_fulfilled,
        mutual_friend_total=score.mutual_friend_total,
    )


def _status_name(cp_model, status) -> str:
    return {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "ERROR",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")


def _combined_profile_status(statuses: list[str]) -> str:
    if not statuses:
        return "OPTIMAL"
    if all(status == "OPTIMAL" for status in statuses):
        return "OPTIMAL"
    if all(status in {"OPTIMAL", "FEASIBLE"} for status in statuses):
        return "FEASIBLE"
    if any(status == "INFEASIBLE" for status in statuses):
        return "INFEASIBLE"
    if any(status == "ERROR" for status in statuses):
        return "ERROR"
    return "UNKNOWN"


def _extract_assignments(solver, x, students: list[Student], class_configs: list[ClassConfig]) -> dict[str, str]:
    return {
        students[i].internal_id: class_configs[c].class_id
        for i in range(len(students))
        for c in range(len(class_configs))
        if solver.BooleanValue(x[(i, c)])
    }


def _add_assignment_hints(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    assignments: dict[str, str],
    *,
    clear_existing: bool = True,
) -> None:
    if clear_existing and hasattr(model, "ClearHints"):
        model.ClearHints()
    for i, student in enumerate(students):
        assigned_class = assignments.get(student.internal_id)
        for c, config in enumerate(class_configs):
            model.AddHint(x[(i, c)], 1 if config.class_id == assigned_class else 0)


def _student_allowed(student: Student, config: ClassConfig, settings: OptimizationSettings) -> bool:
    if settings.enforce_music_profile and config.music_allowed:
        if not student.music_profile or student.music_profile not in config.music_allowed:
            return False
    if settings.enforce_language_profile and config.languages_allowed:
        if not student.second_language or student.second_language not in config.languages_allowed:
            return False
    return True


def _add_manual_rule_constraints(model, x, students, class_configs, manual_rules: list[ManualRule]) -> None:
    for rule in manual_rules:
        student_a = resolve_student_ref(students, rule.student_a)
        student_b = resolve_student_ref(students, rule.student_b)
        if not student_a:
            continue
        a = students.index(student_a)
        if rule.type == "FIX_CLASS" and rule.class_id:
            for c, config in enumerate(class_configs):
                model.Add(x[(a, c)] == (1 if config.class_id == rule.class_id else 0))
        elif rule.type == "TOGETHER" and student_b:
            b = students.index(student_b)
            for c in range(len(class_configs)):
                model.Add(x[(a, c)] == x[(b, c)])
        elif rule.type == "SEPARATE" and student_b:
            b = students.index(student_b)
            for c in range(len(class_configs)):
                model.Add(x[(a, c)] + x[(b, c)] <= 1)


def _add_friend_relationship_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    objective_terms: list,
    *,
    label_prefix: str = "friend_pair",
    relationship_filter: Callable | None = None,
    unit_weight: bool = False,
    hint_assignments: dict[str, str] | None = None,
) -> None:
    student_index_by_id = {student.internal_id: index for index, student in enumerate(students)}
    hint_class_by_index = _hint_class_by_index(students, class_configs, hint_assignments)
    for relationship in build_friend_relationships(students):
        if relationship_filter and not relationship_filter(relationship):
            continue
        weight = 1 if unit_weight else friend_relationship_weight(relationship, settings)
        if weight <= 0:
            continue
        i = student_index_by_id[relationship.student_a.internal_id]
        j = student_index_by_id[relationship.student_b.internal_id]
        same = _same_class_bool(
            model,
            x,
            i,
            j,
            len(class_configs),
            f"{label_prefix}_same_{i}_{j}",
            hint_class_by_index=hint_class_by_index,
        )
        objective_terms.append(weight * (1 - same))


def _is_mutual_relationship(relationship) -> bool:
    return relationship.priority_a is not None and relationship.priority_b is not None


def _has_friend1_priority(relationship) -> bool:
    return relationship.priority_a == 1 or relationship.priority_b == 1


def _has_friend2_priority(relationship) -> bool:
    return relationship.priority_a == 2 or relationship.priority_b == 2


def _add_no_friend_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    weight: int,
    objective_terms: list,
    label_prefix: str = "friend_any",
    *,
    hint_assignments: dict[str, str] | None = None,
) -> None:
    if weight <= 0:
        return
    student_index_by_id = {student.internal_id: index for index, student in enumerate(students)}
    hint_class_by_index = _hint_class_by_index(students, class_configs, hint_assignments)
    for i, student in enumerate(students):
        friend_indexes = [
            student_index_by_id[friend.internal_id]
            for friend in (
                resolve_student_ref(students, student.friend1),
                resolve_student_ref(students, student.friend2),
            )
            if friend
        ]
        if not friend_indexes:
            continue
        same_vars = [
            _same_class_bool(
                model,
                x,
                i,
                j,
                len(class_configs),
                f"{label_prefix}_same_{i}_{j}",
                hint_class_by_index=hint_class_by_index,
            )
            for j in sorted(set(friend_indexes))
        ]
        any_same = model.NewBoolVar(f"{label_prefix}_same_{i}")
        model.AddMaxEquality(any_same, same_vars)
        if hint_class_by_index:
            own_class = hint_class_by_index.get(i)
            friend_classes = [hint_class_by_index.get(j) for j in sorted(set(friend_indexes))]
            model.AddHint(any_same, 1 if own_class is not None and own_class in friend_classes else 0)
        objective_terms.append(weight * (1 - any_same))


def _same_class_bool(
    model,
    x,
    i: int,
    j: int,
    class_count: int,
    label: str,
    *,
    hint_class_by_index: dict[int, int] | None = None,
):
    same = model.NewBoolVar(label)
    both_vars = []
    for c in range(class_count):
        both = model.NewBoolVar(f"{label}_both_{c}")
        model.AddBoolAnd([x[(i, c)], x[(j, c)]]).OnlyEnforceIf(both)
        model.AddBoolOr([x[(i, c)].Not(), x[(j, c)].Not()]).OnlyEnforceIf(both.Not())
        if hint_class_by_index:
            model.AddHint(both, 1 if hint_class_by_index.get(i) == c and hint_class_by_index.get(j) == c else 0)
        both_vars.append(both)
    model.Add(sum(both_vars) == same)
    if hint_class_by_index:
        model.AddHint(
            same,
            1
            if hint_class_by_index.get(i) is not None and hint_class_by_index.get(i) == hint_class_by_index.get(j)
            else 0,
        )
    return same


def _hint_class_by_index(
    students: list[Student],
    class_configs: list[ClassConfig],
    assignments: dict[str, str] | None,
) -> dict[int, int] | None:
    if not assignments:
        return None
    class_index_by_id = {config.class_id: index for index, config in enumerate(class_configs)}
    result = {}
    for i, student in enumerate(students):
        class_index = class_index_by_id.get(assignments.get(student.internal_id, ""))
        if class_index is not None:
            result[i] = class_index
    return result


def _add_mixed_language_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    class_weight: int,
    minority_weight: int,
    objective_terms: list,
    label_prefix: str = "language",
) -> None:
    if class_weight <= 0 and minority_weight <= 0:
        return
    f_indexes = [i for i, student in enumerate(students) if student.second_language == "F"]
    l_indexes = [i for i, student in enumerate(students) if student.second_language == "L"]
    if not f_indexes or not l_indexes:
        return

    for c, config in enumerate(class_configs):
        f_count = model.NewIntVar(0, len(f_indexes), f"{label_prefix}_f_count_{config.class_id}")
        l_count = model.NewIntVar(0, len(l_indexes), f"{label_prefix}_l_count_{config.class_id}")
        has_f = model.NewBoolVar(f"{label_prefix}_has_f_{config.class_id}")
        has_l = model.NewBoolVar(f"{label_prefix}_has_l_{config.class_id}")
        is_mixed = model.NewBoolVar(f"{label_prefix}_mixed_{config.class_id}")

        model.Add(f_count == sum(x[(i, c)] for i in f_indexes))
        model.Add(l_count == sum(x[(i, c)] for i in l_indexes))
        model.Add(f_count >= 1).OnlyEnforceIf(has_f)
        model.Add(f_count == 0).OnlyEnforceIf(has_f.Not())
        model.Add(l_count >= 1).OnlyEnforceIf(has_l)
        model.Add(l_count == 0).OnlyEnforceIf(has_l.Not())
        model.AddBoolAnd([has_f, has_l]).OnlyEnforceIf(is_mixed)
        model.AddBoolOr([has_f.Not(), has_l.Not()]).OnlyEnforceIf(is_mixed.Not())
        if class_weight > 0:
            objective_terms.append(class_weight * is_mixed)
        if minority_weight > 0:
            minority = model.NewIntVar(0, min(len(f_indexes), len(l_indexes)), f"{label_prefix}_minority_{config.class_id}")
            model.AddMinEquality(minority, [f_count, l_count])
            objective_terms.append(minority_weight * minority)


def _add_mixed_music_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    class_weight: int,
    minority_weight: int,
    focus_shortfall_weight: int,
    objective_terms: list,
    label_prefix: str = "music",
) -> None:
    if class_weight <= 0 and minority_weight <= 0 and focus_shortfall_weight <= 0:
        return

    focus_profiles = ("B", "S", "G")
    profile_indexes = {
        profile: [
            i for i, student in enumerate(students) if student.music_profile == profile
        ]
        for profile in focus_profiles
    }
    regular_indexes = [i for i, student in enumerate(students) if student.music_profile == "Reg"]
    if sum(1 for indexes in profile_indexes.values() if indexes) <= 1 and focus_shortfall_weight <= 0:
        return

    for c, config in enumerate(class_configs):
        has_profile = {}
        profile_counts = {}
        for profile, indexes in profile_indexes.items():
            profile_count = model.NewIntVar(0, len(indexes), f"{label_prefix}_{profile}_count_{config.class_id}")
            profile_counts[profile] = profile_count
            has_profile[profile] = model.NewBoolVar(f"{label_prefix}_has_{profile}_{config.class_id}")
            model.Add(profile_count == sum(x[(i, c)] for i in indexes))
            model.Add(profile_count >= 1).OnlyEnforceIf(has_profile[profile])
            model.Add(profile_count == 0).OnlyEnforceIf(has_profile[profile].Not())

        pair_mixed_vars = []
        for index, profile_a in enumerate(focus_profiles):
            for profile_b in focus_profiles[index + 1 :]:
                pair_mixed = model.NewBoolVar(f"{label_prefix}_mixed_{profile_a}_{profile_b}_{config.class_id}")
                model.AddBoolAnd([has_profile[profile_a], has_profile[profile_b]]).OnlyEnforceIf(pair_mixed)
                model.AddBoolOr([has_profile[profile_a].Not(), has_profile[profile_b].Not()]).OnlyEnforceIf(pair_mixed.Not())
                pair_mixed_vars.append(pair_mixed)

        is_mixed = model.NewBoolVar(f"{label_prefix}_mixed_{config.class_id}")
        model.AddMaxEquality(is_mixed, pair_mixed_vars)
        if class_weight > 0:
            objective_terms.append(class_weight * is_mixed)

        if minority_weight > 0:
            focus_total = model.NewIntVar(0, len(students), f"{label_prefix}_focus_total_{config.class_id}")
            max_focus = model.NewIntVar(0, len(students), f"{label_prefix}_focus_max_{config.class_id}")
            minority = model.NewIntVar(0, len(students), f"{label_prefix}_minority_{config.class_id}")
            model.Add(focus_total == sum(profile_counts.values()))
            model.AddMaxEquality(max_focus, list(profile_counts.values()))
            model.Add(minority == focus_total - max_focus)
            objective_terms.append(minority_weight * minority)

        if focus_shortfall_weight > 0:
            regular_count = model.NewIntVar(0, len(regular_indexes), f"{label_prefix}_reg_count_{config.class_id}")
            focus_total = model.NewIntVar(0, len(students), f"{label_prefix}_focus_strength_total_{config.class_id}")
            has_focus = model.NewBoolVar(f"{label_prefix}_has_focus_{config.class_id}")
            shortfall = model.NewIntVar(0, len(students), f"{label_prefix}_focus_shortfall_{config.class_id}")
            model.Add(regular_count == sum(x[(i, c)] for i in regular_indexes))
            model.Add(focus_total == sum(profile_counts.values()))
            model.Add(focus_total >= 1).OnlyEnforceIf(has_focus)
            model.Add(focus_total == 0).OnlyEnforceIf(has_focus.Not())
            model.Add(shortfall >= regular_count - focus_total).OnlyEnforceIf(has_focus)
            model.Add(shortfall == 0).OnlyEnforceIf(has_focus.Not())
            objective_terms.append(focus_shortfall_weight * shortfall)


def _add_soft_profile_terms(
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    enforce_hard: bool,
    weight: int,
    student_getter: Callable[[Student], str | None],
    allowed_getter: Callable[[ClassConfig], list[str]],
    objective_terms: list,
) -> None:
    if enforce_hard or weight <= 0:
        return
    for i, student in enumerate(students):
        student_value = student_getter(student)
        for c, config in enumerate(class_configs):
            allowed = allowed_getter(config)
            if allowed and student_value not in allowed:
                objective_terms.append(weight * x[(i, c)])


def _add_class_size_policy_terms(model, x, students: list[Student], class_configs: list[ClassConfig], objective_terms: list) -> None:
    for c, config in enumerate(class_configs):
        policy = getattr(config, "size_policy", None)
        if not policy or policy.soft_weight <= 0:
            continue
        class_size = sum(x[(i, c)] for i in range(len(students)))
        max_deviation = max(policy.comfort_min, config.size_max - policy.comfort_max, 0)
        for deviation in range(1, max_deviation + 1):
            under_step = model.NewBoolVar(f"class_size_under_{config.class_id}_{deviation}")
            model.Add(class_size <= policy.comfort_min - deviation).OnlyEnforceIf(under_step)
            model.Add(class_size >= policy.comfort_min - deviation + 1).OnlyEnforceIf(under_step.Not())
            over_step = model.NewBoolVar(f"class_size_over_{config.class_id}_{deviation}")
            model.Add(class_size >= policy.comfort_max + deviation).OnlyEnforceIf(over_step)
            model.Add(class_size <= policy.comfort_max + deviation - 1).OnlyEnforceIf(over_step.Not())
            objective_terms.append(policy.soft_weight * (2 * deviation - 1) * under_step)
            objective_terms.append(policy.soft_weight * (2 * deviation - 1) * over_step)


def _add_support_distribution_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    weight: int,
    objective_terms: list,
) -> None:
    if weight <= 0:
        return
    support_indexes = [i for i, student in enumerate(students) if student.is_support]
    if not support_indexes:
        return
    upper_bound = support_upper_bound(len(support_indexes), len(class_configs))
    for c, config in enumerate(class_configs):
        count = sum(x[(i, c)] for i in support_indexes)
        _add_excess_square_step_terms(
            model,
            count,
            upper_bound,
            min(len(support_indexes), config.size_max),
            weight,
            f"support_{config.class_id}",
            objective_terms,
        )


def _add_gender_balance_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    weight: int,
    objective_terms: list,
) -> None:
    if weight <= 0:
        return
    female_indexes = [i for i, student in enumerate(students) if student.gender == "w"]
    if not female_indexes:
        return
    class_count = len(class_configs)
    female_total = len(female_indexes)
    max_deviation = max(female_total * class_count, len(students) * class_count - female_total)
    for c, config in enumerate(class_configs):
        count = sum(x[(i, c)] for i in female_indexes)
        abs_deviation = model.NewIntVar(0, max_deviation, f"dev_female_{config.class_id}")
        model.AddAbsEquality(abs_deviation, count * class_count - female_total)
        for extra_child in range(1, config.size_max + 1):
            threshold = (2 + extra_child) * class_count
            if threshold > max_deviation:
                break
            step = model.NewBoolVar(f"gender_excess_{config.class_id}_{extra_child}")
            model.Add(abs_deviation >= threshold).OnlyEnforceIf(step)
            model.Add(abs_deviation <= threshold - 1).OnlyEnforceIf(step.Not())
            objective_terms.append(weight * (2 * extra_child - 1) * step)


def _add_concentration_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    getter: Callable[[Student], str | None],
    weight: int,
    objective_terms: list,
    label: str,
    *,
    free_count: int,
) -> None:
    if weight <= 0:
        return
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, student in enumerate(students):
        key = getter(student)
        if key:
            grouped[key].append(index)
    for key, indexes in grouped.items():
        if len(indexes) <= free_count:
            continue
        for c, config in enumerate(class_configs):
            count = sum(x[(i, c)] for i in indexes)
            _add_excess_square_step_terms(
                model,
                count,
                free_count,
                min(len(indexes), config.size_max),
                weight,
                f"{label}_{key}_{c}",
                objective_terms,
            )


def _add_excess_square_step_terms(
    model,
    count,
    free_count: int,
    max_possible: int,
    weight: int,
    label: str,
    objective_terms: list,
) -> None:
    for excess in range(1, max_possible - free_count + 1):
        threshold = free_count + excess
        step = model.NewBoolVar(f"excess_{label}_{excess}")
        model.Add(count >= threshold).OnlyEnforceIf(step)
        model.Add(count <= threshold - 1).OnlyEnforceIf(step.Not())
        objective_terms.append(weight * (2 * excess - 1) * step)


def _add_keep_existing_terms(
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    weight: int,
    objective_terms: list,
) -> None:
    if weight <= 0:
        return
    class_index_by_id = {config.class_id: c for c, config in enumerate(class_configs)}
    for i, student in enumerate(students):
        if student.original_class in class_index_by_id:
            objective_terms.append(weight * (1 - x[(i, class_index_by_id[student.original_class])]))


def _solve_greedy_fallback(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rules: list[ManualRule],
) -> SolverResult:
    assignments: dict[str, str] = {}
    sizes = {config.class_id: 0 for config in class_configs}
    configs_by_id = {config.class_id: config for config in class_configs}

    for rule in manual_rules:
        if rule.type != "FIX_CLASS" or not rule.class_id:
            continue
        student = resolve_student_ref(students, rule.student_a)
        config = configs_by_id.get(rule.class_id)
        if not student or not config or not _student_allowed(student, config, settings):
            return SolverResult("INFEASIBLE", {}, message="Fixierung ist nicht erfüllbar.")
        if sizes[rule.class_id] >= config.size_max:
            return SolverResult("INFEASIBLE", {}, message="Fixierte Klasse ist voll.")
        assignments[student.internal_id] = rule.class_id
        sizes[rule.class_id] += 1

    for student in students:
        if student.internal_id in assignments:
            continue
        candidates = [
            config
            for config in class_configs
            if _student_allowed(student, config, settings) and sizes[config.class_id] < config.size_max
        ]
        if not candidates:
            return SolverResult(
                "INFEASIBLE",
                {},
                message="Fallback konnte keine zulässige Klasse für alle Schüler finden.",
            )
        candidates.sort(key=lambda config: (sizes[config.class_id], config.class_id))
        chosen = candidates[0]
        assignments[student.internal_id] = chosen.class_id
        sizes[chosen.class_id] += 1

    score = score_solution(students, assignments, settings, class_configs, manual_rules)
    if score.hard_violations:
        return SolverResult("INFEASIBLE", assignments, score_report=score, message="Fallback verletzt harte Regeln.")
    return SolverResult(
        "FEASIBLE",
        assignments,
        score_report=score,
        message="OR-Tools ist nicht installiert. Es wurde ein einfacher Fallback verwendet.",
    )

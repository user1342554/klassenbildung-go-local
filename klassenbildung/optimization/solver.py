from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable

from klassenbildung.core.models import (
    ClassConfig,
    ManualRule,
    OptimizationSettings,
    SolverResult,
    Student,
)
from klassenbildung.optimization.scoring import resolve_student_ref, score_solution


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

    objective_terms = []
    _add_friend_terms(model, x, students, class_configs, lambda student: student.friend1, settings.weight_friend1, objective_terms)
    _add_friend_terms(model, x, students, class_configs, lambda student: student.friend2, settings.weight_friend2, objective_terms)
    _add_soft_profile_terms(
        x,
        students,
        class_configs,
        enforce_hard=settings.enforce_music_profile,
        weight=settings.weight_music_profile,
        student_getter=lambda student: student.music_profile,
        allowed_getter=lambda config: config.music_allowed,
        objective_terms=objective_terms,
    )
    _add_soft_profile_terms(
        x,
        students,
        class_configs,
        enforce_hard=settings.enforce_language_profile,
        weight=settings.weight_language_profile,
        student_getter=lambda student: student.second_language,
        allowed_getter=lambda config: config.languages_allowed,
        objective_terms=objective_terms,
    )
    _add_distribution_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: 1 if student.is_support else 0,
        settings.weight_support_distribution,
        objective_terms,
        "support",
    )
    _add_distribution_terms(
        model,
        x,
        students,
        class_configs,
        lambda student: 1 if student.gender == "w" else 0,
        settings.weight_gender_balance,
        objective_terms,
        "female",
    )
    _add_concentration_terms(model, x, students, class_configs, lambda student: student.school, settings.weight_primary_school, objective_terms, "school")
    _add_concentration_terms(model, x, students, class_configs, lambda student: student.primary_class, settings.weight_primary_class, objective_terms, "primary_class")
    _add_concentration_terms(model, x, students, class_configs, lambda student: student.nationality, settings.weight_nationality, objective_terms, "nationality")
    _add_concentration_terms(model, x, students, class_configs, lambda student: student.religion, settings.weight_religion, objective_terms, "religion")
    _add_keep_existing_terms(x, students, class_configs, settings.weight_keep_existing, objective_terms)

    if objective_terms:
        model.Minimize(sum(objective_terms))
    else:
        model.Minimize(0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.solver_time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "ERROR",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    if status_name not in {"OPTIMAL", "FEASIBLE"}:
        return SolverResult(status_name, {}, message="Solver hat keine gültige Einteilung gefunden.")

    assignments = {
        students[i].internal_id: class_configs[c].class_id
        for i in student_indexes
        for c in class_indexes
        if solver.BooleanValue(x[(i, c)])
    }
    score = score_solution(students, assignments, settings, class_configs, manual_rules)
    return SolverResult(
        status_name,
        assignments,
        score_report=score,
        objective_value=int(solver.ObjectiveValue()),
    )


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


def _add_friend_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    getter: Callable[[Student], str | None],
    weight: int,
    objective_terms: list,
) -> None:
    if weight <= 0:
        return
    for i, student in enumerate(students):
        friend = resolve_student_ref(students, getter(student))
        if not friend:
            continue
        j = students.index(friend)
        same = model.NewBoolVar(f"same_{i}_{j}_{len(objective_terms)}")
        both_vars = []
        for c in range(len(class_configs)):
            both = model.NewBoolVar(f"both_{i}_{j}_{c}_{len(objective_terms)}")
            model.AddBoolAnd([x[(i, c)], x[(j, c)]]).OnlyEnforceIf(both)
            model.AddBoolOr([x[(i, c)].Not(), x[(j, c)].Not()]).OnlyEnforceIf(both.Not())
            both_vars.append(both)
        model.Add(sum(both_vars) == same)
        objective_terms.append(weight * (1 - same))


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


def _add_distribution_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    getter: Callable[[Student], int],
    weight: int,
    objective_terms: list,
    label: str,
) -> None:
    if weight <= 0:
        return
    total = sum(getter(student) for student in students)
    class_count = len(class_configs)
    max_deviation = max(total * class_count, 1)
    for c in range(class_count):
        count = sum(getter(student) * x[(i, c)] for i, student in enumerate(students))
        deviation = model.NewIntVar(0, max_deviation, f"dev_{label}_{c}")
        model.AddAbsEquality(deviation, count * class_count - total)
        objective_terms.append(weight * deviation)


def _add_concentration_terms(
    model,
    x,
    students: list[Student],
    class_configs: list[ClassConfig],
    getter: Callable[[Student], str | None],
    weight: int,
    objective_terms: list,
    label: str,
) -> None:
    if weight <= 0:
        return
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, student in enumerate(students):
        key = getter(student)
        if key:
            grouped[key].append(index)
    class_count = len(class_configs)
    for key, indexes in grouped.items():
        if len(indexes) <= 1:
            continue
        threshold = math.ceil(len(indexes) / class_count) + 1
        for c in range(class_count):
            count = sum(x[(i, c)] for i in indexes)
            excess = model.NewIntVar(0, len(indexes), f"excess_{label}_{key}_{c}")
            model.Add(excess >= count - threshold)
            objective_terms.append(weight * excess)


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

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable

from klassenbildung.core.models import (
    ClassConfig,
    ClassReport,
    ManualRule,
    OptimizationSettings,
    ScoreReport,
    Student,
)


def resolve_student_ref(students: list[Student], reference: str | None) -> Student | None:
    if not reference:
        return None
    needle = reference.strip().lower()
    for student in students:
        candidates = {
            student.internal_id.lower(),
            (student.nr or "").lower(),
            student.full_name.lower(),
            student.sort_name.lower(),
        }
        if needle in candidates:
            return student
    return None


def score_solution(
    students: list[Student],
    assignments: dict[str, str],
    settings: OptimizationSettings,
    class_configs: list[ClassConfig],
    manual_rules: list[ManualRule] | None = None,
) -> ScoreReport:
    manual_rules = manual_rules or []
    class_by_id = {config.class_id: config for config in class_configs}
    students_by_class: dict[str, list[Student]] = {config.class_id: [] for config in class_configs}
    hard_violations: list[str] = []
    warnings: list[str] = []

    for student in students:
        class_id = assignments.get(student.internal_id)
        if not class_id:
            hard_violations.append(f"{student.display_label}: keine Klasse zugeordnet")
            continue
        if class_id not in class_by_id:
            hard_violations.append(f"{student.display_label}: unbekannte Klasse {class_id}")
            continue
        students_by_class[class_id].append(student)

    for config in class_configs:
        size = len(students_by_class[config.class_id])
        if size < config.size_min:
            hard_violations.append(f"{config.class_id}: zu klein ({size} < {config.size_min})")
        if size > config.size_max:
            hard_violations.append(f"{config.class_id}: zu groß ({size} > {config.size_max})")

    for student in students:
        class_id = assignments.get(student.internal_id)
        config = class_by_id.get(class_id or "")
        if not config:
            continue
        if settings.enforce_music_profile and config.music_allowed:
            if not student.music_profile or student.music_profile not in config.music_allowed:
                hard_violations.append(
                    f"{student.display_label}: Musikprofil {student.music_profile or 'leer'} passt nicht zu {class_id}"
                )
        if settings.enforce_language_profile and config.languages_allowed:
            if not student.second_language or student.second_language not in config.languages_allowed:
                hard_violations.append(
                    f"{student.display_label}: Sprache {student.second_language or 'leer'} passt nicht zu {class_id}"
                )

    for rule in manual_rules:
        _score_manual_rule(rule, students, assignments, hard_violations)

    class_reports = [
        _build_class_report(config.class_id, students_by_class[config.class_id]) for config in class_configs
    ]

    friend1_total, friend1_fulfilled, friend1_penalty, unmet1, unresolved1 = _score_friend_requests(
        students,
        assignments,
        lambda student: student.friend1,
        settings.weight_friend1,
        "Freund 1",
    )
    friend2_total, friend2_fulfilled, friend2_penalty, unmet2, unresolved2 = _score_friend_requests(
        students,
        assignments,
        lambda student: student.friend2,
        settings.weight_friend2,
        "Freund 2",
    )
    warnings.extend(unresolved1)
    warnings.extend(unresolved2)

    total_score = friend1_penalty + friend2_penalty
    if not settings.enforce_music_profile:
        total_score += settings.weight_music_profile * _soft_profile_mismatches(
            students,
            assignments,
            class_by_id,
            lambda student: student.music_profile,
            lambda config: config.music_allowed,
        )
    if not settings.enforce_language_profile:
        total_score += settings.weight_language_profile * _soft_profile_mismatches(
            students,
            assignments,
            class_by_id,
            lambda student: student.second_language,
            lambda config: config.languages_allowed,
        )
    total_score += settings.weight_support_distribution * _scaled_distribution_deviation(
        class_reports,
        lambda report: report.support_count,
    )
    total_score += settings.weight_gender_balance * _scaled_distribution_deviation(
        class_reports,
        lambda report: report.gender_counts.get("w", 0),
    )
    total_score += settings.weight_primary_school * _concentration_penalty(
        class_reports,
        lambda report: report.school_counts,
    )
    total_score += settings.weight_primary_class * _concentration_penalty(
        class_reports,
        lambda report: {},
    )
    total_score += settings.weight_nationality * _concentration_penalty(
        class_reports,
        lambda report: report.nationality_counts,
    )
    total_score += settings.weight_religion * _concentration_penalty(
        class_reports,
        lambda report: report.religion_counts,
    )
    total_score += settings.weight_keep_existing * _changed_existing_assignments(students, assignments)

    return ScoreReport(
        total_score=int(total_score),
        hard_violations=hard_violations,
        friend1_total=friend1_total,
        friend1_fulfilled=friend1_fulfilled,
        friend2_total=friend2_total,
        friend2_fulfilled=friend2_fulfilled,
        class_reports=class_reports,
        warnings=warnings,
        unmet_friend_requests=unmet1 + unmet2,
    )


def _build_class_report(class_id: str, students: list[Student]) -> ClassReport:
    return ClassReport(
        class_id=class_id,
        size=len(students),
        gender_counts=_counter(students, lambda student: student.gender),
        language_counts=_counter(students, lambda student: student.second_language),
        music_counts=_counter(students, lambda student: student.music_profile),
        support_count=sum(1 for student in students if student.is_support),
        school_counts=_counter(students, lambda student: student.school),
        religion_counts=_counter(students, lambda student: student.religion),
        nationality_counts=_counter(students, lambda student: student.nationality),
    )


def _counter(students: list[Student], getter: Callable[[Student], str | None]) -> dict[str, int]:
    return dict(Counter(getter(student) or "leer" for student in students))


def _score_friend_requests(
    students: list[Student],
    assignments: dict[str, str],
    getter: Callable[[Student], str | None],
    weight: int,
    label: str,
) -> tuple[int, int, int, list[str], list[str]]:
    total = 0
    fulfilled = 0
    unmet: list[str] = []
    unresolved: list[str] = []
    for student in students:
        friend_ref = getter(student)
        if not friend_ref:
            continue
        friend = resolve_student_ref(students, friend_ref)
        if not friend:
            unresolved.append(f"{student.display_label}: {label} nicht gefunden ({friend_ref})")
            continue
        total += 1
        if assignments.get(student.internal_id) == assignments.get(friend.internal_id):
            fulfilled += 1
        else:
            unmet.append(f"{label}: {student.display_label} nicht mit {friend.display_label}")
    return total, fulfilled, (total - fulfilled) * weight, unmet, unresolved


def _soft_profile_mismatches(
    students: list[Student],
    assignments: dict[str, str],
    class_by_id: dict[str, ClassConfig],
    student_getter: Callable[[Student], str | None],
    allowed_getter: Callable[[ClassConfig], list[str]],
) -> int:
    mismatches = 0
    for student in students:
        config = class_by_id.get(assignments.get(student.internal_id) or "")
        if not config:
            continue
        allowed = allowed_getter(config)
        if allowed and student_getter(student) not in allowed:
            mismatches += 1
    return mismatches


def _scaled_distribution_deviation(
    class_reports: list[ClassReport],
    getter: Callable[[ClassReport], int],
) -> int:
    if not class_reports:
        return 0
    total = sum(getter(report) for report in class_reports)
    class_count = len(class_reports)
    return sum(abs(getter(report) * class_count - total) for report in class_reports)


def _concentration_penalty(
    class_reports: list[ClassReport],
    getter: Callable[[ClassReport], dict[str, int]],
) -> int:
    totals: dict[str, int] = defaultdict(int)
    for report in class_reports:
        for key, count in getter(report).items():
            if key != "leer":
                totals[key] += count

    penalty = 0
    class_count = len(class_reports) or 1
    for report in class_reports:
        counts = getter(report)
        for key, count in counts.items():
            if key == "leer":
                continue
            threshold = math.ceil(totals[key] / class_count) + 1
            penalty += max(0, count - threshold)
    return penalty


def _changed_existing_assignments(students: list[Student], assignments: dict[str, str]) -> int:
    return sum(
        1
        for student in students
        if student.original_class and assignments.get(student.internal_id) != student.original_class
    )


def _score_manual_rule(
    rule: ManualRule,
    students: list[Student],
    assignments: dict[str, str],
    hard_violations: list[str],
) -> None:
    student_a = resolve_student_ref(students, rule.student_a)
    student_b = resolve_student_ref(students, rule.student_b)
    if not student_a:
        return
    if rule.type == "FIX_CLASS" and assignments.get(student_a.internal_id) != rule.class_id:
        hard_violations.append(f"{student_a.display_label}: Fixierung auf {rule.class_id} verletzt")
    if rule.type == "TOGETHER" and student_b:
        if assignments.get(student_a.internal_id) != assignments.get(student_b.internal_id):
            hard_violations.append(
                f"{student_a.display_label} und {student_b.display_label}: Zusammen-Regel verletzt"
            )
    if rule.type == "SEPARATE" and student_b:
        if assignments.get(student_a.internal_id) == assignments.get(student_b.internal_id):
            hard_violations.append(
                f"{student_a.display_label} und {student_b.display_label}: Trennungsregel verletzt"
            )

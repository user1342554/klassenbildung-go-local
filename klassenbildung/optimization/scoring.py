from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable

from klassenbildung.core.normalization import normalize_primary_class
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

    friend1_total, friend1_fulfilled, unmet1, unresolved1 = _score_friend_requests(
        students,
        assignments,
        lambda student: student.friend1,
        "Freundeswunsch 1",
    )
    friend2_total, friend2_fulfilled, unmet2, unresolved2 = _score_friend_requests(
        students,
        assignments,
        lambda student: student.friend2,
        "Freundeswunsch 2",
    )
    mutual_total, mutual_fulfilled = _score_mutual_friend_requests(
        students,
        assignments,
    )
    friendship_score, unmet_relationships = _score_friend_relationships(students, assignments, settings)
    isolated_count, isolated_messages = _score_friend_isolation(students, assignments)
    warnings.extend(unresolved1)
    warnings.extend(unresolved2)

    mixed_language_class_count = sum(1 for report in class_reports if report.is_language_mixed)
    mixed_music_class_count = sum(1 for report in class_reports if report.is_music_mixed)
    language_minority_student_count = sum(report.language_minority_count for report in class_reports)
    music_minority_student_count = sum(report.music_minority_count for report in class_reports)
    music_focus_shortfall_count = sum(report.music_focus_shortfall for report in class_reports)

    category_scores = {
        "Klassengröße Komfortbereich": _class_size_policy_score(class_reports, class_by_id),
        "Freundschaften getrennt": friendship_score,
        "Kinder ohne Wunschfreund": settings.weight_no_friend * isolated_count,
        "F/L-Mischklassen": settings.weight_mixed_language_class * mixed_language_class_count,
        "F/L-Minderheit in Mischklassen": settings.weight_language_minority_student
        * language_minority_student_count,
        "Musik-Mischklassen B/S/G": settings.weight_mixed_music_class * mixed_music_class_count,
        "Musik-Minderheit in Mischklassen": settings.weight_music_minority_student
        * music_minority_student_count,
        "Musik-Profilanteil": settings.weight_music_focus_shortfall * music_focus_shortfall_count,
        "R-Ballung": settings.weight_support_distribution * _support_distribution_penalty_units(class_reports),
        "Geschlechter-Schieflage": settings.weight_gender_balance * _gender_balance_penalty_units(class_reports),
        "Grundschulballung": settings.weight_primary_school
        * _concentration_penalty_units(class_reports, lambda report: report.school_counts, free_count=3),
        "Grundschulklassen-Ballung": settings.weight_primary_class
        * _concentration_penalty_units(class_reports, lambda report: report.primary_class_counts, free_count=2),
        "Bestehende Einteilung": settings.weight_keep_existing * _changed_existing_assignments(students, assignments),
    }
    if not settings.enforce_music_profile:
        category_scores["Klassen-Musikprofil"] = settings.weight_music_profile * _soft_profile_mismatches(
            students,
            assignments,
            class_by_id,
            lambda student: student.music_profile,
            lambda config: config.music_allowed,
        )
    if not settings.enforce_language_profile:
        category_scores["Klassen-Sprachprofil"] = settings.weight_language_profile * _soft_profile_mismatches(
            students,
            assignments,
            class_by_id,
            lambda student: student.second_language,
            lambda config: config.languages_allowed,
        )
    category_scores = {label: points for label, points in category_scores.items() if points}
    total_score = sum(category_scores.values())

    return ScoreReport(
        total_score=int(total_score),
        hard_violations=hard_violations,
        friend1_total=friend1_total,
        friend1_fulfilled=friend1_fulfilled,
        friend2_total=friend2_total,
        friend2_fulfilled=friend2_fulfilled,
        mutual_friend_total=mutual_total,
        mutual_friend_fulfilled=mutual_fulfilled,
        mixed_language_class_count=mixed_language_class_count,
        mixed_music_class_count=mixed_music_class_count,
        language_minority_student_count=language_minority_student_count,
        music_minority_student_count=music_minority_student_count,
        music_focus_shortfall_count=music_focus_shortfall_count,
        isolated_friend_request_count=isolated_count,
        class_reports=class_reports,
        category_scores=category_scores,
        friend_profile_conflicts=_friend_profile_conflict_counts(students),
        warnings=warnings,
        unmet_friend_requests=unmet_relationships + isolated_messages + unmet1 + unmet2,
    )


def _build_class_report(class_id: str, students: list[Student]) -> ClassReport:
    language_counts = _counter(students, lambda student: student.second_language)
    music_counts = _counter(students, lambda student: student.music_profile)
    return ClassReport(
        class_id=class_id,
        size=len(students),
        gender_counts=_counter(students, lambda student: student.gender),
        language_counts=language_counts,
        music_counts=music_counts,
        is_language_mixed=language_counts.get("F", 0) > 0 and language_counts.get("L", 0) > 0,
        language_minority_count=_language_minority_count(language_counts),
        is_music_mixed=_has_mixed_music_focus(music_counts),
        music_minority_count=_music_minority_count(music_counts),
        music_focus_shortfall=_music_focus_shortfall(music_counts),
        support_count=sum(1 for student in students if student.is_support),
        school_counts=_counter(students, lambda student: student.school),
        primary_class_counts=_counter(students, _primary_school_class_key),
        religion_counts=_counter(students, lambda student: student.religion),
        nationality_counts=_counter(students, lambda student: student.nationality),
    )


def _has_mixed_music_focus(music_counts: dict[str, int]) -> bool:
    focus_profiles = {"B", "S", "G"}
    present_focus_profiles = [
        profile for profile in focus_profiles if music_counts.get(profile, 0) > 0
    ]
    return len(present_focus_profiles) > 1


def _language_minority_count(language_counts: dict[str, int]) -> int:
    f_count = language_counts.get("F", 0)
    l_count = language_counts.get("L", 0)
    if not f_count or not l_count:
        return 0
    return min(f_count, l_count)


def _music_minority_count(music_counts: dict[str, int]) -> int:
    focus_counts = [music_counts.get(profile, 0) for profile in ("B", "S", "G")]
    present_counts = [count for count in focus_counts if count > 0]
    if len(present_counts) <= 1:
        return 0
    return sum(present_counts) - max(present_counts)


def _music_focus_shortfall(music_counts: dict[str, int]) -> int:
    focus_total = sum(music_counts.get(profile, 0) for profile in ("B", "S", "G"))
    if focus_total <= 0:
        return 0
    return max(0, music_counts.get("Reg", 0) - focus_total)


def _counter(students: list[Student], getter: Callable[[Student], str | None]) -> dict[str, int]:
    return dict(Counter(getter(student) or "leer" for student in students))


def _primary_school_class_key(student: Student) -> str | None:
    primary_class = normalize_primary_class(student.primary_class)
    if not primary_class:
        return None
    school = (student.school or "unbekannte Schule").strip() or "unbekannte Schule"
    return f"{school} / {primary_class}"


def _score_friend_requests(
    students: list[Student],
    assignments: dict[str, str],
    getter: Callable[[Student], str | None],
    label: str,
) -> tuple[int, int, list[str], list[str]]:
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
    return total, fulfilled, unmet, unresolved


def _score_mutual_friend_requests(
    students: list[Student],
    assignments: dict[str, str],
) -> tuple[int, int]:
    pairs = [
        relationship
        for relationship in build_friend_relationships(students)
        if relationship.priority_a is not None and relationship.priority_b is not None
    ]
    fulfilled = 0
    for relationship in pairs:
        if assignments.get(relationship.student_a.internal_id) == assignments.get(relationship.student_b.internal_id):
            fulfilled += 1
    return len(pairs), fulfilled


class FriendRelationship:
    def __init__(
        self,
        student_a: Student,
        student_b: Student,
        priority_a: int | None,
        priority_b: int | None,
    ) -> None:
        self.student_a = student_a
        self.student_b = student_b
        self.priority_a = priority_a
        self.priority_b = priority_b


def build_friend_relationships(students: list[Student]) -> list[FriendRelationship]:
    requests: dict[str, dict[str, int]] = defaultdict(dict)
    student_by_id = {student.internal_id: student for student in students}
    for student in students:
        for priority, friend_ref in ((1, student.friend1), (2, student.friend2)):
            friend = resolve_student_ref(students, friend_ref)
            if friend:
                current_priority = requests[student.internal_id].get(friend.internal_id)
                requests[student.internal_id][friend.internal_id] = min(
                    priority,
                    current_priority or priority,
                )

    pair_ids: set[tuple[str, str]] = set()
    for student_id, requested_by_priority in requests.items():
        for friend_id in requested_by_priority:
            pair_ids.add(tuple(sorted((student_id, friend_id))))

    return [
        FriendRelationship(
            student_by_id[student_id],
            student_by_id[friend_id],
            requests.get(student_id, {}).get(friend_id),
            requests.get(friend_id, {}).get(student_id),
        )
        for student_id, friend_id in sorted(pair_ids)
    ]


def friend_relationship_weight(relationship: FriendRelationship, settings: OptimizationSettings) -> int:
    priority_a = relationship.priority_a
    priority_b = relationship.priority_b
    if priority_a is not None and priority_b is not None:
        if priority_a == 1 and priority_b == 1:
            return settings.weight_mutual_friend
        if priority_a == 1 or priority_b == 1:
            return max(settings.weight_mutual_friend * 4 // 5, settings.weight_friend1)
        return max(settings.weight_mutual_friend * 7 // 10, settings.weight_friend2)
    priority = priority_a if priority_a is not None else priority_b
    return settings.weight_friend1 if priority == 1 else settings.weight_friend2


def _score_friend_relationships(
    students: list[Student],
    assignments: dict[str, str],
    settings: OptimizationSettings,
) -> tuple[int, list[str]]:
    penalty = 0
    unmet: list[str] = []
    for relationship in build_friend_relationships(students):
        if assignments.get(relationship.student_a.internal_id) == assignments.get(relationship.student_b.internal_id):
            continue
        weight = friend_relationship_weight(relationship, settings)
        penalty += weight
        unmet.append(
            "Freundespaar getrennt: "
            f"{relationship.student_a.display_label} nicht mit {relationship.student_b.display_label} "
            f"({weight} Punkte)"
        )
    return penalty, unmet


def _score_friend_isolation(
    students: list[Student],
    assignments: dict[str, str],
) -> tuple[int, list[str]]:
    isolated = 0
    messages: list[str] = []
    for student in students:
        friends = [
            friend
            for friend in (
                resolve_student_ref(students, student.friend1),
                resolve_student_ref(students, student.friend2),
            )
            if friend
        ]
        if not friends:
            continue
        if any(assignments.get(student.internal_id) == assignments.get(friend.internal_id) for friend in friends):
            continue
        isolated += 1
        messages.append(f"Kein Wunschfreund in Klasse: {student.display_label}")
    return isolated, messages


def _friend_profile_conflict_counts(students: list[Student]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for student in students:
        for label, friend_ref in (("Freund 1", student.friend1), ("Freund 2", student.friend2)):
            friend = resolve_student_ref(students, friend_ref)
            if not friend:
                continue
            if _is_language_conflict(student, friend):
                counts[f"{label} F/L-Konflikt"] += 1
            if _is_music_focus_conflict(student, friend):
                counts[f"{label} B/S/G-Konflikt"] += 1

    for relationship in build_friend_relationships(students):
        if relationship.priority_a is None or relationship.priority_b is None:
            continue
        language_conflict = _is_language_conflict(relationship.student_a, relationship.student_b)
        music_conflict = _is_music_focus_conflict(relationship.student_a, relationship.student_b)
        if language_conflict:
            counts["Gegenseitig F/L-Konflikt"] += 1
        if music_conflict:
            counts["Gegenseitig B/S/G-Konflikt"] += 1
        if language_conflict and music_conflict:
            counts["Gegenseitig Sprache und Musik konfliktig"] += 1
    return dict(sorted(counts.items()))


def _is_language_conflict(student_a: Student, student_b: Student) -> bool:
    languages = {student_a.second_language, student_b.second_language}
    return languages == {"F", "L"}


def _is_music_focus_conflict(student_a: Student, student_b: Student) -> bool:
    focus_profiles = {"B", "S", "G"}
    return (
        student_a.music_profile in focus_profiles
        and student_b.music_profile in focus_profiles
        and student_a.music_profile != student_b.music_profile
    )


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


def support_upper_bound(total_support: int, class_count: int) -> int:
    if total_support <= 0 or class_count <= 0:
        return 0
    average = total_support / class_count
    if average.is_integer():
        return int(average) + 1
    return math.ceil(average) + 1


def _support_distribution_penalty_units(class_reports: list[ClassReport]) -> int:
    if not class_reports:
        return 0
    upper_bound = support_upper_bound(
        sum(report.support_count for report in class_reports),
        len(class_reports),
    )
    return sum(max(0, report.support_count - upper_bound) ** 2 for report in class_reports)


def _gender_balance_penalty_units(class_reports: list[ClassReport]) -> int:
    if not class_reports:
        return 0
    female_total = sum(report.gender_counts.get("w", 0) for report in class_reports)
    class_count = len(class_reports)
    tolerance_scaled = 2 * class_count
    penalty = 0
    for report in class_reports:
        abs_deviation_scaled = abs(report.gender_counts.get("w", 0) * class_count - female_total)
        if abs_deviation_scaled < tolerance_scaled + class_count:
            continue
        excess_children = abs_deviation_scaled // class_count - 2
        penalty += excess_children**2
    return penalty


def _concentration_penalty_units(
    class_reports: list[ClassReport],
    getter: Callable[[ClassReport], dict[str, int]],
    *,
    free_count: int,
) -> int:
    penalty = 0
    for report in class_reports:
        counts = getter(report)
        for key, count in counts.items():
            if key == "leer":
                continue
            penalty += max(0, count - free_count) ** 2
    return penalty


def _class_size_policy_score(class_reports: list[ClassReport], class_by_id: dict[str, ClassConfig]) -> int:
    score = 0
    for report in class_reports:
        policy = getattr(class_by_id[report.class_id], "size_policy", None)
        if not policy or policy.soft_weight <= 0:
            continue
        under = max(0, policy.comfort_min - report.size)
        over = max(0, report.size - policy.comfort_max)
        score += policy.soft_weight * (under * under + over * over)
    return score


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
    if rule.type == "ALLOW_CLASSES" and rule.class_ids:
        class_id = assignments.get(student_a.internal_id)
        if class_id not in set(rule.class_ids):
            allowed = ", ".join(rule.class_ids)
            hard_violations.append(f"{student_a.display_label}: erlaubte Klassen {allowed} verletzt")
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

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from klassenbildung.core.models import (
    ClassConfig,
    OptimizationSettings,
    ProfileSlackReport,
    Student,
)
from klassenbildung.optimization.scoring import (
    build_friend_relationships,
    resolve_student_ref,
    score_solution,
)
from klassenbildung.presentation.result_view_model import CandidateSummary
from klassenbildung.services.candidate_selection import review_candidates
from klassenbildung.services.manual_rules import NoteReviewStatus
from klassenbildung.validation.finality import (
    GENDER_TARGET_MIN_CLASS_SIZE,
    GENDER_TARGET_MIN,
    GENDER_TARGET_MAX,
    MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS,
    MAX_PRIMARY_SCHOOL_PER_CLASS,
    MAX_SUPPORT_PER_CLASS,
)


ProfileType = Literal["language", "music"]


class ReviewWarningLevel(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class ReviewReadiness(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StudentRiskRow:
    student_id: str
    display_name: str
    class_id: str
    friend1: str | None
    friend1_class: str | None
    friend2: str | None
    friend2_class: str | None
    has_manual_note: bool
    note_text: str | None


@dataclass(frozen=True)
class FriendshipRiskRow:
    student_a_id: str
    student_a_name: str
    student_a_class: str
    student_b_id: str
    student_b_name: str
    student_b_class: str
    priority_a: int | None
    priority_b: int | None
    has_manual_note: bool
    note_text: str | None


@dataclass(frozen=True)
class StudentNoteRow:
    student_id: str
    display_name: str
    class_id: str
    note_text: str
    review_status: NoteReviewStatus = NoteReviewStatus.UNREVIEWED
    automatically_evaluated: bool = False


@dataclass(frozen=True)
class MixedClassRow:
    class_id: str
    profile_type: ProfileType
    majority_label: str
    minority_label: str
    minority_count: int
    minority_students: list[str]


@dataclass(frozen=True)
class ClassLoadRow:
    class_id: str
    size: int
    support_count: int
    male_count: int
    female_count: int
    largest_school_count: int
    largest_primary_class_count: int


@dataclass(frozen=True)
class ReviewWarning:
    level: ReviewWarningLevel
    message: str


@dataclass(frozen=True)
class CandidateReviewModel:
    summary: CandidateSummary
    readiness: ReviewReadiness
    students_without_wishfriend: list[StudentRiskRow]
    separated_mutual_friendships: list[FriendshipRiskRow]
    students_with_manual_notes: list[StudentNoteRow]
    fl_mixed_classes: list[MixedClassRow]
    music_mixed_classes: list[MixedClassRow]
    class_load_rows: list[ClassLoadRow]
    warnings: list[ReviewWarning]

    @property
    def blocker_count(self) -> int:
        return sum(1 for warning in self.warnings if warning.level == ReviewWarningLevel.BLOCKER)

    @property
    def warning_count(self) -> int:
        return sum(1 for warning in self.warnings if warning.level == ReviewWarningLevel.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for warning in self.warnings if warning.level == ReviewWarningLevel.INFO)

    def visible_text(self) -> str:
        parts = [
            self.summary.key,
            review_readiness_text(self.readiness),
            str(self.summary.without_wishfriend),
            f"{self.summary.friend1_satisfied}/{self.summary.friend1_total}",
            f"{self.summary.mutual_satisfied}/{self.summary.mutual_total}",
            f"{self.summary.friend2_satisfied}/{self.summary.friend2_total}",
            str(self.summary.fl_mixed_actual),
            str(self.summary.music_mixed_actual),
            str(self.summary.fl_minority),
            str(self.summary.music_minority),
        ]
        for row in self.students_without_wishfriend:
            parts.extend([row.display_name, row.class_id, row.note_text or ""])
        for row in self.separated_mutual_friendships:
            parts.extend([row.student_a_name, row.student_b_name, row.note_text or ""])
        for row in self.students_with_manual_notes:
            parts.extend([row.display_name, row.note_text, row.review_status.value])
        for row in self.fl_mixed_classes + self.music_mixed_classes:
            parts.extend([row.class_id, row.majority_label, row.minority_label, *row.minority_students])
        for row in self.class_load_rows:
            parts.extend([row.class_id, str(row.size), str(row.support_count)])
        for warning in self.warnings:
            parts.append(warning.message)
        return "\n".join(parts)


@dataclass(frozen=True)
class ReviewCandidateGroups:
    reviewable: list[CandidateReviewModel]
    blocked: list[CandidateReviewModel]


def review_readiness_text(readiness: ReviewReadiness) -> str:
    return {
        ReviewReadiness.READY_FOR_REVIEW: "Bereit zur pädagogischen Prüfung",
        ReviewReadiness.NEEDS_ATTENTION: "Prüfen, enthält Warnungen",
        ReviewReadiness.BLOCKED: "Nicht verwendbar, Blocker vorhanden",
    }[readiness]


def review_warning_count_text(review: CandidateReviewModel) -> str:
    return f"{review.blocker_count} Blocker · {review.warning_count} Warnungen · {review.info_count} Hinweise"


def review_warning_messages(review: CandidateReviewModel, level: ReviewWarningLevel) -> list[str]:
    return [warning.message for warning in review.warnings if warning.level == level]


def group_reviews_by_readiness(reviews: list[CandidateReviewModel]) -> ReviewCandidateGroups:
    return ReviewCandidateGroups(
        reviewable=[review for review in reviews if review.readiness != ReviewReadiness.BLOCKED],
        blocked=[review for review in reviews if review.readiness == ReviewReadiness.BLOCKED],
    )


def build_candidate_review_model(
    summary: CandidateSummary,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    note_review_status_by_student: dict[str, NoteReviewStatus] | None = None,
) -> CandidateReviewModel:
    score = score_solution(students, summary.assignments, settings, class_configs)
    students_by_class = _students_by_class(students, class_configs, summary.assignments)
    fl_rows = _mixed_class_rows(students_by_class, "language")
    music_rows = _mixed_class_rows(students_by_class, "music")
    isolated_rows = _students_without_wishfriend(students, summary.assignments)
    mutual_rows = _separated_mutual_friendships(students, summary.assignments)
    note_rows = _students_with_manual_notes(
        students,
        summary.assignments,
        note_review_status_by_student or {},
    )
    class_load_rows = [
        ClassLoadRow(
            class_id=report.class_id,
            size=report.size,
            support_count=report.support_count,
            male_count=report.gender_counts.get("m", 0),
            female_count=report.gender_counts.get("w", 0),
            largest_school_count=_largest_count(report.school_counts),
            largest_primary_class_count=_largest_count(report.primary_class_counts),
        )
        for report in score.class_reports
    ]
    warnings = _review_warnings(
        summary,
        score,
        class_configs,
        isolated_rows,
        mutual_rows,
        note_rows,
        class_load_rows,
    )
    return CandidateReviewModel(
        summary=summary,
        readiness=_review_readiness(summary, warnings),
        students_without_wishfriend=isolated_rows,
        separated_mutual_friendships=mutual_rows,
        students_with_manual_notes=note_rows,
        fl_mixed_classes=fl_rows,
        music_mixed_classes=music_rows,
        class_load_rows=class_load_rows,
        warnings=warnings,
    )


def build_candidate_review_models(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[CandidateReviewModel]:
    return [
        build_candidate_review_model(summary, students, class_configs, settings)
        for summary in review_candidates(solver_result, len(students))
        if summary.assignments
    ]


def candidate_review_to_record(review: CandidateReviewModel) -> dict[str, object]:
    return {
        "key": review.summary.key,
        "name": review.summary.name,
        "readiness": review.readiness.value,
        "readiness_text": review_readiness_text(review.readiness),
        "without_wishfriend": len(review.students_without_wishfriend),
        "separated_mutual_friendships": len(review.separated_mutual_friendships),
        "students_with_manual_notes": len(review.students_with_manual_notes),
        "unreviewed_notes": sum(
            1 for row in review.students_with_manual_notes if row.review_status == NoteReviewStatus.UNREVIEWED
        ),
        "kept_note_hints": sum(
            1 for row in review.students_with_manual_notes if row.review_status == NoteReviewStatus.KEPT_AS_NOTE
        ),
        "converted_note_rules": sum(
            1 for row in review.students_with_manual_notes if row.review_status == NoteReviewStatus.CONVERTED_TO_RULE
        ),
        "fl_minority": sum(row.minority_count for row in review.fl_mixed_classes),
        "music_minority": sum(row.minority_count for row in review.music_mixed_classes),
        "class_load_rows": len(review.class_load_rows),
        "blockers": review.blocker_count,
        "warnings": review.warning_count,
        "infos": review.info_count,
    }


def candidate_review_records(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[dict[str, object]]:
    return [
        candidate_review_to_record(review)
        for review in build_candidate_review_models(solver_result, students, class_configs, settings)
    ]


def candidate_review_models_from_reports(
    reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[CandidateReviewModel]:
    solver_result = type("SolverResultLike", (), {"profile_slack_reports": reports})()
    return build_candidate_review_models(solver_result, students, class_configs, settings)


def _students_without_wishfriend(
    students: list[Student],
    assignments: dict[str, str],
) -> list[StudentRiskRow]:
    rows = []
    for student in students:
        friend1 = resolve_student_ref(students, student.friend1)
        friend2 = resolve_student_ref(students, student.friend2)
        friends = [friend for friend in (friend1, friend2) if friend]
        if not friends:
            continue
        class_id = assignments.get(student.internal_id) or "-"
        if any(class_id == assignments.get(friend.internal_id) for friend in friends):
            continue
        rows.append(
            StudentRiskRow(
                student_id=student.internal_id,
                display_name=student.display_label,
                class_id=class_id,
                friend1=friend1.display_label if friend1 else None,
                friend1_class=assignments.get(friend1.internal_id) if friend1 else None,
                friend2=friend2.display_label if friend2 else None,
                friend2_class=assignments.get(friend2.internal_id) if friend2 else None,
                has_manual_note=student_has_manual_note(student),
                note_text=student_effective_note_text(student),
            )
        )
    return rows


def _separated_mutual_friendships(
    students: list[Student],
    assignments: dict[str, str],
) -> list[FriendshipRiskRow]:
    rows = []
    for relationship in build_friend_relationships(students):
        if relationship.priority_a is None or relationship.priority_b is None:
            continue
        class_a = assignments.get(relationship.student_a.internal_id) or "-"
        class_b = assignments.get(relationship.student_b.internal_id) or "-"
        if class_a == class_b:
            continue
        note_text = _pair_note_text(relationship.student_a, relationship.student_b)
        rows.append(
            FriendshipRiskRow(
                student_a_id=relationship.student_a.internal_id,
                student_a_name=relationship.student_a.display_label,
                student_a_class=class_a,
                student_b_id=relationship.student_b.internal_id,
                student_b_name=relationship.student_b.display_label,
                student_b_class=class_b,
                priority_a=relationship.priority_a,
                priority_b=relationship.priority_b,
                has_manual_note=bool(note_text),
                note_text=note_text or None,
            )
        )
    return rows


def _students_with_manual_notes(
    students: list[Student],
    assignments: dict[str, str],
    note_review_status_by_student: dict[str, NoteReviewStatus],
) -> list[StudentNoteRow]:
    return [
        StudentNoteRow(
            student_id=student.internal_id,
            display_name=student.display_label,
            class_id=assignments.get(student.internal_id) or "-",
            note_text=student_effective_note_text(student) or "",
            review_status=note_review_status_by_student.get(student.internal_id, NoteReviewStatus.UNREVIEWED),
        )
        for student in sorted(students, key=lambda item: (item.sort_name, item.row_number))
        if student_has_manual_note(student)
    ]


def _students_by_class(
    students: list[Student],
    class_configs: list[ClassConfig],
    assignments: dict[str, str],
) -> dict[str, list[Student]]:
    by_class = {config.class_id: [] for config in class_configs}
    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id in by_class:
            by_class[class_id].append(student)
    return by_class


def _mixed_class_rows(
    students_by_class: dict[str, list[Student]],
    profile_type: ProfileType,
) -> list[MixedClassRow]:
    rows = []
    for class_id, class_students in students_by_class.items():
        if profile_type == "language":
            counts = _counts(class_students, lambda student: student.second_language)
            labels = ["F", "L"]
        else:
            counts = _counts(class_students, lambda student: student.music_profile)
            labels = ["B", "S", "G"]
        present = {label: counts.get(label, 0) for label in labels if counts.get(label, 0) > 0}
        if len(present) <= 1:
            continue
        majority_label = sorted(present.items(), key=lambda item: (-item[1], item[0]))[0][0]
        minority_labels = [label for label in labels if label in present and label != majority_label]
        minority_students = [
            _student_label_with_note(student)
            for student in sorted(class_students, key=lambda item: (item.sort_name, item.row_number))
            if (
                student.second_language if profile_type == "language" else student.music_profile
            )
            in minority_labels
        ]
        rows.append(
            MixedClassRow(
                class_id=class_id,
                profile_type=profile_type,
                majority_label=majority_label,
                minority_label=", ".join(minority_labels),
                minority_count=len(minority_students),
                minority_students=minority_students,
            )
        )
    return rows


def _review_warnings(
    summary: CandidateSummary,
    score,
    class_configs: list[ClassConfig],
    isolated_rows: list[StudentRiskRow],
    mutual_rows: list[FriendshipRiskRow],
    note_rows: list[StudentNoteRow],
    class_load_rows: list[ClassLoadRow],
) -> list[ReviewWarning]:
    warnings = []
    for violation in score.hard_violations:
        warnings.append(ReviewWarning(ReviewWarningLevel.BLOCKER, violation))
    if summary.candidate_for_review and summary.key != "A":
        warnings.append(ReviewWarning(ReviewWarningLevel.INFO, "Profil-Lockerung nötig."))
    if summary.music_minority >= 30:
        warnings.append(ReviewWarning(ReviewWarningLevel.WARNING, f"Hohe Musik-Minderheit: {summary.music_minority}."))
    if summary.fl_minority >= 20:
        warnings.append(ReviewWarning(ReviewWarningLevel.WARNING, f"Hohe F/L-Minderheit: {summary.fl_minority}."))
    if mutual_rows:
        warnings.append(
            ReviewWarning(
                ReviewWarningLevel.WARNING,
                f"{len(mutual_rows)} getrennte gegenseitige Freundschaften.",
            )
        )
    isolated_with_note = sum(1 for row in isolated_rows if row.has_manual_note)
    if isolated_with_note:
        warnings.append(
            ReviewWarning(
                ReviewWarningLevel.WARNING,
                f"{isolated_with_note} Kinder ohne Wunschfreund haben eine manuelle Notiz.",
            )
        )
    mutual_with_note = sum(1 for row in mutual_rows if row.has_manual_note)
    if mutual_with_note:
        warnings.append(
            ReviewWarning(
                ReviewWarningLevel.WARNING,
                f"{mutual_with_note} getrennte gegenseitige Freundschaften enthalten eine manuelle Notiz.",
            )
        )
    unreviewed_note_rows = [
        row for row in note_rows if row.review_status == NoteReviewStatus.UNREVIEWED
    ]
    if unreviewed_note_rows:
        warnings.append(
            ReviewWarning(
                ReviewWarningLevel.BLOCKER,
                f"{len(unreviewed_note_rows)} ungeprüfte Notizen. Vor einer Freigabe als Regel oder Hinweis entscheiden.",
            )
        )
    elif note_rows:
        warnings.append(
            ReviewWarning(
                ReviewWarningLevel.INFO,
                f"{len(note_rows)} manuelle Notizen sind als Regel oder Hinweis entschieden.",
            )
        )
    for row in class_load_rows:
        if row.largest_school_count > MAX_PRIMARY_SCHOOL_PER_CLASS:
            warnings.append(
                ReviewWarning(
                    ReviewWarningLevel.BLOCKER,
                    f"{row.class_id}: Grundschulballung {row.largest_school_count}, erlaubt höchstens {MAX_PRIMARY_SCHOOL_PER_CLASS}.",
                )
            )
        if row.largest_primary_class_count > MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS:
            warnings.append(
                ReviewWarning(
                    ReviewWarningLevel.BLOCKER,
                    f"{row.class_id}: Grundschule/alte Klasse {row.largest_primary_class_count}, erlaubt höchstens {MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS}.",
                )
            )
        if row.support_count > MAX_SUPPORT_PER_CLASS:
            warnings.append(
                ReviewWarning(
                    ReviewWarningLevel.BLOCKER,
                    f"{row.class_id}: R-/Unterstützungsballung {row.support_count}, erlaubt höchstens {MAX_SUPPORT_PER_CLASS}.",
                )
            )
        elif row.support_count >= 3:
            warnings.append(
                ReviewWarning(
                    ReviewWarningLevel.WARNING,
                    f"{row.class_id}: hohe R-/Unterstützungsballung ({row.support_count}).",
                )
            )
        if row.size >= GENDER_TARGET_MIN_CLASS_SIZE:
            gender_issues = [
                f"m={row.male_count}"
                if row.male_count < GENDER_TARGET_MIN or row.male_count > GENDER_TARGET_MAX
                else "",
                f"w={row.female_count}"
                if row.female_count < GENDER_TARGET_MIN or row.female_count > GENDER_TARGET_MAX
                else "",
            ]
            gender_issues = [issue for issue in gender_issues if issue]
            if gender_issues:
                warnings.append(
                    ReviewWarning(
                        ReviewWarningLevel.WARNING,
                        f"{row.class_id}: Geschlecht außerhalb Zielzone {GENDER_TARGET_MIN}-{GENDER_TARGET_MAX}: "
                        + ", ".join(gender_issues)
                        + ".",
                    )
                )
    config_by_id = {config.class_id: config for config in class_configs}
    for row in class_load_rows:
        policy = getattr(config_by_id.get(row.class_id), "size_policy", None)
        if not policy:
            continue
        if policy.hard_min <= row.size <= policy.hard_max and (
            row.size < policy.comfort_min or row.size > policy.comfort_max
        ):
            warnings.append(
                ReviewWarning(
                    ReviewWarningLevel.WARNING,
                    f"{row.class_id}: Klassengröße außerhalb des Komfortbereichs ({row.size}).",
                )
            )
    if not summary.gap_reliable:
        warnings.append(ReviewWarning(ReviewWarningLevel.INFO, "Gültiger Prüfkandidat, aber nicht bewiesen optimal."))
    return warnings


def _review_readiness(summary: CandidateSummary, warnings: list[ReviewWarning]) -> ReviewReadiness:
    if any(warning.level == ReviewWarningLevel.BLOCKER for warning in warnings):
        return ReviewReadiness.BLOCKED
    if not summary.social_threshold_met or not summary.candidate_for_review:
        return ReviewReadiness.NEEDS_ATTENTION
    if any(warning.level == ReviewWarningLevel.WARNING for warning in warnings):
        return ReviewReadiness.NEEDS_ATTENTION
    return ReviewReadiness.READY_FOR_REVIEW


def _counts(students: list[Student], getter) -> dict[str, int]:
    counts: dict[str, int] = {}
    for student in students:
        key = getter(student) or "leer"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _largest_count(counts: dict[str, int]) -> int:
    values = [count for key, count in counts.items() if key != "leer"]
    return max(values, default=0)


def _pair_note_text(student_a: Student, student_b: Student) -> str:
    notes = []
    if student_has_manual_note(student_a):
        notes.append(f"{student_a.display_label}: {student_effective_note_text(student_a)}")
    if student_has_manual_note(student_b):
        notes.append(f"{student_b.display_label}: {student_effective_note_text(student_b)}")
    return " | ".join(notes)


def _student_label_with_note(student: Student) -> str:
    suffix = " 📝" if student_has_manual_note(student) else ""
    return f"{student.display_label}{suffix}"


def student_effective_note_text(student: object) -> str | None:
    note_text = getattr(student, "note_text", None)
    if note_text is not None:
        return note_text
    return getattr(student, "comment", None)


def student_has_manual_note(student: object) -> bool:
    note_text = student_effective_note_text(student)
    return bool(note_text and note_text.strip())

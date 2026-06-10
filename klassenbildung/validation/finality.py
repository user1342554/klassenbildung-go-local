from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Literal

from klassenbildung.core.constants import DEFAULT_DISTRIBUTION_LIMITS
from klassenbildung.core.models import (
    OptimizationSettings,
    ScoreReport,
    Student,
    ValidationMessage,
    student_has_manual_note,
)


FinalityLevel = Literal["BLOCKER", "WARNING", "INFO"]

MAX_PRIMARY_SCHOOL_PER_CLASS = DEFAULT_DISTRIBUTION_LIMITS["max_primary_school_per_class"]
MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS = DEFAULT_DISTRIBUTION_LIMITS["max_primary_school_class_per_class"]
GENDER_TARGET_MIN = DEFAULT_DISTRIBUTION_LIMITS["gender_target_min"]
GENDER_TARGET_MAX = DEFAULT_DISTRIBUTION_LIMITS["gender_target_max"]
GENDER_TARGET_MIN_CLASS_SIZE = DEFAULT_DISTRIBUTION_LIMITS["gender_target_min_class_size"]
MAX_SUPPORT_PER_CLASS = DEFAULT_DISTRIBUTION_LIMITS["max_support_per_class"]
WITHOUT_WISHFRIEND_WARNING = 45

DATA_BLOCKER_MESSAGES = {
    "Schülernummer fehlt.",
    "Schülernummer ist nicht numerisch.",
    "Schülernummer kommt mehrfach vor.",
    "Eignung ist leer oder ungewöhnlich.",
    "2. Fremdsprache ist leer oder unbekannt.",
    "Musikklasse ist leer oder unbekannt.",
    "Freundeswunsch 1 ist nicht zuordenbar.",
    "Freundeswunsch 2 ist nicht zuordenbar.",
    "Freundeswunsch 1 ist mehrdeutig.",
    "Freundeswunsch 2 ist mehrdeutig.",
    "Wert enthält führende oder abschließende Leerzeichen.",
}


@dataclass(frozen=True)
class FinalityFinding:
    level: FinalityLevel
    category: str
    message: str
    class_id: str | None = None


@dataclass(frozen=True)
class FinalityReport:
    data_blockers: list[ValidationMessage] = field(default_factory=list)
    unreviewed_notes: int = 0
    unresolved_notes: int = 0
    profile_violations: int = 0
    manual_rule_violations: int = 0
    hard_violations: int = 0
    findings: list[FinalityFinding] = field(default_factory=list)
    accepted_warning_ids: set[str] = field(default_factory=set)

    @property
    def class_blockers(self) -> list[FinalityFinding]:
        return [finding for finding in self.findings if finding.level == "BLOCKER"]

    @property
    def warnings(self) -> list[FinalityFinding]:
        return [finding for finding in self.findings if finding.level == "WARNING"]

    @property
    def undecided_warnings(self) -> list[FinalityFinding]:
        return [
            finding
            for finding in self.warnings
            if finding_id(finding) not in self.accepted_warning_ids
        ]

    @property
    def other_hard_violations(self) -> int:
        return max(0, self.hard_violations - self.profile_violations - self.manual_rule_violations)

    @property
    def has_blockers(self) -> bool:
        return bool(self.blocker_labels())

    def blocker_labels(self) -> list[str]:
        labels = []
        if self.profile_violations:
            labels.append(f"{self.profile_violations} Profilverletzungen")
        if self.manual_rule_violations:
            labels.append(f"{self.manual_rule_violations} verletzte manuelle Regeln")
        if self.other_hard_violations:
            labels.append(f"{self.other_hard_violations} sonstige harte Regelverletzungen")
        for category, count in _count_by_category(self.class_blockers).items():
            labels.append(f"{count} {category}")
        return labels

    def warning_labels(self) -> list[str]:
        labels = []
        for category, count in _count_by_category(self.warnings).items():
            labels.append(f"{count} {category}")
        return labels


def finality_report(
    students: list[Student],
    score_report: ScoreReport | None,
    validation_messages: list[ValidationMessage] | None,
    note_review_status_by_student: dict[str, object] | None,
    *,
    profile_violations: int = 0,
    manual_rule_violations: int = 0,
    settings: OptimizationSettings | None = None,
    accepted_warning_ids: set[str] | None = None,
) -> FinalityReport:
    hard_violations = len(score_report.hard_violations) if score_report else 0
    note_statuses = note_review_status_by_student or {}
    return FinalityReport(
        data_blockers=finality_data_blockers(validation_messages or []),
        unreviewed_notes=unreviewed_note_count(students, note_statuses),
        unresolved_notes=unresolved_note_count(students, note_statuses),
        profile_violations=profile_violations,
        manual_rule_violations=manual_rule_violations,
        hard_violations=hard_violations,
        findings=class_finality_findings(score_report, settings),
        accepted_warning_ids=set(accepted_warning_ids or set()),
    )


def finality_data_blockers(messages: list[ValidationMessage]) -> list[ValidationMessage]:
    return [
        message
        for message in messages
        if message.severity == "FEHLER" or message.message in DATA_BLOCKER_MESSAGES
    ]


def unreviewed_note_count(students: list[Student], note_review_status_by_student: dict[str, object]) -> int:
    return sum(
        1
        for student in students
        if student_has_manual_note(student)
        and _status_value(note_review_status_by_student.get(student.internal_id, "unreviewed")) == "unreviewed"
    )


def unresolved_note_count(students: list[Student], note_review_status_by_student: dict[str, object]) -> int:
    return sum(
        1
        for student in students
        if student_has_manual_note(student)
        and _status_value(note_review_status_by_student.get(student.internal_id, "unreviewed")) == "unresolved_blocker"
    )


def finding_id(finding: FinalityFinding) -> str:
    raw = f"{finding.level}|{finding.category}|{finding.class_id or ''}|{finding.message}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def class_finality_findings(
    score_report: ScoreReport | None,
    settings: OptimizationSettings | None = None,
) -> list[FinalityFinding]:
    if not score_report:
        return []
    limits = _distribution_limits(settings)
    findings: list[FinalityFinding] = []
    for report in score_report.class_reports:
        school_name, school_count = _largest_item(report.school_counts)
        if school_count > limits["max_primary_school_per_class"]:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "Grundschul-Ballungsblocker",
                    f"{report.class_id}: {school_count} Kinder aus {school_name}; erlaubt sind höchstens {limits['max_primary_school_per_class']}.",
                    report.class_id,
                )
            )

        primary_name, primary_count = _largest_item(report.primary_class_counts)
        if primary_count > limits["max_primary_school_class_per_class"]:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "Grundschulklassen-Ballungsblocker",
                    f"{report.class_id}: {primary_count} Kinder aus {primary_name}; erlaubt sind höchstens {limits['max_primary_school_class_per_class']}.",
                    report.class_id,
                )
            )

        if report.support_count > limits["max_support_per_class"]:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "R-Obergrenzenblocker",
                    f"{report.class_id}: {report.support_count} R-/Unterstützungsmarkierungen; erlaubt sind höchstens {limits['max_support_per_class']}.",
                    report.class_id,
                )
            )
        elif report.support_count >= 3:
            findings.append(
                FinalityFinding(
                    "WARNING",
                    "R-Warnung",
                    f"{report.class_id}: {report.support_count} R-/Unterstützungsmarkierungen.",
                    report.class_id,
                )
            )

        if report.size >= limits["gender_target_min_class_size"]:
            for label, count in (("m", report.gender_counts.get("m", 0)), ("w", report.gender_counts.get("w", 0))):
                if count < limits["gender_target_min"] or count > limits["gender_target_max"]:
                    findings.append(
                        FinalityFinding(
                            "WARNING",
                            "Geschlechter-Zielzonenwarnung",
                            f"{report.class_id}: {label}={count}, Zielzone {limits['gender_target_min']}-{limits['gender_target_max']}; pädagogische Begründung erforderlich.",
                            report.class_id,
                        )
                    )
    if score_report.isolated_friend_request_count > WITHOUT_WISHFRIEND_WARNING:
        findings.append(
            FinalityFinding(
                "WARNING",
                "Freundschaftswarnung",
                f"{score_report.isolated_friend_request_count} Kinder haben keinen Wunschfreund in der Klasse; Ziel ist unter {WITHOUT_WISHFRIEND_WARNING}.",
            )
        )
    return findings


def gender_target_zone_text(settings: OptimizationSettings | None = None) -> str:
    limits = _distribution_limits(settings)
    return f"{limits['gender_target_min']}-{limits['gender_target_max']}"


def gender_target_status(
    size: int,
    male_count: int,
    female_count: int,
    settings: OptimizationSettings | None = None,
) -> str:
    limits = _distribution_limits(settings)
    if size < limits["gender_target_min_class_size"]:
        return "nicht bewertet bei kleinen Klassen"
    issues = []
    if male_count < limits["gender_target_min"] or male_count > limits["gender_target_max"]:
        issues.append(f"m={male_count}")
    if female_count < limits["gender_target_min"] or female_count > limits["gender_target_max"]:
        issues.append(f"w={female_count}")
    if not issues:
        return "im Zielbereich"
    return "außerhalb Zielzone, Begründung erforderlich: " + ", ".join(issues)


def _distribution_limits(settings: OptimizationSettings | None) -> dict[str, int]:
    return {
        key: int(getattr(settings, key, default)) if settings is not None else default
        for key, default in DEFAULT_DISTRIBUTION_LIMITS.items()
    }


def _largest_item(counts: dict[str, int]) -> tuple[str, int]:
    relevant = [(key, count) for key, count in counts.items() if key != "leer"]
    if not relevant:
        return "-", 0
    return max(relevant, key=lambda item: item[1])


def _status_value(status: object) -> str:
    return getattr(status, "value", str(status))


def _count_by_category(findings: list[FinalityFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return counts

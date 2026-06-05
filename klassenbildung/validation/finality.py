from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from klassenbildung.core.models import ScoreReport, Student, ValidationMessage, student_has_manual_note


FinalityLevel = Literal["BLOCKER", "WARNING", "INFO"]

MAX_PRIMARY_SCHOOL_PER_CLASS = 10
MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS = 6
GENDER_TARGET_MIN = 12
GENDER_TARGET_MAX = 18
GENDER_TARGET_MIN_CLASS_SIZE = 24
MAX_SUPPORT_PER_CLASS = 4
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
    profile_violations: int = 0
    manual_rule_violations: int = 0
    hard_violations: int = 0
    findings: list[FinalityFinding] = field(default_factory=list)

    @property
    def class_blockers(self) -> list[FinalityFinding]:
        return [finding for finding in self.findings if finding.level == "BLOCKER"]

    @property
    def warnings(self) -> list[FinalityFinding]:
        return [finding for finding in self.findings if finding.level == "WARNING"]

    @property
    def other_hard_violations(self) -> int:
        return max(0, self.hard_violations - self.profile_violations - self.manual_rule_violations)

    @property
    def has_blockers(self) -> bool:
        return bool(self.blocker_labels())

    def blocker_labels(self) -> list[str]:
        labels = []
        if self.data_blockers:
            labels.append(f"{len(self.data_blockers)} Datenblocker")
        if self.unreviewed_notes:
            labels.append(f"{self.unreviewed_notes} ungeprüfte Notizen")
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
) -> FinalityReport:
    hard_violations = len(score_report.hard_violations) if score_report else 0
    return FinalityReport(
        data_blockers=finality_data_blockers(validation_messages or []),
        unreviewed_notes=unreviewed_note_count(students, note_review_status_by_student or {}),
        profile_violations=profile_violations,
        manual_rule_violations=manual_rule_violations,
        hard_violations=hard_violations,
        findings=class_finality_findings(score_report),
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


def class_finality_findings(score_report: ScoreReport | None) -> list[FinalityFinding]:
    if not score_report:
        return []
    findings: list[FinalityFinding] = []
    for report in score_report.class_reports:
        school_name, school_count = _largest_item(report.school_counts)
        if school_count > MAX_PRIMARY_SCHOOL_PER_CLASS:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "Grundschul-Ballungsblocker",
                    f"{report.class_id}: {school_count} Kinder aus {school_name}; erlaubt sind höchstens {MAX_PRIMARY_SCHOOL_PER_CLASS}.",
                    report.class_id,
                )
            )

        primary_name, primary_count = _largest_item(report.primary_class_counts)
        if primary_count > MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "Grundschulklassen-Ballungsblocker",
                    f"{report.class_id}: {primary_count} Kinder aus {primary_name}; erlaubt sind höchstens {MAX_PRIMARY_SCHOOL_CLASS_PER_CLASS}.",
                    report.class_id,
                )
            )

        if report.support_count > MAX_SUPPORT_PER_CLASS:
            findings.append(
                FinalityFinding(
                    "BLOCKER",
                    "R-Obergrenzenblocker",
                    f"{report.class_id}: {report.support_count} R-/Unterstützungsmarkierungen; erlaubt sind höchstens {MAX_SUPPORT_PER_CLASS}.",
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

        if report.size >= GENDER_TARGET_MIN_CLASS_SIZE:
            for label, count in (("m", report.gender_counts.get("m", 0)), ("w", report.gender_counts.get("w", 0))):
                if count < GENDER_TARGET_MIN or count > GENDER_TARGET_MAX:
                    findings.append(
                        FinalityFinding(
                            "WARNING",
                            "Geschlechter-Zielzonenwarnung",
                            f"{report.class_id}: {label}={count}, Zielzone {GENDER_TARGET_MIN}-{GENDER_TARGET_MAX}.",
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


def gender_target_zone_text() -> str:
    return f"{GENDER_TARGET_MIN}-{GENDER_TARGET_MAX}"


def gender_target_status(size: int, male_count: int, female_count: int) -> str:
    if size < GENDER_TARGET_MIN_CLASS_SIZE:
        return "nicht bewertet bei kleinen Klassen"
    issues = []
    if male_count < GENDER_TARGET_MIN or male_count > GENDER_TARGET_MAX:
        issues.append(f"m={male_count}")
    if female_count < GENDER_TARGET_MIN or female_count > GENDER_TARGET_MAX:
        issues.append(f"w={female_count}")
    if not issues:
        return "im Zielbereich"
    return "außerhalb Zielzone: " + ", ".join(issues)


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

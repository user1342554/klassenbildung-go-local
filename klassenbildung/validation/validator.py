from __future__ import annotations

from collections import Counter

from klassenbildung.core.constants import (
    ALLOWED_ELIGIBILITY,
    ALLOWED_GENDERS,
    ALLOWED_LANGUAGES,
    ALLOWED_MUSIC_PROFILES,
)
from klassenbildung.core.models import (
    ClassConfig,
    ManualRule,
    OptimizationSettings,
    Student,
    ValidationMessage,
    ValidationResult,
)
from klassenbildung.optimization.scoring import resolve_student_ref
from klassenbildung.validation.warnings import primary_class_looks_irregular


def validate_students(
    students: list[Student],
    class_configs: list[ClassConfig] | None = None,
    settings: OptimizationSettings | None = None,
    manual_rules: list[ManualRule] | None = None,
    base_messages: list[ValidationMessage] | None = None,
) -> ValidationResult:
    messages = list(base_messages or [])
    class_configs = class_configs or []
    settings = settings or OptimizationSettings()
    manual_rules = manual_rules or []

    if not students:
        messages.append(ValidationMessage("FEHLER", "Keine Schüler erkannt."))
        return ValidationResult(messages)

    messages.extend(_validate_student_fields(students))
    messages.extend(_validate_manual_rules(students, manual_rules))

    if not class_configs:
        messages.append(ValidationMessage("FEHLER", "Keine Klassen konfiguriert."))
    else:
        messages.extend(_validate_hard_profile_feasibility(students, class_configs, settings))
        min_total = sum(config.size_min for config in class_configs)
        max_total = sum(config.size_max for config in class_configs)
        if len(students) < min_total:
            messages.append(
                ValidationMessage(
                    "FEHLER",
                    f"Zu wenige Schüler für die Mindestgrößen: {len(students)} Schüler, "
                    f"Mindestsumme {min_total}.",
                )
            )
        if len(students) > max_total:
            messages.append(
                ValidationMessage(
                    "FEHLER",
                    f"Zu viele Schüler für die Maximalgrößen: {len(students)} Schüler, "
                    f"Maximalsumme {max_total}.",
                )
            )

    return ValidationResult(messages)


def _validate_student_fields(students: list[Student]) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    nr_counts = Counter(student.nr for student in students if student.nr)

    for student in students:
        if not student.nr:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Schülernummer fehlt.",
                    student.row_number,
                    "Nr",
                    None,
                )
            )
        elif not student.nr.isdigit():
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Schülernummer ist nicht numerisch.",
                    student.row_number,
                    "Nr",
                    student.nr,
                )
            )
        elif nr_counts[student.nr] > 1:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Schülernummer kommt mehrfach vor.",
                    student.row_number,
                    "Nr",
                    student.nr,
                )
            )

        if not student.eligibility or student.eligibility not in ALLOWED_ELIGIBILITY:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Eignung ist leer oder ungewöhnlich.",
                    student.row_number,
                    "Eignung",
                    student.eligibility,
                )
            )
        if student.gender not in ALLOWED_GENDERS:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Geschlecht ist leer oder unbekannt.",
                    student.row_number,
                    "Geschlecht",
                    student.gender,
                )
            )
        if student.second_language not in ALLOWED_LANGUAGES:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "2. Fremdsprache ist leer oder unbekannt.",
                    student.row_number,
                    "2. Fremdsprache",
                    student.second_language,
                )
            )
        if student.music_profile not in ALLOWED_MUSIC_PROFILES:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Musikklasse ist leer oder unbekannt.",
                    student.row_number,
                    "Musikklasse",
                    student.music_profile,
                )
            )
        if primary_class_looks_irregular(student.primary_class):
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Grundschulklasse wirkt uneinheitlich geschrieben.",
                    student.row_number,
                    "Klasse",
                    student.primary_class,
                )
            )
        if student.comment:
            messages.append(
                ValidationMessage(
                    "WARNUNG",
                    "Bemerkung muss manuell geprüft werden.",
                    student.row_number,
                    "Bemerkung",
                    student.comment,
                )
            )
    return messages


def _validate_hard_profile_feasibility(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    for student in students:
        allowed = [
            config
            for config in class_configs
            if _student_allowed_by_hard_profiles(student, config, settings)
        ]
        if not allowed:
            messages.append(
                ValidationMessage(
                    "FEHLER",
                    "Harte Profilregeln lassen für diesen Schüler keine Klasse zu.",
                    student.row_number,
                    "Profil",
                    student.display_label,
                )
            )
    return messages


def _student_allowed_by_hard_profiles(
    student: Student,
    config: ClassConfig,
    settings: OptimizationSettings,
) -> bool:
    if settings.enforce_music_profile and config.music_allowed:
        if not student.music_profile or student.music_profile not in config.music_allowed:
            return False
    if settings.enforce_language_profile and config.languages_allowed:
        if not student.second_language or student.second_language not in config.languages_allowed:
            return False
    return True


def _validate_manual_rules(
    students: list[Student],
    manual_rules: list[ManualRule],
) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    for rule in manual_rules:
        if not resolve_student_ref(students, rule.student_a):
            messages.append(ValidationMessage("FEHLER", "Manuelle Regel verweist auf unbekannten Schüler."))
        if rule.student_b and not resolve_student_ref(students, rule.student_b):
            messages.append(ValidationMessage("FEHLER", "Manuelle Regel verweist auf unbekannten zweiten Schüler."))
        if rule.type == "FIX_CLASS" and not rule.class_id:
            messages.append(ValidationMessage("FEHLER", "Fixierungsregel hat keine Zielklasse."))
    return messages


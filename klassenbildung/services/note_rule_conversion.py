from __future__ import annotations

from dataclasses import dataclass

from klassenbildung.core.models import ManualRule, RuleType, Student, student_effective_note_text, student_has_manual_note
from klassenbildung.optimization.scoring import resolve_student_ref


class NoteRuleConversionError(ValueError):
    pass


@dataclass(frozen=True)
class NoteRuleConversionResult:
    student_id: str
    note_text: str
    rule: ManualRule | None
    kept_as_hint: bool = False


def convert_note_to_manual_rule(
    students: list[Student],
    student_id: str,
    rule_type: RuleType,
    *,
    selected_student_id: str | None = None,
    class_id: str | None = None,
    confirmed: bool = False,
) -> NoteRuleConversionResult:
    student = _student_with_note(students, student_id)
    if not confirmed:
        raise NoteRuleConversionError("Notiz-Umwandlung braucht eine ausdrückliche Bestätigung.")

    if rule_type in {"SEPARATE", "TOGETHER"}:
        if not selected_student_id:
            raise NoteRuleConversionError("Für diese Regel muss ein zweiter Schüler explizit ausgewählt werden.")
        other = resolve_student_ref(students, selected_student_id)
        if not other:
            raise NoteRuleConversionError("Der ausgewählte zweite Schüler wurde nicht gefunden.")
        if other.internal_id == student.internal_id:
            raise NoteRuleConversionError("Eine Paarregel braucht zwei unterschiedliche Schüler.")
        return NoteRuleConversionResult(
            student_id=student.internal_id,
            note_text=student_effective_note_text(student) or "",
            rule=ManualRule(rule_type, student.internal_id, other.internal_id),
        )

    if rule_type == "FIX_CLASS":
        if not class_id:
            raise NoteRuleConversionError("Für eine Klassenfixierung muss eine Zielklasse ausgewählt werden.")
        return NoteRuleConversionResult(
            student_id=student.internal_id,
            note_text=student_effective_note_text(student) or "",
            rule=ManualRule("FIX_CLASS", student.internal_id, class_id=class_id),
        )

    raise NoteRuleConversionError(f"Unbekannter Regeltyp: {rule_type}")


def keep_note_as_hint(
    students: list[Student],
    student_id: str,
    *,
    confirmed: bool = False,
) -> NoteRuleConversionResult:
    student = _student_with_note(students, student_id)
    if not confirmed:
        raise NoteRuleConversionError("Hinweis-Entscheidung braucht eine ausdrückliche Bestätigung.")
    return NoteRuleConversionResult(
        student_id=student.internal_id,
        note_text=student_effective_note_text(student) or "",
        rule=None,
        kept_as_hint=True,
    )


def _student_with_note(students: list[Student], student_id: str) -> Student:
    student = resolve_student_ref(students, student_id)
    if not student:
        raise NoteRuleConversionError("Der Schüler wurde nicht gefunden.")
    if not student_has_manual_note(student):
        raise NoteRuleConversionError("Dieser Schüler hat keine manuelle Notiz.")
    return student

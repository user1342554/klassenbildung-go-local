from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal

from klassenbildung.core.models import ManualRule
from klassenbildung.optimization.scoring import resolve_student_ref

if TYPE_CHECKING:
    from klassenbildung.core.models import Student


RuleType = Literal["FIX_CLASS", "SEPARATE", "TOGETHER"]


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
    available_class_ids: Iterable[str] | None = None,
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
            note_text=_student_effective_note_text(student) or "",
            rule=ManualRule(rule_type, student.internal_id, other.internal_id),
        )

    if rule_type == "FIX_CLASS":
        if not class_id:
            raise NoteRuleConversionError("Für eine Klassenfixierung muss eine Zielklasse ausgewählt werden.")
        if available_class_ids is not None and class_id not in set(available_class_ids):
            raise NoteRuleConversionError(f"Die Zielklasse {class_id} ist nicht bekannt.")
        return NoteRuleConversionResult(
            student_id=student.internal_id,
            note_text=_student_effective_note_text(student) or "",
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
        note_text=_student_effective_note_text(student) or "",
        rule=None,
        kept_as_hint=True,
    )


def _student_with_note(students: list[Student], student_id: str) -> Student:
    student = resolve_student_ref(students, student_id)
    if not student:
        raise NoteRuleConversionError("Der Schüler wurde nicht gefunden.")
    if not _student_has_manual_note(student):
        raise NoteRuleConversionError("Dieser Schüler hat keine manuelle Notiz.")
    return student


def _student_effective_note_text(student: object) -> str | None:
    note_text = getattr(student, "note_text", None)
    if note_text is not None:
        return note_text
    return getattr(student, "comment", None)


def _student_has_manual_note(student: object) -> bool:
    note_text = _student_effective_note_text(student)
    return bool(note_text and note_text.strip())

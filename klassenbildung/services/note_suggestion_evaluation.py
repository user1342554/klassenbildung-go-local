from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from klassenbildung.core.models import Student
from klassenbildung.optimization.scoring import resolve_student_ref
from klassenbildung.services.note_rule_conversion import NoteRuleSuggestion, suggest_note_rules


@dataclass(frozen=True)
class NoteSuggestionEvaluation:
    note_total_count: int = 0
    recognized_candidate_count: int = 0
    checkable_rule_count: int = 0
    fulfilled_rule_count: int = 0
    violated_rule_count: int = 0
    unresolved_risk_count: int = 0
    violated_labels: tuple[str, ...] = field(default_factory=tuple)
    fulfilled_labels: tuple[str, ...] = field(default_factory=tuple)
    unresolved_labels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_any_finding(self) -> bool:
        return bool(self.recognized_candidate_count or self.unresolved_risk_count)

    @property
    def recognized_rule_count(self) -> int:
        return self.checkable_rule_count


def evaluate_note_suggestions(
    students: list[Student],
    assignments: dict[str, str],
    *,
    available_class_ids: Iterable[str] | None = None,
    ignored_student_ids: Iterable[str] | None = None,
) -> NoteSuggestionEvaluation:
    ignored = set(ignored_student_ids or [])
    suggestions_by_student = suggest_note_rules(students, available_class_ids=available_class_ids)
    note_total = 0
    recognized = 0
    checkable = 0
    fulfilled = 0
    violated = 0
    unresolved = 0
    fulfilled_labels: list[str] = []
    violated_labels: list[str] = []
    unresolved_labels: list[str] = []

    for student in students:
        if student.internal_id in ignored:
            continue
        if student.has_manual_note:
            note_total += 1
        suggestions = suggestions_by_student.get(student.internal_id, [])
        if not suggestions and student.has_manual_note:
            unresolved += 1
            unresolved_labels.append(f"{student.display_label}: keine eindeutige Regel erkannt")
            continue

        for suggestion in suggestions:
            recognized += 1
            label = _suggestion_label(students, suggestion)
            if not suggestion.has_rule:
                unresolved += 1
                unresolved_labels.append(label)
                continue
            result = _suggestion_fulfilled(suggestion, assignments)
            if result is None:
                unresolved += 1
                unresolved_labels.append(label)
                continue
            checkable += 1
            if result:
                fulfilled += 1
                fulfilled_labels.append(label)
            else:
                violated += 1
                violated_labels.append(label)

    return NoteSuggestionEvaluation(
        note_total_count=note_total,
        recognized_candidate_count=recognized,
        checkable_rule_count=checkable,
        fulfilled_rule_count=fulfilled,
        violated_rule_count=violated,
        unresolved_risk_count=unresolved,
        violated_labels=tuple(violated_labels),
        fulfilled_labels=tuple(fulfilled_labels),
        unresolved_labels=tuple(unresolved_labels),
    )


def note_suggestion_sort_key(evaluation: NoteSuggestionEvaluation | None) -> tuple[int, int, int]:
    if evaluation is None:
        return (0, 0, 0)
    return (
        evaluation.violated_rule_count,
        -evaluation.fulfilled_rule_count,
        evaluation.unresolved_risk_count,
    )


def note_suggestion_summary_text(evaluation: NoteSuggestionEvaluation | None) -> str:
    if evaluation is None or not evaluation.has_any_finding:
        return "keine erkannten Notizvorschläge"
    return (
        f"{evaluation.fulfilled_rule_count}/{evaluation.checkable_rule_count} prüfbare Regelkandidaten erfüllt; "
        f"{evaluation.violated_rule_count} verletzt; "
        f"{evaluation.unresolved_risk_count} ungeklärte Risiken; "
        f"{evaluation.recognized_candidate_count} erkannte Hinweise aus {evaluation.note_total_count} Notizen"
    )


def _suggestion_fulfilled(
    suggestion: NoteRuleSuggestion,
    assignments: dict[str, str],
) -> bool | None:
    source_class = assignments.get(suggestion.student_id)
    if not source_class:
        return None
    if suggestion.rule_type == "FIX_CLASS":
        return source_class == suggestion.class_id
    if suggestion.rule_type == "ALLOW_CLASSES":
        return source_class in set(suggestion.class_ids)
    if suggestion.rule_type in {"SEPARATE", "TOGETHER"}:
        if not suggestion.selected_student_id:
            return None
        target_class = assignments.get(suggestion.selected_student_id)
        if not target_class:
            return None
        if suggestion.rule_type == "SEPARATE":
            return source_class != target_class
        return source_class == target_class
    return None


def _suggestion_label(students: list[Student], suggestion: NoteRuleSuggestion) -> str:
    student = resolve_student_ref(students, suggestion.student_id)
    prefix = f"{student.display_label}: " if student else ""
    if suggestion.rule_type == "FIX_CLASS":
        return f"{prefix}Klassenfixierung {suggestion.class_id or '-'}"
    if suggestion.rule_type == "ALLOW_CLASSES":
        return f"{prefix}erlaubte Klassen {', '.join(suggestion.class_ids) or '-'}"
    if suggestion.rule_type == "SEPARATE":
        return f"{prefix}Trennregel {_student_label(students, suggestion.selected_student_id)}"
    if suggestion.rule_type == "TOGETHER":
        return f"{prefix}Zusammen-Regel {_student_label(students, suggestion.selected_student_id)}"
    return f"{prefix}{suggestion.message or 'offene Notiz'}"


def _student_label(students: list[Student], student_id: str | None) -> str:
    if not student_id:
        return "-"
    student = resolve_student_ref(students, student_id)
    return student.display_label if student else student_id

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable, Literal

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, Student, ValidationMessage
from klassenbildung.optimization.scoring import resolve_student_ref
from klassenbildung.validation.validator import validate_students


ManualRuleSource = Literal["note", "manual"]


@dataclass(frozen=True)
class ManualRuleEntry:
    id: str
    rule: ManualRule
    source: ManualRuleSource
    active: bool = True
    note_student_id: str | None = None


def manual_rule_entries(raw_entries: Iterable[ManualRuleEntry | ManualRule]) -> list[ManualRuleEntry]:
    entries = []
    for item in raw_entries:
        if isinstance(item, ManualRuleEntry):
            entries.append(item)
        elif isinstance(item, ManualRule):
            entries.append(create_manual_rule_entry(item, source="manual"))
    return entries


def create_manual_rule_entry(
    rule: ManualRule,
    *,
    source: ManualRuleSource,
    active: bool = True,
    note_student_id: str | None = None,
) -> ManualRuleEntry:
    return ManualRuleEntry(
        id=_manual_rule_entry_id(rule, source, note_student_id),
        rule=rule,
        source=source,
        active=active,
        note_student_id=note_student_id,
    )


def add_manual_rule_entry(
    entries: list[ManualRuleEntry],
    rule: ManualRule,
    *,
    source: ManualRuleSource,
    note_student_id: str | None = None,
) -> tuple[list[ManualRuleEntry], bool]:
    new_entry = create_manual_rule_entry(rule, source=source, note_student_id=note_student_id)
    for entry in entries:
        if entry.id == new_entry.id:
            if entry.active:
                return entries, False
            return [new_entry if item.id == entry.id else item for item in entries], True
    return [*entries, new_entry], True


def active_manual_rules(entries: list[ManualRuleEntry]) -> list[ManualRule]:
    return [entry.rule for entry in entries if entry.active]


def update_manual_rule_entry(
    entries: list[ManualRuleEntry],
    entry_id: str,
    *,
    rule: ManualRule | None = None,
    active: bool | None = None,
) -> list[ManualRuleEntry]:
    updated = []
    for entry in entries:
        if entry.id != entry_id:
            updated.append(entry)
            continue
        updated.append(
            ManualRuleEntry(
                id=entry.id,
                rule=rule or entry.rule,
                source=entry.source,
                active=entry.active if active is None else active,
                note_student_id=entry.note_student_id,
            )
        )
    return updated


def delete_manual_rule_entry(entries: list[ManualRuleEntry], entry_id: str) -> list[ManualRuleEntry]:
    return [entry for entry in entries if entry.id != entry_id]


def validation_errors_for_new_rule(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    entries: list[ManualRuleEntry],
    rule: ManualRule,
) -> list[ValidationMessage]:
    trial_rules = [*active_manual_rules(entries), rule]
    validation = validate_students(students, class_configs, settings, manual_rules=trial_rules)
    return validation.errors


def validation_errors_for_entries(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    entries: list[ManualRuleEntry],
) -> list[ValidationMessage]:
    validation = validate_students(students, class_configs, settings, manual_rules=active_manual_rules(entries))
    return validation.errors


def manual_rule_entry_records(entries: list[ManualRuleEntry], students: list[Student]) -> list[dict[str, object]]:
    return [
        {
            "id": entry.id,
            "Typ": _rule_type_label(entry.rule.type),
            "Schüler": _student_label(students, entry.rule.student_a),
            "Ziel / Partner": _rule_target_label(entry.rule, students),
            "Quelle": "aus Notiz" if entry.source == "note" else "manuell",
            "Status": "aktiv" if entry.active else "deaktiviert",
        }
        for entry in entries
    ]


def _manual_rule_entry_id(rule: ManualRule, source: ManualRuleSource, note_student_id: str | None) -> str:
    raw = f"{source}|{note_student_id or ''}|{rule.type}|{rule.student_a}|{rule.student_b or ''}|{rule.class_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _rule_type_label(rule_type: str) -> str:
    return {
        "SEPARATE": "Trennen",
        "TOGETHER": "Zusammen",
        "FIX_CLASS": "Fixierung",
    }.get(rule_type, rule_type)


def _rule_target_label(rule: ManualRule, students: list[Student]) -> str:
    if rule.type == "FIX_CLASS":
        return rule.class_id or "-"
    return _student_label(students, rule.student_b)


def _student_label(students: list[Student], student_ref: str | None) -> str:
    if not student_ref:
        return "-"
    student = resolve_student_ref(students, student_ref)
    return student.display_label if student else student_ref

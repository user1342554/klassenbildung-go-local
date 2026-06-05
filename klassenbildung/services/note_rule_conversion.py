from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import TYPE_CHECKING, Iterable, Literal

from klassenbildung.core.models import ManualRule
from klassenbildung.core.normalization import normalize_class_id
from klassenbildung.optimization.scoring import resolve_student_ref

if TYPE_CHECKING:
    from klassenbildung.core.models import Student


RuleType = Literal["FIX_CLASS", "ALLOW_CLASSES", "SEPARATE", "TOGETHER"]


class NoteRuleConversionError(ValueError):
    pass


@dataclass(frozen=True)
class NoteRuleConversionResult:
    student_id: str
    note_text: str
    rule: ManualRule | None
    kept_as_hint: bool = False


@dataclass(frozen=True)
class NoteRuleSuggestion:
    student_id: str
    note_text: str
    rule_type: RuleType | None
    selected_student_id: str | None = None
    class_id: str | None = None
    class_ids: tuple[str, ...] = ()
    message: str = ""

    @property
    def has_rule(self) -> bool:
        return self.rule_type is not None


@dataclass(frozen=True)
class _StudentMentionMatch:
    student: Student
    fuzzy: bool = False


def convert_note_to_manual_rule(
    students: list[Student],
    student_id: str,
    rule_type: RuleType,
    *,
    selected_student_id: str | None = None,
    class_id: str | None = None,
    class_ids: Iterable[str] | None = None,
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

    if rule_type == "ALLOW_CLASSES":
        normalized_available = {
            normalized
            for normalized in (normalize_class_id(item) for item in (available_class_ids or []))
            if normalized
        }
        normalized_class_ids = tuple(
            dict.fromkeys(
                normalized
                for normalized in (normalize_class_id(item) for item in (class_ids or []))
                if normalized
            )
        )
        if not normalized_class_ids:
            raise NoteRuleConversionError("Für erlaubte Klassen muss mindestens eine Klasse ausgewählt werden.")
        if normalized_available and any(item not in normalized_available for item in normalized_class_ids):
            unknown = ", ".join(item for item in normalized_class_ids if item not in normalized_available)
            raise NoteRuleConversionError(f"Unbekannte erlaubte Klasse(n): {unknown}.")
        return NoteRuleConversionResult(
            student_id=student.internal_id,
            note_text=_student_effective_note_text(student) or "",
            rule=ManualRule("ALLOW_CLASSES", student.internal_id, class_ids=normalized_class_ids),
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


def suggest_note_rule_actions(
    students: list[Student],
    student_id: str,
    *,
    available_class_ids: Iterable[str] | None = None,
) -> list[NoteRuleSuggestion]:
    student = _student_with_note(students, student_id)
    note_text = _student_effective_note_text(student) or ""
    normalized_class_ids = {
        normalized
        for normalized in (normalize_class_id(class_id) for class_id in (available_class_ids or []))
        if normalized
    }
    suggestions: list[NoteRuleSuggestion] = []

    class_id = _suggested_fixed_class(note_text, normalized_class_ids)
    if class_id:
        suggestions.append(
            NoteRuleSuggestion(
                student_id=student.internal_id,
                note_text=note_text,
                rule_type="FIX_CLASS",
                class_id=class_id,
                message=f"Die Notiz klingt nach einer festen Zielklasse: {class_id}.",
            )
        )

    class_set = _suggested_class_set(note_text, normalized_class_ids)
    if class_set:
        suggestions.append(
            NoteRuleSuggestion(
                student_id=student.internal_id,
                note_text=note_text,
                rule_type="ALLOW_CLASSES",
                class_ids=class_set,
                message="Die Notiz klingt nach erlaubten Zielklassen: " + ", ".join(class_set) + ".",
            )
        )

    separate_match = _suggested_pair_target(students, student, note_text, mode="SEPARATE")
    if separate_match:
        separate_target = separate_match.student
        suggestions.append(
            NoteRuleSuggestion(
                student_id=student.internal_id,
                note_text=note_text,
                rule_type="SEPARATE",
                selected_student_id=separate_target.internal_id,
                message=_pair_suggestion_message("Trennregel", separate_match),
            )
        )
    elif _contains_unresolved_separation(note_text):
        suggestions.append(
            NoteRuleSuggestion(
                student_id=student.internal_id,
                note_text=note_text,
                rule_type=None,
                message=_unresolved_separation_message(students, student, note_text),
            )
        )

    together_match = _suggested_pair_target(students, student, note_text, mode="TOGETHER")
    if together_match:
        together_target = together_match.student
        suggestions.append(
            NoteRuleSuggestion(
                student_id=student.internal_id,
                note_text=note_text,
                rule_type="TOGETHER",
                selected_student_id=together_target.internal_id,
                message=_pair_suggestion_message("Zusammen-Regel", together_match),
            )
        )

    return suggestions


def suggest_note_rules(
    students: list[Student],
    *,
    available_class_ids: Iterable[str] | None = None,
) -> dict[str, list[NoteRuleSuggestion]]:
    return {
        student.internal_id: suggest_note_rule_actions(
            students,
            student.internal_id,
            available_class_ids=available_class_ids,
        )
        for student in students
        if _student_has_manual_note(student)
    }


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


def _suggested_fixed_class(note_text: str, available_class_ids: set[str]) -> str | None:
    if not available_class_ids:
        return None
    normalized_text = note_text.casefold()
    if not re.search(r"\b(nur|moeglich|möglich|ausschliesslich|ausschließlich|fix|fest)\b", normalized_text):
        return None
    matches = [
        class_id
        for class_id in (
            normalize_class_id(match.group(0))
            for match in re.finditer(r"\b\d{1,2}\s*[a-zA-Z]\b", note_text)
        )
        if class_id in available_class_ids
    ]
    unique_matches = sorted(set(matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def _suggested_class_set(note_text: str, available_class_ids: set[str]) -> tuple[str, ...] | None:
    if not available_class_ids:
        return None
    if not re.fullmatch(r"\s*[a-zA-Z](?:\s*[-/,]\s*[a-zA-Z])+\s*", note_text):
        return None
    class_by_letter = {
        class_id[-1].casefold(): class_id
        for class_id in available_class_ids
        if re.fullmatch(r"\d{1,2}[a-zA-Z]", class_id)
    }
    requested_letters = [token.casefold() for token in re.findall(r"[a-zA-Z]", note_text)]
    suggested_classes = []
    for letter in requested_letters:
        class_id = class_by_letter.get(letter)
        if class_id and class_id not in suggested_classes:
            suggested_classes.append(class_id)
    if len(suggested_classes) < 2 or len(suggested_classes) != len(set(requested_letters)):
        return None
    return tuple(suggested_classes)


def _suggested_pair_target(
    students: list[Student],
    student: Student,
    note_text: str,
    *,
    mode: RuleType,
) -> _StudentMentionMatch | None:
    normalized_text = note_text.casefold()
    if mode == "SEPARATE":
        if not _looks_like_separation_note(normalized_text):
            return None
    elif mode == "TOGETHER":
        if re.search(r"\bnicht\s+(mit|zusammen|neben)\b", normalized_text):
            return None
        if not re.search(r"\b(zusammen\s+mit|mit|zu)\b", normalized_text):
            return None
    else:
        return None
    return _resolve_unique_student_mention(students, student, note_text)


def _looks_like_separation_note(normalized_text: str) -> bool:
    return bool(
        re.search(r"\b(nicht\s+mit|nicht\s+zusammen\s+mit|nicht\s+neben|trennen\s+von)\b", normalized_text)
        or re.search(r"\bnicht\s+(moeglich|möglich)\b", normalized_text)
        or re.search(r"\bnicht\s+in\s+(eine|einer|die\s+gleiche|derselben)\s+klasse\b", normalized_text)
    )


def _resolve_unique_student_mention(
    students: list[Student],
    source_student: Student,
    note_text: str,
) -> _StudentMentionMatch | None:
    normalized_note = _normalized_search_text(note_text)
    note_tokens = set(re.findall(r"\w+", normalized_note))
    matches = []
    for candidate in students:
        if candidate.internal_id == source_student.internal_id:
            continue
        if _student_is_mentioned(candidate, normalized_note, note_tokens):
            matches.append(candidate)
    if len(matches) == 1:
        return _StudentMentionMatch(matches[0])
    if matches:
        return None

    fuzzy_matches = []
    for candidate in students:
        if candidate.internal_id == source_student.internal_id:
            continue
        if _student_is_fuzzily_mentioned(candidate, note_tokens):
            fuzzy_matches.append(candidate)
    return _StudentMentionMatch(fuzzy_matches[0], fuzzy=True) if len(fuzzy_matches) == 1 else None


def _student_is_mentioned(student: Student, normalized_note: str, note_tokens: set[str]) -> bool:
    if student.nr and student.nr.casefold() in note_tokens:
        return True
    first_name = _normalized_search_text(student.first_name)
    last_name = _normalized_search_text(student.last_name)
    full_name = _normalized_search_text(student.full_name)
    sort_name = _normalized_search_text(student.sort_name)
    if full_name and full_name in normalized_note:
        return True
    if sort_name and sort_name in normalized_note:
        return True
    if first_name and last_name and first_name in note_tokens and last_name in note_tokens:
        return True
    if first_name and first_name in note_tokens:
        return True
    return False


def _student_is_fuzzily_mentioned(student: Student, note_tokens: set[str]) -> bool:
    searchable_names = [
        _normalized_search_text(student.first_name),
        _normalized_search_text(student.last_name),
    ]
    meaningful_tokens = [
        token
        for token in note_tokens
        if len(token) >= 5 and token not in _COMMON_NOTE_WORDS
    ]
    for token in meaningful_tokens:
        for name in searchable_names:
            if len(name) < 5:
                continue
            if SequenceMatcher(None, token, name).ratio() >= 0.86:
                return True
    return False


def _pair_suggestion_message(rule_label: str, match: _StudentMentionMatch) -> str:
    if match.fuzzy:
        return f"Möglicherweise gemeint: {match.student.display_label}. Bitte vor dem Anlegen der {rule_label} prüfen."
    return f"Die Notiz klingt nach einer {rule_label} mit {match.student.display_label}."


def _contains_unresolved_separation(note_text: str) -> bool:
    normalized_text = note_text.casefold()
    return bool(
        _looks_like_separation_note(normalized_text)
        or re.search(r"\b(schwester|schwestern|bruder|brueder|brüder|geschwister)\b", normalized_text)
    )


def _unresolved_separation_message(students: list[Student], student: Student, note_text: str) -> str:
    normalized_text = note_text.casefold()
    if re.search(r"\b(schwester|schwestern|bruder|brueder|brüder|geschwister)\b", normalized_text):
        if re.search(r"\b(gegenseitig|gewünscht|gewuenscht|wunsch)\b", normalized_text):
            return "Schwester manuell identifizieren; Hinweis spricht für Wunsch- oder Zusammen-Regel."
        return "Trennhinweis auf Geschwister, bitte betroffene Person manuell auswählen."

    missing_first_name = _missing_first_name_after_not_with(students, student, note_text)
    if missing_first_name:
        return missing_first_name

    if re.search(r"\bnicht\s+(moeglich|möglich)\b", normalized_text):
        friend_labels = _friend_labels(students, student)
        if friend_labels:
            return "Kein Partner genannt. Prüfen gegen Wunschfreunde: " + ", ".join(friend_labels) + "."

    return "Die Notiz klingt nach einer Trennregel, nennt aber keinen eindeutig erkennbaren zweiten Schüler."


def _missing_first_name_after_not_with(students: list[Student], source_student: Student, note_text: str) -> str | None:
    match = re.search(r"\bnicht\s+mit\s+([A-Za-zÄÖÜäöüß-]+)", note_text)
    if not match:
        return None
    raw_name = match.group(1).strip("-")
    normalized_name = _normalized_search_text(raw_name)
    if not normalized_name:
        return None
    exact_matches = [
        student
        for student in students
        if student.internal_id != source_student.internal_id
        and _normalized_search_text(student.first_name) == normalized_name
    ]
    if len(exact_matches) > 1:
        return f"Mehrere Schüler mit Vorname {raw_name} gefunden; bitte manuell auswählen."
    if not exact_matches:
        return f"Kein Schüler mit Vorname {raw_name} gefunden."
    return None


def _friend_labels(students: list[Student], student: Student) -> list[str]:
    labels = []
    for reference in (student.friend1, student.friend2):
        friend = resolve_student_ref(students, reference)
        if friend:
            labels.append(friend.display_label)
        elif reference:
            labels.append(reference)
    return labels


_COMMON_NOTE_WORDS = {
    "bitte",
    "nicht",
    "moeglich",
    "möglich",
    "klasse",
    "klassen",
    "zusammen",
    "unterschiedlich",
    "unterschiedlicher",
    "unterschiedlichern",
    "wegen",
    "durch",
    "eine",
    "einer",
}


def _normalized_search_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value.casefold())).strip()

from __future__ import annotations

import importlib
import inspect
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st

import klassenbildung.core.models as core_models_module
import klassenbildung.core.settings as core_settings_module
import klassenbildung.excel_io.excel_export as excel_export_module
import klassenbildung.presentation.candidate_review as candidate_review_module
import klassenbildung.presentation.optimization_progress as optimization_progress_module
import klassenbildung.presentation.candidate_summary as candidate_summary_module
import klassenbildung.services.manual_rules as manual_rules_module
import klassenbildung.services.note_rule_conversion as note_rule_conversion_module
import klassenbildung.validation.finality as finality_module
from klassenbildung.core.constants import DEFAULT_WEIGHTS
from klassenbildung.core.models import (
    ClassConfig,
    ManualRule,
    OptimizationSettings,
    Student,
    ValidationMessage,
)
from klassenbildung.core.settings import (
    coerce_settings,
    generate_class_configs,
    load_class_configs,
    load_settings,
    save_class_configs,
    save_settings,
)
from klassenbildung.core.statistics import build_import_statistics
from klassenbildung.excel_io.excel_export import export_excel
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.optimization.solver import clear_profile_incumbent_cache, solve_assignments
from klassenbildung.presentation.wording import (
    candidate_tradeoff_text as summary_tradeoff_text,
    candidate_warning_lines as summary_warning_lines,
)
from klassenbildung.services.candidate_selection import (
    balanced_candidate as summary_balanced_candidate,
    candidate_summaries,
    decision_candidate_cards as summary_decision_candidate_cards,
    diagnostic_candidate as summary_diagnostic_candidate,
    review_candidates as summary_review_candidates,
    social_strongest_candidate as summary_social_strongest_candidate,
)
from klassenbildung.ui.tables import (
    class_configs_to_frame,
    comments_to_frame,
    messages_to_frame,
    score_to_class_frame,
)
from klassenbildung.validation.validator import validate_students


def _reload_stale_project_modules() -> None:
    """Streamlit can rerun app.py while keeping imported project modules alive."""
    global ClassConfig, OptimizationSettings, Student, ValidationMessage
    global student_effective_note_text, student_has_manual_note
    global coerce_settings, generate_class_configs, load_class_configs, load_settings
    global save_class_configs, save_settings
    global export_excel
    global candidate_review_module, candidate_summary_module
    global optimization_progress_module
    global manual_rules_module
    global note_rule_conversion_module

    stale_core = "comfort_tolerance" not in inspect.signature(generate_class_configs).parameters
    stale_summary = not hasattr(candidate_summary_module, "candidate_summary_records")
    stale_progress = not hasattr(optimization_progress_module, "progress_event_message")
    stale_manual_rules = not hasattr(manual_rules_module, "student_effective_note_text")
    stale_note_rules = not hasattr(note_rule_conversion_module, "suggest_note_rule_actions")
    stale_review = (
        not hasattr(candidate_review_module, "build_candidate_review_model")
        or "note_review_status_by_student"
        not in inspect.signature(candidate_review_module.build_candidate_review_model).parameters
        or not hasattr(candidate_review_module, "candidate_review_records")
        or not hasattr(candidate_review_module, "ReviewReadiness")
        or not hasattr(candidate_review_module, "review_readiness_text")
    )
    stale_export = (
        "include_expert_diagnostics" not in inspect.signature(export_excel).parameters
        or "export_source_candidate_key" not in inspect.signature(export_excel).parameters
        or not hasattr(excel_export_module, "_write_candidate_summary_sheet")
        or not hasattr(excel_export_module, "_candidate_reports_for_export")
        or not hasattr(excel_export_module, "_write_class_profile_sheet")
        or not hasattr(excel_export_module, "_write_candidate_class_sheet")
        or not hasattr(excel_export_module, "_write_candidate_decision_sheet")
        or "zusammengefasste_varianten" not in getattr(excel_export_module, "CANDIDATE_EXPORT_FIELDS", [])
        or "displayed_candidate_count" not in inspect.signature(excel_export_module._write_overview_sheet).parameters
        or "selected_candidate_key" not in inspect.signature(excel_export_module._write_overview_sheet).parameters
        or "decision_context" not in inspect.signature(excel_export_module._write_overview_sheet).parameters
        or "class_configs" not in inspect.signature(excel_export_module._write_notes_sheet).parameters
    )
    if (
        not stale_core
        and not stale_summary
        and not stale_progress
        and not stale_review
        and not stale_export
        and not stale_manual_rules
        and not stale_note_rules
    ):
        return

    if stale_core:
        reloaded_models = importlib.reload(core_models_module)
        reloaded_settings = importlib.reload(core_settings_module)
        ClassConfig = reloaded_models.ClassConfig
        OptimizationSettings = reloaded_models.OptimizationSettings
        Student = reloaded_models.Student
        ValidationMessage = reloaded_models.ValidationMessage
        student_effective_note_text = reloaded_models.student_effective_note_text
        student_has_manual_note = reloaded_models.student_has_manual_note
        coerce_settings = reloaded_settings.coerce_settings
        generate_class_configs = reloaded_settings.generate_class_configs
        load_class_configs = reloaded_settings.load_class_configs
        load_settings = reloaded_settings.load_settings
        save_class_configs = reloaded_settings.save_class_configs
        save_settings = reloaded_settings.save_settings
        manual_rules_module = importlib.reload(manual_rules_module)
        note_rule_conversion_module = importlib.reload(note_rule_conversion_module)

    if stale_summary:
        candidate_summary_module = importlib.reload(candidate_summary_module)

    if stale_progress:
        optimization_progress_module = importlib.reload(optimization_progress_module)

    if stale_review:
        candidate_review_module = importlib.reload(candidate_review_module)

    if stale_manual_rules:
        manual_rules_module = importlib.reload(manual_rules_module)

    if stale_note_rules:
        note_rule_conversion_module = importlib.reload(note_rule_conversion_module)

    if stale_export or stale_summary or stale_review:
        export_excel = importlib.reload(excel_export_module).export_excel


def student_effective_note_text(student: object) -> str | None:
    note_text = getattr(student, "note_text", None)
    if note_text is not None:
        return note_text
    return getattr(student, "comment", None)


def student_has_manual_note(student: object) -> bool:
    note_text = student_effective_note_text(student)
    return bool(note_text and note_text.strip())


_reload_stale_project_modules()


st.set_page_config(page_title="Klassenbildung", layout="wide")

DUMMY_EXCEL_PATH = Path("DummyDaten.xlsx")
COMMENT_REVIEW_MESSAGE = "Bemerkung muss manuell geprüft werden."


@dataclass(frozen=True)
class ExportCandidateOption:
    option_id: str
    candidate_key: str
    mode: str
    label: str
    caption: str
    assignments: dict[str, str]
    score_report: object

WEIGHT_HELP = {
    "weight_mutual_friend": (
        "Strafwert für ein getrenntes gegenseitiges Freundespaar. Es wird als Paar gezählt, nicht zusätzlich "
        "zu beiden Einzelwünschen addiert."
    ),
    "weight_friend1": (
        "Strafwert für einen getrennten einseitigen ersten Freundeswunsch. Höher bedeutet: Die App trennt Freund 1 nur, "
        "wenn andere wichtige Ziele dagegen sprechen."
    ),
    "weight_friend2": (
        "Strafwert für einen getrennten einseitigen zweiten Freundeswunsch. Niedriger als Freund 1."
    ),
    "weight_no_friend": (
        "Zusätzlicher Strafwert pro Kind, das keinen einzigen gefundenen Wunschfreund in seiner Klasse hat."
    ),
    "weight_mixed_language_class": (
        "Grundstrafe pro Klasse, in der Französisch und Latein gemeinsam vorkommen."
    ),
    "weight_language_minority_student": (
        "Zusatzstrafe für jeden Schüler der kleineren Sprachgruppe in einer F/L-Mischklasse."
    ),
    "weight_mixed_music_class": (
        "Grundstrafe pro Klasse, in der mehrere B/S/G-Profile gemeinsam vorkommen. Reg zählt dabei neutral."
    ),
    "weight_music_minority_student": (
        "Zusatzstrafe für Schüler aus kleineren B/S/G-Profilgruppen in einer Musik-Mischklasse."
    ),
    "weight_music_focus_shortfall": (
        "Strafe, wenn eine Klasse zwar B/S/G-Schüler enthält, aber mehr Reg-Schüler als Profil-Schüler hat."
    ),
    "weight_support_distribution": (
        "Bestraft R-/Unterstützungsballungen erst außerhalb der Toleranz und dann quadratisch steigend."
    ),
    "weight_gender_balance": (
        "Bestraft m/w-Schieflagen erst außerhalb einer Toleranz von etwa zwei Kindern pro Klasse."
    ),
    "weight_primary_school": (
        "Bestraft Ballungen aus derselben Grundschule erst ab dem vierten Kind in einer neuen Klasse."
    ),
    "weight_primary_class": (
        "Bestraft Ballungen aus derselben alten Grundschulklasse erst ab dem dritten Kind."
    ),
}
PREVIOUS_DEFAULT_WEIGHTS = {
    "weight_music_profile": 800,
    "weight_language_profile": 800,
    "weight_mixed_language_class": 50000,
    "weight_mixed_music_class": 50000,
    "weight_friend1": 1000,
    "weight_friend2": 300,
    "weight_mutual_friend": 2500,
    "weight_support_distribution": 250,
    "weight_gender_balance": 80,
    "weight_primary_school": 50,
    "weight_primary_class": 40,
    "weight_nationality": 10,
    "weight_religion": 5,
    "weight_keep_existing": 0,
}
PREVIOUS_REBALANCED_DEFAULT_WEIGHTS = {
    "weight_music_profile": 15000,
    "weight_language_profile": 15000,
    "weight_mixed_language_class": 1500,
    "weight_mixed_music_class": 1500,
    "weight_friend1": 1800,
    "weight_friend2": 600,
    "weight_mutual_friend": 4500,
    "weight_support_distribution": 300,
    "weight_gender_balance": 80,
    "weight_primary_school": 60,
    "weight_primary_class": 40,
    "weight_nationality": 5,
    "weight_religion": 0,
    "weight_keep_existing": 0,
}
PREVIOUS_REQUIRED_PROFILE_DEFAULT_WEIGHTS = {
    "weight_music_profile": 0,
    "weight_language_profile": 0,
    "weight_mixed_language_class": 1500,
    "weight_mixed_music_class": 1500,
    "weight_friend1": 1800,
    "weight_friend2": 600,
    "weight_mutual_friend": 4500,
    "weight_support_distribution": 300,
    "weight_gender_balance": 80,
    "weight_primary_school": 60,
    "weight_primary_class": 40,
    "weight_nationality": 5,
    "weight_religion": 0,
    "weight_keep_existing": 0,
}
PREVIOUS_STRICT_MIX_DEFAULT_WEIGHTS = {
    "weight_music_profile": 0,
    "weight_language_profile": 0,
    "weight_mixed_language_class": 50000,
    "weight_mixed_music_class": 50000,
    "weight_friend1": 1800,
    "weight_friend2": 600,
    "weight_mutual_friend": 4500,
    "weight_support_distribution": 300,
    "weight_gender_balance": 80,
    "weight_primary_school": 60,
    "weight_primary_class": 40,
    "weight_nationality": 5,
    "weight_religion": 0,
    "weight_keep_existing": 0,
}


def main() -> None:
    st.title("Klassenbildung")

    _init_state()
    st.sidebar.toggle("Expertenmodus", value=st.session_state.get("expert_mode", False), key="expert_mode")
    st.sidebar.caption("Im Standardmodus stehen Entscheidung, Kandidaten und manuelle Prüfung im Vordergrund.")
    settings = _current_settings()

    tabs = st.tabs(
        [
            "1 Excel prüfen",
            "2 Einstellungen",
            "3 Berechnen",
            "4 Ergebnis",
        ]
    )

    with tabs[0]:
        _upload_tab(settings)
    with tabs[1]:
        _settings_tab()
    with tabs[2]:
        _optimization_tab(settings)
    with tabs[3]:
        _result_tab(settings)


def _init_state() -> None:
    st.session_state.setdefault("settings", load_settings())
    st.session_state.settings = coerce_settings(st.session_state.settings)
    st.session_state.setdefault("class_configs", load_class_configs())
    st.session_state.setdefault("import_result", None)
    st.session_state.setdefault("validation_result", None)
    st.session_state.setdefault("solver_result", None)
    st.session_state.setdefault("manual_rules", [])
    st.session_state.setdefault("manual_rule_entries", [])
    st.session_state.setdefault("note_hints_kept", set())
    st.session_state.setdefault("student_data_hash", None)
    st.session_state.setdefault("manual_rule_reset_message", None)


def _set_import_result(result) -> None:
    new_hash = manual_rules_module.student_data_hash(result.students)
    old_hash = st.session_state.get("student_data_hash")
    st.session_state.import_result = result
    st.session_state.validation_result = None
    st.session_state.solver_result = None
    if old_hash and old_hash != new_hash:
        _clear_manual_rule_state()
        st.session_state.manual_rule_reset_message = (
            "Die hochgeladenen Daten haben sich geändert. Manuelle Regeln wurden zurückgesetzt."
        )
    st.session_state.student_data_hash = new_hash


def _clear_manual_rule_state() -> None:
    st.session_state.manual_rules = []
    st.session_state.manual_rule_entries = []
    st.session_state.note_hints_kept = set()


def _manual_rules() -> list[ManualRule]:
    entries = _manual_rule_entries()
    rules = manual_rules_module.active_manual_rules(entries)
    st.session_state.manual_rules = rules
    return rules


def _manual_rule_entries():
    raw_entries = st.session_state.get("manual_rule_entries", [])
    if not raw_entries and st.session_state.get("manual_rules"):
        raw_entries = st.session_state.manual_rules
    entries = manual_rules_module.manual_rule_entries(raw_entries)
    st.session_state.manual_rule_entries = entries
    return entries


def _note_review_status_by_student():
    return manual_rules_module.note_review_status_by_student(
        _manual_rule_entries(),
        set(st.session_state.get("note_hints_kept", set())),
    )


def _store_manual_rule(
    rule: ManualRule,
    *,
    source: str,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    note_student_id: str | None = None,
) -> tuple[bool, list[ValidationMessage]]:
    entries = _manual_rule_entries()
    errors = manual_rules_module.validation_errors_for_new_rule(
        students,
        class_configs,
        settings,
        entries,
        rule,
    )
    if errors:
        return False, errors
    entries, changed = manual_rules_module.add_manual_rule_entry(
        entries,
        rule,
        source=source,
        note_student_id=note_student_id,
    )
    st.session_state.manual_rule_entries = entries
    st.session_state.manual_rules = manual_rules_module.active_manual_rules(entries)
    st.session_state.solver_result = None
    return changed, []


def _current_settings() -> OptimizationSettings:
    current: OptimizationSettings = coerce_settings(st.session_state.settings)
    current = _migrate_previous_default_weights(current)
    st.session_state.settings = current
    return current


def _migrate_previous_default_weights(settings: OptimizationSettings) -> OptimizationSettings:
    if all(getattr(settings, key) == value for key, value in PREVIOUS_DEFAULT_WEIGHTS.items()):
        return replace(settings, **DEFAULT_WEIGHTS)
    if all(getattr(settings, key) == value for key, value in PREVIOUS_REBALANCED_DEFAULT_WEIGHTS.items()):
        return replace(settings, **DEFAULT_WEIGHTS)
    if all(getattr(settings, key) == value for key, value in PREVIOUS_REQUIRED_PROFILE_DEFAULT_WEIGHTS.items()):
        return replace(settings, **DEFAULT_WEIGHTS)
    if all(getattr(settings, key) == value for key, value in PREVIOUS_STRICT_MIX_DEFAULT_WEIGHTS.items()):
        return replace(settings, **DEFAULT_WEIGHTS)
    if (
        settings.weight_music_profile == 0
        and settings.weight_language_profile == 0
        and settings.weight_mixed_language_class <= PREVIOUS_REQUIRED_PROFILE_DEFAULT_WEIGHTS["weight_mixed_language_class"]
        and settings.weight_mixed_music_class <= PREVIOUS_REQUIRED_PROFILE_DEFAULT_WEIGHTS["weight_mixed_music_class"]
    ):
        return replace(
            settings,
            weight_mixed_language_class=DEFAULT_WEIGHTS["weight_mixed_language_class"],
            weight_mixed_music_class=DEFAULT_WEIGHTS["weight_mixed_music_class"],
        )
    return settings


def _settings_tab() -> None:
    current = _current_settings()
    result = st.session_state.import_result

    st.subheader("Klassenrahmen und Rechenzeit")
    total_students = len(result.students) if result else 210
    class_configs: list[ClassConfig] = st.session_state.class_configs
    average_size = max(1, round(total_students / max(len(class_configs) or 7, 1)))
    col1, col2, col3, col4 = st.columns(4)
    class_count = col1.number_input(
        "Anzahl Klassen",
        min_value=1,
        max_value=15,
        value=len(class_configs) or 7,
        key="settings_class_count",
    )
    target_size = col2.number_input(
        "Wunschgröße",
        min_value=1,
        max_value=40,
        value=average_size,
        key="settings_target_size",
    )
    soft_tolerance = col3.number_input(
        "normaler Spielraum",
        min_value=0,
        max_value=10,
        value=2,
        key="settings_soft_tolerance",
    )
    hard_tolerance = col4.number_input(
        "äußerste Grenze",
        min_value=int(soft_tolerance),
        max_value=15,
        value=max(5, int(soft_tolerance)),
        key="settings_hard_tolerance",
        help="Aus Wunschgröße und äußerer Grenze werden die harten Klassengrößen berechnet.",
    )
    time_limit = st.select_slider(
        "Max. Rechenzeit pro Prüfschritt",
        options=[10, 30, 60, 120],
        value=current.solver_time_limit_seconds,
        key="settings_time_limit",
    )
    soft_min = max(0, int(target_size) - int(soft_tolerance))
    soft_max = int(target_size) + int(soft_tolerance)
    hard_min = max(0, int(target_size) - int(hard_tolerance))
    hard_max = int(target_size) + int(hard_tolerance)
    st.caption(
        f"Ziel: {int(target_size)} Kinder pro Klasse. Normaler Bereich: {soft_min}-{soft_max}. "
        f"Harte Grenze: {hard_min}-{hard_max}."
    )
    st.caption(
        "Die Rechenzeit gilt pro Prüfschritt. Die App prüft nacheinander F/L, Musik, Kinder ohne Wunschfreund, "
        "starke Freundschaften, kleinere Profilgruppen und danach die Restqualität."
    )

    preview_configs = generate_class_configs(
        total_students=total_students,
        class_count=int(class_count),
        year=5,
        target_size=int(target_size),
        comfort_tolerance=int(soft_tolerance),
        hard_tolerance=int(hard_tolerance),
        existing_profiles=class_configs,
    )
    preview_configs = _without_generated_labels(preview_configs)
    st.dataframe(_class_size_preview_frame(preview_configs), width="stretch", hide_index=True)

    st.subheader("Feste Klassenprofile")
    st.caption(
        "Wenn Klassen wie 5a S+F/L oder 5e G/Reg+F/L administrativ fest vorgegeben sind, "
        "müssen diese Profile hier als harte Regeln aktiv sein. Reg ist nur dort erlaubt, wo es im Musikprofil der Klasse steht."
    )
    profile_col_a, profile_col_b = st.columns(2)
    enforce_language_profile = profile_col_a.checkbox(
        "Sprachprofile der Klassen erzwingen",
        value=current.enforce_language_profile,
        key="settings_enforce_language_profile",
    )
    enforce_music_profile = profile_col_b.checkbox(
        "Musikprofile der Klassen erzwingen",
        value=current.enforce_music_profile,
        key="settings_enforce_music_profile",
    )
    preview_configs = _class_profile_controls(preview_configs)
    st.dataframe(class_configs_to_frame(preview_configs), width="stretch", hide_index=True)

    st.subheader("Gewichtungen")
    st.info(
        "Standard ist ein mehrstufiges Modell: zuerst werden F/L-Mischklassen minimiert, danach Musik-Mischklassen, "
        "danach Kinder ohne Wunschfreund und starke Freundschaften. Erst danach wird die Schwere der Mischung geglättet."
    )
    st.caption(
        "Die Profil-Minimierung schützt die Anzahl der Mischklassen vor Freundschaftsdominanz. "
        "Die Gewichte steuern danach die Schwere, den technischen Score und die Restabwägung."
    )
    if st.button("Empfohlene Gewichtungen laden", key="settings_reset_weights"):
        current = replace(current, **DEFAULT_WEIGHTS)
        save_settings(current)
        st.session_state.settings = current
        st.session_state.solver_result = None
        st.rerun()

    st.markdown("**Sprache und Musik**")
    st.caption(
        "Die Anzahl der Mischklassen wird zuerst minimiert. Die Minderheiten-Strafe zählt anschließend, wie stark eine unvermeidbare Mischung ist."
    )
    weight_mixed_language_class = _weight_slider(
        "F/L-Mischklasse",
        "weight_mixed_language_class",
        current.weight_mixed_language_class,
        max_value=30000,
        step=500,
    )
    weight_language_minority_student = _weight_slider(
        "F/L-Minderheit pro Schüler",
        "weight_language_minority_student",
        current.weight_language_minority_student,
        max_value=5000,
        step=100,
    )
    weight_mixed_music_class = _weight_slider(
        "Musik-Mischklasse B/S/G",
        "weight_mixed_music_class",
        current.weight_mixed_music_class,
        max_value=30000,
        step=500,
    )
    weight_music_minority_student = _weight_slider(
        "Musik-Minderheit pro Schüler",
        "weight_music_minority_student",
        current.weight_music_minority_student,
        max_value=5000,
        step=100,
    )
    weight_music_focus_shortfall = _weight_slider(
        "Musik-Profilanteil",
        "weight_music_focus_shortfall",
        current.weight_music_focus_shortfall,
        max_value=3000,
        step=100,
    )

    st.markdown("**Freundeswünsche**")
    weight_mutual_friend = _weight_slider(
        "Gegenseitige Freunde zusammenhalten",
        "weight_mutual_friend",
        current.weight_mutual_friend,
        max_value=15000,
        step=250,
    )
    weight_friend1 = _weight_slider(
        "Freundeswunsch 1 erfüllen",
        "weight_friend1",
        current.weight_friend1,
        max_value=5000,
        step=100,
    )
    weight_friend2 = _weight_slider(
        "Freundeswunsch 2 erfüllen",
        "weight_friend2",
        current.weight_friend2,
        max_value=2500,
        step=50,
    )
    weight_no_friend = _weight_slider(
        "Kein Wunschfreund in Klasse",
        "weight_no_friend",
        current.weight_no_friend,
        max_value=20000,
        step=500,
    )

    advanced = _advanced_weight_values(current)
    with st.expander("Weitere Gewichtungen", expanded=False):
        advanced = _advanced_weight_controls(current)

    settings = OptimizationSettings(
        enforce_music_profile=enforce_music_profile,
        enforce_language_profile=enforce_language_profile,
        weight_music_profile=0,
        weight_language_profile=0,
        weight_mixed_language_class=weight_mixed_language_class,
        weight_language_minority_student=weight_language_minority_student,
        weight_mixed_music_class=weight_mixed_music_class,
        weight_music_minority_student=weight_music_minority_student,
        weight_music_focus_shortfall=weight_music_focus_shortfall,
        weight_friend1=weight_friend1,
        weight_friend2=weight_friend2,
        weight_mutual_friend=weight_mutual_friend,
        weight_no_friend=weight_no_friend,
        solver_time_limit_seconds=time_limit,
        **advanced,
    )

    if st.button("Einstellungen übernehmen"):
        save_class_configs(preview_configs)
        save_settings(settings)
        st.session_state.settings = settings
        st.session_state.class_configs = preview_configs
        st.session_state.solver_result = None
        st.success("Einstellungen übernommen.")
        st.rerun()


def _advanced_weight_values(current: OptimizationSettings) -> dict[str, int]:
    return {
        "weight_support_distribution": current.weight_support_distribution,
        "weight_gender_balance": current.weight_gender_balance,
        "weight_primary_school": current.weight_primary_school,
        "weight_primary_class": current.weight_primary_class,
        "weight_nationality": 0,
        "weight_religion": 0,
        "weight_keep_existing": 0,
    }


def _advanced_weight_controls(current: OptimizationSettings) -> dict[str, int]:
    st.caption(
        "R, Geschlecht und Grundschule werden toleranz- bzw. schwellenbasiert bewertet. "
        "Staat/Nationalität, Religion und bestehende Einteilung sind als aktive Kriterien deaktiviert."
    )
    return {
        "weight_support_distribution": _weight_slider(
            "R-Verteilung",
            "weight_support_distribution",
            current.weight_support_distribution,
            max_value=5000,
            step=100,
        ),
        "weight_gender_balance": _weight_slider(
            "Geschlecht",
            "weight_gender_balance",
            current.weight_gender_balance,
            max_value=1500,
            step=50,
        ),
        "weight_primary_school": _weight_slider(
            "Grundschule",
            "weight_primary_school",
            current.weight_primary_school,
            max_value=1500,
            step=50,
        ),
        "weight_primary_class": _weight_slider(
            "Grundschulklasse",
            "weight_primary_class",
            current.weight_primary_class,
            max_value=1500,
            step=50,
        ),
        "weight_nationality": 0,
        "weight_religion": 0,
        "weight_keep_existing": 0,
    }


def _weight_slider(
    label: str,
    key: str,
    value: int,
    *,
    max_value: int,
    step: int,
) -> int:
    return st.slider(
        label,
        min_value=0,
        max_value=max_value,
        value=min(max(value, 0), max_value),
        step=step,
        help=WEIGHT_HELP[key],
    )


def _without_generated_labels(class_configs: list[ClassConfig]) -> list[ClassConfig]:
    return class_configs


def _class_size_preview_frame(class_configs: list[ClassConfig]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": config.class_id,
                "Wunschgröße": int(st.session_state.get("settings_target_size", config.size_max)),
                "normal": (
                    f"{max(0, int(st.session_state.get('settings_target_size', config.size_max)) - int(st.session_state.get('settings_soft_tolerance', 0)))}-"
                    f"{int(st.session_state.get('settings_target_size', config.size_max)) + int(st.session_state.get('settings_soft_tolerance', 0))}"
                ),
                "hart": f"{config.size_min}-{config.size_max}",
            }
            for config in class_configs
        ]
    )


def _class_profile_controls(class_configs: list[ClassConfig]) -> list[ClassConfig]:
    edited_configs: list[ClassConfig] = []
    with st.expander("Profile je Klasse bearbeiten", expanded=False):
        st.caption("Leere Auswahl bedeutet hier nicht 'alle', sondern: kein festes Profil für diese Klasse hinterlegt.")
        for config in class_configs:
            col_a, col_b = st.columns([1, 1])
            music = col_a.multiselect(
                f"{config.class_id} Musik",
                options=["Reg", "B", "S", "G"],
                default=config.music_allowed,
                key=f"profile_music_{config.class_id}",
            )
            languages = col_b.multiselect(
                f"{config.class_id} Sprache",
                options=["F", "L"],
                default=config.languages_allowed,
                key=f"profile_language_{config.class_id}",
            )
            edited_configs.append(
                ClassConfig(
                    class_id=config.class_id,
                    label=config.label,
                    size_min=config.size_min,
                    size_max=config.size_max,
                    music_allowed=list(music),
                    languages_allowed=list(languages),
                    size_policy=getattr(config, "size_policy", None),
                )
            )
    if edited_configs:
        return edited_configs
    return class_configs


def _friend_wish_frame(friend_stats: dict[str, int]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Kennzahl": "Freundeswunsch 1 eingetragen", "Anzahl": friend_stats["friend1"]},
            {"Kennzahl": "Freundeswunsch 2 eingetragen", "Anzahl": friend_stats["friend2"]},
            {"Kennzahl": "Mindestens ein Wunsch", "Anzahl": friend_stats["any"]},
            {"Kennzahl": "Ohne Freundeswunsch", "Anzahl": friend_stats["none"]},
        ]
    )


def _upload_tab(settings: OptimizationSettings) -> None:
    st.subheader("Datei laden")
    if DUMMY_EXCEL_PATH.exists():
        col_a, col_b = st.columns([1, 1])
        if col_a.button("Testdatei laden"):
            result = import_excel(DUMMY_EXCEL_PATH.read_bytes(), filename=DUMMY_EXCEL_PATH.name)
            _set_import_result(result)
            st.rerun()
        col_b.download_button(
            "Testdatei herunterladen",
            data=DUMMY_EXCEL_PATH.read_bytes(),
            file_name=DUMMY_EXCEL_PATH.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption(f"Lokale Testdatei: {DUMMY_EXCEL_PATH.name}")

    uploaded = st.file_uploader("Excel-Datei hochladen", type=["xlsx", "xlsm"])
    if uploaded and st.button("Datei prüfen"):
        result = import_excel(uploaded, filename=uploaded.name)
        _set_import_result(result)

    result = st.session_state.import_result
    if not result:
        st.info("Noch keine Datei geladen.")
        return
    if st.session_state.get("manual_rule_reset_message"):
        st.warning(st.session_state.manual_rule_reset_message)
        st.session_state.manual_rule_reset_message = None

    st.subheader(result.source_filename or "Excel-Datei")
    stats = build_import_statistics(result.students)
    friend_stats = _friend_wish_stats(result.students)

    st.markdown("**Dateiüberblick**")
    cols = st.columns(4)
    cols[0].metric("Schüler", stats["student_count"])
    cols[1].metric("Klassen", len(result.detected_classes))
    cols[2].metric("Bemerkungen", stats["comment_count"])
    cols[3].metric("R-Markierungen", stats["support_count"])

    st.markdown("**Freundeswünsche**")
    st.dataframe(_friend_wish_frame(friend_stats), width="stretch", hide_index=True)

    st.markdown("**Verteilungen**")
    col_a, col_b, col_c = st.columns(3)
    col_a.dataframe(pd.DataFrame(stats["languages"].items(), columns=["Sprache", "Anzahl"]), width="stretch", hide_index=True)
    col_b.dataframe(pd.DataFrame(stats["gender"].items(), columns=["Geschlecht", "Anzahl"]), width="stretch", hide_index=True)
    col_c.dataframe(pd.DataFrame(stats["music"].items(), columns=["Musik", "Anzahl"]), width="stretch", hide_index=True)

    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
        manual_rules=_manual_rules(),
        base_messages=result.messages,
    )
    st.session_state.validation_result = validation_result
    if validation_result.has_errors:
        st.error("Diese Datei hat blockierende Fehler.")
        st.dataframe(messages_to_frame(validation_result.errors), width="stretch", hide_index=True)
    else:
        st.success("Datei ist für eine Vorschlagsrechnung nutzbar.")
        data_blockers = finality_module.finality_data_blockers(validation_result.messages)
        if data_blockers:
            st.error(
                f"Finalexport gesperrt: {len(data_blockers)} Datenblocker. "
                "Schülernummern, Profile und nicht zuordenbare Freundeswünsche müssen vor einer Freigabe geklärt werden."
            )
            st.dataframe(messages_to_frame(data_blockers), width="stretch", hide_index=True)
        visible_warnings = _visible_validation_warnings(validation_result.warnings)
        if visible_warnings:
            st.warning(f"{len(visible_warnings)} Dinge bitte in der Excel-Datei prüfen.")
            st.dataframe(messages_to_frame(visible_warnings), width="stretch", hide_index=True)
    _render_import_note_review_panel(result.students, st.session_state.class_configs, settings)
    _render_manual_rules_panel(result.students, st.session_state.class_configs, settings, "upload")


def _validation_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    if not result:
        st.info("Erst eine Excel-Datei hochladen.")
        return
    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
        manual_rules=_manual_rules(),
        base_messages=result.messages,
    )
    st.session_state.validation_result = validation_result
    st.dataframe(messages_to_frame(validation_result.messages), width="stretch")
    if validation_result.has_errors:
        st.error("Fehler blockieren die Optimierung.")
    else:
        st.success("Keine blockierenden Fehler gefunden.")


def _comments_tab() -> None:
    result = st.session_state.import_result
    if not result:
        st.info("Erst eine Excel-Datei hochladen.")
        return
    frame = comments_to_frame(result.students)
    if frame.empty:
        st.success("Keine Bemerkungen gefunden.")
    else:
        st.dataframe(frame, width="stretch")


def _render_import_note_review_panel(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> None:
    note_rows = _manual_note_rows(students, assignments={})
    if not note_rows:
        return
    st.markdown("**Bemerkungen als Regeln prüfen**")
    st.caption(
        "Eindeutige Hinweise wie 'nur 5e möglich' oder 'nicht mit 23' werden vorgeschlagen. "
        "Unklare Hinweise müssen bewusst ausgewählt oder als Hinweis behalten werden."
    )
    _render_note_status_frame("Bemerkungen", note_rows)
    _render_note_rule_controls(note_rows, students, class_configs, settings, "upload_notes")


def _manual_note_rows(students: list[Student], assignments: dict[str, str]) -> list:
    statuses = _note_review_status_by_student()
    return [
        candidate_review_module.StudentNoteRow(
            student_id=student.internal_id,
            display_name=student.display_label,
            class_id=assignments.get(student.internal_id) or student.original_class or "-",
            note_text=student_effective_note_text(student) or "",
            review_status=statuses.get(student.internal_id, manual_rules_module.NoteReviewStatus.UNREVIEWED),
        )
        for student in sorted(students, key=lambda item: (item.sort_name, item.row_number))
        if student_has_manual_note(student)
    ]


def _render_manual_rules_panel(
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    key_suffix: str,
) -> None:
    entries = _manual_rule_entries()
    st.markdown("**Aktive manuelle Regeln**")
    records = manual_rules_module.manual_rule_entry_records(entries, students)
    if not records:
        st.info("Noch keine manuellen Regeln angelegt.")
        return

    st.dataframe(pd.DataFrame(records).drop(columns=["id"]), width="stretch", hide_index=True)
    entry_by_id = {entry.id: entry for entry in entries}
    selected_id = st.selectbox(
        "Regel auswählen",
        options=list(entry_by_id),
        format_func=lambda entry_id: _manual_rule_option_label(entry_by_id[entry_id], students),
        key=f"manual_rule_select_{key_suffix}",
    )
    selected_entry = entry_by_id[selected_id]
    action_col_a, action_col_b = st.columns(2)
    active_label = "Deaktivieren" if selected_entry.active else "Aktivieren"
    if action_col_a.button(active_label, key=f"manual_rule_toggle_{key_suffix}"):
        st.session_state.manual_rule_entries = manual_rules_module.update_manual_rule_entry(
            entries,
            selected_entry.id,
            active=not selected_entry.active,
        )
        st.session_state.manual_rules = _manual_rules()
        st.session_state.solver_result = None
        st.rerun()
    if action_col_b.button("Löschen", key=f"manual_rule_delete_{key_suffix}"):
        st.session_state.manual_rule_entries = manual_rules_module.delete_manual_rule_entry(entries, selected_entry.id)
        st.session_state.manual_rules = _manual_rules()
        st.session_state.solver_result = None
        st.rerun()
    if st.button("Regeln zurücksetzen", key=f"manual_rule_clear_{key_suffix}"):
        _clear_manual_rule_state()
        st.session_state.solver_result = None
        st.rerun()

    with st.expander("Regel bearbeiten", expanded=False):
        updated_rule = _manual_rule_edit_controls(selected_entry.rule, students, class_configs, key_suffix)
        if st.button("Regel speichern", key=f"manual_rule_save_{key_suffix}"):
            updated_entries = manual_rules_module.update_manual_rule_entry(entries, selected_entry.id, rule=updated_rule)
            errors = manual_rules_module.validation_errors_for_entries(students, class_configs, settings, updated_entries)
            if errors:
                st.error("Diese Änderung erzeugt Regelkonflikte.")
                st.dataframe(messages_to_frame(errors), width="stretch", hide_index=True)
            else:
                st.session_state.manual_rule_entries = updated_entries
                st.session_state.manual_rules = _manual_rules()
                st.session_state.solver_result = None
                st.success("Regel gespeichert. Bitte danach neu optimieren.")
                st.rerun()


def _manual_rule_edit_controls(rule: ManualRule, students: list[Student], class_configs: list[ClassConfig], key_suffix: str) -> ManualRule:
    rule_type_options = {
        "Trennen": "SEPARATE",
        "Zusammen": "TOGETHER",
        "Fixierung": "FIX_CLASS",
        "Erlaubte Klassen": "ALLOW_CLASSES",
    }
    current_label = next(label for label, value in rule_type_options.items() if value == rule.type)
    selected_type_label = st.selectbox(
        "Typ",
        options=list(rule_type_options),
        index=list(rule_type_options).index(current_label),
        key=f"manual_rule_edit_type_{key_suffix}",
    )
    selected_type = rule_type_options[selected_type_label]
    student_labels = {student.display_label: student.internal_id for student in students}
    student_label_by_id = {value: label for label, value in student_labels.items()}
    student_a_label = st.selectbox(
        "Schüler",
        options=sorted(student_labels),
        index=sorted(student_labels).index(student_label_by_id.get(rule.student_a, sorted(student_labels)[0])),
        key=f"manual_rule_edit_student_a_{key_suffix}",
    )
    student_a = student_labels[student_a_label]
    if selected_type == "FIX_CLASS":
        class_ids = [config.class_id for config in class_configs]
        selected_class = st.selectbox(
            "Zielklasse",
            options=class_ids,
            index=class_ids.index(rule.class_id) if rule.class_id in class_ids else 0,
            key=f"manual_rule_edit_class_{key_suffix}",
        )
        return ManualRule("FIX_CLASS", student_a, class_id=selected_class)
    if selected_type == "ALLOW_CLASSES":
        class_ids = [config.class_id for config in class_configs]
        selected_classes = st.multiselect(
            "Erlaubte Klassen",
            options=class_ids,
            default=[class_id for class_id in rule.class_ids if class_id in class_ids] or class_ids[:1],
            key=f"manual_rule_edit_allowed_classes_{key_suffix}",
        )
        return ManualRule("ALLOW_CLASSES", student_a, class_ids=tuple(selected_classes))

    other_options = sorted(label for label, student_id in student_labels.items() if student_id != student_a)
    if not other_options:
        return ManualRule(selected_type, student_a, student_a)
    current_other_label = student_label_by_id.get(rule.student_b, other_options[0])
    other_label = st.selectbox(
        "Partner",
        options=other_options,
        index=other_options.index(current_other_label) if current_other_label in other_options else 0,
        key=f"manual_rule_edit_student_b_{key_suffix}",
    )
    return ManualRule(selected_type, student_a, student_labels[other_label])


def _manual_rule_option_label(entry, students: list[Student]) -> str:
    record = manual_rules_module.manual_rule_entry_records([entry], students)[0]
    return f"{record['Typ']}: {record['Schüler']} -> {record['Ziel / Partner']} ({record['Status']})"


def _class_config_tab() -> None:
    class_configs: list[ClassConfig] = st.session_state.class_configs

    st.subheader("Klassenprofile")
    st.dataframe(class_configs_to_frame(st.session_state.class_configs), width="stretch")

    with st.expander("Profile bearbeiten", expanded=False):
        edited_configs: list[ClassConfig] = []
        for config in class_configs:
            with st.expander(config.class_id, expanded=False):
                music = st.multiselect(
                    "Musikangebot",
                    options=["Reg", "B", "S", "G"],
                    default=config.music_allowed,
                    key=f"music_{config.class_id}",
                    help="Organisatorische Notiz für diese Klasse. Das Standardmodell trennt Musik über die Gewichtungen, nicht über harte Profilverbote.",
                )
                languages = st.multiselect(
                    "Sprachangebot",
                    options=["F", "L"],
                    default=config.languages_allowed,
                    key=f"lang_{config.class_id}",
                    help="Organisatorische Notiz für diese Klasse. Das Standardmodell trennt F/L über die Gewichtungen, nicht über harte Profilverbote.",
                )
                size_min = st.number_input("min", min_value=0, max_value=40, value=config.size_min, key=f"min_{config.class_id}")
                size_max = st.number_input("max", min_value=0, max_value=40, value=config.size_max, key=f"max_{config.class_id}")
                edited_configs.append(
                    ClassConfig(
                        class_id=config.class_id,
                        label=config.class_id,
                        size_min=int(size_min),
                        size_max=int(size_max),
                        music_allowed=list(music),
                        languages_allowed=list(languages),
                    )
                )

        if st.button("Klassen speichern", key="details_save_classes"):
            save_class_configs(edited_configs)
            st.session_state.class_configs = edited_configs
            st.session_state.solver_result = None
            st.success("Klassen gespeichert.")


def _optimization_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    if not result:
        st.info("Erst eine Excel-Datei hochladen.")
        return

    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
        manual_rules=_manual_rules(),
        base_messages=result.messages,
    )
    if validation_result.has_errors:
        st.error("Berechnung blockiert, weil Fehler gefunden wurden.")
        st.dataframe(messages_to_frame(validation_result.errors), width="stretch")
        return

    if st.button("Klassen vorschlagen", type="primary"):
        status_box = st.empty()
        progress_bar = st.progress(0.0)
        current_step_box = st.empty()
        started_at = perf_counter()
        current_step_box.info("Berechnung wird vorbereitet. Die App prüft gleich die Einteilung Schritt für Schritt.")

        def _update_progress(event: dict[str, object]) -> None:
            progress_bar.progress(optimization_progress_module.progress_fraction_for_event(event))
            current_step_box.info(optimization_progress_module.progress_event_message(event))

        solver_result = solve_assignments(
            result.students,
            st.session_state.class_configs,
            settings,
            manual_rules=_manual_rules(),
            progress_callback=_update_progress,
        )
        st.session_state.solver_result = solver_result
        elapsed = perf_counter() - started_at
        progress_bar.progress(1.0)
        current_step_box.success(
            f"Berechnung abgeschlossen nach {elapsed:.1f} Sekunden. "
            + optimization_progress_module.calculation_result_summary(solver_result, len(result.students))
        )
        if solver_result.status in {"OPTIMAL", "FEASIBLE"}:
            verdict = _quality_verdict(solver_result, len(result.students))
            if verdict["severity"] == "error":
                status_box.error(f"Gültige Lösung nach {elapsed:.1f} Sekunden, aber nicht freigabefähig.")
            elif verdict["severity"] == "warning":
                if _review_candidates(solver_result):
                    status_box.warning(
                        "Gültige Lösung gefunden: strenge Profilvariante nicht freigabefähig; "
                        f"Prüfkandidaten mit Profil-Lockerung gefunden nach {elapsed:.1f} Sekunden."
                    )
                else:
                    status_box.warning(f"Gültige Lösung nach {elapsed:.1f} Sekunden, aber nur mit Prüfung verwenden.")
            else:
                status_box.success(f"Berechnung fertig nach {elapsed:.1f} Sekunden.")
        else:
            status_label, status_hint = _solver_status_text(solver_result.status)
            status_box.error(f"Berechnung beendet nach {elapsed:.1f} Sekunden: {status_label}. {status_hint}")

    solver_result = st.session_state.solver_result
    if solver_result:
        if solver_result.score_report:
            status_label, status_hint = _overall_status_text(_overall_status(solver_result, len(result.students)))
        else:
            status_label, status_hint = _solver_status_text(solver_result.status)
        st.metric("Ergebnis", status_label)
        st.caption(status_hint)
        if solver_result.message:
            st.info(solver_result.message)
        _render_calculation_report(solver_result, len(result.students))
        if solver_result.score_report:
            score = solver_result.score_report
            _render_standard_result(
                solver_result,
                result.students,
                st.session_state.class_configs,
                settings,
                include_review=False,
                key_suffix="optimierung",
            )
            if score.hard_violations:
                st.error("Das Ergebnis enthält harte Regelverletzungen und sollte so nicht exportiert werden.")
            else:
                st.success("Harte Regelverletzungen: 0")
            _render_technical_expander(
                solver_result,
                result.students,
                st.session_state.class_configs,
                settings,
                score,
                "optimierung",
            )


def _result_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    solver_result = st.session_state.solver_result
    if not result or not solver_result or not solver_result.score_report:
        st.info("Noch kein Ergebnis vorhanden.")
        return

    score = solver_result.score_report
    _render_manual_rules_panel(result.students, st.session_state.class_configs, settings, "result")
    _render_calculation_report(solver_result, len(result.students))
    _render_standard_result(
        solver_result,
        result.students,
        st.session_state.class_configs,
        settings,
        include_review=True,
        key_suffix="ergebnis",
    )

    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
        manual_rules=_manual_rules(),
        base_messages=result.messages,
    )
    st.session_state.validation_result = validation_result
    validation_messages = validation_result.messages
    export_options = _export_candidate_options(
        solver_result,
        result.students,
        st.session_state.class_configs,
        settings,
    )
    if not export_options:
        st.error("Keine exportierbare Klassenliste vorhanden.")
        return
    export_option = _render_export_choice(export_options)
    export_blockers = _export_blocker_messages(
        result.students,
        export_option.assignments,
        export_option.score_report,
        validation_messages,
        st.session_state.class_configs,
        settings,
    )
    if export_blockers:
        st.error(
            "Finalexport gesperrt: "
            + "; ".join(export_blockers)
            + ". Es ist nur ein Prüfexport möglich."
        )
    export_bytes = export_excel(
        result.workbook_bytes,
        result.students,
        export_option.assignments,
        st.session_state.class_configs,
        export_option.score_report,
        validation_messages,
        solver_result.profile_baseline_report,
        solver_result.phase_reports,
        solver_result.profile_slack_reports,
        solver_result.profile_refinement_reports,
        include_expert_diagnostics=_expert_mode(),
        settings=settings,
        manual_rule_entries=_manual_rule_entries_for_export(),
        note_review_status_by_student=_note_review_status_by_student(),
        export_source_candidate_key=export_option.candidate_key,
        export_selection_mode=export_option.mode,
    )
    st.download_button(
        "Excel exportieren",
        data=export_bytes,
        file_name="Klassenbildung_Pruefstand_nicht_final.xlsx" if export_blockers else "Klassenbildung_Ergebnis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    _render_technical_expander(
        solver_result,
        result.students,
        st.session_state.class_configs,
        settings,
        score,
        "ergebnis",
    )


def _export_candidate_options(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[ExportCandidateOption]:
    if not solver_result.score_report:
        return []

    student_count = len(students)
    active_rules = manual_rules_module.active_manual_rules(_manual_rule_entries_for_export())
    summaries = [summary for summary in candidate_summaries(solver_result, student_count) if summary.assignments]
    scored_summaries = [
        (
            summary,
            score_solution(students, summary.assignments, settings, class_configs, active_rules),
        )
        for summary in summaries
    ]
    current_candidate_key = _candidate_key_for_assignments(solver_result.assignments, summaries) or "X"

    strict_option = ExportCandidateOption(
        option_id="current_result",
        candidate_key=current_candidate_key,
        mode="Regelkonform",
        label=f"Regelkonform: {current_candidate_key} - aktuelle Ergebnisliste",
        caption=_export_option_caption(
            "Aktuelle Ergebnisliste ohne harte Regelverletzungen. Nicht automatisch die score-beste Lösung.",
            solver_result.score_report,
        ),
        assignments=dict(solver_result.assignments),
        score_report=solver_result.score_report,
    )

    score_candidates = [
        strict_option,
        *[
            _summary_export_option(
                option_id=f"candidate_score_pool_{summary.key}",
                mode="Kandidat",
                summary=summary,
                score=score,
                caption_prefix="Dokumentierter Prüfkandidat.",
            )
            for summary, score in scored_summaries
        ],
    ]
    score_best = min(
        score_candidates,
        key=lambda option: (
            getattr(option.score_report, "total_score", 0),
            getattr(option.score_report, "isolated_friend_request_count", 0),
            option.candidate_key == "X",
        ),
    )

    options = [
        replace(
            score_best,
            option_id="score_best",
            mode="Score-beste Lösung",
            label=f"Score-beste Lösung (empfohlen): {score_best.candidate_key}",
            caption=_export_option_caption(
                "Niedrigster dokumentierter Punktwert in der Kandidatenbewertung.",
                score_best.score_report,
            ),
        ),
        strict_option,
    ]

    profile_minimal = summary_diagnostic_candidate(solver_result, student_count)
    balanced = summary_balanced_candidate(solver_result, student_count)
    social = summary_social_strongest_candidate(solver_result, student_count)
    score_by_key = {summary.key: score for summary, score in scored_summaries}
    if profile_minimal and profile_minimal.assignments and profile_minimal.key in score_by_key:
        options.append(
            _summary_export_option(
                option_id="profile_minimal",
                mode="Profilminimal",
                summary=profile_minimal,
                score=score_by_key[profile_minimal.key],
                caption_prefix="Strengere Vergleichsrichtung mit möglichst wenigen Mischklassen.",
            )
        )
    if balanced and balanced.assignments:
        options.append(
            _summary_export_option(
                option_id="balanced",
                mode="Ausgewogen",
                summary=balanced,
                score=score_by_key[balanced.key],
                caption_prefix="Profilkosten und soziale Werte gemeinsam prüfen.",
            )
        )
    if social and social.assignments:
        options.append(
            _summary_export_option(
                option_id="social",
                mode="Sozialoptimiert",
                summary=social,
                score=score_by_key[social.key],
                caption_prefix="Stärkste soziale Kennzahlen unter den Prüfkandidaten.",
            )
        )

    return options


def _candidate_key_for_assignments(assignments: dict[str, str], summaries: list) -> str | None:
    fingerprint = tuple(sorted(assignments.items()))
    for summary in summaries:
        if tuple(sorted(summary.assignments.items())) == fingerprint:
            return summary.key
    return None


def _summary_export_option(
    *,
    option_id: str,
    mode: str,
    summary,
    score,
    caption_prefix: str,
) -> ExportCandidateOption:
    return ExportCandidateOption(
        option_id=option_id,
        candidate_key=summary.key,
        mode=mode,
        label=f"{mode}: {summary.key} - {summary.name}",
        caption=_export_option_caption(caption_prefix, score),
        assignments=dict(summary.assignments),
        score_report=score,
    )


def _export_option_caption(prefix: str, score) -> str:
    return (
        f"{prefix} Punktwert {getattr(score, 'total_score', '-')}; "
        f"ohne Wunschfreund {getattr(score, 'isolated_friend_request_count', '-')}; "
        f"Freund 1 {_ratio_text(getattr(score, 'friend1_fulfilled', 0), getattr(score, 'friend1_total', 0))}; "
        f"gegenseitig {_ratio_text(getattr(score, 'mutual_friend_fulfilled', 0), getattr(score, 'mutual_friend_total', 0))}."
    )


def _render_export_choice(options: list[ExportCandidateOption]) -> ExportCandidateOption:
    st.markdown("**Exportgrundlage wählen**")
    option_by_id = {option.option_id: option for option in options}
    option_ids = list(option_by_id)
    selected_id = st.selectbox(
        "Welche Lösung soll exportiert werden?",
        options=option_ids,
        format_func=lambda option_id: option_by_id[option_id].label,
        index=0,
        key="export_candidate_option",
    )
    selected = option_by_id[selected_id]
    score_best_key = option_by_id[option_ids[0]].candidate_key
    st.caption(selected.caption)
    if selected.candidate_key != score_best_key:
        st.warning(
            f"Achtung: Die gewählte Exportgrundlage {selected.candidate_key} ist nicht die "
            f"score-beste dokumentierte Lösung. Score-beste Lösung: {score_best_key}."
        )
    else:
        st.success("Diese Exportgrundlage ist die score-beste dokumentierte Lösung.")
    return selected


def _render_calculation_report(solver_result, student_count: int) -> None:
    st.markdown("**Was die Berechnung ergeben hat**")
    st.info(optimization_progress_module.calculation_result_summary(solver_result, student_count))


def _render_technical_expander(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    score,
    key_suffix: str,
) -> None:
    with st.expander("Technische Details anzeigen", expanded=_expert_mode()):
        st.caption("Dieser Bereich ist für Admins und Fehlersuche. Für die pädagogische Entscheidung reichen die Kandidatenkarten oben.")
        _render_quality_notice(solver_result, len(students))

        stat_col_a, stat_col_b = st.columns(2)
        stat_col_a.dataframe(_overall_distribution_frame(students), width="stretch", hide_index=True)
        stat_col_b.dataframe(_assignment_quality_frame(students, solver_result.assignments, score), width="stretch", hide_index=True)

        phase_frame = _solver_phase_frame(solver_result)
        if not phase_frame.empty:
            st.subheader("Solverphasen")
            st.dataframe(phase_frame, width="stretch", hide_index=True)
        recommendation_frame = _profile_recommendation_frame(solver_result)
        if not recommendation_frame.empty:
            st.subheader("Empfohlene Prüfkandidaten")
            st.info(_profile_recommendation_text(solver_result))
            st.dataframe(recommendation_frame, width="stretch", hide_index=True)
        slack_frame = _profile_slack_frame(solver_result)
        if not slack_frame.empty:
            st.subheader("Profil-Lockerungs-Vergleich")
            st.dataframe(slack_frame, width="stretch", hide_index=True)
            _render_incumbent_cache_controls(key_suffix)
        refinement_frame = _profile_refinement_frame(solver_result)
        if not refinement_frame.empty:
            st.subheader("Vertiefungsläufe")
            st.dataframe(refinement_frame, width="stretch", hide_index=True)

        conflict_frame = _friend_profile_conflict_frame(score)
        if not conflict_frame.empty:
            st.subheader("Profilkonflikte in Freundschaften")
            st.dataframe(conflict_frame, width="stretch", hide_index=True)

        st.subheader("Pro Klasse der Diagnose-Lösung A")
        st.dataframe(score_to_class_frame(score), width="stretch", hide_index=True)

        penalty_frame = _penalty_breakdown_frame(score)
        if not penalty_frame.empty:
            st.subheader("Strafpunkte je Kategorie")
            st.dataframe(penalty_frame, width="stretch", hide_index=True)

        alert_frame = _class_alert_frame(score)
        if not alert_frame.empty:
            st.subheader("Auffällige Klassen")
            st.dataframe(alert_frame, width="stretch", hide_index=True)

        if score.unmet_friend_requests:
            st.subheader("Nicht erfüllte Freundeswünsche")
            st.dataframe(pd.DataFrame({"Meldung": score.unmet_friend_requests}), width="stretch", hide_index=True)

        if score.hard_violations:
            st.subheader("Harte Regelverletzungen")
            st.dataframe(pd.DataFrame({"Meldung": score.hard_violations}), width="stretch", hide_index=True)

        st.subheader("Rohdaten")
        st.write(_solver_debug_payload(solver_result, students, class_configs, settings, score))


def _solver_debug_payload(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    score,
) -> dict[str, object]:
    student_count = len(students)
    return {
        "solver_status": solver_result.status,
        "objective_value": solver_result.objective_value,
        "best_objective_bound": solver_result.best_objective_bound,
        "relative_gap": solver_result.relative_gap,
        "profile_status": solver_result.profile_status,
        "profile_objective_value": solver_result.profile_objective_value,
        "profile_best_objective_bound": solver_result.profile_best_objective_bound,
        "profile_relative_gap": solver_result.profile_relative_gap,
        "last_accepted_phase": solver_result.last_accepted_phase,
        "last_accepted_phase_status": solver_result.last_accepted_phase_status,
        "last_accepted_phase_gap": solver_result.last_accepted_phase_gap,
        "failed_phase": solver_result.failed_phase,
        "failed_phase_status": solver_result.failed_phase_status,
        "skipped_phase": solver_result.skipped_phase,
        "skipped_phase_status": solver_result.skipped_phase_status,
        "skipped_phase_reason": solver_result.skipped_phase_reason,
        "displayed_solution_source": solver_result.displayed_solution_source,
        "displayed_solution_gap": solver_result.displayed_solution_gap,
        "displayed_solution_gap_source": solver_result.displayed_solution_gap_source,
        "profile_min_fl_mixed_classes": solver_result.profile_min_fl_mixed_classes,
        "profile_min_music_mixed_classes": solver_result.profile_min_music_mixed_classes,
        "profile_status_fl": solver_result.profile_status_fl,
        "profile_status_music": solver_result.profile_status_music,
        "profile_gap_fl": solver_result.profile_gap_fl,
        "profile_gap_music": solver_result.profile_gap_music,
        "approval_test_status": solver_result.approval_test_status,
        "approval_test_limit_without_wishfriend": solver_result.approval_test_limit_without_wishfriend,
        "approval_test_metric_value": solver_result.approval_test_metric_value,
        "found_without_wishfriend": solver_result.found_without_wishfriend,
        "approval_threshold_without_wishfriend": solver_result.approval_threshold_without_wishfriend,
        "approval_possible_but_unproven": solver_result.approval_possible_but_unproven,
        "overall_status": _overall_status(solver_result, student_count),
        "default_review_candidate": _balanced_candidate(solver_result).variant if _balanced_candidate(solver_result) else None,
        "social_strongest_candidate": _primary_candidate(solver_result).variant if _primary_candidate(solver_result) else None,
        "fl_preserving_candidate": _fl_conservative_candidate(solver_result).variant if _fl_conservative_candidate(solver_result) else None,
        "strict_variant_role": "diagnostic_only" if solver_result.profile_slack_reports else None,
        "review_candidates_available": bool(_review_candidates(solver_result)),
        "candidate_summaries": candidate_summary_module.candidate_summary_records(solver_result, student_count),
        "candidate_reviews": candidate_review_module.candidate_review_records(solver_result, students, class_configs, settings),
        "score": score.total_score,
    }


def _manual_rule_entries_for_export():
    return list(_manual_rule_entries())


def _export_blocker_messages(
    students: list[Student],
    assignments: dict[str, str],
    score,
    validation_messages: list[ValidationMessage],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> list[str]:
    del assignments, class_configs, settings
    report = finality_module.finality_report(
        students,
        score,
        validation_messages,
        _note_review_status_by_student(),
    )
    return report.blocker_labels()


def _unreviewed_note_count(students: list[Student]) -> int:
    return finality_module.unreviewed_note_count(students, _note_review_status_by_student())


def _visible_validation_warnings(messages: list[ValidationMessage]) -> list[ValidationMessage]:
    return [
        message
        for message in messages
        if not (message.severity == "WARNUNG" and message.message == COMMENT_REVIEW_MESSAGE)
    ]


def _solver_status_text(status: str) -> tuple[str, str]:
    if status == "OPTIMAL":
        return "Beste Lösung bewiesen", "Die Berechnung hat gezeigt, dass sie mit diesen Regeln nichts Besseres findet."
    if status == "FEASIBLE":
        return "Gültige Lösung gefunden", "Die harten Regeln sind erfüllt; die Qualitätszahlen unten entscheiden, ob die Lösung pädagogisch brauchbar ist."
    if status == "INFEASIBLE":
        return "Keine gültige Lösung", "Die Regeln oder Klassengrößen widersprechen sich wahrscheinlich."
    if status == "UNKNOWN":
        return "Keine sichere Lösung im Zeitlimit", "Die Berechnung hatte innerhalb der Rechenzeit keine verwertbare Lösung."
    if status == "MISSING_DEPENDENCY":
        return "OR-Tools fehlt", "Es wurde kein vollständiger Optimierer gefunden."
    return status, "Technischer Berechnungsstatus."


def _overall_status_text(status: str) -> tuple[str, str]:
    if status == "AUTO_APPROVABLE":
        return "Automatisch freigabefähig", "Soziale Grenze und technische Qualität sind im Zielbereich."
    if status == "REVIEW_CANDIDATES_FOUND":
        return "Prüfkandidaten gefunden", "Die profilminimale Variante scheitert sozial, aber Varianten mit Profil-Lockerung erfüllen die soziale Grenze und müssen pädagogisch geprüft werden."
    if status == "STRICT_ONLY_NOT_APPROVABLE":
        return "Profilminimal nicht freigabefähig", "Nur die profilminimale Diagnose-Lösung liegt vor; die soziale Grenze wird verfehlt."
    if status == "NO_USABLE_SOLUTION_FOUND":
        return "Keine brauchbare Lösung", "Es wurde keine Lösung oder kein Kandidat gefunden, der die Qualitätsgrenzen sinnvoll erfüllt."
    return status, "Fachlicher Gesamtstatus."


def _expert_mode() -> bool:
    return bool(st.session_state.get("expert_mode", False))


def _ratio_text(fulfilled: int, total: int) -> str:
    if total <= 0:
        return "0/0"
    percent = round(fulfilled / total * 100)
    return f"{fulfilled}/{total} ({percent}%)"


def _overall_distribution_frame(students: list[Student]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for category, values in [
        ("Geschlecht", Counter(student.gender or "leer" for student in students)),
        ("Sprache", Counter(student.second_language or "leer" for student in students)),
        ("Musik", Counter(student.music_profile or "leer" for student in students)),
        ("R-Markierung", Counter("ja" if student.is_support else "nein" for student in students)),
        ("Bemerkung", Counter("ja" if student_has_manual_note(student) else "nein" for student in students)),
    ]:
        for value, count in values.items():
            rows.append({"Kategorie": category, "Wert": value, "Anzahl": count})
    return pd.DataFrame(rows)


def _friend_wish_stats(students: list[Student]) -> dict[str, int]:
    friend1 = sum(1 for student in students if student.friend1)
    friend2 = sum(1 for student in students if student.friend2)
    any_friend = sum(1 for student in students if student.friend1 or student.friend2)
    return {
        "friend1": friend1,
        "friend2": friend2,
        "any": any_friend,
        "none": len(students) - any_friend,
    }


def _assignment_quality_frame(
    students: list[Student],
    assignments: dict[str, str],
    score,
) -> pd.DataFrame:
    no_friend_wish_count = sum(1 for student in students if not student.friend1 and not student.friend2)
    comment_count = sum(1 for student in students if student_has_manual_note(student))
    assigned_count = sum(1 for student in students if assignments.get(student.internal_id))
    return pd.DataFrame(
        [
            {"Kennzahl": "Zugeordnet", "Wert": f"{assigned_count}/{len(students)}"},
            {"Kennzahl": "Ohne Freundeswunsch", "Wert": str(no_friend_wish_count)},
            {"Kennzahl": "Mit Anmerkung", "Wert": str(comment_count)},
            {"Kennzahl": "Freundeswunsch 1 erfüllt", "Wert": _ratio_text(score.friend1_fulfilled, score.friend1_total)},
            {"Kennzahl": "Freundeswunsch 2 erfüllt", "Wert": _ratio_text(score.friend2_fulfilled, score.friend2_total)},
            {"Kennzahl": "Gegenseitige Freunde erfüllt", "Wert": _ratio_text(score.mutual_friend_fulfilled, score.mutual_friend_total)},
            {"Kennzahl": "Kinder ohne Wunschfreund in Klasse", "Wert": str(score.isolated_friend_request_count)},
            {"Kennzahl": "F/L-Mischklassen", "Wert": str(score.mixed_language_class_count)},
            {"Kennzahl": "F/L-Minderheits-Schüler", "Wert": str(score.language_minority_student_count)},
            {"Kennzahl": "Musik-Mischklassen", "Wert": str(score.mixed_music_class_count)},
            {"Kennzahl": "Musik-Minderheits-Schüler", "Wert": str(score.music_minority_student_count)},
            {"Kennzahl": "Musik-Profilanteil-Fehlmenge", "Wert": str(score.music_focus_shortfall_count)},
        ]
    )


def _review_student_risk_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": row.class_id,
                "Name": row.display_name,
                "Freund 1": _friend_with_class(row.friend1, row.friend1_class),
                "Freund 2": _friend_with_class(row.friend2, row.friend2_class),
                "Notiz": "📝 Notiz vorhanden" if row.has_manual_note else "",
            }
            for row in rows
        ]
    )


def _review_friendship_risk_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klassen": f"{row.student_a_class} / {row.student_b_class}",
                "Paar": f"{row.student_a_name} / {row.student_b_name}",
                "Priorität": f"{row.priority_a} / {row.priority_b}",
                "Notiz": "📝 Notiz vorhanden" if row.has_manual_note else "",
            }
            for row in rows
        ]
    )


def _review_note_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": row.class_id,
                "Name": row.display_name,
                "Notiz": row.note_text,
                "Prüfstatus": _note_review_status_text(row.review_status),
                "Automatisch ausgewertet": "nein" if not row.automatically_evaluated else "ja",
            }
            for row in rows
        ]
    )


def _note_review_status_text(status) -> str:
    if status == manual_rules_module.NoteReviewStatus.CONVERTED_TO_RULE:
        return "in Regel umgewandelt"
    if status == manual_rules_module.NoteReviewStatus.KEPT_AS_NOTE:
        return "als Hinweis behalten"
    return "noch ungeprüft"


def _review_mixed_class_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": row.class_id,
                "Bereich": "F/L" if row.profile_type == "language" else "Musik",
                "Mehrheit": row.majority_label,
                "Minderheit": row.minority_label,
                "Minderheits-Schüler": row.minority_count,
                "Schüler": ", ".join(row.minority_students),
            }
            for row in rows
        ]
    )


def _review_class_load_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": row.class_id,
                "Größe": row.size,
                "R": row.support_count,
                "m": row.male_count,
                "w": row.female_count,
                "Geschlecht Zielzone": finality_module.gender_target_zone_text(),
                "Geschlecht Bewertung": finality_module.gender_target_status(
                    row.size,
                    row.male_count,
                    row.female_count,
                ),
                "größte Grundschule": row.largest_school_count,
                "größte Grundschule/alte Klasse": row.largest_primary_class_count,
            }
            for row in rows
        ]
    )


def _friend_with_class(name: str | None, class_id: str | None) -> str:
    if not name:
        return "-"
    return f"{name} ({class_id or '-'})"


def _quality_verdict(solver_result, student_count: int) -> dict[str, str]:
    score = solver_result.score_report
    if not score:
        return {"severity": "error", "label": "nicht freigabefähig", "message": "Keine Qualitätsauswertung vorhanden."}
    if score.hard_violations:
        return {"severity": "error", "label": "nicht freigabefähig", "message": "Harte Regelverletzungen vorhanden."}

    gap = solver_result.displayed_solution_gap if solver_result.displayed_solution_gap is not None else solver_result.relative_gap
    threshold = solver_result.approval_threshold_without_wishfriend or int(student_count * 0.15)
    isolated_share = score.isolated_friend_request_count / max(student_count, 1)
    if score.isolated_friend_request_count > threshold:
        message = (
            f"Gefundene Lösung nicht freigabefähig: "
            f"{score.isolated_friend_request_count}/{student_count} Kinder ohne Wunschfreund "
            f"({isolated_share * 100:.1f}%). Erlaubt wären höchstens {threshold}/{student_count}."
        )
        if solver_result.approval_test_status == "UNKNOWN":
            message += " Der direkte Freigabetest wurde nicht zuverlässig abgeschlossen."
        if solver_result.approval_possible_but_unproven:
            message += " Eine freigabefähige Lösung ist damit nicht widerlegt."
        review_candidates = _review_candidates(solver_result)
        if review_candidates:
            message += f" Mit Profil-Lockerung wurden {len(review_candidates)} Prüfkandidaten gefunden."
            return {
                "severity": "warning",
                "label": "Prüfkandidaten gefunden",
                "message": message,
            }
        return {"severity": "error", "label": "nicht freigabefähig", "message": message}
    if gap is None and solver_result.status != "OPTIMAL":
        return {
            "severity": "error",
            "label": "nicht freigabefähig",
            "message": "Diagnose-Lösung A wurde technisch nicht zuverlässig abgeschlossen.",
        }
    if gap is not None and gap > 0.20:
        return {
            "severity": "error",
            "label": "nicht freigabefähig",
            "message": "Die technische Prüfung der angezeigten Lösung ist zu unsicher.",
        }
    if gap is not None and gap > 0.05:
        return {
            "severity": "warning",
            "label": "nur mit Prüfung",
            "message": "Die technische Prüfung ist noch nicht eng genug für eine automatische Freigabe.",
        }
    if isolated_share > 0.10:
        return {
            "severity": "warning",
            "label": "nur mit Prüfung",
            "message": f"{score.isolated_friend_request_count} Kinder ohne Wunschfreund ({isolated_share * 100:.1f}%).",
        }
    return {"severity": "success", "label": "freigabefähig", "message": "Technische Prüfung und soziale Mindestqualität im Zielbereich."}


def _overall_status(solver_result, student_count: int) -> str:
    score = solver_result.score_report
    if not score or score.hard_violations:
        return "NO_USABLE_SOLUTION_FOUND"
    if _review_candidates(solver_result):
        return "REVIEW_CANDIDATES_FOUND"
    threshold = solver_result.approval_threshold_without_wishfriend or int(student_count * 0.15)
    gap = solver_result.displayed_solution_gap if solver_result.displayed_solution_gap is not None else solver_result.relative_gap
    if score.isolated_friend_request_count <= threshold and (solver_result.status == "OPTIMAL" or (gap is not None and gap <= 0.05)):
        return "AUTO_APPROVABLE"
    if score.isolated_friend_request_count > threshold:
        return "STRICT_ONLY_NOT_APPROVABLE"
    return "NO_USABLE_SOLUTION_FOUND"


def _review_candidates(solver_result) -> list:
    candidates = [
        report
        for report in solver_result.profile_slack_reports
        if report.variant != "A streng" and report.review_candidate and report.isolated_friend_request_count is not None
    ]
    return sorted(
        candidates,
        key=lambda report: (
            report.isolated_friend_request_count,
            -(report.mutual_friend_fulfilled or 0),
            -(report.friend1_fulfilled or 0),
        ),
    )


def _diagnostic_report(solver_result):
    for report in solver_result.profile_slack_reports:
        if report.variant == "A streng":
            return report
    return None


def _fl_conservative_candidate(solver_result):
    for report in _review_candidates(solver_result):
        if report.variant == "C Musik +2":
            return report
    return None


def _primary_candidate(solver_result):
    candidates = _review_candidates(solver_result)
    return candidates[0] if candidates else None


def _balanced_candidate(solver_result):
    candidates = _review_candidates(solver_result)
    if not candidates:
        return None
    for report in candidates:
        if report.variant == "E beide +1":
            return report
    return min(
        candidates,
        key=lambda report: (
            report.language_mixed_limit + report.music_mixed_limit,
            report.isolated_friend_request_count,
        ),
    )


def _render_decision_kpis(solver_result, student_count: int) -> None:
    review_candidates = _review_candidates(solver_result)
    diagnostic = _diagnostic_report(solver_result)
    if not review_candidates:
        st.markdown("**Angezeigte Diagnose-Lösung: A strenges Profilminimum**")
        score = solver_result.score_report
        if not score:
            return
        cols = st.columns(7)
        cols[0].metric("Harte Regelverletzungen", len(score.hard_violations))
        cols[1].metric("Freund 1", _ratio_text(score.friend1_fulfilled, score.friend1_total))
        cols[2].metric("Freund 2", _ratio_text(score.friend2_fulfilled, score.friend2_total))
        cols[3].metric("Gegenseitig", _ratio_text(score.mutual_friend_fulfilled, score.mutual_friend_total))
        cols[4].metric("F/L-Mischklassen", score.mixed_language_class_count)
        cols[5].metric("Musik-Mischklassen", score.mixed_music_class_count)
        cols[6].metric("Ohne Wunschfreund", score.isolated_friend_request_count)
        return

    st.markdown("**Entscheidungsübersicht**")
    cards = [
        ("Diagnose A", diagnostic, "strenges Profilminimum, nicht verwenden"),
        ("Sozial stärkster Kandidat", _primary_candidate(solver_result), "beste soziale Kennzahlen"),
        ("Balancierter Kandidat", _balanced_candidate(solver_result), "Profilkosten/Soziales abwägen"),
        ("F/L-schonender Kandidat", _fl_conservative_candidate(solver_result), "F/L möglichst streng, Musik gelockert"),
    ]
    unique_cards = []
    seen_variants = set()
    for title, report, caption in cards:
        if not report or report.variant in seen_variants:
            continue
        seen_variants.add(report.variant)
        unique_cards.append((title, report, caption))
    cols = st.columns(min(len(unique_cards), 4))
    for col, (title, report, caption) in zip(cols, unique_cards):
        col.metric(title, f"{report.isolated_friend_request_count}/{student_count}", help=caption)
        col.caption(
            f"{report.variant} | F1 {_ratio_text_optional(report.friend1_fulfilled, report.friend1_total)} | "
            f"gegenseitig {_ratio_text_optional(report.mutual_friend_fulfilled, report.mutual_friend_total)} | "
            f"F/L {report.mixed_language_class_count}/{report.language_mixed_limit}, "
            f"Musik {report.mixed_music_class_count}/{report.music_mixed_limit}"
        )


def _render_standard_result(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    *,
    include_review: bool,
    key_suffix: str,
) -> None:
    student_count = len(students)
    review_candidates = summary_review_candidates(solver_result, student_count)
    diagnostic = summary_diagnostic_candidate(solver_result, student_count)
    status = _overall_status(solver_result, student_count)
    status_label, _ = _overall_status_text(status)

    st.subheader("Entscheidungsvorlage")
    if review_candidates:
        st.warning(
            f"{status_label}: Die strenge Profilvariante ist sozial nicht brauchbar. "
            f"{len(review_candidates)} Varianten mit Profil-Lockerung erfüllen die soziale Mindestgrenze. "
            "Keine automatische Freigabe: pädagogische Prüfung nötig."
        )
        if diagnostic:
            st.caption(
                f"Strenge Diagnose A: {diagnostic.without_wishfriend}/{student_count} Kinder ohne Wunschfreund. "
                "Diese Variante dient nur als Begründung, warum strikt getrennte Profile hier nicht reichen."
            )
    else:
        verdict = _quality_verdict(solver_result, student_count)
        if verdict["severity"] == "error":
            st.error(f"{verdict['label']}: {verdict['message']}")
        elif verdict["severity"] == "warning":
            st.warning(f"{verdict['label']}: {verdict['message']}")
        else:
            st.success(f"{verdict['label']}: {verdict['message']}")

    _render_candidate_cards(solver_result, students, class_configs, settings, key_suffix)

    if include_review:
        _render_candidate_review(solver_result, students, class_configs, settings, key_suffix)


def _decision_candidate_cards(solver_result) -> list[tuple[str, object, str]]:
    student_count = _student_count_from_solver_result(solver_result)
    return summary_decision_candidate_cards(solver_result, student_count)


def _student_count_from_solver_result(solver_result) -> int:
    assignment_counts = [len(report.assignments or {}) for report in solver_result.profile_slack_reports]
    if solver_result.assignments:
        assignment_counts.append(len(solver_result.assignments))
    return max(assignment_counts, default=0)


def _render_candidate_cards(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    key_suffix: str,
) -> None:
    student_count = len(students)
    cards = summary_decision_candidate_cards(solver_result, student_count)
    if not cards:
        return
    st.markdown("**Prüfkandidaten**")
    summaries = candidate_summaries(solver_result, student_count)
    note_statuses = _note_review_status_by_student()
    card_reviews = {
        summary.key: candidate_review_module.build_candidate_review_model(
            summary,
            students,
            class_configs,
            settings,
            note_review_status_by_student=note_statuses,
        )
        for _, summary, _ in cards
        if summary.assignments
    }
    visible_cards = [
        (title, summary, caption, card_reviews.get(summary.key))
        for title, summary, caption in cards
        if card_reviews.get(summary.key) is None
        or card_reviews[summary.key].readiness != candidate_review_module.ReviewReadiness.BLOCKED
    ]
    blocked_reviews = [
        (title, card_reviews[summary.key])
        for title, summary, _ in cards
        if card_reviews.get(summary.key)
        and card_reviews[summary.key].readiness == candidate_review_module.ReviewReadiness.BLOCKED
    ]
    if visible_cards:
        cols = st.columns(min(len(visible_cards), 3))
        for col, (title, summary, caption, review) in zip(cols, visible_cards):
            with col.container(border=True):
                st.markdown(f"**{title}**")
                st.metric("Kinder ohne Wunschfreund", f"{summary.without_wishfriend}/{student_count}")
                st.caption(
                    f"Freund 1: {_ratio_text(summary.friend1_satisfied, summary.friend1_total)} | "
                    f"gegenseitig: {_ratio_text(summary.mutual_satisfied, summary.mutual_total)}"
                )
                st.caption(
                    f"Profil: F/L {summary.fl_mixed_actual}, Musik {summary.music_mixed_actual}"
                )
                st.caption(summary_tradeoff_text(summary, summaries))
                warnings = summary_warning_lines(summary)
                if warnings:
                    st.warning(" ".join(warnings))
                elif review and review.readiness == candidate_review_module.ReviewReadiness.NEEDS_ATTENTION:
                    st.warning(candidate_review_module.review_readiness_text(review.readiness))
                else:
                    st.info(caption)
                if st.button("Kandidat prüfen", key=f"review_candidate_{key_suffix}_{summary.key}"):
                    st.session_state.review_candidate_variant = summary.key
                    st.rerun()
    if blocked_reviews:
        with st.expander("Nicht verwendbare Varianten", expanded=False):
            for title, review in blocked_reviews:
                st.error(f"{title}: {candidate_review_module.review_readiness_text(review.readiness)}")
                blocker_messages = candidate_review_module.review_warning_messages(
                    review,
                    candidate_review_module.ReviewWarningLevel.BLOCKER,
                )
                if blocker_messages:
                    st.caption(" ".join(blocker_messages))


def _render_candidate_review(
    solver_result,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    key_suffix: str,
) -> None:
    student_count = len(students)
    cards = summary_decision_candidate_cards(solver_result, student_count)
    if not cards:
        return
    st.markdown("**Kandidatenprüfung**")
    label_by_key = {summary.key: title for title, summary, _ in cards}
    keys = [summary.key for _, summary, _ in cards]
    selected_key = st.session_state.get("review_candidate_variant")
    if selected_key not in keys:
        selected_key = keys[0]
    selected_label = st.selectbox(
        "Variante zur Prüfung",
        options=keys,
        format_func=lambda key: label_by_key.get(key, key),
        index=keys.index(selected_key),
        key=f"candidate_review_select_{key_suffix}",
    )
    st.session_state.review_candidate_variant = selected_label
    summary = next(item for _, item, _ in cards if item.key == selected_label)
    if not summary.assignments:
        st.info("Für diesen Kandidaten liegt keine Klassenzuweisung zur Detailprüfung vor.")
        return
    review = candidate_review_module.build_candidate_review_model(
        summary,
        students,
        class_configs,
        settings,
        note_review_status_by_student=_note_review_status_by_student(),
    )

    st.markdown(f"**{label_by_key.get(summary.key, summary.key)}**")
    readiness_text = candidate_review_module.review_readiness_text(review.readiness)
    if review.readiness == candidate_review_module.ReviewReadiness.BLOCKED:
        st.error(readiness_text)
    elif review.readiness == candidate_review_module.ReviewReadiness.NEEDS_ATTENTION:
        st.warning(readiness_text)
    else:
        st.success(readiness_text)

    cols = st.columns(6)
    cols[0].metric("Ohne Wunschfreund", summary.without_wishfriend)
    cols[1].metric("Freund 1", _ratio_text(summary.friend1_satisfied, summary.friend1_total))
    cols[2].metric("Gegenseitig", _ratio_text(summary.mutual_satisfied, summary.mutual_total))
    cols[3].metric("F/L", f"{summary.fl_mixed_actual}/{summary.fl_mixed_allowed}")
    cols[4].metric("Musik", f"{summary.music_mixed_actual}/{summary.music_mixed_allowed}")
    cols[5].metric("Notizen", len(review.students_with_manual_notes))
    st.caption(summary_tradeoff_text(summary, candidate_summaries(solver_result, student_count)))
    if review.warnings:
        st.caption(candidate_review_module.review_warning_count_text(review))
        blocker_messages = candidate_review_module.review_warning_messages(
            review, candidate_review_module.ReviewWarningLevel.BLOCKER
        )
        warning_messages = candidate_review_module.review_warning_messages(
            review, candidate_review_module.ReviewWarningLevel.WARNING
        )
        info_messages = candidate_review_module.review_warning_messages(
            review, candidate_review_module.ReviewWarningLevel.INFO
        )
        if blocker_messages:
            st.error(" ".join(blocker_messages))
        if warning_messages:
            st.warning(" ".join(warning_messages))
        if info_messages:
            st.info(" ".join(info_messages))

    tab_a, tab_b, tab_c, tab_d, tab_e, tab_f = st.tabs(
        [
            "Kinder ohne Wunschfreund",
            "Gegenseitige Freunde",
            "Manuelle Notizen",
            "F/L-Mischklassen",
            "Musik-Mischklassen",
            "Klassenbelastung",
        ]
    )
    with tab_a:
        isolated_frame = _review_student_risk_frame(review.students_without_wishfriend)
        if isolated_frame.empty:
            st.success("Kein Kind ist ohne Wunschfreund.")
        else:
            st.dataframe(isolated_frame, width="stretch", hide_index=True)
    with tab_b:
        mutual_frame = _review_friendship_risk_frame(review.separated_mutual_friendships)
        if mutual_frame.empty:
            st.success("Keine getrennten gegenseitigen Freundschaften.")
        else:
            st.dataframe(mutual_frame, width="stretch", hide_index=True)
    with tab_c:
        note_rows = review.students_with_manual_notes
        if not note_rows:
            st.success("Keine manuellen Notizen in diesem Kandidaten.")
        else:
            st.caption("Eindeutige Hinweise werden vorgeschlagen. Jede Notiz muss als Regel oder als Hinweis entschieden werden.")
            unreviewed_rows = [
                row for row in note_rows if row.review_status == manual_rules_module.NoteReviewStatus.UNREVIEWED
            ]
            kept_rows = [
                row for row in note_rows if row.review_status == manual_rules_module.NoteReviewStatus.KEPT_AS_NOTE
            ]
            converted_rows = [
                row for row in note_rows if row.review_status == manual_rules_module.NoteReviewStatus.CONVERTED_TO_RULE
            ]
            st.caption(
                f"{len(unreviewed_rows)} ungeprüft · {len(kept_rows)} als Hinweis behalten · "
                f"{len(converted_rows)} in Regeln umgewandelt"
            )
            _render_note_status_frame("Nicht ausgewertete Notizen", unreviewed_rows)
            _render_note_status_frame("Als Hinweis behalten", kept_rows)
            _render_note_status_frame("In Regeln umgewandelte Notizen", converted_rows)
            _render_note_rule_controls(note_rows, students, class_configs, settings, key_suffix)
    with tab_d:
        fl_frame = _review_mixed_class_frame(review.fl_mixed_classes)
        if fl_frame.empty:
            st.success("Keine F/L-Mischklassen in diesem Kandidaten.")
        else:
            st.dataframe(fl_frame, width="stretch", hide_index=True)
    with tab_e:
        music_frame = _review_mixed_class_frame(review.music_mixed_classes)
        if music_frame.empty:
            st.success("Keine Musik-Mischklassen in diesem Kandidaten.")
        else:
            st.dataframe(music_frame, width="stretch", hide_index=True)
    with tab_f:
        st.dataframe(_review_class_load_frame(review.class_load_rows), width="stretch", hide_index=True)


def _render_note_rule_controls(
    note_rows,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    key_suffix: str,
) -> None:
    st.markdown("**Notiz in Regel umwandeln**")
    note_by_id = {row.student_id: row for row in note_rows}
    note_options = list(note_by_id)
    if not note_options:
        return
    selected_note_id = st.selectbox(
        "Notiz auswählen",
        options=note_options,
        format_func=lambda student_id: note_by_id[student_id].display_name,
        key=f"note_rule_student_{key_suffix}",
    )
    selected_note = note_by_id[selected_note_id]
    st.caption(f"Manuelle Notiz: {selected_note.note_text}")
    class_ids = [config.class_id for config in class_configs]
    suggestions = note_rule_conversion_module.suggest_note_rule_actions(
        students,
        selected_note_id,
        available_class_ids=class_ids,
    )
    rule_suggestions = [suggestion for suggestion in suggestions if suggestion.has_rule]
    manual_attention = [suggestion for suggestion in suggestions if not suggestion.has_rule]
    for suggestion in rule_suggestions:
        st.info(suggestion.message)
    for suggestion in manual_attention:
        st.warning(suggestion.message)

    suggested_rule = rule_suggestions[0] if rule_suggestions else None
    action_options = [
        "Als Trennregel anlegen",
        "Als Zusammenregel anlegen",
        "Als Klassenfixierung anlegen",
        "Als erlaubte Klassen anlegen",
        "Nur als Hinweis behalten",
    ]
    suggested_action = {
        "SEPARATE": "Als Trennregel anlegen",
        "TOGETHER": "Als Zusammenregel anlegen",
        "FIX_CLASS": "Als Klassenfixierung anlegen",
        "ALLOW_CLASSES": "Als erlaubte Klassen anlegen",
    }.get(getattr(suggested_rule, "rule_type", None), "Nur als Hinweis behalten")
    action = st.radio(
        "Aktion",
        options=action_options,
        index=action_options.index(suggested_action),
        key=f"note_rule_action_{key_suffix}_{selected_note_id}",
    )

    other_student_id = None
    class_id = None
    allowed_class_ids: tuple[str, ...] = ()
    if action in {"Als Trennregel anlegen", "Als Zusammenregel anlegen"}:
        other_labels = {
            student.display_label: student.internal_id
            for student in students
            if student.internal_id != selected_note_id
        }
        if not other_labels:
            st.warning("Für eine Paarregel fehlt ein zweiter Schüler.")
            return
        suggested_student_id = (
            suggested_rule.selected_student_id
            if suggested_rule
            and (
                (action == "Als Trennregel anlegen" and suggested_rule.rule_type == "SEPARATE")
                or (action == "Als Zusammenregel anlegen" and suggested_rule.rule_type == "TOGETHER")
            )
            else None
        )
        suggested_label = next(
            (label for label, student_id in other_labels.items() if student_id == suggested_student_id),
            None,
        )
        sorted_other_labels = sorted(other_labels)
        other_label = st.selectbox(
            "Zweiter Schüler",
            options=sorted_other_labels,
            index=sorted_other_labels.index(suggested_label) if suggested_label in sorted_other_labels else 0,
            key=f"note_rule_other_{key_suffix}_{selected_note_id}",
        )
        other_student_id = other_labels[other_label]
    elif action == "Als Klassenfixierung anlegen":
        if not class_configs:
            st.warning("Für eine Klassenfixierung ist keine Zielklasse konfiguriert.")
            return
        suggested_class_id = (
            suggested_rule.class_id
            if suggested_rule and suggested_rule.rule_type == "FIX_CLASS" and suggested_rule.class_id in class_ids
            else None
        )
        class_id = st.selectbox(
            "Zielklasse",
            options=class_ids,
            index=class_ids.index(suggested_class_id) if suggested_class_id in class_ids else 0,
            key=f"note_rule_class_{key_suffix}_{selected_note_id}",
        )
    elif action == "Als erlaubte Klassen anlegen":
        if not class_configs:
            st.warning("Für eine Klassenregel sind keine Klassen konfiguriert.")
            return
        suggested_class_ids = (
            list(suggested_rule.class_ids)
            if suggested_rule and suggested_rule.rule_type == "ALLOW_CLASSES"
            else []
        )
        selected_classes = st.multiselect(
            "Erlaubte Klassen",
            options=class_ids,
            default=[class_id for class_id in suggested_class_ids if class_id in class_ids] or class_ids[:1],
            key=f"note_rule_allowed_classes_{key_suffix}_{selected_note_id}",
        )
        allowed_class_ids = tuple(selected_classes)

    if st.button("Entscheidung übernehmen", key=f"note_rule_submit_{key_suffix}_{selected_note_id}"):
        try:
            if action == "Nur als Hinweis behalten":
                result = note_rule_conversion_module.keep_note_as_hint(
                    students,
                    selected_note_id,
                    confirmed=True,
                )
                st.session_state.note_hints_kept = set(st.session_state.get("note_hints_kept", set()))
                st.session_state.note_hints_kept.add(result.student_id)
                st.info("Notiz bleibt als Hinweis erhalten.")
            else:
                rule_type = {
                    "Als Trennregel anlegen": "SEPARATE",
                    "Als Zusammenregel anlegen": "TOGETHER",
                    "Als Klassenfixierung anlegen": "FIX_CLASS",
                    "Als erlaubte Klassen anlegen": "ALLOW_CLASSES",
                }[action]
                result = note_rule_conversion_module.convert_note_to_manual_rule(
                    students,
                    selected_note_id,
                    rule_type,
                    selected_student_id=other_student_id,
                    class_id=class_id,
                    class_ids=allowed_class_ids,
                    available_class_ids=[config.class_id for config in class_configs],
                    confirmed=True,
                )
                if result.rule:
                    changed, errors = _store_manual_rule(
                        result.rule,
                        source="note",
                        students=students,
                        class_configs=class_configs,
                        settings=settings,
                        note_student_id=result.student_id,
                    )
                    if errors:
                        st.error("Diese Regel erzeugt Konflikte und wurde nicht gespeichert.")
                        st.dataframe(messages_to_frame(errors), width="stretch", hide_index=True)
                    elif changed:
                        st.success("Regel angelegt. Bitte danach neu optimieren.")
                    else:
                        st.info("Diese Regel ist bereits aktiv.")
        except note_rule_conversion_module.NoteRuleConversionError as error:
            st.error(str(error))

    active_rules = _manual_rules()
    if active_rules:
        st.caption(f"Aktive manuelle Regeln: {len(active_rules)}")


def _render_note_status_frame(title: str, rows) -> None:
    if not rows:
        return
    st.markdown(f"**{title}**")
    st.dataframe(_review_note_frame(rows), width="stretch", hide_index=True)


def _render_quality_notice(solver_result, student_count: int) -> None:
    verdict = _quality_verdict(solver_result, student_count)
    frame = _quality_summary_frame(solver_result, student_count, verdict)
    review_candidates = _review_candidates(solver_result)
    if review_candidates:
        primary = _primary_candidate(solver_result)
        balanced = _balanced_candidate(solver_result)
        fl_candidate = _fl_conservative_candidate(solver_result)
        candidate_parts = []
        for label, report in (
            ("sozial stärkste Alternative", primary),
            ("balancierter Prüfkandidat", balanced),
            ("F/L-schonender Prüfkandidat", fl_candidate),
        ):
            if report and report.variant not in {part[0] for part in candidate_parts}:
                candidate_parts.append(
                    (
                        report.variant,
                        f"{label}: {report.variant} mit {report.isolated_friend_request_count}/{student_count} ohne Wunschfreund",
                    )
                )
        st.warning(
            "Strenge Profilvariante nicht freigabefähig; "
            f"{len(review_candidates)} Prüfkandidat(en) mit Profil-Lockerung gefunden. "
            + "; ".join(part[1] for part in candidate_parts)
            + ". Keine automatische Freigabe wegen Profil-Lockerung und nicht belastbarer technischer Prüfung."
        )
    else:
        if verdict["severity"] == "error":
            st.error(f"{verdict['label']}: {verdict['message']}")
        elif verdict["severity"] == "warning":
            st.warning(f"{verdict['label']}: {verdict['message']}")
        else:
            st.success(f"{verdict['label']}: {verdict['message']}")
    if solver_result.approval_test_status:
        st.info(
            f"Strenge Diagnose A: Freigabetest ohne Wunschfreund <= "
            f"{solver_result.approval_test_limit_without_wishfriend}: {solver_result.approval_test_status}."
        )
    if solver_result.approval_possible_but_unproven:
        st.warning(
            "Unter strengen Profilgrenzen wurde keine freigabefähige soziale Lösung gefunden. "
            "Der Solver hat aber nicht bewiesen, dass eine solche Lösung mit strengem Profilminimum unmöglich ist."
        )
    if solver_result.skipped_phase:
        st.warning(
            f"Angezeigt wird die letzte akzeptierte Lösung aus {solver_result.displayed_solution_source or '-'}; "
            f"{solver_result.skipped_phase} wurde nicht gestartet."
        )
    if solver_result.failed_phase:
        st.warning(
            f"Angezeigt wird die letzte akzeptierte Lösung aus {solver_result.displayed_solution_source or '-'}; "
            f"{solver_result.failed_phase} endete mit {solver_result.failed_phase_status}."
        )
    st.dataframe(frame, width="stretch", hide_index=True)


def _quality_summary_frame(solver_result, student_count: int, verdict: dict[str, str]) -> pd.DataFrame:
    score = solver_result.score_report
    isolated_count = score.isolated_friend_request_count if score else 0
    isolated_share = isolated_count / max(student_count, 1)
    profile_gap = _max_phase_gap(solver_result.phase_reports[:2])
    review_candidates = _review_candidates(solver_result)
    review_text = "; ".join(
        f"{report.variant}: {report.isolated_friend_request_count}/{student_count}"
        for report in review_candidates[:3]
    )
    return pd.DataFrame(
        [
            {
                "Kennzahl": "Profilphase",
                "Wert": f"{solver_result.profile_status or '-'}, Gap {_percent_text(profile_gap)}",
                "Bewertung": "bewiesen" if solver_result.profile_status == "OPTIMAL" else "nicht bewiesen",
            },
            {
                "Kennzahl": "Strenge Diagnosephase",
                "Wert": f"{solver_result.status}, Gap {_percent_text(solver_result.displayed_solution_gap)}",
                "Bewertung": _gap_label(solver_result.displayed_solution_gap, solver_result.status),
            },
            {
                "Kennzahl": "Freigabetest",
                "Wert": (
                    f"Ohne Wunschfreund <= {solver_result.approval_test_limit_without_wishfriend}: "
                    f"{solver_result.approval_test_status or '-'}"
                ),
                "Bewertung": (
                    "nicht widerlegt"
                    if solver_result.approval_possible_but_unproven
                    else _value_text(solver_result.approval_test_metric_value)
                ),
            },
            {
                "Kennzahl": "Letzte akzeptierte Phase",
                "Wert": solver_result.last_accepted_phase or "-",
                "Bewertung": f"{solver_result.last_accepted_phase_status or '-'}, Gap {_percent_text(solver_result.last_accepted_phase_gap)}",
            },
            {
                "Kennzahl": "Fehlgeschlagene Phase",
                "Wert": solver_result.failed_phase or "-",
                "Bewertung": solver_result.failed_phase_status or "-",
            },
            {
                "Kennzahl": "Übersprungene Phase",
                "Wert": solver_result.skipped_phase or "-",
                "Bewertung": solver_result.skipped_phase_reason or solver_result.skipped_phase_status or "-",
            },
            {
                "Kennzahl": "Angezeigte Diagnose-Lösung A",
                "Wert": solver_result.displayed_solution_source or "-",
                "Bewertung": (
                    f"strenges Profilminimum, Gap {_percent_text(solver_result.displayed_solution_gap)}"
                    if solver_result.displayed_solution_source
                    else "-"
                ),
            },
            {
                "Kennzahl": "Kinder ohne Wunschfreund",
                "Wert": f"{isolated_count}/{student_count} ({isolated_share * 100:.1f}%)",
                "Bewertung": _isolation_label(isolated_share),
            },
            {
                "Kennzahl": "Prüfkandidaten mit Profil-Lockerung",
                "Wert": review_text or "-",
                "Bewertung": (
                    "gültige Prüfkandidaten, nicht automatisch freigegeben"
                    if review_candidates
                    else "keine soziale Variante mit Profil-Lockerung im Zielbereich"
                ),
            },
            {
                "Kennzahl": "Gesamtbewertung",
                "Wert": verdict["label"],
                "Bewertung": verdict["message"],
            },
        ]
    )


def _max_phase_gap(phases) -> float | None:
    gaps = [phase.relative_gap for phase in phases if phase.relative_gap is not None]
    return max(gaps, default=None)


def _gap_label(gap: float | None, status: str) -> str:
    if status == "OPTIMAL":
        return "bewiesen"
    if gap is None:
        return "nicht belastbar"
    if gap <= 0.05:
        return "gut"
    if gap <= 0.20:
        return "prüfen"
    return "nicht freigabefähig"


def _isolation_label(share: float) -> str:
    if share <= 0.05:
        return "gut"
    if share <= 0.10:
        return "vertretbar"
    if share <= 0.15:
        return "problematisch"
    return "nicht freigabefähig"


def _penalty_breakdown_frame(score) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Kategorie": label, "Strafpunkte": points}
            for label, points in sorted(score.category_scores.items(), key=lambda item: (-item[1], item[0]))
        ]
    )


def _solver_phase_frame(solver_result) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Phase": phase.name,
                "Status": phase.status,
                "Gap": _percent_text(phase.relative_gap),
                "Objective": _value_text(phase.objective_value),
                "Best Bound": _value_text(phase.best_objective_bound),
                "F/L-Mischklassen": _value_text(phase.mixed_language_class_count),
                "Musik-Mischklassen": _value_text(phase.mixed_music_class_count),
                "F/L-Minderheit": _value_text(phase.language_minority_student_count),
                "Musik-Minderheit": _value_text(phase.music_minority_student_count),
                "Ohne Wunschfreund": _value_text(phase.isolated_friend_request_count),
                "Freund 1": _ratio_text_optional(phase.friend1_fulfilled, phase.friend1_total),
                "Gegenseitig": _ratio_text_optional(phase.mutual_friend_fulfilled, phase.mutual_friend_total),
                "Freund 2": _ratio_text_optional(phase.friend2_fulfilled, phase.friend2_total),
            }
            for phase in solver_result.phase_reports
        ]
    )


def _profile_recommendation_frame(solver_result) -> pd.DataFrame:
    reports = _sort_decision_reports(
        [report for report in solver_result.profile_slack_reports if report.recommendation_role]
    )
    if not reports:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Entscheidung": report.recommendation_role,
                "Variante": report.variant,
                "Profil": _profile_limit_text(report),
                "Ohne Wunschfreund": _value_text(report.isolated_friend_request_count),
                "Freund 1": _ratio_text_optional(report.friend1_fulfilled, report.friend1_total),
                "Gegenseitig": _ratio_text_optional(report.mutual_friend_fulfilled, report.mutual_friend_total),
                "Einordnung": _candidate_tradeoff_text(report, solver_result),
                "Bewertung": _candidate_summary(report),
            }
            for report in reports
        ]
    )


def _profile_recommendation_text(solver_result) -> str:
    reports = [
        report
        for report in solver_result.profile_slack_reports
        if report.variant != "A streng" and report.isolated_friend_request_count is not None
    ]
    if not reports:
        return "Strenges Profilminimum ist nur Diagnose; es wurden keine auswertbaren Varianten mit Profil-Lockerung gefunden."
    threshold = solver_result.approval_threshold_without_wishfriend
    best = min(
        reports,
        key=lambda report: (
            report.isolated_friend_request_count,
            -(report.mutual_friend_fulfilled or 0),
            -(report.friend1_fulfilled or 0),
        ),
    )
    social_reports = [report for report in reports if report.social_limit_met]
    carried = [report for report in reports if report.dominance_source]
    if not social_reports:
        text = (
            "Keine Variante mit Profil-Lockerung erfüllt aktuell die soziale Freigabegrenze. "
            f"Bester gefundener Suchkandidat: {best.variant} mit "
            f"{best.isolated_friend_request_count}"
            f"{f' von erlaubt {threshold}' if threshold is not None else ''} Kindern ohne Wunschfreund."
        )
    else:
        best_social = _primary_candidate(solver_result)
        balanced = _balanced_candidate(solver_result)
        solo_music = [report for report in reports if report.variant in {"B Musik +1", "C Musik +2"} and report.social_limit_met]
        solo_language = [report for report in reports if report.variant == "D F/L +1" and report.social_limit_met]
        if not solo_music and not solo_language:
            combined_note = (
                "Der größte soziale Gewinn entsteht hier durch kombinierte Profil-Lockerung; "
                "einzelne Musik- oder F/L-Lockerung reicht in diesem Lauf nicht aus. "
                "Die Varianten werden nach Entscheidungsrolle dargestellt."
            )
        else:
            combined_note = (
                "Die Varianten werden nach Entscheidungsrolle dargestellt; der Vergleich zeigt, "
                "ob Musik-, F/L- oder kombinierte Lockerung den größten sozialen Gewinn liefert."
            )
        text = (
            f"{len(social_reports)} Variante(n) mit Profil-Lockerung erreichen die soziale Grenze. "
            f"{combined_note} "
            f"Sozial stärkster Kandidat: {best_social.variant} mit "
            f"{best_social.isolated_friend_request_count} Kindern ohne Wunschfreund."
        )
        if balanced and balanced.variant != best_social.variant:
            text += (
                f" Balancierter Kandidat: {balanced.variant} mit "
                f"{balanced.isolated_friend_request_count} Kindern ohne Wunschfreund "
                f"und weniger Profil-Lockerung."
            )
        text += " Keine automatische Freigabe, weil technische Qualität und Profil-Lockerung geprüft werden müssen."
    if carried:
        text += " Bessere gespeicherte Kandidaten bleiben auch in lockereren Varianten erhalten."
    return text


def _profile_slack_frame(solver_result, reports=None) -> pd.DataFrame:
    reports = solver_result.profile_slack_reports if reports is None else reports
    reports = _sort_decision_reports(reports)
    return pd.DataFrame(
        [
            {
                "Variante": report.variant,
                "F/L Ist": _value_text(report.mixed_language_class_count),
                "F/L erlaubt": report.language_mixed_limit,
                "Musik Ist": _value_text(report.mixed_music_class_count),
                "Musik erlaubt": report.music_mixed_limit,
                "Status": report.status,
                "Gap": _percent_text(report.relative_gap),
                "Ohne Wunschfreund": _value_text(report.isolated_friend_request_count),
                "Freund 1": _ratio_text_optional(report.friend1_fulfilled, report.friend1_total),
                "Gegenseitig": _ratio_text_optional(report.mutual_friend_fulfilled, report.mutual_friend_total),
                "Freund 2": _ratio_text_optional(report.friend2_fulfilled, report.friend2_total),
                "F/L-Minderheit": _value_text(report.language_minority_student_count),
                "Musik-Minderheit": _value_text(report.music_minority_student_count),
                "Near-Miss": _approval_text(report.near_miss),
                "Zieltest-Kandidat": _approval_text(report.candidate_for_target_test),
                "Soziale Grenze erfüllt": _approval_text(report.social_limit_met),
                "Gap belastbar": _approval_text(report.gap_reliable),
                "Profil-Lockerung nötig": _approval_text(report.profile_slack_needed),
                "Automatisch freigabefähig": _approval_text(report.approvable),
                "Kandidat für Prüfung": _approval_text(report.review_candidate),
                "Optimierung versucht": _approval_text(report.optimization_attempted),
                "Zieltest-Status": report.target_test_status or "-",
                "Vertiefung versucht": _approval_text(report.refinement_attempted),
                "Vertiefung-Status": report.refinement_status or "-",
                "Quelle": report.displayed_source or report.solution_source or "-",
                "Dominanz von": report.dominance_source or "-",
            }
            for report in reports
        ]
    )


def _sort_decision_reports(reports) -> list:
    order = {
        "A streng": 0,
        "F mehr Profil-Slack": 1,
        "E beide +1": 2,
        "C Musik +2": 3,
        "B Musik +1": 4,
        "D F/L +1": 5,
    }
    return sorted(reports, key=lambda report: (order.get(report.variant, 99), report.variant))


def _render_incumbent_cache_controls(key_suffix: str) -> None:
    with st.expander("Gespeicherte Bestkandidaten", expanded=False):
        st.caption(
            "Die App speichert lokal nur interne Schüler-IDs und Klassenzuweisungen in "
            "`config/profile_incumbents.json`, damit gute Kandidaten bei Folgeläufen nicht verloren gehen. "
            "Die Datei ist ignoriert und wird gegen den Eingabedaten-Hash validiert, bleibt aber sensible lokale Schülerdaten."
        )
        if st.button("Gespeicherte Bestkandidaten löschen", key=f"clear_profile_incumbents_{key_suffix}"):
            clear_profile_incumbent_cache()
            st.success("Gespeicherte Bestkandidaten wurden gelöscht.")


def _profile_refinement_frame(solver_result) -> pd.DataFrame:
    reports = solver_result.profile_refinement_reports
    return pd.DataFrame(
        [
            {
                "Variante": report.variant,
                "Angezeigter Status": report.status,
                "Angezeigte Quelle": report.displayed_source or report.solution_source or "-",
                "Ohne Wunschfreund": _value_text(report.isolated_friend_request_count),
                "Freund 1": _ratio_text_optional(report.friend1_fulfilled, report.friend1_total),
                "Gegenseitig": _ratio_text_optional(report.mutual_friend_fulfilled, report.mutual_friend_total),
                "F/L Ist": _value_text(report.mixed_language_class_count),
                "Musik Ist": _value_text(report.mixed_music_class_count),
                "F/L-Minderheit": _value_text(report.language_minority_student_count),
                "Musik-Minderheit": _value_text(report.music_minority_student_count),
                "Vertiefung versucht": _approval_text(report.refinement_attempted),
                "Vertiefung-Status": report.refinement_status or "-",
                "Vertiefungsergebnis": (
                    "keine Verbesserung, angezeigter Kandidat bleibt erhalten"
                    if report.refinement_attempted and (report.displayed_source or report.solution_source) == "carried_candidate"
                    else "angezeigte Lösung aus Vertiefung/Zieltest"
                ),
                "Gap": _percent_text(report.relative_gap),
                "Kandidat für Prüfung": _approval_text(report.review_candidate),
            }
            for report in reports
        ]
    )


def _profile_limit_text(report) -> str:
    return (
        f"F/L {report.mixed_language_class_count or '-'} von max. {report.language_mixed_limit}; "
        f"Musik {report.mixed_music_class_count or '-'} von max. {report.music_mixed_limit}"
    )


def _candidate_summary(report) -> str:
    if not report.social_limit_met:
        if report.near_miss:
            return "soziale Grenze knapp verfehlt; Zieltest sinnvoll"
        return "soziale Grenze nicht erfüllt"
    if report.gap_reliable:
        return "sozial im Zielbereich und Gap belastbar"
    return "gültiger Prüfkandidat, aber nicht bewiesen optimal"


def _candidate_tradeoff_text(report, solver_result) -> str:
    if report.variant == "A streng":
        return "Diagnosevariante; nicht als Hauptlösung verwenden, wenn soziale Grenze verfehlt ist."
    c = next((item for item in solver_result.profile_slack_reports if item.variant == "C Musik +2"), None)
    e = next((item for item in solver_result.profile_slack_reports if item.variant == "E beide +1"), None)
    if report.variant == "C Musik +2":
        return "F/L bleibt streng; Musik wird deutlich gelockert."
    if report.variant == "E beide +1":
        if c and c.isolated_friend_request_count is not None and report.isolated_friend_request_count is not None:
            if report.isolated_friend_request_count < c.isolated_friend_request_count:
                return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial liegt E knapp vor C."
            if report.isolated_friend_request_count == c.isolated_friend_request_count:
                return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial sind beide gleichauf."
            return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial liegt E knapp hinter C."
        return "Balanciert Profilkosten und soziale Mindestqualität."
    if report.variant == "F mehr Profil-Slack":
        if e and e.isolated_friend_request_count is not None and report.isolated_friend_request_count is not None:
            diff = e.isolated_friend_request_count - report.isolated_friend_request_count
            return f"{diff} Kinder weniger ohne Wunschfreund als E; dafür mehr Musikmischung."
        return "Sozial stärkste Variante; profilseitig teurer."
    return "-"


def _approval_text(value: bool | None) -> str:
    if value is None:
        return "-"
    return "ja" if value else "nein"


def _value_text(value: object | None) -> str:
    return "-" if value is None else str(value)


def _ratio_text_optional(fulfilled: int | None, total: int | None) -> str:
    if fulfilled is None or total is None:
        return "-"
    return _ratio_text(fulfilled, total)


def _percent_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _friend_profile_conflict_frame(score) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Konflikt": label, "Anzahl": count}
            for label, count in sorted(score.friend_profile_conflicts.items())
            if count
        ]
    )


def _class_alert_frame(score) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    findings_by_class: dict[str, list[str]] = {}
    for finding in finality_module.class_finality_findings(score):
        if finding.class_id:
            findings_by_class.setdefault(finding.class_id, []).append(finding.message)
    for report in score.class_reports:
        notes = []
        notes.extend(findings_by_class.get(report.class_id, []))
        if report.is_language_mixed:
            notes.append(f"F/L gemischt, Minderheit {report.language_minority_count}")
        if report.is_music_mixed:
            notes.append(f"Musikprofile gemischt, Minderheit {report.music_minority_count}")
        if report.music_focus_shortfall:
            notes.append(f"Musik-Profilanteil schwach ({report.music_focus_shortfall})")
        school_counts = {school: count for school, count in report.school_counts.items() if school != "leer"}
        if school_counts:
            school, count = max(school_counts.items(), key=lambda item: item[1])
            if finality_module.MAX_PRIMARY_SCHOOL_PER_CLASS >= count >= max(4, report.size // 3):
                notes.append(f"Ballung Grundschule {school} ({count})")
        if notes:
            rows.append({"Klasse": report.class_id, "Auffälligkeit": "; ".join(notes)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st

from klassenbildung.core.constants import DEFAULT_WEIGHTS
from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student, ValidationMessage
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
from klassenbildung.optimization.scoring import resolve_student_ref, score_solution
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.ui.tables import (
    class_configs_to_frame,
    comments_to_frame,
    messages_to_frame,
    score_to_class_frame,
)
from klassenbildung.validation.validator import validate_students


st.set_page_config(page_title="Klassenbildung", layout="wide")

DUMMY_EXCEL_PATH = Path("Dummy_Klassenbildung_FakeDaten.xlsx")
COMMENT_REVIEW_MESSAGE = "Bemerkung muss manuell geprüft werden."

WEIGHT_HELP = {
    "weight_mutual_friend": (
        "Zusatzgewicht, wenn zwei Schüler sich gegenseitig nennen. Das kommt zusätzlich zu den normalen "
        "Freundeswunsch-Gewichten und ist deshalb stärker als ein einseitiger Wunsch."
    ),
    "weight_friend1": (
        "Gewicht für den ersten Freundeswunsch. Höher bedeutet: Der Solver trennt Freund 1 nur, "
        "wenn andere wichtige Ziele dagegen sprechen."
    ),
    "weight_friend2": (
        "Gewicht für den zweiten Freundeswunsch. Niedriger als Freund 1, weil der erste Wunsch wichtiger zählt."
    ),
    "weight_mixed_language_class": (
        "Strafe pro Klasse, in der Französisch und Latein gemischt werden. Das verhindert unnötige Mischklassen, "
        "ohne die gewählte Fremdsprache eines Schülers zu ändern."
    ),
    "weight_mixed_music_class": (
        "Strafe pro Klasse, in der mehrere Musikprofile wie Bläser, Streicher und Gesang gemischt werden. "
        "Das reduziert Mischklassen, ohne das gewählte Musikprofil eines Schülers zu ändern."
    ),
    "weight_support_distribution": (
        "Verteilt R-/Unterstützungsmarkierungen gleichmäßiger auf die Klassen. Höher bedeutet weniger Ballung."
    ),
    "weight_gender_balance": (
        "Versucht m/w ungefähr gleichmäßig zu verteilen. Sollte niedriger bleiben als Freundeswünsche."
    ),
    "weight_primary_school": (
        "Verhindert zu starke Ballungen aus derselben abgebenden Grundschule. Es ist keine Trennungsregel."
    ),
    "weight_primary_class": (
        "Verhindert zu starke Ballungen aus derselben alten Grundschulklasse. Niedriger als Freundeswünsche halten."
    ),
    "weight_nationality": (
        "Sehr schwache Verteilung nach Staat/Nationalität. In der Regel niedrig halten oder auf 0 setzen."
    ),
    "weight_religion": (
        "Sehr schwache Verteilung nach Religion. Standard ist 0, weil sie normalerweise keine Klassenentscheidung treiben soll."
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
    settings = _current_settings()

    tabs = st.tabs(
        [
            "1 Excel prüfen",
            "2 Einstellungen",
            "3 Berechnen",
            "4 Ergebnis",
            "5 Editor",
            "6 Details",
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
    with tabs[4]:
        _editor_tab(settings)
    with tabs[5]:
        _class_config_tab()
        _comments_tab()


def _init_state() -> None:
    st.session_state.setdefault("settings", load_settings())
    st.session_state.settings = coerce_settings(st.session_state.settings)
    st.session_state.setdefault("class_configs", load_class_configs())
    st.session_state.setdefault("import_result", None)
    st.session_state.setdefault("validation_result", None)
    st.session_state.setdefault("solver_result", None)


def _current_settings() -> OptimizationSettings:
    current: OptimizationSettings = coerce_settings(st.session_state.settings)
    current = _migrate_previous_default_weights(current)
    current = _disable_fixed_profile_routing(current)
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
    return settings


def _disable_fixed_profile_routing(settings: OptimizationSettings) -> OptimizationSettings:
    return replace(
        settings,
        enforce_music_profile=False,
        enforce_language_profile=False,
        weight_music_profile=0,
        weight_language_profile=0,
    )


def _settings_tab() -> None:
    current = _current_settings()
    result = st.session_state.import_result

    st.subheader("Klassenrahmen und Rechenzeit")
    total_students = len(result.students) if result else 210
    class_configs: list[ClassConfig] = st.session_state.class_configs
    col1, col2, col3 = st.columns(3)
    class_count = col1.number_input(
        "Anzahl Klassen",
        min_value=1,
        max_value=15,
        value=len(class_configs) or 7,
        key="settings_class_count",
    )
    max_size = col2.number_input(
        "Max. Klassengröße",
        min_value=1,
        max_value=40,
        value=30,
        key="settings_max_size",
    )
    time_limit = col3.select_slider(
        "Max. Rechenzeit",
        options=[10, 30, 60, 120],
        value=current.solver_time_limit_seconds,
        key="settings_time_limit",
    )
    st.caption(
        "Die Rechenzeit ist eine Obergrenze: der Solver liefert eine gültige Lösung, sobald er eine findet, "
        "und nutzt die Restzeit nur, um sie weiter zu verbessern oder zu beweisen."
    )

    preview_configs = generate_class_configs(
        total_students=total_students,
        class_count=int(class_count),
        year=5,
        max_size=int(max_size),
        existing_profiles=class_configs,
    )
    preview_configs = _without_generated_labels(preview_configs)
    st.dataframe(_class_size_preview_frame(preview_configs), width="stretch", hide_index=True)

    st.subheader("Gewichtungen")
    st.info(
        "Sprache und Musikprofil bleiben immer beim Schüler erhalten. Es gibt keine harte Zuordnung zu "
        "vorgefertigten F-, L-, Bläser-, Streicher- oder Gesangsklassen. Mischklassen sind erlaubt; "
        "die Slider steuern nur, wie stark der Solver unnötige Mischklassen vermeiden soll."
    )
    st.caption("Große Zahl = wichtiger. 0 bedeutet: dieses weiche Kriterium wird ignoriert.")
    if st.button("Empfohlene Gewichtungen laden", key="settings_reset_weights"):
        current = _disable_fixed_profile_routing(replace(current, **DEFAULT_WEIGHTS))
        save_settings(current)
        st.session_state.settings = current
        st.session_state.solver_result = None
        st.rerun()

    st.markdown("**Freundeswünsche**")
    weight_mutual_friend = _weight_slider(
        "Gegenseitige Freunde zusammenhalten",
        "weight_mutual_friend",
        current.weight_mutual_friend,
        max_value=10000,
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
        max_value=3000,
        step=50,
    )

    st.markdown("**Mischklassen vermeiden**")
    weight_mixed_language_class = _weight_slider(
        "F/L-Mischklassen vermeiden",
        "weight_mixed_language_class",
        current.weight_mixed_language_class,
        max_value=150000,
        step=1000,
    )
    weight_mixed_music_class = _weight_slider(
        "Musik-Mischklassen vermeiden",
        "weight_mixed_music_class",
        current.weight_mixed_music_class,
        max_value=150000,
        step=1000,
    )

    advanced = _advanced_weight_values(current)
    with st.expander("Weitere Gewichtungen", expanded=False):
        advanced = _advanced_weight_controls(current)

    settings = OptimizationSettings(
        enforce_music_profile=False,
        enforce_language_profile=False,
        weight_music_profile=0,
        weight_language_profile=0,
        weight_mixed_language_class=weight_mixed_language_class,
        weight_mixed_music_class=weight_mixed_music_class,
        weight_friend1=weight_friend1,
        weight_friend2=weight_friend2,
        weight_mutual_friend=weight_mutual_friend,
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
        "weight_nationality": current.weight_nationality,
        "weight_religion": current.weight_religion,
        "weight_keep_existing": 0,
    }


def _advanced_weight_controls(current: OptimizationSettings) -> dict[str, int]:
    return {
        "weight_support_distribution": _weight_slider(
            "R-Verteilung",
            "weight_support_distribution",
            current.weight_support_distribution,
            max_value=2000,
            step=50,
        ),
        "weight_gender_balance": _weight_slider(
            "Geschlecht",
            "weight_gender_balance",
            current.weight_gender_balance,
            max_value=500,
            step=10,
        ),
        "weight_primary_school": _weight_slider(
            "Grundschule",
            "weight_primary_school",
            current.weight_primary_school,
            max_value=500,
            step=10,
        ),
        "weight_primary_class": _weight_slider(
            "Grundschulklasse",
            "weight_primary_class",
            current.weight_primary_class,
            max_value=500,
            step=10,
        ),
        "weight_nationality": _weight_slider(
            "Staat/Nationalität",
            "weight_nationality",
            current.weight_nationality,
            max_value=100,
            step=5,
        ),
        "weight_religion": _weight_slider(
            "Religion",
            "weight_religion",
            current.weight_religion,
            max_value=100,
            step=5,
        ),
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
    return [replace(config, label=config.class_id) for config in class_configs]


def _class_size_preview_frame(class_configs: list[ClassConfig]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": config.class_id,
                "min": config.size_min,
                "max": config.size_max,
            }
            for config in class_configs
        ]
    )


def _detected_import_frame(sheet_names: list[str], detected_classes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Bereich": "Blätter", "Wert": ", ".join(sheet_names) or "-"},
            {"Bereich": "Klassen", "Wert": ", ".join(detected_classes) or "-"},
        ]
    )


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
            st.session_state.import_result = result
            st.session_state.validation_result = None
            st.session_state.solver_result = None
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
        st.session_state.import_result = result
        st.session_state.validation_result = None
        st.session_state.solver_result = None

    result = st.session_state.import_result
    if not result:
        st.info("Noch keine Datei geladen.")
        return

    st.subheader(result.source_filename or "Excel-Datei")
    stats = build_import_statistics(result.students)
    friend_stats = _friend_wish_stats(result.students)

    st.markdown("**Dateiüberblick**")
    cols = st.columns(4)
    cols[0].metric("Schüler", stats["student_count"])
    cols[1].metric("Klassen", len(result.detected_classes))
    cols[2].metric("Bemerkungen", stats["comment_count"])
    cols[3].metric("R-Markierungen", stats["support_count"])

    info_col, wish_col = st.columns([1, 1])
    with info_col:
        st.markdown("**Erkannt**")
        st.dataframe(_detected_import_frame(result.sheet_names, result.detected_classes), width="stretch", hide_index=True)
    with wish_col:
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
        base_messages=result.messages,
    )
    st.session_state.validation_result = validation_result
    if validation_result.has_errors:
        st.error("Diese Datei hat blockierende Fehler.")
        st.dataframe(messages_to_frame(validation_result.errors), width="stretch", hide_index=True)
    else:
        st.success("Datei ist für die Optimierung nutzbar.")
        visible_warnings = _visible_validation_warnings(validation_result.warnings)
        if visible_warnings:
            st.warning(f"{len(visible_warnings)} Dinge bitte in der Excel-Datei prüfen.")
            st.dataframe(messages_to_frame(visible_warnings), width="stretch", hide_index=True)


def _validation_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    if not result:
        st.info("Erst eine Excel-Datei hochladen.")
        return
    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
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
                    help="Harte Regel: Nur Schüler mit einem dieser Musikprofile dürfen in diese Klasse. Leer bedeutet: alle Musikprofile sind möglich.",
                )
                languages = st.multiselect(
                    "Sprachangebot",
                    options=["F", "L"],
                    default=config.languages_allowed,
                    key=f"lang_{config.class_id}",
                    help="Harte Regel: Nur Schüler mit einer dieser Fremdsprachen dürfen in diese Klasse. Leer bedeutet: beide Sprachen sind möglich.",
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
        base_messages=result.messages,
    )
    if validation_result.has_errors:
        st.error("Optimierung blockiert, weil Fehler gefunden wurden.")
        st.dataframe(messages_to_frame(validation_result.errors), width="stretch")
        return

    if st.button("Klassen vorschlagen", type="primary"):
        status_box = st.empty()
        started_at = perf_counter()
        status_box.info("Optimierung läuft. Der PC rechnet gerade...")
        with st.spinner("Klassen werden berechnet..."):
            solver_result = solve_assignments(result.students, st.session_state.class_configs, settings)
        st.session_state.solver_result = solver_result
        elapsed = perf_counter() - started_at
        if solver_result.status in {"OPTIMAL", "FEASIBLE"}:
            status_box.success(f"Optimierung fertig nach {elapsed:.1f} Sekunden.")
        else:
            status_box.error(f"Optimierung beendet nach {elapsed:.1f} Sekunden: {solver_result.status}")

    solver_result = st.session_state.solver_result
    if solver_result:
        status_label, status_hint = _solver_status_text(solver_result.status)
        st.metric("Ergebnis", status_label)
        st.caption(status_hint)
        if solver_result.message:
            st.info(solver_result.message)
        if solver_result.score_report:
            score = solver_result.score_report
            cols = st.columns(6)
            cols[0].metric("Harte Regelverletzungen", len(score.hard_violations))
            cols[1].metric("Freundeswunsch 1 erfüllt", _ratio_text(score.friend1_fulfilled, score.friend1_total))
            cols[2].metric("Freundeswunsch 2 erfüllt", _ratio_text(score.friend2_fulfilled, score.friend2_total))
            cols[3].metric("Gegenseitige Freunde", _ratio_text(score.mutual_friend_fulfilled, score.mutual_friend_total))
            cols[4].metric("F/L-Mischklassen", score.mixed_language_class_count)
            cols[5].metric("Musik-Mischklassen", score.mixed_music_class_count)
            if score.hard_violations:
                st.error("Das Ergebnis enthält harte Regelverletzungen und sollte so nicht exportiert werden.")
            else:
                st.success("0 harte Regelverletzungen")
            with st.expander("Technische Details", expanded=False):
                st.write(
                    {
                        "solver_status": solver_result.status,
                        "objective_value": solver_result.objective_value,
                        "score": score.total_score,
                    }
                )


def _result_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    solver_result = st.session_state.solver_result
    if not result or not solver_result or not solver_result.score_report:
        st.info("Noch kein Ergebnis vorhanden.")
        return

    score = solver_result.score_report
    cols = st.columns(7)
    cols[0].metric("Schüler", len(result.students))
    cols[1].metric("Klassen", len(st.session_state.class_configs))
    cols[2].metric("Freundeswunsch 1 erfüllt", _ratio_text(score.friend1_fulfilled, score.friend1_total))
    cols[3].metric("Freundeswunsch 2 erfüllt", _ratio_text(score.friend2_fulfilled, score.friend2_total))
    cols[4].metric("Gegenseitige Freunde", _ratio_text(score.mutual_friend_fulfilled, score.mutual_friend_total))
    cols[5].metric("F/L-Mischklassen", score.mixed_language_class_count)
    cols[6].metric("Musik-Mischklassen", score.mixed_music_class_count)

    st.subheader("Gesamtstatistik")
    stat_col_a, stat_col_b = st.columns(2)
    stat_col_a.dataframe(_overall_distribution_frame(result.students), width="stretch", hide_index=True)
    stat_col_b.dataframe(_assignment_quality_frame(result.students, solver_result.assignments, score), width="stretch", hide_index=True)

    st.subheader("Pro Klasse")
    st.dataframe(score_to_class_frame(score), width="stretch", hide_index=True)

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

    validation_messages = st.session_state.validation_result.messages if st.session_state.validation_result else []
    export_bytes = export_excel(
        result.workbook_bytes,
        result.students,
        solver_result.assignments,
        st.session_state.class_configs,
        score,
        validation_messages,
    )
    st.download_button(
        "Excel exportieren",
        data=export_bytes,
        file_name="Klassenbildung_Ergebnis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _editor_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    solver_result = st.session_state.solver_result
    if not result or not solver_result or not solver_result.score_report:
        st.info("Erst ein Ergebnis berechnen.")
        return

    assignments = dict(solver_result.assignments)
    score = solver_result.score_report
    st.subheader("Manuell nachsteuern")
    cols = st.columns(4)
    cols[0].metric("Freundeswunsch 1 erfüllt", _ratio_text(score.friend1_fulfilled, score.friend1_total))
    cols[1].metric("Freundeswunsch 2 erfüllt", _ratio_text(score.friend2_fulfilled, score.friend2_total))
    cols[2].metric("Gegenseitig", f"{score.mutual_friend_fulfilled}/{score.mutual_friend_total}")
    cols[3].metric("Harte Verletzungen", len(score.hard_violations))

    class_ids = [config.class_id for config in st.session_state.class_configs]
    if result.students:
        st.session_state.setdefault("editor_selected_student", result.students[0].internal_id)

    table_col, detail_col = st.columns([2, 1])
    with table_col:
        st.caption("Klicke eine Zeile an oder wähle rechts eine Person aus. Verschieben passiert rechts im Detailbereich.")
        for config in st.session_state.class_configs:
            frame = _student_assignment_frame(result.students, assignments, class_id=config.class_id)
            with st.expander(f"{config.class_id} ({len(frame)} Schüler)", expanded=True):
                if frame.empty:
                    st.info("Keine Schüler in dieser Klasse.")
                    continue
                event = st.dataframe(
                    frame,
                    width="stretch",
                    hide_index=True,
                    column_order=[
                        "Nr",
                        "Name",
                        "Sprache",
                        "Musik",
                        "R",
                        "Anmerkung",
                        "Freundeswunsch 1 erfüllt",
                        "Freundeswunsch 2 erfüllt",
                        "Zufriedenheit",
                    ],
                    key=f"editor_table_{config.class_id}",
                    on_select="rerun",
                    selection_mode="single-row",
                )
                selected_rows = _selected_row_indexes(event)
                if selected_rows:
                    st.session_state.editor_selected_student = frame.iloc[selected_rows[0]]["internal_id"]

    with detail_col:
        labels = {student.display_label: student.internal_id for student in result.students}
        label_options = sorted(labels)
        selected_id = st.session_state.get("editor_selected_student")
        if selected_id not in set(labels.values()) and result.students:
            selected_id = result.students[0].internal_id
        selected_label_by_id = {value: label for label, value in labels.items()}
        selected_index = (
            label_options.index(selected_label_by_id[selected_id])
            if selected_id in selected_label_by_id
            else 0
        )
        selected_label = st.selectbox("Person", options=label_options, index=selected_index)
        selected = next(student for student in result.students if student.internal_id == labels[selected_label])
        st.session_state.editor_selected_student = selected.internal_id
        current_class = assignments.get(selected.internal_id, "")

        st.subheader("Person")
        person_data = {
            "Nr": selected.nr,
            "Name": selected.full_name,
            "aktuelle Klasse": current_class,
            "Sprache": selected.second_language,
            "Musik": selected.music_profile,
            "Geschlecht": selected.gender,
            "R-Markierung": "ja" if selected.is_support else "nein",
            "Grundschule": selected.school,
            "Grundschulklasse": selected.primary_class,
            "Freundeswunsch 1": selected.friend1,
            "Freundeswunsch 2": selected.friend2,
        }
        st.table(pd.DataFrame(person_data.items(), columns=["Feld", "Wert"]))
        if selected.comment:
            st.warning(f"Anmerkung: {selected.comment}")
        else:
            st.info("Keine Anmerkung.")

        st.dataframe(
            _student_friend_detail_frame(selected, result.students, assignments),
            width="stretch",
            hide_index=True,
        )

        satisfaction = _student_satisfaction(selected, result.students, assignments)
        st.metric("Zufriedenheit", satisfaction["display"])
        st.progress(satisfaction["percent"] / 100 if satisfaction["percent"] >= 0 else 0.0)

        st.subheader("Klasse ändern")
        target_index = class_ids.index(current_class) if current_class in class_ids else 0
        target_class = st.selectbox("Neue Klasse", options=class_ids, index=target_index)
        if st.button("Schüler verschieben", type="primary", disabled=target_class == current_class):
            updated_assignments = dict(assignments)
            updated_assignments[selected.internal_id] = target_class
            updated_score = score_solution(
                result.students,
                updated_assignments,
                settings,
                st.session_state.class_configs,
            )
            st.session_state.solver_result = replace(
                solver_result,
                assignments=updated_assignments,
                score_report=updated_score,
                message="Manuell angepasst.",
            )
            st.success(f"{selected.display_label} wurde nach {target_class} verschoben.")
            st.rerun()


def _student_assignment_frame(
    students: list[Student],
    assignments: dict[str, str],
    class_id: str | None = None,
) -> pd.DataFrame:
    rows = []
    for student in students:
        assigned_class = assignments.get(student.internal_id)
        if class_id and assigned_class != class_id:
            continue
        satisfaction = _student_satisfaction(student, students, assignments)
        friend_statuses = _student_friend_statuses(student, students, assignments)
        rows.append(
            {
                "internal_id": student.internal_id,
                "Klasse": assigned_class,
                "Nr": student.nr,
                "Name": student.full_name,
                "Sprache": student.second_language,
                "Musik": student.music_profile,
                "R": "ja" if student.is_support else "",
                "Anmerkung": "JA" if student.comment else "",
                "Freundeswunsch 1 erfüllt": friend_statuses["friend1"]["label"],
                "Freundeswunsch 2 erfüllt": friend_statuses["friend2"]["label"],
                "Zufriedenheit": satisfaction["display"],
            }
        )
    columns = [
        "internal_id",
        "Klasse",
        "Nr",
        "Name",
        "Sprache",
        "Musik",
        "R",
        "Anmerkung",
        "Freundeswunsch 1 erfüllt",
        "Freundeswunsch 2 erfüllt",
        "Zufriedenheit",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    return frame.sort_values(["Klasse", "Name"], na_position="last")


def _student_satisfaction(
    student: Student,
    students: list[Student],
    assignments: dict[str, str],
) -> dict[str, object]:
    statuses = _student_friend_statuses(student, students, assignments).values()
    checks = [status["fulfilled"] for status in statuses if status["counts"]]

    if not checks:
        return {"label": "keine Freundeswünsche", "percent": -1, "display": "-"}

    fulfilled = sum(1 for item in checks if item is True)
    percent = int(round(fulfilled / len(checks) * 100))
    return {
        "label": f"{fulfilled}/{len(checks)}",
        "percent": percent,
        "display": f"{percent}% ({fulfilled}/{len(checks)})",
    }


def _student_friend_statuses(
    student: Student,
    students: list[Student],
    assignments: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        "friend1": _friend_status(student, students, assignments, student.friend1),
        "friend2": _friend_status(student, students, assignments, student.friend2),
    }


def _friend_status(
    student: Student,
    students: list[Student],
    assignments: dict[str, str],
    friend_ref: str | None,
) -> dict[str, object]:
    if not friend_ref:
        return {
            "label": "kein Wunsch",
            "fulfilled": None,
            "counts": False,
            "friend_label": "-",
            "friend_class": "-",
        }
    friend = resolve_student_ref(students, friend_ref)
    if not friend:
        return {
            "label": "nicht gefunden",
            "fulfilled": False,
            "counts": True,
            "friend_label": friend_ref,
            "friend_class": "-",
        }
    same_class = assignments.get(student.internal_id) == assignments.get(friend.internal_id)
    return {
        "label": "ja" if same_class else "nein",
        "fulfilled": same_class,
        "counts": True,
        "friend_label": friend.display_label,
        "friend_class": assignments.get(friend.internal_id, "-"),
    }


def _student_friend_detail_frame(
    student: Student,
    students: list[Student],
    assignments: dict[str, str],
) -> pd.DataFrame:
    statuses = _student_friend_statuses(student, students, assignments)
    return pd.DataFrame(
        [
            {
                "Wunsch": "Freundeswunsch 1",
                "Eintrag": student.friend1 or "-",
                "Person": statuses["friend1"]["friend_label"],
                "Klasse": statuses["friend1"]["friend_class"],
                "Erfüllt": statuses["friend1"]["label"],
            },
            {
                "Wunsch": "Freundeswunsch 2",
                "Eintrag": student.friend2 or "-",
                "Person": statuses["friend2"]["friend_label"],
                "Klasse": statuses["friend2"]["friend_class"],
                "Erfüllt": statuses["friend2"]["label"],
            },
        ]
    )


def _visible_validation_warnings(messages: list[ValidationMessage]) -> list[ValidationMessage]:
    return [
        message
        for message in messages
        if not (message.severity == "WARNUNG" and message.message == COMMENT_REVIEW_MESSAGE)
    ]


def _solver_status_text(status: str) -> tuple[str, str]:
    if status == "OPTIMAL":
        return "Beste Lösung bewiesen", "Der Solver hat bewiesen, dass er mit diesen Regeln nichts Besseres findet."
    if status == "FEASIBLE":
        return "Gültige Lösung gefunden", "Die Einteilung erfüllt die harten Regeln. Mehr Rechenzeit kann sie eventuell verbessern."
    if status == "INFEASIBLE":
        return "Keine gültige Lösung", "Die Regeln oder Klassengrößen widersprechen sich wahrscheinlich."
    if status == "UNKNOWN":
        return "Keine sichere Lösung im Zeitlimit", "Der Solver hatte innerhalb der Rechenzeit keine verwertbare Lösung."
    if status == "MISSING_DEPENDENCY":
        return "OR-Tools fehlt", "Es wurde kein vollständiger Optimierer gefunden."
    return status, "Technischer Solverstatus."


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
        ("Bemerkung", Counter("ja" if student.comment else "nein" for student in students)),
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
    comment_count = sum(1 for student in students if student.comment)
    assigned_count = sum(1 for student in students if assignments.get(student.internal_id))
    return pd.DataFrame(
        [
            {"Kennzahl": "Zugeordnet", "Wert": f"{assigned_count}/{len(students)}"},
            {"Kennzahl": "Ohne Freundeswunsch", "Wert": str(no_friend_wish_count)},
            {"Kennzahl": "Mit Anmerkung", "Wert": str(comment_count)},
            {"Kennzahl": "Freundeswunsch 1 erfüllt", "Wert": _ratio_text(score.friend1_fulfilled, score.friend1_total)},
            {"Kennzahl": "Freundeswunsch 2 erfüllt", "Wert": _ratio_text(score.friend2_fulfilled, score.friend2_total)},
            {"Kennzahl": "Gegenseitige Freunde erfüllt", "Wert": _ratio_text(score.mutual_friend_fulfilled, score.mutual_friend_total)},
            {"Kennzahl": "F/L-Mischklassen", "Wert": str(score.mixed_language_class_count)},
            {"Kennzahl": "Musik-Mischklassen", "Wert": str(score.mixed_music_class_count)},
        ]
    )


def _class_alert_frame(score) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for report in score.class_reports:
        notes = []
        if report.is_language_mixed:
            notes.append("F/L gemischt")
        if report.is_music_mixed:
            notes.append("Musikprofile gemischt")
        if report.support_count >= 4:
            notes.append(f"viele R-Markierungen ({report.support_count})")
        school_counts = {school: count for school, count in report.school_counts.items() if school != "leer"}
        if school_counts:
            school, count = max(school_counts.items(), key=lambda item: item[1])
            if count >= max(4, report.size // 3):
                notes.append(f"Ballung Grundschule {school} ({count})")
        if notes:
            rows.append({"Klasse": report.class_id, "Auffälligkeit": "; ".join(notes)})
    return pd.DataFrame(rows)


def _selected_row_indexes(event) -> list[int]:
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection", {})
    rows = getattr(selection, "rows", None)
    if rows is None and isinstance(selection, dict):
        rows = selection.get("rows", [])
    return list(rows or [])


if __name__ == "__main__":
    main()

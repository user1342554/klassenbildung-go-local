from __future__ import annotations

import pandas as pd
import streamlit as st

from klassenbildung.core.models import ClassConfig, OptimizationSettings
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
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.ui.tables import (
    class_configs_to_frame,
    comments_to_frame,
    messages_to_frame,
    score_to_class_frame,
)
from klassenbildung.validation.validator import validate_students


st.set_page_config(page_title="Klassenbildung", layout="wide")


def main() -> None:
    st.title("Klassenbildung")

    _init_state()
    settings = _settings_panel()

    tabs = st.tabs(
        [
            "1 Upload",
            "2 Datenprüfung",
            "3 Klassen",
            "4 Optimierung",
            "5 Ergebnis",
            "6 Bemerkungen",
        ]
    )

    with tabs[0]:
        _upload_tab()
    with tabs[1]:
        _validation_tab(settings)
    with tabs[2]:
        _class_config_tab()
    with tabs[3]:
        _optimization_tab(settings)
    with tabs[4]:
        _result_tab(settings)
    with tabs[5]:
        _comments_tab()


def _init_state() -> None:
    st.session_state.setdefault("settings", load_settings())
    st.session_state.settings = coerce_settings(st.session_state.settings)
    st.session_state.setdefault("class_configs", load_class_configs())
    st.session_state.setdefault("import_result", None)
    st.session_state.setdefault("validation_result", None)
    st.session_state.setdefault("solver_result", None)


def _settings_panel() -> OptimizationSettings:
    current: OptimizationSettings = coerce_settings(st.session_state.settings)
    st.session_state.settings = current
    with st.sidebar:
        st.header("Regeln")
        enforce_music = st.checkbox("Musikprofil hart", value=current.enforce_music_profile)
        enforce_language = st.checkbox("Fremdsprache hart", value=current.enforce_language_profile)
        st.header("Gewichtungen")
        soft_profile_weights = {
            "weight_music_profile": current.weight_music_profile,
            "weight_language_profile": current.weight_language_profile,
        }
        if not enforce_music:
            soft_profile_weights["weight_music_profile"] = st.slider(
                "Musikprofil-Abweichung",
                0,
                3000,
                current.weight_music_profile,
                step=50,
            )
        if not enforce_language:
            soft_profile_weights["weight_language_profile"] = st.slider(
                "Fremdsprachen-Abweichung",
                0,
                3000,
                current.weight_language_profile,
                step=50,
            )
        weights = {
            **soft_profile_weights,
            "weight_friend1": st.slider("Freund 1", 0, 3000, current.weight_friend1, step=50),
            "weight_friend2": st.slider("Freund 2", 0, 1500, current.weight_friend2, step=50),
            "weight_support_distribution": st.slider("R-Verteilung", 0, 1000, current.weight_support_distribution, step=25),
            "weight_gender_balance": st.slider("Geschlecht", 0, 500, current.weight_gender_balance, step=10),
            "weight_primary_school": st.slider("Grundschule", 0, 500, current.weight_primary_school, step=10),
            "weight_primary_class": st.slider("Grundschulklasse", 0, 500, current.weight_primary_class, step=10),
            "weight_nationality": st.slider("Staat/Nationalität", 0, 200, current.weight_nationality, step=5),
            "weight_religion": st.slider("Religion", 0, 200, current.weight_religion, step=5),
            "weight_keep_existing": st.slider("bestehende Einteilung behalten", 0, 1000, current.weight_keep_existing, step=25),
        }
        time_limit = st.select_slider("Zeitlimit Solver", options=[10, 30, 60, 120], value=current.solver_time_limit_seconds)
        if st.button("Einstellungen speichern"):
            settings = OptimizationSettings(
                enforce_music_profile=enforce_music,
                enforce_language_profile=enforce_language,
                solver_time_limit_seconds=time_limit,
                **weights,
            )
            save_settings(settings)
            st.session_state.settings = settings
            st.success("Einstellungen gespeichert.")

    return OptimizationSettings(
        enforce_music_profile=enforce_music,
        enforce_language_profile=enforce_language,
        solver_time_limit_seconds=time_limit,
        **weights,
    )


def _upload_tab() -> None:
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
    cols = st.columns(4)
    stats = build_import_statistics(result.students)
    cols[0].metric("Schüler", stats["student_count"])
    cols[1].metric("Klassen", len(result.detected_classes))
    cols[2].metric("Bemerkungen", stats["comment_count"])
    cols[3].metric("R-Markierungen", stats["support_count"])

    st.write("Erkannte Blätter:", ", ".join(result.sheet_names))
    st.write("Erkannte Klassen:", ", ".join(result.detected_classes) or "keine")

    col_a, col_b, col_c = st.columns(3)
    col_a.dataframe(pd.DataFrame(stats["languages"].items(), columns=["Sprache", "Anzahl"]), use_container_width=True)
    col_b.dataframe(pd.DataFrame(stats["gender"].items(), columns=["Geschlecht", "Anzahl"]), use_container_width=True)
    col_c.dataframe(pd.DataFrame(stats["music"].items(), columns=["Musik", "Anzahl"]), use_container_width=True)


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
    st.dataframe(messages_to_frame(validation_result.messages), use_container_width=True)
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
        st.dataframe(frame, use_container_width=True)


def _class_config_tab() -> None:
    result = st.session_state.import_result
    class_configs: list[ClassConfig] = st.session_state.class_configs

    total_students = len(result.students) if result else 210
    col1, col2, col3 = st.columns(3)
    class_count = col1.number_input("Anzahl Klassen", min_value=1, max_value=15, value=len(class_configs) or 7)
    year = col2.number_input("Jahrgang", min_value=1, max_value=13, value=5)
    max_size = col3.number_input("Maximale Klassengröße", min_value=1, max_value=40, value=30)

    if st.button("Klassen aus Schülerzahl erzeugen"):
        st.session_state.class_configs = generate_class_configs(
            total_students=total_students,
            class_count=int(class_count),
            year=int(year),
            max_size=int(max_size),
            existing_profiles=class_configs,
        )
        st.rerun()

    edited_configs: list[ClassConfig] = []
    for config in st.session_state.class_configs:
        with st.expander(config.class_id, expanded=False):
            label = st.text_input("Label", value=config.label, key=f"label_{config.class_id}")
            music = st.multiselect(
                "Musik erlaubt",
                options=["Reg", "B", "S", "G"],
                default=config.music_allowed,
                key=f"music_{config.class_id}",
            )
            languages = st.multiselect(
                "Sprache erlaubt",
                options=["F", "L"],
                default=config.languages_allowed,
                key=f"lang_{config.class_id}",
            )
            size_min = st.number_input("min", min_value=0, max_value=40, value=config.size_min, key=f"min_{config.class_id}")
            size_max = st.number_input("max", min_value=0, max_value=40, value=config.size_max, key=f"max_{config.class_id}")
            edited_configs.append(
                ClassConfig(
                    class_id=config.class_id,
                    label=label,
                    size_min=int(size_min),
                    size_max=int(size_max),
                    music_allowed=list(music),
                    languages_allowed=list(languages),
                )
            )

    if st.button("Klassenprofile speichern"):
        save_class_configs(edited_configs)
        st.session_state.class_configs = edited_configs
        st.success("Klassenprofile gespeichert.")

    st.dataframe(class_configs_to_frame(edited_configs or st.session_state.class_configs), use_container_width=True)


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
        st.dataframe(messages_to_frame(validation_result.errors), use_container_width=True)
        return

    if st.button("Klassen vorschlagen"):
        solver_result = solve_assignments(result.students, st.session_state.class_configs, settings)
        st.session_state.solver_result = solver_result

    solver_result = st.session_state.solver_result
    if solver_result:
        st.metric("Solver-Status", solver_result.status)
        if solver_result.message:
            st.info(solver_result.message)
        if solver_result.score_report:
            st.metric("Gesamtscore", solver_result.score_report.total_score)
            if solver_result.score_report.hard_violations:
                st.error(f"{len(solver_result.score_report.hard_violations)} harte Regelverletzungen")
            else:
                st.success("0 harte Regelverletzungen")


def _result_tab(settings: OptimizationSettings) -> None:
    result = st.session_state.import_result
    solver_result = st.session_state.solver_result
    if not result or not solver_result or not solver_result.score_report:
        st.info("Noch kein Ergebnis vorhanden.")
        return

    score = solver_result.score_report
    cols = st.columns(4)
    cols[0].metric("Schüler", len(result.students))
    cols[1].metric("Klassen", len(st.session_state.class_configs))
    cols[2].metric("Freund 1", f"{score.friend1_fulfilled}/{score.friend1_total}")
    cols[3].metric("Freund 2", f"{score.friend2_fulfilled}/{score.friend2_total}")

    st.subheader("Pro Klasse")
    st.dataframe(score_to_class_frame(score), use_container_width=True)

    if score.unmet_friend_requests:
        st.subheader("Nicht erfüllte Freundeswünsche")
        st.dataframe(pd.DataFrame({"Meldung": score.unmet_friend_requests}), use_container_width=True)

    if score.hard_violations:
        st.subheader("Harte Regelverletzungen")
        st.dataframe(pd.DataFrame({"Meldung": score.hard_violations}), use_container_width=True)

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


if __name__ == "__main__":
    main()

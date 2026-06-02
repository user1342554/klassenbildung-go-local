from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import perf_counter

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
    st.session_state.settings = current
    return current


def _settings_tab() -> None:
    current = _current_settings()
    result = st.session_state.import_result

    st.subheader("Klassen und Rechenzeit")
    total_students = len(result.students) if result else 210
    class_configs: list[ClassConfig] = st.session_state.class_configs
    col1, col2, col3, col4 = st.columns(4)
    class_count = col1.number_input("Anzahl Klassen", min_value=1, max_value=15, value=len(class_configs) or 7)
    year = col2.number_input("Jahrgang", min_value=1, max_value=13, value=5)
    max_size = col3.number_input("Max. Klassengröße", min_value=1, max_value=40, value=30)
    time_limit = col4.select_slider(
        "Max. Rechenzeit",
        options=[10, 30, 60, 120],
        value=current.solver_time_limit_seconds,
    )
    st.caption(
        "Der Solver sucht nach gültigen Lösungen und versucht zu beweisen, dass keine bessere existiert. "
        "Ohne Zeitlimit kann dieser Beweis sehr lange dauern. OPTIMAL ist bewiesen bestes Ergebnis; "
        "FEASIBLE ist ein gültiges, aber nicht bewiesen bestes Ergebnis."
    )

    if st.button("Klassen aus Schülerzahl erzeugen"):
        st.session_state.class_configs = generate_class_configs(
            total_students=total_students,
            class_count=int(class_count),
            year=int(year),
            max_size=int(max_size),
            existing_profiles=class_configs,
        )
        st.session_state.solver_result = None
        st.rerun()

    st.dataframe(class_configs_to_frame(st.session_state.class_configs), use_container_width=True)

    st.subheader("Gewichtungen")
    weight_mixed_language_class = st.slider(
        "F/L-Mischklassen vermeiden",
        0,
        100000,
        current.weight_mixed_language_class,
        step=1000,
    )
    weight_mixed_music_class = st.slider(
        "Musik-Mischklassen vermeiden",
        0,
        100000,
        current.weight_mixed_music_class,
        step=1000,
    )
    weight_mutual_friend = st.slider(
        "Gegenseitige Freunde",
        0,
        5000,
        current.weight_mutual_friend,
        step=100,
    )
    weight_friend1 = st.slider("Freund 1", 0, 3000, current.weight_friend1, step=50)
    weight_friend2 = st.slider("Freund 2", 0, 1500, current.weight_friend2, step=50)

    advanced = _advanced_weight_values(current)
    with st.expander("Weitere Gewichtungen", expanded=False):
        advanced = _advanced_weight_controls(current)

    settings = OptimizationSettings(
        enforce_music_profile=False,
        enforce_language_profile=False,
        weight_music_profile=current.weight_music_profile,
        weight_language_profile=current.weight_language_profile,
        weight_mixed_language_class=weight_mixed_language_class,
        weight_mixed_music_class=weight_mixed_music_class,
        weight_friend1=weight_friend1,
        weight_friend2=weight_friend2,
        weight_mutual_friend=weight_mutual_friend,
        solver_time_limit_seconds=time_limit,
        **advanced,
    )

    if st.button("Einstellungen übernehmen"):
        save_settings(settings)
        st.session_state.settings = settings
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
        "weight_keep_existing": current.weight_keep_existing,
    }


def _advanced_weight_controls(current: OptimizationSettings) -> dict[str, int]:
    return {
        "weight_support_distribution": st.slider("R-Verteilung", 0, 1000, current.weight_support_distribution, step=25),
        "weight_gender_balance": st.slider("Geschlecht", 0, 500, current.weight_gender_balance, step=10),
        "weight_primary_school": st.slider("Grundschule", 0, 500, current.weight_primary_school, step=10),
        "weight_primary_class": st.slider("Grundschulklasse", 0, 500, current.weight_primary_class, step=10),
        "weight_nationality": st.slider("Staat/Nationalität", 0, 200, current.weight_nationality, step=5),
        "weight_religion": st.slider("Religion", 0, 200, current.weight_religion, step=5),
        "weight_keep_existing": st.slider("bestehende Einteilung behalten", 0, 1000, current.weight_keep_existing, step=25),
    }


def _upload_tab(settings: OptimizationSettings) -> None:
    st.subheader("Datei laden")
    if DUMMY_EXCEL_PATH.exists():
        st.info(f"Testdatei: {DUMMY_EXCEL_PATH.resolve()}")
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

    validation_result = validate_students(
        result.students,
        st.session_state.class_configs,
        settings,
        base_messages=result.messages,
    )
    st.session_state.validation_result = validation_result
    if validation_result.has_errors:
        st.error("Diese Datei hat blockierende Fehler.")
        st.dataframe(messages_to_frame(validation_result.errors), use_container_width=True)
    else:
        st.success("Datei ist für die Optimierung nutzbar.")
        if validation_result.warnings:
            with st.expander(f"{len(validation_result.warnings)} Warnungen anzeigen", expanded=False):
                st.dataframe(messages_to_frame(validation_result.warnings), use_container_width=True)


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
    st.subheader("Klassen")
    st.dataframe(class_configs_to_frame(st.session_state.class_configs), use_container_width=True)

    with st.expander("Klassen bearbeiten", expanded=False):
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
                    "Musik-Hinweis",
                    options=["Reg", "B", "S", "G"],
                    default=config.music_allowed,
                    key=f"music_{config.class_id}",
                )
                languages = st.multiselect(
                    "Sprach-Hinweis",
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

        if st.button("Klassen speichern"):
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
        st.dataframe(messages_to_frame(validation_result.errors), use_container_width=True)
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
    cols = st.columns(6)
    cols[0].metric("Schüler", len(result.students))
    cols[1].metric("Klassen", len(st.session_state.class_configs))
    cols[2].metric("Freund 1", f"{score.friend1_fulfilled}/{score.friend1_total}")
    cols[3].metric("Freund 2", f"{score.friend2_fulfilled}/{score.friend2_total}")
    cols[4].metric("F/L-Mix", score.mixed_language_class_count)
    cols[5].metric("Musik-Mix", score.mixed_music_class_count)
    st.metric("Gegenseitige Freunde", f"{score.mutual_friend_fulfilled}/{score.mutual_friend_total}")

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
    cols[0].metric("Freund 1", f"{score.friend1_fulfilled}/{score.friend1_total}")
    cols[1].metric("Freund 2", f"{score.friend2_fulfilled}/{score.friend2_total}")
    cols[2].metric("Gegenseitig", f"{score.mutual_friend_fulfilled}/{score.mutual_friend_total}")
    cols[3].metric("Harte Verletzungen", len(score.hard_violations))

    table = _student_assignment_frame(result.students, assignments)
    st.dataframe(table, use_container_width=True)

    labels = {student.display_label: student.internal_id for student in result.students}
    selected_label = st.selectbox("Schüler auswählen", options=sorted(labels))
    selected = next(student for student in result.students if student.internal_id == labels[selected_label])
    current_class = assignments.get(selected.internal_id, "")
    class_ids = [config.class_id for config in st.session_state.class_configs]

    col_left, col_right = st.columns([1, 1])
    with col_left:
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
            "Freund 1": selected.friend1,
            "Freund 2": selected.friend2,
        }
        st.table(pd.DataFrame(person_data.items(), columns=["Feld", "Wert"]))
        if selected.comment:
            st.warning(f"Anmerkung: {selected.comment}")
        else:
            st.info("Keine Anmerkung.")

        satisfaction = _student_satisfaction(selected, result.students, assignments)
        st.metric("Zufriedenheit", satisfaction["label"])
        st.progress(satisfaction["percent"] / 100 if satisfaction["percent"] >= 0 else 0.0)

    with col_right:
        st.subheader("Klasse ändern")
        target_index = class_ids.index(current_class) if current_class in class_ids else 0
        target_class = st.selectbox("Neue Klasse", options=class_ids, index=target_index)
        if st.button("Schüler verschieben", type="primary"):
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


def _student_assignment_frame(students, assignments: dict[str, str]) -> pd.DataFrame:
    rows = []
    for student in students:
        satisfaction = _student_satisfaction(student, students, assignments)
        rows.append(
            {
                "Klasse": assignments.get(student.internal_id),
                "Nr": student.nr,
                "Name": student.full_name,
                "Sprache": student.second_language,
                "Musik": student.music_profile,
                "Anmerkung": "JA" if student.comment else "",
                "Wünsche erfüllt": satisfaction["label"],
                "Zufriedenheit": satisfaction["display"],
            }
        )
    return pd.DataFrame(rows).sort_values(["Klasse", "Name"], na_position="last")


def _student_satisfaction(student, students, assignments: dict[str, str]) -> dict[str, object]:
    checks = []
    for friend_ref in (student.friend1, student.friend2):
        friend = resolve_student_ref(students, friend_ref)
        if friend:
            checks.append(assignments.get(student.internal_id) == assignments.get(friend.internal_id))

    if not checks:
        return {"label": "keine Wünsche", "percent": -1, "display": "-"}

    fulfilled = sum(1 for item in checks if item)
    percent = int(round(fulfilled / len(checks) * 100))
    return {
        "label": f"{fulfilled}/{len(checks)}",
        "percent": percent,
        "display": f"{percent}%",
    }


if __name__ == "__main__":
    main()

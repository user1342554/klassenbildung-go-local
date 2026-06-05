from __future__ import annotations

from datetime import datetime
from dataclasses import replace
import io as py_io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

import klassenbildung.presentation.candidate_review as candidate_review_module
import klassenbildung.presentation.candidate_summary as candidate_summary_module
import klassenbildung.services.manual_rules as manual_rules_module
import klassenbildung.services.note_rule_conversion as note_rule_conversion_module
import klassenbildung.validation.finality as finality_module
from klassenbildung.presentation.result_view_model import VARIANT_KEYS
from klassenbildung.core.constants import BASIS_SHEET_NAME, EXPORT_COLUMN_COUNT
from klassenbildung.core.models import (
    ClassConfig,
    OptimizationSettings,
    ProfileSlackReport,
    ScoreReport,
    SolverPhaseReport,
    Student,
    ValidationMessage,
)
from klassenbildung.core.normalization import normalize_class_id
from klassenbildung.core.settings import load_settings
from klassenbildung.optimization.scoring import score_solution


SELECTED_EXPORT_VARIANT = "Exportierte Klassenliste"
SELECTED_EXPORT_KEY = "X"
SELECTED_EXPORT_SOURCE = "exported_solution"
LANGUAGE_PROFILE_MEANING = (
    "F/L im Klassenprofil bedeutet: F und L sind erlaubt; echte Zielmischung wird separat als Hinweis bewertet."
)


CANDIDATE_EXPORT_FIELDS = [
    *candidate_summary_module.CANDIDATE_SUMMARY_FIELDS,
    "zusammengefasste_varianten",
    "entscheidungshinweis",
    "empfohlen_fuer_modus",
    "score",
    "freigabestatus",
    "datenblocker",
    "finalitaets_blocker",
    "harte_profilverletzungen",
    "verletzte_aktive_manuelle_regeln",
    "ungepruefte_notizen",
    "groesste_grundschule",
    "groesste_grundschule_alte_klasse",
    "maedchen_spannweite",
    "geschlechter_schieflage",
    "musik_profilfehlmenge",
]


def export_excel(
    source_workbook_bytes: bytes | None,
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    score_report: ScoreReport | None = None,
    validation_messages: list[ValidationMessage] | None = None,
    profile_baseline_report: ScoreReport | None = None,
    phase_reports: list[SolverPhaseReport] | None = None,
    profile_slack_reports: list[ProfileSlackReport] | None = None,
    profile_refinement_reports: list[ProfileSlackReport] | None = None,
    include_expert_diagnostics: bool = False,
    settings: OptimizationSettings | None = None,
    manual_rule_entries: list | None = None,
    note_review_status_by_student: dict[str, object] | None = None,
    export_source_candidate_key: str | None = None,
    export_selection_mode: str = "Regelkonform",
) -> bytes:
    workbook = _load_or_create_workbook(source_workbook_bytes)
    basis = workbook[BASIS_SHEET_NAME]
    active_settings = settings or load_settings()
    validation_messages = validation_messages or []

    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id:
            basis.cell(row=student.row_number, column=1).value = class_id

    manual_rule_entries = manual_rule_entries or []
    note_review_status_by_student = note_review_status_by_student or {}
    raw_candidate_reports = _candidate_reports_for_export(
        profile_slack_reports or [],
        score_report,
        assignments,
        len(students),
        export_source_candidate_key or SELECTED_EXPORT_KEY,
    )
    candidate_reports, candidate_groups = _deduplicated_candidate_reports(raw_candidate_reports)
    decision_context = _candidate_decision_context(
        candidate_reports,
        students,
        class_configs,
        active_settings,
        manual_rule_entries,
        export_source_candidate_key or SELECTED_EXPORT_KEY,
        export_selection_mode,
        candidate_groups,
    )

    _replace_class_sheets(workbook, basis, students, assignments, class_configs)
    _write_overview_sheet(
        workbook,
        students,
        assignments,
        class_configs,
        manual_rule_entries,
        note_review_status_by_student,
        score_report,
        len(profile_slack_reports or []),
        len(candidate_reports),
        export_source_candidate_key or (SELECTED_EXPORT_KEY if score_report else "-"),
        decision_context,
        validation_messages,
        active_settings,
    )
    _write_score_sheet(
        workbook,
        score_report,
        profile_baseline_report,
        phase_reports or [] if include_expert_diagnostics else [],
        profile_slack_reports or [] if include_expert_diagnostics else [],
        profile_refinement_reports or [] if include_expert_diagnostics else [],
    )
    _write_class_profile_sheet(workbook, students, assignments, class_configs, score_report, active_settings)
    _write_candidate_summary_sheet(
        workbook,
        candidate_reports,
        students,
        class_configs,
        active_settings,
        manual_rule_entries,
        note_review_status_by_student,
        validation_messages,
        candidate_groups,
    )
    _write_candidate_decision_sheet(
        workbook,
        students,
        candidate_reports,
        class_configs,
        active_settings,
        manual_rule_entries,
    )
    _write_candidate_detail_sheet(
        workbook,
        students,
        class_configs,
        candidate_reports,
        active_settings,
        note_review_status_by_student,
    )
    _write_candidate_class_sheet(workbook, students, candidate_reports)
    _write_candidate_score_sheet(
        workbook,
        students,
        class_configs,
        candidate_reports,
        active_settings,
        manual_rule_entries,
    )
    _write_manual_rules_sheet(workbook, manual_rule_entries, students, assignments)
    _write_notes_sheet(
        workbook,
        students,
        assignments,
        class_configs,
        manual_rule_entries,
        note_review_status_by_student,
    )
    if "Manuelle Änderungen" in workbook.sheetnames:
        del workbook["Manuelle Änderungen"]
    _move_basis_helper_rows(workbook, basis, students)
    _write_warning_sheet(workbook, validation_messages or [])

    output = py_io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _write_overview_sheet(
    workbook: Workbook,
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    manual_rule_entries: list,
    note_review_status_by_student: dict[str, object],
    score_report: ScoreReport | None,
    solver_candidate_count: int,
    displayed_candidate_count: int,
    selected_candidate_key: str,
    decision_context: dict[str, str],
    validation_messages: list[ValidationMessage],
    settings: OptimizationSettings,
) -> None:
    if "Übersicht" in workbook.sheetnames:
        del workbook["Übersicht"]
    sheet = workbook.create_sheet("Übersicht", 0)
    sheet.append(["Feld", "Wert"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    active_rules = sum(1 for entry in manual_rule_entries if getattr(entry, "active", False))
    disabled_rules = sum(1 for entry in manual_rule_entries if not getattr(entry, "active", False))
    unreviewed_notes = _unreviewed_note_count(students, note_review_status_by_student)
    hard_violations = len(score_report.hard_violations) if score_report else 0
    profile_violations = _profile_violation_count(students, assignments, class_configs, settings)
    active_manual_rule_violations = _active_manual_rule_violation_count(
        manual_rule_entries,
        students,
        assignments,
    )
    finality = finality_module.finality_report(
        students,
        score_report,
        validation_messages,
        note_review_status_by_student,
        profile_violations=profile_violations,
        manual_rule_violations=active_manual_rule_violations,
    )
    other_hard_violations = finality.other_hard_violations
    data_blockers = len(finality.data_blockers)
    final_blockers = finality.blocker_labels()
    final_status = (
        "NICHT FINAL - " + "; ".join(final_blockers)
        if final_blockers
        else "Prüfstand ohne bekannte Blocker"
    )
    final_gate = "rot" if final_blockers else "grün"
    final_export_status = "gesperrt - nur Prüfexport erlaubt" if final_blockers else "möglich nach pädagogischer Freigabe"
    rows = [
        ("Freigabestatus", final_status),
        ("Finale Verwendung", "nein" if final_blockers else "nur nach pädagogischer Freigabe"),
        ("Finalitäts-Ampel", final_gate),
        ("Finalexport", final_export_status),
        ("Lösungsstand", "Prüfexport"),
        ("Programmversion", "V13"),
        ("Export-Code-Version", "candidate-export-v13"),
        ("Regelparser-Version", "note-rules-v2"),
        ("Regression-Schutz", "gespeicherte Bestkandidaten werden gegen neu berechnete Kandidaten geprüft"),
        ("Exportierte Klassen entsprechen Kandidat", selected_candidate_key),
        ("Auswahlmodus Export", decision_context.get("selection_mode", "-")),
        ("F/L-Profil bedeutet", decision_context.get("language_profile_meaning", "-")),
        ("Auswahlstrategie", decision_context.get("selection_strategy", "-")),
        ("Score-bester Kandidat", decision_context.get("score_best_candidate", "-")),
        ("Exportierter Kandidat", decision_context.get("selected_candidate", selected_candidate_key)),
        ("Warum nicht Score-bester Kandidat?", decision_context.get("why_not_score_best", "-")),
        ("Empfehlung Regelkonform", decision_context.get("rule_compliant_candidate", "-")),
        ("Empfehlung Profilminimal", decision_context.get("profile_minimal_candidate", "-")),
        ("Empfehlung Sozialoptimiert", decision_context.get("social_optimized_candidate", "-")),
        ("Empfehlung Score-beste Lösung", decision_context.get("score_best_candidate", "-")),
        ("F/L-Zielmischung-Hinweis", decision_context.get("fl_target_mix_hint", "-")),
        (
            "Kandidatenvergleich",
            (
                f"{displayed_candidate_count} eindeutige Kandidat(en) dokumentiert; "
                f"{solver_candidate_count} Solver-Variante(n) geprüft"
                if solver_candidate_count
                else "nur gewählte Lösung dokumentiert; kein vollständiger Variantenvergleich"
            ),
        ),
        ("Harte Regelverletzungen gesamt", hard_violations),
        ("Harte Profilverletzungen", profile_violations),
        ("Verletzte aktive manuelle Regeln", active_manual_rule_violations),
        ("Datenblocker", data_blockers),
        ("Ballungs-/Balanceblocker", len(finality.class_blockers)),
        ("Ballungs-/Balancewarnungen", len(finality.warnings)),
        ("Freigabewarnungen", "; ".join(finality.warning_labels()) or "-"),
        ("Anzahl aktiver Regeln", active_rules),
        ("Anzahl deaktivierter Regeln", disabled_rules),
        ("Anzahl ungeprüfter Notizen", unreviewed_notes),
        ("Export-Zeitpunkt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for row in rows:
        sheet.append(list(row))


def _load_or_create_workbook(source_workbook_bytes: bytes | None) -> Workbook:
    if source_workbook_bytes:
        return load_workbook(py_io.BytesIO(source_workbook_bytes))
    workbook = Workbook()
    workbook.active.title = BASIS_SHEET_NAME
    return workbook


def _replace_class_sheets(
    workbook: Workbook,
    basis,
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
) -> None:
    class_ids = {config.class_id for config in class_configs}
    for title in list(workbook.sheetnames):
        if _is_class_output_sheet_title(title, class_ids):
            del workbook[title]

    header_values = [basis.cell(row=1, column=column).value for column in range(1, EXPORT_COLUMN_COUNT + 1)]
    students_by_class = {config.class_id: [] for config in class_configs}
    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id in students_by_class:
            students_by_class[class_id].append(student)

    for config in class_configs:
        sheet = workbook.create_sheet(config.class_id)
        sheet.append(header_values)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for student in sorted(students_by_class[config.class_id], key=lambda item: (item.sort_name, item.row_number)):
            values = [
                basis.cell(row=student.row_number, column=column).value
                for column in range(1, EXPORT_COLUMN_COUNT + 1)
            ]
            values[0] = config.class_id
            sheet.append(values)
        for column in range(1, EXPORT_COLUMN_COUNT + 1):
            letter = sheet.cell(row=1, column=column).column_letter
            sheet.column_dimensions[letter].width = basis.column_dimensions[letter].width or 12


def _is_class_output_sheet_title(title: str, class_ids: set[str]) -> bool:
    normalized = normalize_class_id(title)
    if normalized not in class_ids:
        return False
    return bool(re.match(r"^\s*\d+\s*[a-zA-Z](?:\s|$|[^a-zA-Z0-9])", title))


def _move_basis_helper_rows(workbook: Workbook, basis, students: list[Student]) -> None:
    if not students:
        return
    last_student_row = max(student.row_number for student in students)
    if basis.max_row <= last_student_row:
        return

    helper_values = []
    for row_index in range(last_student_row + 1, basis.max_row + 1):
        values = [basis.cell(row=row_index, column=column).value for column in range(1, basis.max_column + 1)]
        if any(value is not None for value in values):
            helper_values.append(values)

    if "_Hilfsdaten" in workbook.sheetnames:
        del workbook["_Hilfsdaten"]
    if helper_values:
        helper_sheet = workbook.create_sheet("_Hilfsdaten")
        helper_sheet.append(["Aus dem Basisblatt unterhalb der Schülerdaten übernommen."])
        for values in helper_values:
            helper_sheet.append(values)
        helper_sheet.sheet_state = "hidden"

    basis.delete_rows(last_student_row + 1, basis.max_row - last_student_row)


def _write_score_sheet(
    workbook: Workbook,
    score_report: ScoreReport | None,
    profile_baseline_report: ScoreReport | None = None,
    phase_reports: list[SolverPhaseReport] | None = None,
    profile_slack_reports: list[ProfileSlackReport] | None = None,
    profile_refinement_reports: list[ProfileSlackReport] | None = None,
) -> None:
    if "Auswertung" in workbook.sheetnames:
        del workbook["Auswertung"]
    sheet = workbook.create_sheet("Auswertung")
    sheet.append(["Kennzahl", "Wert"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    if not score_report:
        sheet.append(["Status", "Keine Auswertung vorhanden"])
        return
    sheet.append(["Technischer Score", score_report.total_score])
    sheet.append(["Harte Regelverletzungen", len(score_report.hard_violations)])
    sheet.append(["Freundeswunsch 1 erfüllt", f"{score_report.friend1_fulfilled}/{score_report.friend1_total}"])
    sheet.append(["Freundeswunsch 2 erfüllt", f"{score_report.friend2_fulfilled}/{score_report.friend2_total}"])
    sheet.append(["Gegenseitige Freunde erfüllt", f"{score_report.mutual_friend_fulfilled}/{score_report.mutual_friend_total}"])
    sheet.append(["Kinder ohne Wunschfreund in Klasse", score_report.isolated_friend_request_count])
    sheet.append(["F/L-Mischklassen", score_report.mixed_language_class_count])
    sheet.append(["F/L-Minderheits-Schüler", score_report.language_minority_student_count])
    sheet.append(["Musik-Mischklassen", score_report.mixed_music_class_count])
    sheet.append(["Musik-Minderheits-Schüler", score_report.music_minority_student_count])
    sheet.append(["Musik-Profilanteil-Fehlmenge", score_report.music_focus_shortfall_count])
    if profile_baseline_report:
        sheet.append([])
        sheet.append(["Minimale Profil-Mischklassen", "Minimum", "Aktuelle Lösung"])
        sheet.append(["F/L-Mischklassen", profile_baseline_report.mixed_language_class_count, score_report.mixed_language_class_count])
        sheet.append(["Musik-Mischklassen", profile_baseline_report.mixed_music_class_count, score_report.mixed_music_class_count])
    if score_report.friend_profile_conflicts:
        sheet.append([])
        sheet.append(["Profilkonflikte in Freundschaften", "Anzahl"])
        for label, count in sorted(score_report.friend_profile_conflicts.items()):
            if count:
                sheet.append([label, count])
    if phase_reports:
        sheet.append([])
        sheet.append(
            [
                "Solverphase",
                "Status",
                "Objective",
                "Best Bound",
                "Gap",
                "F/L-Mischklassen",
                "Musik-Mischklassen",
                "F/L-Minderheit",
                "Musik-Minderheit",
                "Ohne Wunschfreund",
                "Freund 1 erfüllt",
                "Gegenseitig erfüllt",
                "Freund 2 erfüllt",
            ]
        )
        for phase in phase_reports:
            sheet.append(
                [
                    phase.name,
                    phase.status,
                    phase.objective_value,
                    phase.best_objective_bound,
                    phase.relative_gap,
                    phase.mixed_language_class_count,
                    phase.mixed_music_class_count,
                    phase.language_minority_student_count,
                    phase.music_minority_student_count,
                    phase.isolated_friend_request_count,
                    _ratio_value(phase.friend1_fulfilled, phase.friend1_total),
                    _ratio_value(phase.mutual_friend_fulfilled, phase.mutual_friend_total),
                    _ratio_value(phase.friend2_fulfilled, phase.friend2_total),
                ]
            )
    _write_profile_variant_rows(sheet, "Profil-Slack-Vergleich", profile_slack_reports or [])
    _write_profile_variant_rows(sheet, "Vertiefungsläufe", profile_refinement_reports or [])
    sheet.append([])
    sheet.append(["Strafkategorie", "Punkte"])
    for label, points in sorted(score_report.category_scores.items(), key=lambda item: (-item[1], item[0])):
        sheet.append([label, points])
    sheet.append([])
    sheet.append(
        [
            "Klasse",
            "Anzahl",
            "m",
            "w",
            "Geschlecht Zielzone",
            "Geschlecht Bewertung",
            "F",
            "L",
            "F/L gemischt",
            "F/L Minderheit",
            "Reg",
            "B",
            "S",
            "G",
            "Musik gemischt",
            "Musik Minderheit",
            "Musik Profilfehlmenge",
            "R",
            "groesste Grundschule",
            "groesste Grundschule/alte Klasse",
        ]
    )
    for report in score_report.class_reports:
        sheet.append(
            [
                report.class_id,
                report.size,
                report.gender_counts.get("m", 0),
                report.gender_counts.get("w", 0),
                finality_module.gender_target_zone_text(),
                finality_module.gender_target_status(
                    report.size,
                    report.gender_counts.get("m", 0),
                    report.gender_counts.get("w", 0),
                ),
                report.language_counts.get("F", 0),
                report.language_counts.get("L", 0),
                "ja" if report.is_language_mixed else "nein",
                report.language_minority_count,
                report.music_counts.get("Reg", 0),
                report.music_counts.get("B", 0),
                report.music_counts.get("S", 0),
                report.music_counts.get("G", 0),
                "ja" if report.is_music_mixed else "nein",
                report.music_minority_count,
                report.music_focus_shortfall,
                report.support_count,
                _largest_count(report.school_counts),
                _largest_count(report.primary_class_counts),
            ]
        )


def _largest_count(counts: dict[str, int]) -> int:
    values = [count for key, count in counts.items() if key != "leer"]
    return max(values, default=0)


def _write_class_profile_sheet(
    workbook: Workbook,
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    score_report: ScoreReport | None,
    settings: OptimizationSettings,
) -> None:
    if "Klassenprofile" in workbook.sheetnames:
        del workbook["Klassenprofile"]
    sheet = workbook.create_sheet("Klassenprofile")
    headers = [
        "Klasse",
        "Profilname",
        "Sprachen erlaubt",
        "Musik erlaubt",
        "Reg erlaubt",
        "Profilregeln aktiv",
        "F/L-Bedeutung",
        "F/L tatsächlich",
        "F/L-Zielhinweis",
        "F",
        "L",
        "Reg",
        "B",
        "S",
        "G",
        "Profilkinder B/S/G",
        "Musik-Profilfehlmenge",
        "Harte Profilverletzungen",
        "Beispiele",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    students_by_class = {config.class_id: [] for config in class_configs}
    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id in students_by_class:
            students_by_class[class_id].append(student)
    report_by_class = {report.class_id: report for report in (score_report.class_reports if score_report else [])}

    for config in class_configs:
        report = report_by_class.get(config.class_id)
        class_students = students_by_class.get(config.class_id, [])
        violations = _profile_violation_labels(class_students, config, settings)
        language_counts = report.language_counts if report else {}
        music_counts = report.music_counts if report else {}
        f_count = language_counts.get("F", 0)
        l_count = language_counts.get("L", 0)
        sheet.append(
            [
                config.class_id,
                config.label,
                ", ".join(config.languages_allowed) or "nicht festgelegt",
                ", ".join(config.music_allowed) or "nicht festgelegt",
                "ja" if "Reg" in config.music_allowed else "nein",
                _profile_enforcement_text(settings),
                _language_profile_meaning(config),
                _language_mix_status(config, f_count, l_count),
                _language_mix_hint(config, f_count, l_count),
                f_count,
                l_count,
                music_counts.get("Reg", 0),
                music_counts.get("B", 0),
                music_counts.get("S", 0),
                music_counts.get("G", 0),
                sum(music_counts.get(profile, 0) for profile in ("B", "S", "G")),
                report.music_focus_shortfall if report else 0,
                len(violations),
                "; ".join(violations[:5]),
            ]
        )


def _language_profile_meaning(config: ClassConfig) -> str:
    languages = set(config.languages_allowed)
    if {"F", "L"}.issubset(languages):
        return "F und L erlaubt; keine harte Zielquote"
    if languages == {"F"}:
        return "nur F erlaubt"
    if languages == {"L"}:
        return "nur L erlaubt"
    return "nicht festgelegt"


def _language_mix_status(config: ClassConfig, f_count: int, l_count: int) -> str:
    if not _class_allows_both_languages(config):
        return "-"
    if f_count and l_count:
        return f"gemischt ({f_count} F / {l_count} L)"
    return f"einsprachig ({f_count} F / {l_count} L)"


def _language_mix_hint(config: ClassConfig, f_count: int, l_count: int) -> str:
    if not _class_allows_both_languages(config):
        return "-"
    if f_count and l_count:
        return "tatsächlich gemischt"
    return "F/L erlaubt, aber im Kandidaten einsprachig"


def _write_candidate_summary_sheet(
    workbook: Workbook,
    profile_slack_reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rule_entries: list,
    note_review_status_by_student: dict[str, object],
    validation_messages: list[ValidationMessage],
    candidate_groups: dict[str, list[str]],
) -> None:
    if "Kandidaten" in workbook.sheetnames:
        del workbook["Kandidaten"]
    records = _candidate_export_records(
        profile_slack_reports,
        students,
        class_configs,
        settings,
        manual_rule_entries,
        note_review_status_by_student,
        validation_messages,
        candidate_groups,
    )
    if not records:
        return
    sheet = workbook.create_sheet("Kandidaten")
    sheet.append(CANDIDATE_EXPORT_FIELDS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for record in records:
        sheet.append([record.get(field) for field in CANDIDATE_EXPORT_FIELDS])


def _candidate_export_records(
    profile_slack_reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rule_entries: list,
    note_review_status_by_student: dict[str, object],
    validation_messages: list[ValidationMessage],
    candidate_groups: dict[str, list[str]],
) -> list[dict[str, object]]:
    base_records = candidate_summary_module.candidate_summary_records_from_reports(profile_slack_reports, len(students))
    active_rules = manual_rules_module.active_manual_rules(manual_rule_entries)
    note_count = _unreviewed_note_count(students, note_review_status_by_student)
    selected_score = _score_for_selected_candidate(profile_slack_reports, students, class_configs, settings, active_rules)
    mode_recommendations = _candidate_mode_recommendations(
        _scored_candidate_reports(profile_slack_reports, students, class_configs, settings, manual_rule_entries)
    )
    records = []
    for report, record in zip(profile_slack_reports, base_records, strict=True):
        assignments = report.assignments or {}
        score = score_solution(students, assignments, settings, class_configs, active_rules) if assignments else None
        profile_violations = _profile_violation_count(students, assignments, class_configs, settings) if assignments else 0
        manual_violations = _active_manual_rule_violation_count(manual_rule_entries, students, assignments) if assignments else 0
        finality = finality_module.finality_report(
            students,
            score,
            validation_messages,
            note_review_status_by_student,
            profile_violations=profile_violations,
            manual_rule_violations=manual_violations,
        )
        variant_group = candidate_groups.get(report.variant, [report.variant])
        enriched = dict(record)
        if _is_export_report(report):
            enriched["key"] = _candidate_key(report)
            enriched["role"] = "selected"
            enriched["recommendation_role"] = report.recommendation_role or "Exportierte Klassenliste"
        elif selected_score and score and score.isolated_friend_request_count < selected_score.isolated_friend_request_count:
            enriched["role"] = "alternative"
        enriched.update(
            {
                "zusammengefasste_varianten": "; ".join(_standard_candidate_name(name) for name in variant_group),
                "entscheidungshinweis": _candidate_decision_hint(report, score, selected_score),
                "empfohlen_fuer_modus": _candidate_mode_text(mode_recommendations, _candidate_key(report)),
                "score": score.total_score if score else report.objective_value,
                "freigabestatus": _candidate_final_status(finality),
                "datenblocker": len(finality.data_blockers),
                "finalitaets_blocker": "; ".join(finality.blocker_labels()) or "-",
                "harte_profilverletzungen": profile_violations,
                "verletzte_aktive_manuelle_regeln": manual_violations,
                "ungepruefte_notizen": note_count,
                "groesste_grundschule": _max_largest_school(score),
                "groesste_grundschule_alte_klasse": _max_largest_primary_class(score),
                "maedchen_spannweite": _female_range(score),
                "geschlechter_schieflage": _female_imbalance(score),
                "musik_profilfehlmenge": score.music_focus_shortfall_count if score else "-",
            }
        )
        records.append(enriched)
    return records


def _candidate_decision_context(
    reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rule_entries: list,
    export_source_candidate_key: str,
    export_selection_mode: str,
    candidate_groups: dict[str, list[str]],
) -> dict[str, str]:
    scored_reports = _scored_candidate_reports(reports, students, class_configs, settings, manual_rule_entries)
    if not scored_reports:
        return {
            "selection_strategy": "Keine bewertbaren Kandidaten dokumentiert.",
            "selection_mode": "-",
            "language_profile_meaning": LANGUAGE_PROFILE_MEANING,
            "score_best_candidate": "-",
            "selected_candidate": "-",
            "why_not_score_best": "-",
            "rule_compliant_candidate": "-",
            "profile_minimal_candidate": "-",
            "social_optimized_candidate": "-",
            "fl_target_mix_hint": "-",
        }

    selected = _selected_scored_report(scored_reports)
    score_best = min(scored_reports, key=lambda item: item[1].total_score)
    mode_recommendations = _candidate_mode_recommendations(scored_reports)
    score_best_key = _display_candidate_key(
        score_best[0],
        candidate_groups,
        preferred_key=export_source_candidate_key,
    )
    selected_key = export_source_candidate_key or (_candidate_key(selected[0]) if selected else "-")
    if not selected:
        return {
            "selection_strategy": "Score-bester Kandidat wird dokumentiert; keine exportierte Klassenliste gefunden.",
            "selection_mode": export_selection_mode or "-",
            "language_profile_meaning": LANGUAGE_PROFILE_MEANING,
            "score_best_candidate": score_best_key,
            "selected_candidate": "-",
            "why_not_score_best": "-",
            "rule_compliant_candidate": mode_recommendations.get("Regelkonform", "-"),
            "profile_minimal_candidate": mode_recommendations.get("Profilminimal", "-"),
            "social_optimized_candidate": mode_recommendations.get("Sozialoptimiert", "-"),
            "fl_target_mix_hint": _fl_target_mix_hint(score_best[1], class_configs),
        }

    if score_best_key == selected_key:
        return {
            "selection_strategy": "Exportierte Klassenliste ist score-bester dokumentierter Kandidat.",
            "selection_mode": export_selection_mode,
            "language_profile_meaning": LANGUAGE_PROFILE_MEANING,
            "score_best_candidate": score_best_key,
            "selected_candidate": selected_key,
            "why_not_score_best": "Exportierter Kandidat ist auch score-bester Kandidat.",
            "rule_compliant_candidate": mode_recommendations.get("Regelkonform", "-"),
            "profile_minimal_candidate": mode_recommendations.get("Profilminimal", "-"),
            "social_optimized_candidate": mode_recommendations.get("Sozialoptimiert", "-"),
            "fl_target_mix_hint": _fl_target_mix_hint(selected[1], class_configs),
        }

    profile_cost = _profile_cost_text(score_best[1], selected[1])
    why = (
            f"Exportmodus {export_selection_mode} priorisiert {selected_key}; {score_best_key} ist Score-beste/Sozialoptimiert-Empfehlung, benötigt aber {profile_cost}."
        if profile_cost
        else f"Exportmodus {export_selection_mode} priorisiert {selected_key}; {score_best_key} hat den niedrigeren Score und sollte als Score-beste/Sozialoptimiert-Alternative geprüft werden."
    )
    return {
        "selection_strategy": (
            f"Modus {export_selection_mode} exportiert die gewählte Prüfgrundlage; "
            "andere Modi können pädagogisch stärkere Alternativen zeigen."
        ),
        "selection_mode": export_selection_mode,
        "language_profile_meaning": LANGUAGE_PROFILE_MEANING,
        "score_best_candidate": score_best_key,
        "selected_candidate": selected_key,
        "why_not_score_best": why,
        "rule_compliant_candidate": mode_recommendations.get("Regelkonform", "-"),
        "profile_minimal_candidate": mode_recommendations.get("Profilminimal", "-"),
        "social_optimized_candidate": mode_recommendations.get("Sozialoptimiert", "-"),
        "fl_target_mix_hint": _fl_target_mix_hint(selected[1], class_configs),
    }


def _scored_candidate_reports(
    reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rule_entries: list,
) -> list[tuple[ProfileSlackReport, ScoreReport]]:
    active_rules = manual_rules_module.active_manual_rules(manual_rule_entries)
    return [
        (report, score_solution(students, report.assignments, settings, class_configs, active_rules))
        for report in reports
        if report.assignments
    ]


def _selected_scored_report(
    scored_reports: list[tuple[ProfileSlackReport, ScoreReport]],
) -> tuple[ProfileSlackReport, ScoreReport] | None:
    for report, score in scored_reports:
        if _is_export_report(report):
            return report, score
    return None


def _candidate_mode_recommendations(
    scored_reports: list[tuple[ProfileSlackReport, ScoreReport]],
) -> dict[str, str]:
    if not scored_reports:
        return {}
    selected = _selected_scored_report(scored_reports)
    score_best = min(scored_reports, key=lambda item: item[1].total_score)
    profile_minimal = next((item for item in scored_reports if _candidate_key(item[0]) == "A"), None)
    rule_compliant = selected or score_best
    social = min(
        scored_reports,
        key=lambda item: (
            item[1].isolated_friend_request_count,
            -item[1].mutual_friend_fulfilled,
            -item[1].friend1_fulfilled,
            -item[1].friend2_fulfilled,
            item[1].total_score,
        ),
    )
    return {
        "Regelkonform": _candidate_key(rule_compliant[0]),
        "Profilminimal": _candidate_key((profile_minimal or rule_compliant)[0]),
        "Sozialoptimiert": _candidate_key(social[0]),
        "Score-beste Lösung": _candidate_key(score_best[0]),
    }


def _candidate_mode_text(mode_recommendations: dict[str, str], candidate_key: str) -> str:
    modes = [mode for mode, key in mode_recommendations.items() if key == candidate_key]
    return "; ".join(modes) if modes else "-"


def _score_for_selected_candidate(
    reports: list[ProfileSlackReport],
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    active_rules: list,
) -> ScoreReport | None:
    for report in reports:
        if _is_export_report(report) and report.assignments:
            return score_solution(students, report.assignments, settings, class_configs, active_rules)
    return None


def _candidate_decision_hint(
    report: ProfileSlackReport,
    score: ScoreReport | None,
    selected_score: ScoreReport | None,
) -> str:
    if _is_export_report(report):
        return "Diese Klassenblätter gehören zu diesem Kandidaten."
    if not score or not selected_score:
        return "-"
    no_friend_delta = score.isolated_friend_request_count - selected_score.isolated_friend_request_count
    score_delta = score.total_score - selected_score.total_score
    friend1_delta = score.friend1_fulfilled - selected_score.friend1_fulfilled
    friend2_delta = score.friend2_fulfilled - selected_score.friend2_fulfilled
    mutual_delta = score.mutual_friend_fulfilled - selected_score.mutual_friend_fulfilled
    fl_mixed_delta = score.mixed_language_class_count - selected_score.mixed_language_class_count
    fl_minority_delta = score.language_minority_student_count - selected_score.language_minority_student_count
    if no_friend_delta < 0:
        benefit = f"{abs(no_friend_delta)} weniger ohne Wunschfreund"
        costs = []
        if fl_mixed_delta > 0:
            costs.append(f"+{fl_mixed_delta} F/L-Mischklasse(n)")
        if fl_minority_delta > 0:
            costs.append(f"+{fl_minority_delta} F/L-Minderheits-Schüler")
        if costs:
            return f"Sozial deutlich besser: {benefit}; Preis: " + "; ".join(costs)
        return f"Sozial deutlich besser: {benefit}."
    if no_friend_delta == 0:
        quality_notes = []
        if friend1_delta < 0 or friend2_delta < 0 or mutual_delta < 0:
            quality_notes.append("schlechtere Freundschaftswerte")
        elif friend1_delta > 0 or friend2_delta > 0 or mutual_delta > 0:
            quality_notes.append("bessere Freundschaftswerte")
        if score_delta > 0:
            quality_notes.append("höherer Score")
        elif score_delta < 0:
            quality_notes.append("niedrigerer Score")
        if quality_notes:
            return "Gleiche Anzahl ohne Wunschfreund wie Export, aber " + " und ".join(quality_notes) + "."
        return "Metrisch identisch zur exportierten Klassenliste."
    return f"{no_friend_delta} mehr ohne Wunschfreund als exportierte Klassenliste."


def _profile_cost_text(candidate_score: ScoreReport, selected_score: ScoreReport) -> str:
    costs = []
    fl_mixed_delta = candidate_score.mixed_language_class_count - selected_score.mixed_language_class_count
    music_mixed_delta = candidate_score.mixed_music_class_count - selected_score.mixed_music_class_count
    fl_minority_delta = candidate_score.language_minority_student_count - selected_score.language_minority_student_count
    music_minority_delta = candidate_score.music_minority_student_count - selected_score.music_minority_student_count
    if fl_mixed_delta > 0:
        costs.append(f"+{fl_mixed_delta} F/L-Mischklasse(n)")
    if music_mixed_delta > 0:
        costs.append(f"+{music_mixed_delta} Musik-Mischklasse(n)")
    if fl_minority_delta > 0:
        costs.append(f"+{fl_minority_delta} F/L-Minderheits-Schüler")
    if music_minority_delta > 0:
        costs.append(f"+{music_minority_delta} Musik-Minderheits-Schüler")
    return "; ".join(costs)


def _fl_target_mix_hint(score_report: ScoreReport, class_configs: list[ClassConfig]) -> str:
    labels = _fl_allowed_single_language_labels(score_report, class_configs)
    if labels:
        return "F/L-erlaubte Klassen einsprachig: " + "; ".join(labels)
    if any(_class_allows_both_languages(config) for config in class_configs):
        return "Alle F/L-erlaubten Klassen sind tatsächlich gemischt."
    return "Keine F/L-erlaubten Klassen definiert."


def _fl_allowed_single_language_labels(score_report: ScoreReport, class_configs: list[ClassConfig]) -> list[str]:
    config_by_id = {config.class_id: config for config in class_configs}
    labels = []
    for report in score_report.class_reports:
        config = config_by_id.get(report.class_id)
        if not config or not _class_allows_both_languages(config):
            continue
        f_count = report.language_counts.get("F", 0)
        l_count = report.language_counts.get("L", 0)
        if not (f_count and l_count):
            labels.append(f"{report.class_id} ({f_count} F / {l_count} L)")
    return labels


def _class_allows_both_languages(config: ClassConfig) -> bool:
    return {"F", "L"}.issubset(set(config.languages_allowed))


def _is_export_report(report: ProfileSlackReport) -> bool:
    return report.variant == SELECTED_EXPORT_VARIANT or report.solution_source == SELECTED_EXPORT_SOURCE


def _candidate_key(report: ProfileSlackReport) -> str:
    if report.variant == SELECTED_EXPORT_VARIANT:
        return SELECTED_EXPORT_KEY
    return candidate_summary_module.candidate_summary_to_record(
        candidate_summary_module.candidate_summaries_from_reports([report], 1)[0]
    )["key"]


def _display_candidate_key(
    report: ProfileSlackReport,
    candidate_groups: dict[str, list[str]],
    *,
    preferred_key: str | None = None,
) -> str:
    key = _candidate_key(report)
    grouped_keys = [_candidate_key_from_variant_name(variant) for variant in candidate_groups.get(report.variant, [])]
    if preferred_key and preferred_key in grouped_keys:
        return preferred_key
    if key == SELECTED_EXPORT_KEY:
        for grouped_key in grouped_keys:
            if grouped_key != SELECTED_EXPORT_KEY:
                return grouped_key
    return key


def _candidate_key_from_variant_name(variant: str) -> str:
    if variant == SELECTED_EXPORT_VARIANT:
        return SELECTED_EXPORT_KEY
    return VARIANT_KEYS.get(variant, variant[:1] or "?")


def _standard_candidate_name(name: str) -> str:
    if name == SELECTED_EXPORT_VARIANT:
        return SELECTED_EXPORT_VARIANT
    return name.replace("Profil-Slack", "Profil-Lockerung")


def _candidate_final_status(finality: finality_module.FinalityReport) -> str:
    blockers = finality.blocker_labels()
    return "NICHT FINAL - " + "; ".join(blockers) if blockers else "prüfbar"


def _max_largest_school(score_report: ScoreReport | None) -> int | str:
    if not score_report:
        return "-"
    return max((_largest_count(report.school_counts) for report in score_report.class_reports), default=0)


def _max_largest_primary_class(score_report: ScoreReport | None) -> int | str:
    if not score_report:
        return "-"
    return max((_largest_count(report.primary_class_counts) for report in score_report.class_reports), default=0)


def _female_range(score_report: ScoreReport | None) -> str:
    if not score_report or not score_report.class_reports:
        return "-"
    female_counts = [report.gender_counts.get("w", 0) for report in score_report.class_reports]
    return f"{min(female_counts)}-{max(female_counts)}"


def _female_imbalance(score_report: ScoreReport | None) -> int | str:
    if not score_report or not score_report.class_reports:
        return "-"
    female_counts = [report.gender_counts.get("w", 0) for report in score_report.class_reports]
    return max(female_counts) - min(female_counts)


def _candidate_reports_for_export(
    profile_slack_reports: list[ProfileSlackReport],
    score_report: ScoreReport | None,
    assignments: dict[str, str],
    student_count: int,
    export_source_candidate_key: str = SELECTED_EXPORT_KEY,
) -> list[ProfileSlackReport]:
    if not score_report:
        return profile_slack_reports
    social_limit = int(student_count * 0.15)
    export_variant = (
        SELECTED_EXPORT_VARIANT
        if export_source_candidate_key == SELECTED_EXPORT_KEY
        else f"{export_source_candidate_key} - exportiert"
    )
    selected_report = ProfileSlackReport(
        variant=export_variant,
        language_mixed_limit=score_report.mixed_language_class_count,
        music_mixed_limit=score_report.mixed_music_class_count,
        status="FEASIBLE",
        objective_value=score_report.total_score,
        mixed_language_class_count=score_report.mixed_language_class_count,
        mixed_music_class_count=score_report.mixed_music_class_count,
        language_minority_student_count=score_report.language_minority_student_count,
        music_minority_student_count=score_report.music_minority_student_count,
        isolated_friend_request_count=score_report.isolated_friend_request_count,
        friend1_fulfilled=score_report.friend1_fulfilled,
        friend1_total=score_report.friend1_total,
        friend2_fulfilled=score_report.friend2_fulfilled,
        friend2_total=score_report.friend2_total,
        mutual_friend_fulfilled=score_report.mutual_friend_fulfilled,
        mutual_friend_total=score_report.mutual_friend_total,
        review_candidate=True,
        social_limit_met=score_report.isolated_friend_request_count <= social_limit,
        gap_reliable=False,
        recommendation_role=(
            "Exportierte Klassenliste"
            if export_source_candidate_key == SELECTED_EXPORT_KEY
            else f"Exportierte Klassenliste aus Kandidat {export_source_candidate_key}"
        ),
        solution_source=SELECTED_EXPORT_SOURCE,
        assignments=dict(assignments),
    )
    return [selected_report, *profile_slack_reports]


def _deduplicated_candidate_reports(
    reports: list[ProfileSlackReport],
) -> tuple[list[ProfileSlackReport], dict[str, list[str]]]:
    display_reports: list[ProfileSlackReport] = []
    representative_by_fingerprint: dict[tuple, str] = {}
    report_by_variant: dict[str, ProfileSlackReport] = {}
    groups: dict[str, list[str]] = {}

    for report in reports:
        fingerprint = _candidate_fingerprint(report)
        if _is_export_report(report):
            display_reports.append(report)
            report_by_variant[report.variant] = report
            groups[report.variant] = [report.variant]
            representative_by_fingerprint.setdefault(fingerprint, report.variant)
            continue

        representative = representative_by_fingerprint.get(fingerprint)
        if representative:
            groups.setdefault(representative, [representative]).append(report.variant)
            continue

        representative_by_fingerprint[fingerprint] = report.variant
        report_by_variant[report.variant] = report
        groups[report.variant] = [report.variant]
        display_reports.append(report)

    return display_reports, groups


def _candidate_fingerprint(report: ProfileSlackReport) -> tuple:
    if report.assignments:
        return ("assignments", tuple(sorted(report.assignments.items())))
    return (
        "metrics",
        report.mixed_language_class_count,
        report.mixed_music_class_count,
        report.language_minority_student_count,
        report.music_minority_student_count,
        report.isolated_friend_request_count,
        report.friend1_fulfilled,
        report.friend2_fulfilled,
        report.mutual_friend_fulfilled,
    )


def _write_profile_variant_rows(sheet, title: str, reports: list[ProfileSlackReport]) -> None:
    if not reports:
        return
    sheet.append([])
    sheet.append([title])
    sheet.append(
        [
            "Variante",
            "F/L Ist",
            "F/L erlaubt",
            "Musik Ist",
            "Musik erlaubt",
            "Status",
            "Objective",
            "Best Bound",
            "Gap",
            "Ohne Wunschfreund",
            "Freund 1 erfüllt",
            "Gegenseitig erfüllt",
            "Freund 2 erfüllt",
            "F/L-Minderheit",
            "Musik-Minderheit",
            "Near-Miss",
            "Zieltest-Kandidat",
            "Soziale Grenze erfüllt",
            "Gap belastbar",
            "Profil-Slack nötig",
            "Automatisch freigabefähig",
            "Kandidat für Prüfung",
            "Optimierung versucht",
            "Zieltest-Status",
            "Vertiefung versucht",
            "Vertiefung-Status",
            "Quelle",
            "Dominanz von",
        ]
    )
    for report in reports:
        sheet.append(
            [
                report.variant,
                report.mixed_language_class_count,
                report.language_mixed_limit,
                report.mixed_music_class_count,
                report.music_mixed_limit,
                report.status,
                report.objective_value,
                report.best_objective_bound,
                report.relative_gap,
                report.isolated_friend_request_count,
                _ratio_value(report.friend1_fulfilled, report.friend1_total),
                _ratio_value(report.mutual_friend_fulfilled, report.mutual_friend_total),
                _ratio_value(report.friend2_fulfilled, report.friend2_total),
                report.language_minority_student_count,
                report.music_minority_student_count,
                _approval_value(report.near_miss),
                _approval_value(report.candidate_for_target_test),
                _approval_value(report.social_limit_met),
                _approval_value(report.gap_reliable),
                _approval_value(report.profile_slack_needed),
                _approval_value(report.approvable),
                _approval_value(report.review_candidate),
                _approval_value(report.optimization_attempted),
                report.target_test_status or "-",
                _approval_value(report.refinement_attempted),
                report.refinement_status or "-",
                report.displayed_source or report.solution_source or "-",
                report.dominance_source or "-",
            ]
        )


def _write_candidate_decision_sheet(
    workbook: Workbook,
    students: list[Student],
    profile_slack_reports: list[ProfileSlackReport],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    manual_rule_entries: list,
) -> None:
    scored_reports = _scored_candidate_reports(
        profile_slack_reports,
        students,
        class_configs,
        settings,
        manual_rule_entries,
    )
    if not scored_reports:
        return
    selected = _selected_scored_report(scored_reports) or scored_reports[0]
    selected_report, selected_score = selected
    if "Kandidaten-Entscheidung" in workbook.sheetnames:
        del workbook["Kandidaten-Entscheidung"]
    sheet = workbook.create_sheet("Kandidaten-Entscheidung")
    headers = [
        "Kandidat",
        "Variante",
        "Einordnung",
        "Empfohlen für Modus",
        "Score",
        "Delta Score zum Export",
        "Kinder ohne Wunschfreund",
        "Delta ohne Wunschfreund zum Export",
        "Freund 1 erfüllt",
        "Delta Freund 1 zum Export",
        "Freund 2 erfüllt",
        "Delta Freund 2 zum Export",
        "Gegenseitige Freunde erfüllt",
        "Delta Gegenseitig zum Export",
        "F/L-Mischklassen",
        "Delta F/L-Mischklassen zum Export",
        "F/L-Minderheits-Schüler",
        "Delta F/L-Minderheit zum Export",
        "F/L-erlaubte Klassen einsprachig",
        "F/L-Zielmischung-Hinweis",
        "größte Grundschule/alte Klasse",
        "Delta Grundschule/alte Klasse zum Export",
        "Geschlechterschieflage",
        "Delta Geschlechterschieflage zum Export",
        "Kinder mit Klassenwechsel gegenüber Export",
        "Entscheidungshinweis",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    mode_recommendations = _candidate_mode_recommendations(scored_reports)
    for report, score in scored_reports:
        class_switches = _assignment_change_count(students, selected_report.assignments or {}, report.assignments or {})
        largest_primary = _numeric_metric(_max_largest_primary_class(score))
        selected_largest_primary = _numeric_metric(_max_largest_primary_class(selected_score))
        gender_imbalance = _numeric_metric(_female_imbalance(score))
        selected_gender_imbalance = _numeric_metric(_female_imbalance(selected_score))
        sheet.append(
            [
                _candidate_key(report),
                _standard_candidate_name(report.variant),
                _candidate_decision_role(report, score, selected_score),
                _candidate_mode_text(mode_recommendations, _candidate_key(report)),
                score.total_score,
                _signed_delta(score.total_score - selected_score.total_score),
                score.isolated_friend_request_count,
                _signed_delta(score.isolated_friend_request_count - selected_score.isolated_friend_request_count),
                _ratio_value(score.friend1_fulfilled, score.friend1_total),
                _signed_delta(score.friend1_fulfilled - selected_score.friend1_fulfilled),
                _ratio_value(score.friend2_fulfilled, score.friend2_total),
                _signed_delta(score.friend2_fulfilled - selected_score.friend2_fulfilled),
                _ratio_value(score.mutual_friend_fulfilled, score.mutual_friend_total),
                _signed_delta(score.mutual_friend_fulfilled - selected_score.mutual_friend_fulfilled),
                score.mixed_language_class_count,
                _signed_delta(score.mixed_language_class_count - selected_score.mixed_language_class_count),
                score.language_minority_student_count,
                _signed_delta(score.language_minority_student_count - selected_score.language_minority_student_count),
                len(_fl_allowed_single_language_labels(score, class_configs)),
                _fl_target_mix_hint(score, class_configs),
                largest_primary,
                _signed_delta(largest_primary - selected_largest_primary),
                gender_imbalance,
                _signed_delta(gender_imbalance - selected_gender_imbalance),
                class_switches,
                _candidate_decision_hint(report, score, selected_score),
            ]
        )


def _candidate_decision_role(
    report: ProfileSlackReport,
    score: ScoreReport,
    selected_score: ScoreReport,
) -> str:
    if _is_export_report(report):
        return "exportiert"
    if score.total_score < selected_score.total_score:
        return "Entscheidungsvorschlag"
    if score.isolated_friend_request_count == selected_score.isolated_friend_request_count:
        return "nicht empfohlen"
    return "Vergleich"


def _assignment_change_count(
    students: list[Student],
    selected_assignments: dict[str, str],
    candidate_assignments: dict[str, str],
) -> int:
    return sum(
        1
        for student in students
        if selected_assignments.get(student.internal_id) != candidate_assignments.get(student.internal_id)
    )


def _numeric_metric(value: int | str) -> int:
    return value if isinstance(value, int) else 0


def _signed_delta(value: int) -> str:
    return "0" if value == 0 else f"{value:+d}"


def _write_candidate_detail_sheet(
    workbook: Workbook,
    students: list[Student],
    class_configs: list[ClassConfig],
    profile_slack_reports: list[ProfileSlackReport],
    settings: OptimizationSettings,
    note_review_status_by_student: dict[str, object],
) -> None:
    summaries = candidate_summary_module.candidate_summaries_from_reports(profile_slack_reports, len(students))
    reviews = [
        candidate_review_module.build_candidate_review_model(
            summary,
            students,
            class_configs,
            settings,
            note_review_status_by_student,
        )
        for summary in summaries
        if summary.assignments
    ]
    if not reviews:
        return
    if "Kandidaten-Details" in workbook.sheetnames:
        del workbook["Kandidaten-Details"]
    sheet = workbook.create_sheet("Kandidaten-Details")
    sheet.append(
        [
            "Variante",
            "Bereich",
            "Klasse",
            "Schueler / Paar",
            "Details",
            "Wert",
            "Notiz vorhanden",
            "Notiztext",
            "Automatisch ausgewertet",
        ]
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for review in reviews:
        _append_review_details(sheet, review)


def _write_candidate_class_sheet(
    workbook: Workbook,
    students: list[Student],
    profile_slack_reports: list[ProfileSlackReport],
) -> None:
    if "Kandidaten-Klassen" in workbook.sheetnames:
        del workbook["Kandidaten-Klassen"]
    sheet = workbook.create_sheet("Kandidaten-Klassen")
    headers = [
        "Kandidat",
        "Variante",
        "Klasse",
        "Nr",
        "Name",
        "abgebende Schule",
        "alte Klasse",
        "Geschlecht",
        "Sprache",
        "Musik",
        "Freund 1",
        "Freund 2",
        "Notiz",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for report in profile_slack_reports:
        if not report.assignments:
            continue
        key = _candidate_key(report)
        name = _standard_candidate_name(report.variant)
        for student in sorted(
            students,
            key=lambda item: (report.assignments.get(item.internal_id, ""), item.sort_name, item.row_number),
        ):
            sheet.append(
                [
                    key,
                    name,
                    report.assignments.get(student.internal_id, "-"),
                    student.nr,
                    student.full_name,
                    student.school,
                    student.primary_class,
                    student.gender,
                    student.second_language,
                    student.music_profile,
                    student.friend1,
                    student.friend2,
                    _student_effective_note_text(student) or "",
                ]
            )


def _write_candidate_score_sheet(
    workbook: Workbook,
    students: list[Student],
    class_configs: list[ClassConfig],
    profile_slack_reports: list[ProfileSlackReport],
    settings: OptimizationSettings,
    manual_rule_entries: list,
) -> None:
    if "Kandidaten-Score" in workbook.sheetnames:
        del workbook["Kandidaten-Score"]
    sheet = workbook.create_sheet("Kandidaten-Score")
    headers = ["Kandidat", "Variante", "Strafkategorie", "Punkte"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    active_rules = manual_rules_module.active_manual_rules(manual_rule_entries)
    for report in profile_slack_reports:
        if not report.assignments:
            continue
        score = score_solution(students, report.assignments, settings, class_configs, active_rules)
        category_scores = score.category_scores or {"Gesamt": score.total_score}
        for label, points in sorted(category_scores.items(), key=lambda item: (-item[1], item[0])):
            sheet.append([_candidate_key(report), _standard_candidate_name(report.variant), label, points])


def _write_manual_rules_sheet(
    workbook: Workbook,
    manual_rule_entries: list,
    students: list[Student],
    assignments: dict[str, str],
) -> None:
    if "Manuelle Regeln" in workbook.sheetnames:
        del workbook["Manuelle Regeln"]
    sheet = workbook.create_sheet("Manuelle Regeln")
    headers = [
        "aktiv/deaktiviert",
        "Typ",
        "Schüler",
        "Partner/Zielklasse",
        "Quelle",
        "aus Notiz",
        "Notizstatus",
        "Erfüllt im Kandidaten",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    if not manual_rule_entries:
        sheet.append(["keine", "-", "-", "-", "-", "-", "-", "-"])
        return
    for record, entry in zip(manual_rules_module.manual_rule_entry_records(manual_rule_entries, students), manual_rule_entries, strict=True):
        note_status = "in Regel umgewandelt" if getattr(entry, "source", None) == "note" else "-"
        sheet.append(
            [
                record["Status"],
                record["Typ"],
                record["Schüler"],
                record["Ziel / Partner"],
                record["Quelle"],
                "ja" if getattr(entry, "source", None) == "note" else "nein",
                note_status,
                _manual_rule_fulfillment(getattr(entry, "rule", None), students, assignments),
            ]
        )


def _write_notes_sheet(
    workbook: Workbook,
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    manual_rule_entries: list,
    note_review_status_by_student: dict[str, object],
) -> None:
    if "Notizen" in workbook.sheetnames:
        del workbook["Notizen"]
    note_students = [student for student in students if _student_has_manual_note(student)]
    if not note_students:
        return
    sheet = workbook.create_sheet("Notizen")
    headers = [
        "Schüler",
        "Klasse im Kandidaten",
        "Status",
        "Notiz",
        "Regelvorschlag erkannt",
        "Vorschlag",
        "Vorschlag im Kandidaten erfüllt?",
        "Bestätigt/aktiv",
        "Erfüllt/verletzt",
        "Umgewandelt in Regel",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    converted_by_student = {
        entry.note_student_id: entry
        for entry in manual_rule_entries
        if getattr(entry, "source", None) == "note" and getattr(entry, "note_student_id", None)
    }
    class_ids = [config.class_id for config in class_configs]
    for student in sorted(note_students, key=lambda item: (item.sort_name, item.row_number)):
        status = note_review_status_by_student.get(student.internal_id, manual_rules_module.NoteReviewStatus.UNREVIEWED)
        converted_entry = converted_by_student.get(student.internal_id)
        suggestions = note_rule_conversion_module.suggest_note_rule_actions(
            students,
            student.internal_id,
            available_class_ids=class_ids,
        )
        sheet.append(
            [
                student.display_label,
                assignments.get(student.internal_id, "-"),
                _note_review_status_text(status),
                _student_effective_note_text(student) or "",
                "ja" if suggestions else "nein",
                _note_suggestion_text(suggestions, students),
                _note_suggestion_fulfillment_text(suggestions, students, assignments),
                _note_confirmation_text(status, converted_entry),
                _note_fulfillment_text(status, converted_entry, students, assignments),
                _manual_rule_label(converted_entry, students) if converted_entry else "",
            ]
        )


def _append_review_details(sheet, review) -> None:
    variant = review.summary.name
    for row in review.students_without_wishfriend:
        detail = "; ".join(
            item
            for item in (
                _friend_with_class(row.friend1, row.friend1_class),
                _friend_with_class(row.friend2, row.friend2_class),
            )
            if item != "-"
        )
        sheet.append(
            [
                variant,
                "Kind ohne Wunschfreund",
                row.class_id,
                row.display_name,
                detail,
                1,
                "ja" if row.has_manual_note else "nein",
                row.note_text or "",
                "nein" if row.has_manual_note else "",
            ]
        )
    for row in review.separated_mutual_friendships:
        sheet.append(
            [
                variant,
                "Gegenseitige Freundschaft getrennt",
                f"{row.student_a_class} / {row.student_b_class}",
                f"{row.student_a_name} / {row.student_b_name}",
                f"Priorität {row.priority_a} / {row.priority_b}",
                1,
                "ja" if row.has_manual_note else "nein",
                row.note_text or "",
                "nein" if row.has_manual_note else "",
            ]
        )
    for row in review.fl_mixed_classes + review.music_mixed_classes:
        area = "F/L" if row.profile_type == "language" else "Musik"
        sheet.append(
            [
                variant,
                f"{area}-Mischklasse",
                row.class_id,
                "-",
                f"Mehrheit {row.majority_label}, Minderheit {row.minority_label}",
                row.minority_count,
                "nein",
                "",
                "",
            ]
        )
        for student_name in row.minority_students:
            sheet.append(
                [
                    variant,
                    f"{area}-Minderheits-Schüler",
                    row.class_id,
                    student_name,
                    f"Minderheit {row.minority_label}",
                    1,
                    "ja" if "📝" in student_name else "nein",
                    "",
                    "nein" if "📝" in student_name else "",
                ]
            )
    for row in review.class_load_rows:
        sheet.append(
            [
                variant,
                "Klassenbelastung",
                row.class_id,
                "-",
                (
                    f"R {row.support_count}, m {row.male_count}, w {row.female_count}, "
                    f"größte Grundschule {row.largest_school_count}, "
                    f"größte Grundschule/alte Klasse {row.largest_primary_class_count}"
                ),
                row.size,
                "nein",
                "",
                "",
            ]
        )
    for row in review.students_with_manual_notes:
        sheet.append(
            [
                variant,
                "Manuelle Notiz",
                row.class_id,
                row.display_name,
                "Regelstatus im Blatt Notizen prüfen.",
                1,
                "ja",
                row.note_text,
                "nein",
            ]
        )


def _friend_with_class(name: str | None, class_id: str | None) -> str:
    if not name:
        return "-"
    return f"{name} ({class_id or '-'})"


def _student_effective_note_text(student: object) -> str | None:
    note_text = getattr(student, "note_text", None)
    if note_text is not None:
        return note_text
    return getattr(student, "comment", None)


def _student_has_manual_note(student: object) -> bool:
    note_text = _student_effective_note_text(student)
    return bool(note_text and note_text.strip())


def _unreviewed_note_count(
    students: list[Student],
    note_review_status_by_student: dict[str, object],
) -> int:
    return sum(
        1
        for student in students
        if _student_has_manual_note(student)
        and _note_review_status_is(
            note_review_status_by_student.get(student.internal_id, manual_rules_module.NoteReviewStatus.UNREVIEWED),
            manual_rules_module.NoteReviewStatus.UNREVIEWED,
        )
    )


def _student_label(students: list[Student], student_id: str | None) -> str:
    if not student_id:
        return "-"
    for student in students:
        if student.internal_id == student_id:
            return student.display_label
    return student_id


def _manual_rule_label(entry, students: list[Student]) -> str:
    if not entry:
        return ""
    record = manual_rules_module.manual_rule_entry_records([entry], students)[0]
    return f"{record['Typ']}: {record['Schüler']} -> {record['Ziel / Partner']}"


def _profile_enforcement_text(settings: OptimizationSettings) -> str:
    if settings.enforce_language_profile and settings.enforce_music_profile:
        return "Sprache und Musik"
    if settings.enforce_language_profile:
        return "Sprache"
    if settings.enforce_music_profile:
        return "Musik"
    return "nein"


def _profile_violation_labels(
    students: list[Student],
    config: ClassConfig,
    settings: OptimizationSettings,
) -> list[str]:
    labels = []
    for student in students:
        if settings.enforce_language_profile and config.languages_allowed:
            if not student.second_language or student.second_language not in config.languages_allowed:
                labels.append(f"{student.display_label}: Sprache {student.second_language or 'leer'}")
        if settings.enforce_music_profile and config.music_allowed:
            if not student.music_profile or student.music_profile not in config.music_allowed:
                labels.append(f"{student.display_label}: Musik {student.music_profile or 'leer'}")
    return labels


def _profile_violation_count(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> int:
    students_by_class = {config.class_id: [] for config in class_configs}
    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id in students_by_class:
            students_by_class[class_id].append(student)
    return sum(
        len(_profile_violation_labels(students_by_class[config.class_id], config, settings))
        for config in class_configs
    )


def _active_manual_rule_violation_count(
    manual_rule_entries: list,
    students: list[Student],
    assignments: dict[str, str],
) -> int:
    count = 0
    for entry in manual_rule_entries:
        if not getattr(entry, "active", False):
            continue
        fulfillment = _manual_rule_fulfillment(getattr(entry, "rule", None), students, assignments)
        if fulfillment == "verletzt":
            count += 1
    return count


def _manual_rule_fulfillment(rule, students: list[Student], assignments: dict[str, str]) -> str:
    if not rule:
        return "-"
    student_a = _student_by_ref(students, getattr(rule, "student_a", None))
    student_b = _student_by_ref(students, getattr(rule, "student_b", None))
    if not student_a:
        return "nicht prüfbar"
    if rule.type == "FIX_CLASS":
        return "erfüllt" if assignments.get(student_a.internal_id) == rule.class_id else "verletzt"
    if rule.type == "ALLOW_CLASSES":
        return "erfüllt" if assignments.get(student_a.internal_id) in set(rule.class_ids) else "verletzt"
    if rule.type == "TOGETHER" and student_b:
        return "erfüllt" if assignments.get(student_a.internal_id) == assignments.get(student_b.internal_id) else "verletzt"
    if rule.type == "SEPARATE" and student_b:
        return "erfüllt" if assignments.get(student_a.internal_id) != assignments.get(student_b.internal_id) else "verletzt"
    return "nicht prüfbar"


def _student_by_ref(students: list[Student], student_ref: str | None) -> Student | None:
    if not student_ref:
        return None
    for student in students:
        if student.internal_id == student_ref or student.nr == student_ref:
            return student
    return None


def _note_suggestion_text(suggestions: list, students: list[Student]) -> str:
    if not suggestions:
        return "-"
    return "; ".join(_single_note_suggestion_text(suggestion, students) for suggestion in suggestions)


def _single_note_suggestion_text(suggestion, students: list[Student]) -> str:
    maybe_prefix = "Möglicherweise gemeint: " if "Möglicherweise gemeint" in getattr(suggestion, "message", "") else ""
    if getattr(suggestion, "rule_type", None) == "FIX_CLASS":
        return f"Klassenfixierung: {suggestion.class_id}"
    if getattr(suggestion, "rule_type", None) == "ALLOW_CLASSES":
        return "Erlaubte Klassen: " + ", ".join(getattr(suggestion, "class_ids", ()) or ())
    if getattr(suggestion, "rule_type", None) == "SEPARATE":
        return f"{maybe_prefix}Trennregel: {_student_label(students, suggestion.selected_student_id)}"
    if getattr(suggestion, "rule_type", None) == "TOGETHER":
        return f"{maybe_prefix}Zusammenregel: {_student_label(students, suggestion.selected_student_id)}"
    return getattr(suggestion, "message", "") or "ungeklärter Hinweis"


def _note_suggestion_fulfillment_text(
    suggestions: list,
    students: list[Student],
    assignments: dict[str, str],
) -> str:
    rule_suggestions = [suggestion for suggestion in suggestions if getattr(suggestion, "rule_type", None)]
    if not rule_suggestions:
        return "nicht prüfbar"
    return "; ".join(
        f"{_single_note_suggestion_text(suggestion, students)}: "
        f"{_suggested_rule_fulfillment(suggestion, students, assignments)}"
        for suggestion in rule_suggestions
    )


def _suggested_rule_fulfillment(suggestion, students: list[Student], assignments: dict[str, str]) -> str:
    student = _student_by_ref(students, getattr(suggestion, "student_id", None))
    if not student:
        return "nicht prüfbar"
    if suggestion.rule_type == "FIX_CLASS":
        return "ja" if assignments.get(student.internal_id) == suggestion.class_id else "nein"
    if suggestion.rule_type == "ALLOW_CLASSES":
        return "ja" if assignments.get(student.internal_id) in set(getattr(suggestion, "class_ids", ())) else "nein"
    other = _student_by_ref(students, getattr(suggestion, "selected_student_id", None))
    if not other:
        return "nicht prüfbar"
    same_class = assignments.get(student.internal_id) == assignments.get(other.internal_id)
    if suggestion.rule_type == "TOGETHER":
        return "ja" if same_class else "nein"
    if suggestion.rule_type == "SEPARATE":
        return "ja" if not same_class else "nein"
    return "nicht prüfbar"


def _note_confirmation_text(status: object, converted_entry) -> str:
    if converted_entry and getattr(converted_entry, "active", False):
        return "ja"
    if converted_entry:
        return "deaktiviert"
    if _note_review_status_is(status, manual_rules_module.NoteReviewStatus.KEPT_AS_NOTE):
        return "als Hinweis behalten"
    return "nein"


def _note_fulfillment_text(
    status: object,
    converted_entry,
    students: list[Student],
    assignments: dict[str, str],
) -> str:
    if converted_entry:
        return _manual_rule_fulfillment(getattr(converted_entry, "rule", None), students, assignments)
    if _note_review_status_is(status, manual_rules_module.NoteReviewStatus.KEPT_AS_NOTE):
        return "nicht angewendet"
    return "ungeklärt"


def _note_review_status_text(status: object) -> str:
    if status == manual_rules_module.NoteReviewStatus.CONVERTED_TO_RULE or str(status) == "converted_to_rule":
        return "in Regel umgewandelt"
    if status == manual_rules_module.NoteReviewStatus.KEPT_AS_NOTE or str(status) == "kept_as_note":
        return "als Hinweis behalten"
    return "ungeprüft"


def _note_review_status_is(status: object, expected: manual_rules_module.NoteReviewStatus) -> bool:
    return status == expected or str(status) == expected.value


def _ratio_value(fulfilled: int | None, total: int | None) -> str:
    if fulfilled is None or total is None:
        return "-"
    return f"{fulfilled}/{total}"


def _approval_value(value: bool | None) -> str:
    if value is None:
        return "-"
    return "ja" if value else "nein"


def _write_warning_sheet(workbook: Workbook, messages: list[ValidationMessage]) -> None:
    if "Warnungen" in workbook.sheetnames:
        del workbook["Warnungen"]
    sheet = workbook.create_sheet("Warnungen")
    sheet.append(["Typ", "Zeile", "Spalte", "Wert", "Meldung"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for message in messages:
        sheet.append(
            [
                message.severity,
                message.row_number,
                message.column,
                message.value,
                message.message,
            ]
        )

from __future__ import annotations

import io as py_io

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

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
from klassenbildung.core.settings import load_settings
from klassenbildung.presentation.candidate_summary import (
    CANDIDATE_SUMMARY_FIELDS,
    candidate_summary_records_from_reports,
)
from klassenbildung.presentation.candidate_review import (
    CandidateReviewModel,
    candidate_review_models_from_reports,
)


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
) -> bytes:
    workbook = _load_or_create_workbook(source_workbook_bytes)
    basis = workbook[BASIS_SHEET_NAME]

    for student in students:
        class_id = assignments.get(student.internal_id)
        if class_id:
            basis.cell(row=student.row_number, column=1).value = class_id

    _replace_class_sheets(workbook, basis, students, assignments, class_configs)
    _write_score_sheet(
        workbook,
        score_report,
        profile_baseline_report,
        phase_reports or [] if include_expert_diagnostics else [],
        profile_slack_reports or [] if include_expert_diagnostics else [],
        profile_refinement_reports or [] if include_expert_diagnostics else [],
    )
    _write_candidate_summary_sheet(workbook, profile_slack_reports or [], len(students))
    _write_candidate_detail_sheet(
        workbook,
        students,
        class_configs,
        profile_slack_reports or [],
        settings or load_settings(),
    )
    _write_warning_sheet(workbook, validation_messages or [])

    output = py_io.BytesIO()
    workbook.save(output)
    return output.getvalue()


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
        if title in class_ids:
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
            "groesste Grundschulklasse",
        ]
    )
    for report in score_report.class_reports:
        sheet.append(
            [
                report.class_id,
                report.size,
                report.gender_counts.get("m", 0),
                report.gender_counts.get("w", 0),
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


def _write_candidate_summary_sheet(
    workbook: Workbook,
    profile_slack_reports: list[ProfileSlackReport],
    student_count: int,
) -> None:
    if "Kandidaten" in workbook.sheetnames:
        del workbook["Kandidaten"]
    records = candidate_summary_records_from_reports(profile_slack_reports, student_count)
    if not records:
        return
    sheet = workbook.create_sheet("Kandidaten")
    sheet.append(CANDIDATE_SUMMARY_FIELDS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for record in records:
        sheet.append([record.get(field) for field in CANDIDATE_SUMMARY_FIELDS])


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


def _write_candidate_detail_sheet(
    workbook: Workbook,
    students: list[Student],
    class_configs: list[ClassConfig],
    profile_slack_reports: list[ProfileSlackReport],
    settings: OptimizationSettings,
) -> None:
    reviews = candidate_review_models_from_reports(profile_slack_reports, students, class_configs, settings)
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


def _append_review_details(sheet, review: CandidateReviewModel) -> None:
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
                    f"größte Grundschulklasse {row.largest_primary_class_count}"
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
                "Diese Notiz wurde nicht automatisch ausgewertet. Bitte prüfen oder in eine Regel umwandeln.",
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

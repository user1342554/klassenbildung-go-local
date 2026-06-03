from __future__ import annotations

import io

from openpyxl import load_workbook

from klassenbildung.core.models import ClassConfig, ManualRule, ProfileSlackReport, Student
from klassenbildung.core.settings import load_settings
from klassenbildung.excel_io.excel_export import export_excel
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.candidate_summary import CANDIDATE_SUMMARY_FIELDS
from klassenbildung.presentation.result_view_model import candidate_summary_from_report
from klassenbildung.services.assignment_draft import ManualMove, create_assignment_draft, move_impact
from klassenbildung.services.manual_rules import NoteReviewStatus, create_manual_rule_entry


def test_export_updates_basis_and_creates_class_sheets(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    class_configs = [
        ClassConfig("5a", "5a", 0, 3, [], []),
        ClassConfig("5b", "5b", 0, 3, [], []),
    ]
    assignments = {
        result.students[0].internal_id: "5a",
        result.students[1].internal_id: "5b",
        result.students[2].internal_id: "5b",
    }
    score = score_solution(result.students, assignments, load_settings(), class_configs)

    exported = export_excel(sample_workbook_bytes, result.students, assignments, class_configs, score, [])
    workbook = load_workbook(io.BytesIO(exported))

    assert "Basis" in workbook.sheetnames
    assert "Übersicht" in workbook.sheetnames
    assert "5a" in workbook.sheetnames
    assert "5b" in workbook.sheetnames
    assert "Auswertung" in workbook.sheetnames
    assert "Warnungen" in workbook.sheetnames
    assert workbook["Basis"]["A3"].value == "5b"
    assert workbook["5b"].max_row == 3


def test_export_writes_candidate_detail_sheet(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    class_configs = [
        ClassConfig("5a", "5a", 0, 3, [], []),
        ClassConfig("5b", "5b", 0, 3, [], []),
    ]
    assignments = {
        result.students[0].internal_id: "5a",
        result.students[1].internal_id: "5b",
        result.students[2].internal_id: "5b",
    }
    score = score_solution(result.students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        review_candidate=True,
        assignments=assignments,
    )

    exported = export_excel(
        sample_workbook_bytes,
        result.students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))

    assert "Kandidaten-Details" in workbook.sheetnames
    assert workbook["Kandidaten-Details"].max_row > 1


def test_candidate_detail_sheet_counts_match_candidate_summary() -> None:
    students = [
        _student(1, "F", "B", friend1="2", friend2="3"),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S", friend1="1"),
        _student(4, "L", "G", friend1="5"),
        _student(5, "L", "S", friend1="4"),
        _student(6, "F", "G"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 6, [], []),
        ClassConfig("5b", "5b", 0, 6, [], []),
    ]
    assignments = {
        "s1": "5a",
        "s2": "5b",
        "s3": "5b",
        "s4": "5a",
        "s5": "5b",
        "s6": "5b",
    }
    score = score_solution(students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="F mehr Profil-Slack",
        language_mixed_limit=2,
        music_mixed_limit=3,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        language_minority_student_count=score.language_minority_student_count,
        music_minority_student_count=score.music_minority_student_count,
        review_candidate=True,
        assignments=assignments,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))
    rows = list(workbook["Kandidaten-Details"].iter_rows(min_row=2, values_only=True))

    assert _detail_count(rows, candidate.variant, "Kind ohne Wunschfreund") == candidate.isolated_friend_request_count
    assert _detail_count(rows, candidate.variant, "F/L-Minderheits-Schüler") == candidate.language_minority_student_count
    assert _detail_count(rows, candidate.variant, "Musik-Minderheits-Schüler") == candidate.music_minority_student_count


def test_candidate_detail_sheet_exports_manual_notes() -> None:
    students = [
        _student(1, "F", "B", friend1="2", note_text="nicht neben Max setzen"),
        _student(2, "L", "S", friend1="1"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    score = score_solution(students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        review_candidate=True,
        assignments=assignments,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))
    rows = list(workbook["Kandidaten-Details"].iter_rows(min_row=2, values_only=True))

    note_rows = [row for row in rows if row[0] == candidate.variant and row[1] == "Manuelle Notiz"]
    assert len(note_rows) == 1
    assert note_rows[0][6] == "ja"
    assert note_rows[0][7] == "nicht neben Max setzen"
    assert note_rows[0][8] == "nein"


def test_standard_export_omits_expert_solver_diagnostics() -> None:
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    score = score_solution(students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        review_candidate=True,
        assignments=assignments,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        phase_reports=[],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))
    values = [
        cell
        for row in workbook["Auswertung"].iter_rows(values_only=True)
        for cell in row
        if isinstance(cell, str)
    ]

    assert "Objective" not in values
    assert "Best Bound" not in values
    assert "Profil-Slack-Vergleich" not in values
    assert "Kandidaten-Details" in workbook.sheetnames


def test_standard_export_uses_candidate_summaries_not_slack_candidates() -> None:
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    score = score_solution(students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        friend1_fulfilled=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        friend2_fulfilled=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
        mutual_friend_fulfilled=score.mutual_friend_fulfilled,
        mutual_friend_total=score.mutual_friend_total,
        review_candidate=True,
        social_limit_met=True,
        assignments=assignments,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))
    exported_text = {
        cell
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
        for cell in row
        if isinstance(cell, str)
    }

    assert "Kandidaten" in workbook.sheetnames
    assert [cell.value for cell in workbook["Kandidaten"][1]] == CANDIDATE_SUMMARY_FIELDS
    assert "slack_candidates" not in exported_text
    assert "primary_recommendation" not in exported_text
    assert "balanced_recommendation" not in exported_text


def test_standard_export_does_not_emit_legacy_slack_sheet() -> None:
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    score = score_solution(students, assignments, load_settings(), class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        review_candidate=True,
        social_limit_met=True,
        assignments=assignments,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
    )
    workbook = load_workbook(io.BytesIO(exported))

    assert "Kandidaten" in workbook.sheetnames
    assert "Kandidaten-Details" in workbook.sheetnames
    assert "Profil-Slack-Vergleich" not in workbook.sheetnames
    assert "slack_candidates" not in workbook.sheetnames


def test_export_writes_manual_rules_notes_and_changes_sheets() -> None:
    students = [
        _student(1, "F", "B", friend1="2", note_text="nicht mit Max zusammen"),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 3, [], []),
        ClassConfig("5b", "5b", 0, 3, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5b"}
    settings = load_settings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        friend1_fulfilled=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        mutual_friend_fulfilled=score.mutual_friend_fulfilled,
        mutual_friend_total=score.mutual_friend_total,
        friend2_fulfilled=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
        mixed_language_class_count=score.mixed_language_class_count,
        mixed_music_class_count=score.mixed_music_class_count,
        language_minority_student_count=score.language_minority_student_count,
        music_minority_student_count=score.music_minority_student_count,
        review_candidate=True,
        social_limit_met=True,
        assignments=assignments,
    )
    summary = candidate_summary_from_report(candidate, len(students))
    draft = create_assignment_draft(summary)
    move = ManualMove("s2", "5a", "5b", reason="Teständerung")
    impact = move_impact(draft, move, summary, students, class_configs, settings)
    manual_rule_entry = create_manual_rule_entry(
        ManualRule("SEPARATE", "s1", "s2"),
        source="note",
        note_student_id="s1",
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
        manual_rule_entries=[manual_rule_entry],
        note_review_status_by_student={"s1": NoteReviewStatus.CONVERTED_TO_RULE},
        manual_moves=[move],
        manual_move_impacts=[impact],
        base_candidate_name="E: E beide +1",
        settings=settings,
    )
    workbook = load_workbook(io.BytesIO(exported))

    overview = _overview_values(workbook)
    assert "Manuelle Regeln" in workbook.sheetnames
    assert "Notizen" in workbook.sheetnames
    assert "Manuelle Änderungen" in workbook.sheetnames
    assert overview["Basis-Kandidat"] == "E: E beide +1"
    assert overview["Manuell verändert"] == "ja"
    assert workbook["Manuelle Regeln"]["A2"].value == "aktiv"
    assert workbook["Notizen"]["C2"].value == "in Regel umgewandelt"
    assert workbook["Manuelle Änderungen"]["B2"].value == "2 - V2 N2"
    assert workbook["Manuelle Änderungen"]["G1"].value == "Delta ohne Wunschfreund"
    assert "schlechter" in workbook["Manuelle Änderungen"]["G2"].value


def test_export_marks_solution_as_manually_changed() -> None:
    workbook = _manual_export_workbook()
    overview = _overview_values(workbook)

    assert overview["Manuell verändert"] == "ja"
    assert overview["Basis-Kandidat"] == "E: E beide +1"


def test_export_manual_changes_count_matches_draft_moves() -> None:
    workbook = _manual_export_workbook()
    overview = _overview_values(workbook)

    assert overview["Anzahl manueller Moves"] == 1


def test_export_draft_fixations_are_listed() -> None:
    workbook = _manual_export_workbook(lock_move=True)
    overview = _overview_values(workbook)

    assert overview["Anzahl Draft-Fixierungen"] == 1
    assert workbook["Manuelle Änderungen"]["E2"].value == "ja"


def test_export_active_manual_rules_match_ui_state() -> None:
    students = [_student(1, "F", "B"), _student(2, "L", "S")]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    settings = load_settings()
    score = score_solution(students, assignments, settings, class_configs)
    active_rule = create_manual_rule_entry(ManualRule("SEPARATE", "s1", "s2"), source="manual")
    disabled_rule = create_manual_rule_entry(
        ManualRule("TOGETHER", "s1", "s2"),
        source="manual",
        active=False,
    )

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        manual_rule_entries=[active_rule, disabled_rule],
        settings=settings,
    )
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)

    assert overview["Anzahl aktiver Regeln"] == 1
    assert overview["Anzahl deaktivierter Regeln"] == 1
    assert workbook["Manuelle Regeln"]["A2"].value == "aktiv"
    assert workbook["Manuelle Regeln"]["A3"].value == "deaktiviert"


def _manual_export_workbook(*, lock_move: bool = False):
    students = [
        _student(1, "F", "B", friend1="2"),
        _student(2, "F", "B", friend1="1"),
        _student(3, "L", "S"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 3, [], []),
        ClassConfig("5b", "5b", 0, 3, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5b"}
    settings = load_settings()
    score = score_solution(students, assignments, settings, class_configs)
    candidate = ProfileSlackReport(
        variant="E beide +1",
        language_mixed_limit=2,
        music_mixed_limit=2,
        status="FEASIBLE",
        isolated_friend_request_count=score.isolated_friend_request_count,
        friend1_fulfilled=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        mutual_friend_fulfilled=score.mutual_friend_fulfilled,
        mutual_friend_total=score.mutual_friend_total,
        friend2_fulfilled=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
        mixed_language_class_count=score.mixed_language_class_count,
        mixed_music_class_count=score.mixed_music_class_count,
        language_minority_student_count=score.language_minority_student_count,
        music_minority_student_count=score.music_minority_student_count,
        review_candidate=True,
        social_limit_met=True,
        assignments=assignments,
    )
    summary = candidate_summary_from_report(candidate, len(students))
    draft = create_assignment_draft(summary)
    move = ManualMove("s3", "5b", "5a", lock_after_move=lock_move, reason="Teständerung")
    impact = move_impact(draft, move, summary, students, class_configs, settings)

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[candidate],
        manual_moves=[move],
        manual_move_impacts=[impact],
        base_candidate_name="E: E beide +1",
        settings=settings,
    )
    return load_workbook(io.BytesIO(exported))


def _overview_values(workbook) -> dict[str, object]:
    return {
        row[0]: row[1]
        for row in workbook["Übersicht"].iter_rows(min_row=2, values_only=True)
        if row[0]
    }


def _student(
    index: int,
    language: str,
    music: str,
    *,
    friend1: str | None = None,
    friend2: str | None = None,
    note_text: str | None = None,
) -> Student:
    return Student(
        internal_id=f"s{index}",
        row_number=index + 1,
        original_class=None,
        nr=str(index),
        school="Grundschule",
        last_name=f"N{index}",
        first_name=f"V{index}",
        eligibility="GYM",
        gender="w" if index % 2 else "m",
        birthdate=None,
        nationality="DE",
        religion="ev",
        second_language=language,
        music_profile=music,
        primary_class="4a",
        friend1=friend1,
        friend2=friend2,
        comment=note_text,
        note_text=note_text,
        is_support=False,
    )


def _detail_count(rows: list[tuple], variant: str, area: str) -> int:
    return sum(int(row[5] or 0) for row in rows if row[0] == variant and row[1] == area)

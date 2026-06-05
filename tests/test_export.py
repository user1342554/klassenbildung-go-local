from __future__ import annotations

import io

from openpyxl import load_workbook

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, ProfileSlackReport, Student, ValidationMessage
from klassenbildung.core.settings import load_settings
from klassenbildung.excel_io.excel_export import CANDIDATE_EXPORT_FIELDS, export_excel
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.candidate_summary import CANDIDATE_SUMMARY_FIELDS
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
    assert workbook["Basis"].max_row == 4
    assert "_Hilfsdaten" in workbook.sheetnames
    assert workbook["_Hilfsdaten"].sheet_state == "hidden"
    assert workbook["5b"].max_row == 3


def test_export_removes_legacy_profile_named_class_sheets(sample_workbook_bytes: bytes) -> None:
    source_workbook = load_workbook(io.BytesIO(sample_workbook_bytes))
    source_workbook.create_sheet("5a S + FL")
    source_workbook.create_sheet("5F G + F")
    source_workbook.create_sheet("Info")
    source_bytes = io.BytesIO()
    source_workbook.save(source_bytes)

    result = import_excel(source_bytes.getvalue())
    class_configs = [
        ClassConfig("5a", "5a S/Reg + F/L", 0, 3, ["Reg", "S"], ["F", "L"]),
        ClassConfig("5b", "5b S/Reg + F", 0, 3, ["Reg", "S"], ["F"]),
        ClassConfig("5f", "5f G/Reg + F", 0, 3, ["Reg", "G"], ["F"]),
    ]
    assignments = {
        result.students[0].internal_id: "5a",
        result.students[1].internal_id: "5b",
        result.students[2].internal_id: "5f",
    }
    score = score_solution(result.students, assignments, load_settings(), class_configs)

    exported = export_excel(source_bytes.getvalue(), result.students, assignments, class_configs, score, [])
    workbook = load_workbook(io.BytesIO(exported))

    assert "5a S + FL" not in workbook.sheetnames
    assert "5F G + F" not in workbook.sheetnames
    assert "5a" in workbook.sheetnames
    assert "5f" in workbook.sheetnames
    assert "Info" in workbook.sheetnames


def test_export_always_writes_candidate_sheets_for_selected_solution(sample_workbook_bytes: bytes) -> None:
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

    assert "Kandidaten" in workbook.sheetnames
    assert "Kandidaten-Details" in workbook.sheetnames
    assert "Manuelle Regeln" in workbook.sheetnames
    assert "Klassenprofile" in workbook.sheetnames
    assert "Kandidaten-Entscheidung" in workbook.sheetnames
    assert "Kandidaten-Klassen" in workbook.sheetnames
    assert "Kandidaten-Score" in workbook.sheetnames
    assert workbook["Kandidaten"]["A2"].value == "X"
    assert workbook["Kandidaten"]["B2"].value == "Exportierte Klassenliste"
    assert workbook["Kandidaten"]["C2"].value == "selected"
    overview = _overview_values(workbook)
    assert str(overview["Freigabestatus"]).startswith("NICHT FINAL")
    assert overview["Programmversion"] == "V13"
    assert overview["Export-Code-Version"] == "candidate-export-v13"
    assert overview["Regelparser-Version"] == "note-rules-v2"
    assert overview["Regression-Schutz"].startswith("gespeicherte Bestkandidaten")
    assert overview["Exportierte Klassen entsprechen Kandidat"] == "X"
    assert overview["Auswahlmodus Export"] == "Regelkonform"
    assert overview["F/L-Profil bedeutet"].startswith("F/L im Klassenprofil bedeutet")
    assert overview["Score-bester Kandidat"] == "X"
    assert overview["Exportierter Kandidat"] == "X"
    assert overview["Warum nicht Score-bester Kandidat?"] == "Exportierter Kandidat ist auch score-bester Kandidat."
    assert overview["Empfehlung Regelkonform"] == "X"
    assert overview["Empfehlung Profilminimal"] == "X"
    assert overview["Empfehlung Sozialoptimiert"] == "X"
    assert overview["Empfehlung Score-beste Lösung"] == "X"
    assert overview["Harte Regelverletzungen gesamt"] == 0
    assert overview["Harte Profilverletzungen"] == 0
    assert overview["Verletzte aktive manuelle Regeln"] == 0
    assert overview["Datenblocker"] == 0
    assert overview["Kandidatenvergleich"] == (
        "nur gewählte Lösung dokumentiert; kein vollständiger Variantenvergleich"
    )
    assert workbook["Manuelle Regeln"]["A2"].value == "keine"
    candidate_headers = [cell.value for cell in workbook["Kandidaten"][1]]
    candidate_values = {
        candidate_headers[index]: workbook["Kandidaten"].cell(row=2, column=index + 1).value
        for index in range(len(candidate_headers))
    }
    assert candidate_headers == CANDIDATE_EXPORT_FIELDS
    assert candidate_values["score"] == score.total_score
    assert candidate_values["entscheidungshinweis"] == "Diese Klassenblätter gehören zu diesem Kandidaten."
    assert candidate_values["empfohlen_fuer_modus"] == (
        "Regelkonform; Profilminimal; Sozialoptimiert; Score-beste Lösung"
    )
    assert candidate_values["freigabestatus"].startswith("NICHT FINAL")
    assert candidate_values["ungepruefte_notizen"] == 1
    assert candidate_values["groesste_grundschule_alte_klasse"] == 1
    assert [cell.value for cell in workbook["Notizen"][1]] == [
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
    forbidden_overview_fields = {
        "Basis-Kandidat",
        "Neuoptimierung",
        "Manuell verändert",
        "Anzahl manueller Moves",
        "Anzahl Draft-Fixierungen",
    }
    assert forbidden_overview_fields.isdisjoint(overview)


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

    assert _detail_count(rows, "Exportierte Klassenliste", "Kind ohne Wunschfreund") == candidate.isolated_friend_request_count
    assert _detail_count(rows, "Exportierte Klassenliste", "F/L-Minderheits-Schüler") == candidate.language_minority_student_count
    assert _detail_count(rows, "Exportierte Klassenliste", "Musik-Minderheits-Schüler") == candidate.music_minority_student_count


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

    note_rows = [row for row in rows if row[0] == "Exportierte Klassenliste" and row[1] == "Manuelle Notiz"]
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
    assert [cell.value for cell in workbook["Kandidaten"][1]][: len(CANDIDATE_SUMMARY_FIELDS)] == CANDIDATE_SUMMARY_FIELDS
    assert "score" in [cell.value for cell in workbook["Kandidaten"][1]]
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


def test_export_marks_selected_solution_and_deduplicates_candidate_families() -> None:
    students = [
        _student(1, "F", "Reg", friend1="2"),
        _student(2, "F", "Reg", friend1="1"),
        _student(3, "F", "Reg", friend1="4"),
        _student(4, "F", "Reg", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    selected_assignments = {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"}
    strict_assignments = {"s1": "5a", "s2": "5b", "s3": "5b", "s4": "5a"}
    social_assignments = {"s1": "5a", "s2": "5a", "s3": "5b", "s4": "5b"}
    score = score_solution(students, selected_assignments, load_settings(), class_configs)
    candidates = [
        _candidate("A streng", strict_assignments, isolated=4, friend1=0),
        _candidate("B Musik +1", strict_assignments, isolated=4, friend1=0),
        _candidate("D F/L +1", social_assignments, isolated=0, friend1=4),
        _candidate("E beide +1", social_assignments, isolated=0, friend1=4),
    ]

    exported = export_excel(
        None,
        students,
        selected_assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=candidates,
        settings=load_settings(),
    )
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)
    rows = list(workbook["Kandidaten"].iter_rows(min_row=2, values_only=True))
    headers = [cell.value for cell in workbook["Kandidaten"][1]]
    records = [dict(zip(headers, row)) for row in rows]

    assert overview["Exportierte Klassen entsprechen Kandidat"] == "X"
    assert overview["Kandidatenvergleich"] == "3 eindeutige Kandidat(en) dokumentiert; 4 Solver-Variante(n) geprüft"
    assert [record["key"] for record in records] == ["X", "A", "D"]
    assert records[0]["role"] == "selected"
    assert records[1]["zusammengefasste_varianten"] == "A streng; B Musik +1"
    assert records[2]["role"] == "alternative"
    assert records[2]["zusammengefasste_varianten"] == "D F/L +1; E beide +1"
    assert "weniger ohne Wunschfreund" in records[2]["entscheidungshinweis"]
    assert overview["Score-bester Kandidat"] == "D"
    assert overview["Exportierter Kandidat"] == "X"
    assert overview["Empfehlung Regelkonform"] == "X"
    assert overview["Empfehlung Profilminimal"] == "A"
    assert overview["Empfehlung Sozialoptimiert"] == "D"
    assert overview["Empfehlung Score-beste Lösung"] == "D"
    assert "Exportmodus Regelkonform priorisiert X" in overview["Warum nicht Score-bester Kandidat?"]
    decision_rows = list(workbook["Kandidaten-Entscheidung"].iter_rows(min_row=2, values_only=True))
    decision_headers = [cell.value for cell in workbook["Kandidaten-Entscheidung"][1]]
    decision_records = [dict(zip(decision_headers, row)) for row in decision_rows]
    assert [record["Kandidat"] for record in decision_records] == ["X", "A", "D"]
    assert decision_records[0]["Einordnung"] == "exportiert"
    assert decision_records[0]["Empfohlen für Modus"] == "Regelkonform"
    assert decision_records[1]["Einordnung"] == "nicht empfohlen"
    assert decision_records[2]["Einordnung"] == "Entscheidungsvorschlag"
    assert decision_records[2]["Empfohlen für Modus"] == "Sozialoptimiert; Score-beste Lösung"
    assert decision_records[2]["Delta ohne Wunschfreund zum Export"].startswith("-")
    assert decision_records[2]["Kinder mit Klassenwechsel gegenüber Export"] == 2
    class_rows = list(workbook["Kandidaten-Klassen"].iter_rows(min_row=2, values_only=True))
    assert {row[0] for row in class_rows} == {"X", "A", "D"}
    score_rows = list(workbook["Kandidaten-Score"].iter_rows(min_row=2, values_only=True))
    assert {row[0] for row in score_rows} == {"X", "A", "D"}


def test_export_can_use_score_best_candidate_as_export_source() -> None:
    students = [
        _student(1, "F", "Reg", friend1="2"),
        _student(2, "F", "Reg", friend1="1"),
        _student(3, "F", "Reg", friend1="4"),
        _student(4, "F", "Reg", friend1="3"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    strict_assignments = {"s1": "5a", "s2": "5b", "s3": "5b", "s4": "5a"}
    social_assignments = {"s1": "5a", "s2": "5a", "s3": "5b", "s4": "5b"}
    score = score_solution(students, social_assignments, load_settings(), class_configs)
    candidates = [
        _candidate("A streng", strict_assignments, isolated=4, friend1=0),
        _candidate("D F/L +1", social_assignments, isolated=0, friend1=4),
        _candidate("E beide +1", social_assignments, isolated=0, friend1=4),
    ]

    exported = export_excel(
        None,
        students,
        social_assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=candidates,
        settings=load_settings(),
        export_source_candidate_key="D",
        export_selection_mode="Score-beste Lösung",
    )
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)
    headers = [cell.value for cell in workbook["Kandidaten"][1]]
    rows = list(workbook["Kandidaten"].iter_rows(min_row=2, values_only=True))
    records = [dict(zip(headers, row)) for row in rows]

    assert overview["Exportierte Klassen entsprechen Kandidat"] == "D"
    assert overview["Auswahlmodus Export"] == "Score-beste Lösung"
    assert overview["Score-bester Kandidat"] == "D"
    assert overview["Exportierter Kandidat"] == "D"
    assert overview["Warum nicht Score-bester Kandidat?"] == "Exportierter Kandidat ist auch score-bester Kandidat."
    assert [record["key"] for record in records] == ["D", "A"]
    assert records[0]["recommendation_role"] == "Exportierte Klassenliste aus Kandidat D"
    assert records[0]["zusammengefasste_varianten"] == "D - exportiert; D F/L +1; E beide +1"


def test_export_candidate_hint_distinguishes_same_isolation_from_friend_quality() -> None:
    students = [
        _student(1, "F", "Reg", friend1="2", friend2="3"),
        _student(2, "F", "Reg", friend1="1", friend2="4"),
        _student(3, "F", "Reg", friend1="4", friend2="1"),
        _student(4, "F", "Reg", friend1="3", friend2="2"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 4, [], []),
        ClassConfig("5b", "5b", 0, 4, [], []),
    ]
    selected_assignments = {"s1": "5a", "s2": "5a", "s3": "5b", "s4": "5b"}
    friend2_only_assignments = {"s1": "5a", "s2": "5b", "s3": "5a", "s4": "5b"}
    score = score_solution(students, selected_assignments, load_settings(), class_configs)

    exported = export_excel(
        None,
        students,
        selected_assignments,
        class_configs,
        score,
        [],
        profile_slack_reports=[_candidate("A streng", friend2_only_assignments, isolated=0, friend1=0)],
        settings=load_settings(),
    )
    workbook = load_workbook(io.BytesIO(exported))
    headers = [cell.value for cell in workbook["Kandidaten"][1]]
    rows = list(workbook["Kandidaten"].iter_rows(min_row=2, values_only=True))
    records = [dict(zip(headers, row)) for row in rows]

    assert records[1]["entscheidungshinweis"] == (
        "Gleiche Anzahl ohne Wunschfreund wie Export, aber schlechtere Freundschaftswerte und höherer Score."
    )


def test_export_writes_manual_rules_and_notes_sheets() -> None:
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
    settings = OptimizationSettings(enforce_language_profile=True, enforce_music_profile=True)
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
        settings=settings,
    )
    workbook = load_workbook(io.BytesIO(exported))

    overview = _overview_values(workbook)
    assert "Manuelle Regeln" in workbook.sheetnames
    assert "Notizen" in workbook.sheetnames
    assert "Manuelle Änderungen" not in workbook.sheetnames
    assert overview["Anzahl aktiver Regeln"] == 1
    assert overview["Anzahl deaktivierter Regeln"] == 0
    assert overview["Anzahl ungeprüfter Notizen"] == 0
    assert overview["Verletzte aktive manuelle Regeln"] == 1
    assert workbook["Manuelle Regeln"]["A2"].value == "aktiv"
    assert workbook["Notizen"]["C2"].value == "in Regel umgewandelt"
    assert workbook["Notizen"]["H2"].value == "ja"
    assert workbook["Notizen"]["I2"].value == "verletzt"
    candidate_headers = [cell.value for cell in workbook["Kandidaten"][1]]
    candidate_values = {
        candidate_headers[index]: workbook["Kandidaten"].cell(row=2, column=index + 1).value
        for index in range(len(candidate_headers))
    }
    assert candidate_values["verletzte_aktive_manuelle_regeln"] == 1


def test_export_marks_unreviewed_notes_as_not_final() -> None:
    students = [
        _student(1, "F", "B", note_text="NUR 5b MÖGLICH"),
        _student(2, "F", "B"),
    ]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
    ]
    assignments = {"s1": "5a", "s2": "5b"}
    score = score_solution(students, assignments, load_settings(), class_configs)

    exported = export_excel(None, students, assignments, class_configs, score, [], settings=load_settings())
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)

    assert str(overview["Freigabestatus"]).startswith("NICHT FINAL")
    assert overview["Finale Verwendung"] == "nein"
    assert overview["Finalitäts-Ampel"] == "rot"
    assert overview["Finalexport"] == "gesperrt - nur Prüfexport erlaubt"
    assert overview["Anzahl ungeprüfter Notizen"] == 1
    assert workbook["Notizen"]["E2"].value == "ja"
    assert workbook["Notizen"]["F2"].value == "Klassenfixierung: 5b"
    assert workbook["Notizen"]["G2"].value == "Klassenfixierung: 5b: nein"
    assert workbook["Notizen"]["I2"].value == "ungeklärt"


def test_export_marks_validation_data_blockers_as_not_final() -> None:
    students = [_student(1, "F", "B"), _student(2, "F", "B")]
    class_configs = [ClassConfig("5a", "5a", 0, 2, [], [])]
    assignments = {"s1": "5a", "s2": "5a"}
    score = score_solution(students, assignments, load_settings(), class_configs)
    validation_messages = [ValidationMessage("WARNUNG", "Schülernummer ist nicht numerisch.", 2, "Nr", "W")]

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        validation_messages,
        settings=load_settings(),
    )
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)

    assert str(overview["Freigabestatus"]).startswith("NICHT FINAL")
    assert overview["Datenblocker"] == 1
    assert "1 Datenblocker" in overview["Freigabestatus"]


def test_export_checks_allowed_classes_manual_rule() -> None:
    students = [_student(1, "F", "B"), _student(2, "F", "B")]
    class_configs = [
        ClassConfig("5a", "5a", 0, 2, [], []),
        ClassConfig("5b", "5b", 0, 2, [], []),
        ClassConfig("5c", "5c", 0, 2, [], []),
    ]
    assignments = {"s1": "5b", "s2": "5b"}
    rule_entry = create_manual_rule_entry(
        ManualRule("ALLOW_CLASSES", "s1", class_ids=("5a", "5c")),
        source="note",
        note_student_id="s1",
    )
    score = score_solution(students, assignments, load_settings(), class_configs, [rule_entry.rule])

    exported = export_excel(
        None,
        students,
        assignments,
        class_configs,
        score,
        [],
        manual_rule_entries=[rule_entry],
        note_review_status_by_student={"s1": NoteReviewStatus.CONVERTED_TO_RULE},
        settings=load_settings(),
    )
    workbook = load_workbook(io.BytesIO(exported))
    overview = _overview_values(workbook)

    assert workbook["Manuelle Regeln"]["B2"].value == "Erlaubte Klassen"
    assert workbook["Manuelle Regeln"]["D2"].value == "5a, 5c"
    assert workbook["Manuelle Regeln"]["H2"].value == "verletzt"
    assert overview["Verletzte aktive manuelle Regeln"] == 1


def test_export_writes_profile_permissions_and_reg_status() -> None:
    students = [
        _student(1, "F", "Reg"),
        _student(2, "F", "S"),
        _student(3, "L", "B"),
    ]
    class_configs = [
        ClassConfig("5a", "5a S/Reg + F", 0, 3, ["Reg", "S"], ["F"]),
    ]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5a"}
    settings = load_settings()
    score = score_solution(students, assignments, settings, class_configs)

    exported = export_excel(None, students, assignments, class_configs, score, [], settings=settings)
    workbook = load_workbook(io.BytesIO(exported))
    headers = [cell.value for cell in workbook["Klassenprofile"][1]]
    values = {headers[index]: workbook["Klassenprofile"].cell(row=2, column=index + 1).value for index in range(len(headers))}

    assert values["Profilname"] == "5a S/Reg + F"
    assert values["Sprachen erlaubt"] == "F"
    assert values["Musik erlaubt"] == "Reg, S"
    assert values["Reg erlaubt"] == "ja"
    assert values["F/L-Bedeutung"] == "nur F erlaubt"
    assert values["F/L tatsächlich"] == "-"
    assert values["F/L-Zielhinweis"] == "-"
    assert values["Harte Profilverletzungen"] == 2
    assert "Sprache L" in values["Beispiele"]
    assert "Musik B" in values["Beispiele"]
    overview = _overview_values(workbook)
    assert overview["Harte Profilverletzungen"] == 2
    assert overview["Harte Regelverletzungen gesamt"] == 2


def test_export_marks_fl_allowed_class_that_is_not_actually_mixed() -> None:
    students = [
        _student(1, "L", "Reg"),
        _student(2, "L", "S"),
        _student(3, "L", "Reg"),
    ]
    class_configs = [
        ClassConfig("5e", "5e G/Reg + F/L", 0, 3, ["Reg", "G"], ["F", "L"]),
    ]
    assignments = {"s1": "5e", "s2": "5e", "s3": "5e"}
    settings = load_settings()
    score = score_solution(students, assignments, settings, class_configs)

    exported = export_excel(None, students, assignments, class_configs, score, [], settings=settings)
    workbook = load_workbook(io.BytesIO(exported))
    headers = [cell.value for cell in workbook["Klassenprofile"][1]]
    values = {headers[index]: workbook["Klassenprofile"].cell(row=2, column=index + 1).value for index in range(len(headers))}
    overview = _overview_values(workbook)
    decision_headers = [cell.value for cell in workbook["Kandidaten-Entscheidung"][1]]
    decision_values = {
        decision_headers[index]: workbook["Kandidaten-Entscheidung"].cell(row=2, column=index + 1).value
        for index in range(len(decision_headers))
    }

    assert values["F/L-Bedeutung"] == "F und L erlaubt; keine harte Zielquote"
    assert values["F/L tatsächlich"] == "einsprachig (0 F / 3 L)"
    assert values["F/L-Zielhinweis"] == "F/L erlaubt, aber im Kandidaten einsprachig"
    assert overview["F/L-Zielmischung-Hinweis"] == "F/L-erlaubte Klassen einsprachig: 5e (0 F / 3 L)"
    assert decision_values["F/L-erlaubte Klassen einsprachig"] == 1
    assert decision_values["F/L-Zielmischung-Hinweis"] == "F/L-erlaubte Klassen einsprachig: 5e (0 F / 3 L)"


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
    assert overview["Verletzte aktive manuelle Regeln"] == 0
    assert workbook["Manuelle Regeln"]["A2"].value == "aktiv"
    assert workbook["Manuelle Regeln"]["A3"].value == "deaktiviert"


def test_primary_class_grouping_uses_school_and_normalized_old_class() -> None:
    students = [
        _student(1, "F", "B", school="Grundschule A", primary_class="4a"),
        _student(2, "F", "B", school="Grundschule B", primary_class="04A"),
        _student(3, "F", "B", school="Grundschule A", primary_class="4 a"),
    ]
    class_configs = [ClassConfig("5a", "5a", 0, 3, [], [])]
    assignments = {"s1": "5a", "s2": "5a", "s3": "5a"}

    score = score_solution(students, assignments, load_settings(), class_configs)

    assert score.class_reports[0].primary_class_counts == {
        "Grundschule A / 4a": 2,
        "Grundschule B / 4a": 1,
    }


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
    school: str = "Grundschule",
    primary_class: str = "4a",
    friend1: str | None = None,
    friend2: str | None = None,
    note_text: str | None = None,
) -> Student:
    return Student(
        internal_id=f"s{index}",
        row_number=index + 1,
        original_class=None,
        nr=str(index),
        school=school,
        last_name=f"N{index}",
        first_name=f"V{index}",
        eligibility="GYM",
        gender="w" if index % 2 else "m",
        birthdate=None,
        nationality="DE",
        religion="ev",
        second_language=language,
        music_profile=music,
        primary_class=primary_class,
        friend1=friend1,
        friend2=friend2,
        comment=note_text,
        note_text=note_text,
        is_support=False,
    )


def _candidate(
    variant: str,
    assignments: dict[str, str],
    *,
    isolated: int,
    friend1: int,
) -> ProfileSlackReport:
    return ProfileSlackReport(
        variant=variant,
        language_mixed_limit=0,
        music_mixed_limit=0,
        status="FEASIBLE",
        isolated_friend_request_count=isolated,
        friend1_fulfilled=friend1,
        friend1_total=4,
        friend2_fulfilled=0,
        friend2_total=0,
        mutual_friend_fulfilled=friend1 // 2,
        mutual_friend_total=2,
        review_candidate=False,
        social_limit_met=False,
        assignments=assignments,
    )


def _detail_count(rows: list[tuple], variant: str, area: str) -> int:
    return sum(int(row[5] or 0) for row in rows if row[0] == variant and row[1] == area)

from __future__ import annotations

import io

from openpyxl import load_workbook

from klassenbildung.core.models import ClassConfig
from klassenbildung.core.settings import load_settings
from klassenbildung.excel_io.excel_export import export_excel
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.optimization.scoring import score_solution


def test_export_only_contains_basis_and_class_sheets(sample_workbook_bytes: bytes) -> None:
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

    assert workbook.sheetnames == ["Basis", "5a", "5b"]
    assert workbook["Basis"]["A2"].value == "5a"
    assert workbook["Basis"]["A3"].value == "5b"
    assert workbook["Basis"]["A4"].value == "5b"
    assert workbook["Basis"].max_row == 4
    assert workbook["5a"].max_row == 2
    assert workbook["5b"].max_row == 3


def test_export_removes_legacy_profile_and_info_sheets(sample_workbook_bytes: bytes) -> None:
    source_workbook = load_workbook(io.BytesIO(sample_workbook_bytes))
    source_workbook.create_sheet("5a S + FL")
    source_workbook.create_sheet("5F G + F")
    source_workbook.create_sheet("Info")
    source_workbook.create_sheet("Übersicht")
    source_workbook.create_sheet("Kandidaten")
    source_workbook.create_sheet("Manuelle Regeln")
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

    assert workbook.sheetnames == ["Basis", "5a", "5b", "5f"]


def test_export_ignores_diagnostic_inputs_in_workbook_shape(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    class_configs = [ClassConfig("5a", "5a", 0, 3, [], [])]
    assignments = {student.internal_id: "5a" for student in result.students}
    score = score_solution(result.students, assignments, load_settings(), class_configs)

    exported = export_excel(
        sample_workbook_bytes,
        result.students,
        assignments,
        class_configs,
        score,
        [],
        include_expert_diagnostics=True,
        manual_rule_entries=[],
        note_review_status_by_student={},
        warning_decision_status_by_id={},
    )
    workbook = load_workbook(io.BytesIO(exported))

    assert workbook.sheetnames == ["Basis", "5a"]

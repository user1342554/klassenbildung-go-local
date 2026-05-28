from __future__ import annotations

from klassenbildung.excel_io.excel_import import import_excel


def test_import_reads_basis_students_and_ignores_stats(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes, filename="sample.xlsx")

    assert len(result.students) == 3
    assert result.detected_classes == ["5a", "5b"]
    assert result.students[0].original_class == "5a"
    assert result.students[0].primary_class == "4a"
    assert result.students[2].primary_class == "0404b"


def test_import_keeps_duplicate_class_columns_separate(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    first = result.students[0]

    assert first.original_class == "5a"
    assert first.primary_class == "4a"


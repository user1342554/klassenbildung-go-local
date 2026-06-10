from __future__ import annotations

from klassenbildung.excel_io.excel_import import import_excel


def test_import_reads_basis_students_and_ignores_stats(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes, filename="sample.xlsx")

    assert len(result.students) == 3
    assert result.detected_classes == ["5a", "5b"]
    assert "2 Klassen-Vorbelegungen in der Eingabedatei erkannt." in [
        message.message for message in result.messages
    ]
    assert result.students[0].original_class == "5a"
    assert result.students[0].primary_class == "4A"
    assert result.students[2].primary_class == "4B"


def test_import_keeps_duplicate_class_columns_separate(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    first = result.students[0]

    assert first.original_class == "5a"
    assert first.primary_class == "4A"


def test_import_reports_header_and_primary_class_normalization(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    info_text = "\n".join(message.message for message in result.messages if message.severity == "INFO")
    info_values = "\n".join(str(message.value) for message in result.messages if message.column == "Klasse")

    assert 'Doppelte Überschrift "Klasse" erkannt' in info_text
    assert "4 a -> 4A" in info_values
    assert "0404b -> 4B" in info_values

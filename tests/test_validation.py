from __future__ import annotations

from klassenbildung.core.models import ValidationMessage
from klassenbildung.core.settings import load_class_configs, load_settings
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.ui.tables import messages_to_frame
from klassenbildung.validation.validator import validate_students


def test_known_data_problems_create_warnings(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    validation = validate_students(result.students, load_class_configs(), load_settings(), base_messages=result.messages)
    warning_text = "\n".join(message.message for message in validation.warnings)

    assert "Schülernummer ist nicht numerisch." in warning_text
    assert "Schülernummer fehlt." in warning_text
    assert "Bemerkung muss manuell geprüft werden." in warning_text
    assert "Grundschulklasse wirkt uneinheitlich geschrieben." in warning_text


def test_warning_table_explains_next_action() -> None:
    frame = messages_to_frame(
        [ValidationMessage("WARNUNG", "Schülernummer ist nicht numerisch.", 5, "Nr", "W")]
    )

    assert "Was tun?" in frame.columns
    assert "Spalte B prüfen" in frame.iloc[0]["Was tun?"]

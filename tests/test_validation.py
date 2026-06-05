from __future__ import annotations

from klassenbildung.core.models import ValidationMessage
from klassenbildung.core.settings import load_class_configs, load_settings
from klassenbildung.excel_io.excel_import import import_excel
from klassenbildung.ui.tables import messages_to_frame
from klassenbildung.validation.finality import finality_data_blockers
from klassenbildung.validation.validator import validate_students


def test_known_data_problems_create_warnings(sample_workbook_bytes: bytes) -> None:
    result = import_excel(sample_workbook_bytes)
    validation = validate_students(result.students, load_class_configs(), load_settings(), base_messages=result.messages)
    warning_text = "\n".join(message.message for message in validation.warnings)

    assert "Schülernummer ist nicht numerisch." in warning_text
    assert "Schülernummer fehlt." in warning_text
    assert "Bemerkung muss manuell geprüft werden." in warning_text
    info_text = "\n".join(message.message for message in validation.messages if message.severity == "INFO")
    assert "Grundschulklassen wurden für die Ballungsbewertung normalisiert." in info_text
    normalization_values = "\n".join(str(message.value) for message in validation.messages if message.column == "Klasse")
    assert "4 a -> 4a" in normalization_values
    assert "0404b -> 4b" in normalization_values
    blocker_text = "\n".join(message.message for message in finality_data_blockers(validation.messages))
    assert "Schülernummer ist nicht numerisch." in blocker_text
    assert "Schülernummer fehlt." in blocker_text


def test_warning_table_explains_next_action() -> None:
    frame = messages_to_frame(
        [ValidationMessage("WARNUNG", "Schülernummer ist nicht numerisch.", 5, "Nr", "W")]
    )

    assert "Was tun?" in frame.columns
    assert "Spalte B prüfen" in frame.iloc[0]["Was tun?"]


def test_note_warning_points_to_rule_prefill() -> None:
    frame = messages_to_frame(
        [ValidationMessage("WARNUNG", "Bemerkung muss manuell geprüft werden.", 5, "Bemerkung", "nur 5e")]
    )

    assert "als Regel vorbefüllen" in frame.iloc[0]["Was tun?"]

from __future__ import annotations

import io

from openpyxl import Workbook

from klassenbildung.core.models import ClassConfig, OptimizationSettings, Student, ValidationMessage
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
    assert "Bemerkung muss manuell geprüft werden." not in warning_text
    info_text = "\n".join(message.message for message in validation.messages if message.severity == "INFO")
    assert "Grundschulklassen wurden für die Ballungsbewertung normalisiert." in info_text
    normalization_values = "\n".join(str(message.value) for message in validation.messages if message.column == "Klasse")
    assert "4 a -> 4A" in normalization_values
    assert "0404b -> 4B" in normalization_values
    blocker_text = "\n".join(message.message for message in finality_data_blockers(validation.messages))
    assert "Schülernummer ist nicht numerisch." in blocker_text
    assert "Schülernummer fehlt." in blocker_text


def test_warning_table_explains_next_action() -> None:
    frame = messages_to_frame(
        [ValidationMessage("WARNUNG", "Schülernummer ist nicht numerisch.", 5, "Nr", "W")]
    )

    assert "Was tun?" in frame.columns
    assert "Spalte B prüfen" in frame.iloc[0]["Was tun?"]


def test_hidden_whitespace_in_raw_excel_cell_is_data_blocker() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Basis"
    sheet.append(
        [
            "Klasse",
            "Nr",
            "abgebende Schule",
            "Nachname",
            "Vorname",
            "Eignung",
            "Geschlecht",
            "Geburtsdatum",
            "Staat",
            "Religion",
            "2. Fremdsprache",
            "Musikklasse",
            "Regulär",
            "Bläser",
            "Streicher",
            "Gesang",
            "Klasse",
            "Freund 1",
            "Freund 2",
            "Bemerkung",
        ]
    )
    sheet.append(
        ["5a", "1", "Grundschule A", "Beyer", "Aylin", "GYM ", "w", None, "DE", "ev", "F", "Reg", None, None, None, None, "4a", None, None, None]
    )
    output = io.BytesIO()
    workbook.save(output)

    result = import_excel(output.getvalue())

    blocker_text = "\n".join(message.message for message in finality_data_blockers(result.messages))
    assert "Wert enthält führende oder abschließende Leerzeichen." in blocker_text


def test_distribution_limit_feasibility_is_validated_before_solver() -> None:
    students = [
        _student(index, school="Grundschule A", primary_class=f"4{chr(96 + index)}")
        for index in range(1, 12)
    ]
    classes = [ClassConfig("5a", "5a", 0, 11, [], [])]

    validation = validate_students(students, classes, OptimizationSettings())

    assert any("Harte Grundschul-Ballungsgrenze" in message.message for message in validation.errors)


def test_duplicate_student_numbers_make_friend_reference_ambiguous() -> None:
    students = [
        _student(1),
        _student(2, nr="7"),
        _student(3, nr="7"),
        _student(4, friend1="7"),
    ]
    classes = [ClassConfig("5a", "5a", 0, 4, [], [])]

    validation = validate_students(students, classes, OptimizationSettings())

    warning_text = "\n".join(message.message for message in validation.warnings)
    blocker_text = "\n".join(message.message for message in finality_data_blockers(validation.messages))
    assert "Freundeswunsch 1 ist mehrdeutig." in warning_text
    assert "Freundeswunsch 1 ist mehrdeutig." in blocker_text


def _student(
    index: int,
    *,
    nr: str | None = None,
    school: str = "Grundschule",
    primary_class: str = "4a",
    friend1: str | None = None,
    support: bool = False,
) -> Student:
    return Student(
        internal_id=f"s{index}",
        row_number=index,
        original_class=None,
        nr=nr if nr is not None else str(index),
        school=school,
        last_name=f"N{index}",
        first_name=f"V{index}",
        eligibility="R" if support else "GYM",
        gender="w" if index % 2 else "m",
        birthdate=None,
        nationality="DE",
        religion="ev",
        second_language="F",
        music_profile="Reg",
        primary_class=primary_class,
        friend1=friend1,
        friend2=None,
        comment=None,
        is_support=support,
    )

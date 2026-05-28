from __future__ import annotations

import io

import pytest
from openpyxl import Workbook


@pytest.fixture
def sample_workbook_bytes() -> bytes:
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
    sheet.append(["5a", "1", "Grundschule A", "Alpha", "Anna", "GYM", "w", None, "DE", "ev", "F", "Reg", None, None, None, None, "4a", "2", None, None])
    sheet.append(["5a", "W", "Grundschule A", "Beta", "Ben", "R", "m", None, "DE", "rk", "F", "Reg", None, None, None, None, "4 a", "1", None, "nicht mit Schwester"])
    sheet.append(["5b", None, "Grundschule B", "Gamma", "Gina", "GYM", "w", None, "DE", "ev", "L", "S", None, None, "x", None, "0404b", None, None, None])
    sheet.append(["Summe", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


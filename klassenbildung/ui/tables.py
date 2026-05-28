from __future__ import annotations

import pandas as pd

from klassenbildung.core.models import ClassConfig, ScoreReport, Student, ValidationMessage


def messages_to_frame(messages: list[ValidationMessage]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Typ": message.severity,
                "Zeile": message.row_number,
                "Spalte": message.column,
                "Wert": message.value,
                "Meldung": message.message,
            }
            for message in messages
        ]
    )


def comments_to_frame(students: list[Student]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Zeile": student.row_number,
                "Nr": student.nr,
                "Name": student.display_label,
                "aktuelle Klasse": student.original_class,
                "Bemerkung": student.comment,
            }
            for student in students
            if student.comment
        ]
    )


def class_configs_to_frame(class_configs: list[ClassConfig]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": config.class_id,
                "Label": config.label,
                "Musik erlaubt": ", ".join(config.music_allowed),
                "Sprache erlaubt": ", ".join(config.languages_allowed),
                "min": config.size_min,
                "max": config.size_max,
            }
            for config in class_configs
        ]
    )


def score_to_class_frame(score_report: ScoreReport) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Klasse": report.class_id,
                "Anzahl": report.size,
                "m": report.gender_counts.get("m", 0),
                "w": report.gender_counts.get("w", 0),
                "F": report.language_counts.get("F", 0),
                "L": report.language_counts.get("L", 0),
                "Reg": report.music_counts.get("Reg", 0),
                "B": report.music_counts.get("B", 0),
                "S": report.music_counts.get("S", 0),
                "G": report.music_counts.get("G", 0),
                "R": report.support_count,
            }
            for report in score_report.class_reports
        ]
    )


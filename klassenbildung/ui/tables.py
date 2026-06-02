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
                "Wert": message.value if message.value not in (None, "") else "leer",
                "Problem": message.message,
                "Was tun?": _message_action(message),
            }
            for message in messages
        ]
    )


def _message_action(message: ValidationMessage) -> str:
    text = message.message
    if message.severity == "INFO":
        return "Keine Aktion nötig."
    if "Schülernummer fehlt" in text:
        return "In Spalte B eine eindeutige Schülernummer eintragen."
    if "Schülernummer ist nicht numerisch" in text:
        return "Spalte B prüfen: Die Schülernummer sollte eine Zahl sein."
    if "Schülernummer kommt mehrfach" in text:
        return "Spalte B prüfen: Jede Schülernummer darf nur einmal vorkommen."
    if "Eignung ist leer oder ungewöhnlich" in text:
        return "Spalte F prüfen: Erwartet wird GYM oder R. Leere/andere Werte korrigieren oder bewusst so lassen."
    if "Geschlecht ist leer oder unbekannt" in text:
        return "Spalte G prüfen: Erwartet wird m oder w."
    if "2. Fremdsprache ist leer oder unbekannt" in text:
        return "Spalte K prüfen: Erwartet wird F oder L."
    if "Musikklasse ist leer oder unbekannt" in text:
        return "Spalte L oder die Musik-Spalten M-P prüfen: Erwartet wird Reg, B, S oder G."
    if "Grundschulklasse wirkt uneinheitlich" in text:
        return "Spalte Q vereinheitlichen, z.B. 4a statt 4 a, 04A oder 0404a."
    if "Bemerkung muss manuell geprüft werden" in text:
        return "Im Details-Tab oder Editor manuell lesen. Das Programm macht daraus keine automatische Regel."
    if "Basis" in text and "fehlt" in text:
        return 'Excel-Datei prüfen: Das Arbeitsblatt muss "Basis" heißen.'
    if "Header-Zeile" in text:
        return "Die Kopfzeile mit Nr und abgebende Schule prüfen."
    if "Keine Schüler erkannt" in text:
        return "Prüfen, ob im Blatt Basis echte Schülerzeilen mit abgebender Schule stehen."
    if "Keine Klassen konfiguriert" in text:
        return "In Einstellungen die Anzahl Klassen übernehmen."
    if "Zu wenige Schüler für die Mindestgrößen" in text:
        return "Mindestgrößen oder Anzahl Klassen senken."
    if "Zu viele Schüler für die Maximalgrößen" in text:
        return "Maximale Klassengröße oder Anzahl Klassen erhöhen."
    if "Harte Profilregeln lassen" in text:
        return "Klassenprofile prüfen: Für diesen Schüler muss mindestens eine Klasse passen."
    if "Harte Profilregeln sind mit" in text:
        return "Klassengrößen/Profile lockern oder mehr passende Plätze schaffen."
    return "Zeile und Spalte in der Excel-Datei prüfen."


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
                "Musik-Hinweis": ", ".join(config.music_allowed),
                "Sprach-Hinweis": ", ".join(config.languages_allowed),
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
                "F/L gemischt": "ja" if report.is_language_mixed else "nein",
                "Reg": report.music_counts.get("Reg", 0),
                "B": report.music_counts.get("B", 0),
                "S": report.music_counts.get("S", 0),
                "G": report.music_counts.get("G", 0),
                "Musik gemischt": "ja" if report.is_music_mixed else "nein",
                "R": report.support_count,
            }
            for report in score_report.class_reports
        ]
    )

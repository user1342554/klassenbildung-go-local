from __future__ import annotations

from klassenbildung.presentation.result_view_model import CandidateSummary


def candidate_warning_lines(summary: CandidateSummary) -> list[str]:
    warnings = []
    if summary.music_minority >= 30:
        warnings.append(f"Warnung: hohe Musik-Minderheit: {summary.music_minority}.")
    if summary.fl_minority >= 20:
        warnings.append(f"Warnung: hohe F/L-Minderheit: {summary.fl_minority}.")
    if summary.key != "A":
        warnings.append("Pädagogische Prüfung nötig.")
    return warnings


def candidate_summary_text(summary: CandidateSummary) -> str:
    if not summary.social_threshold_met:
        return "soziale Grenze nicht erfüllt"
    if summary.gap_reliable:
        return "sozial im Zielbereich und technisch belastbar"
    return "gültige Lösung, aber nicht bewiesen optimal"


def candidate_tradeoff_text(summary: CandidateSummary, all_summaries: list[CandidateSummary]) -> str:
    if summary.key == "A":
        return "Diagnosevariante; nicht als Hauptlösung verwenden, wenn die soziale Grenze verfehlt ist."
    c = next((item for item in all_summaries if item.key == "C"), None)
    e = next((item for item in all_summaries if item.key == "E"), None)
    if summary.key == "C":
        return "C hält F/L streng, braucht dafür aber starke Musik-Lockerung."
    if summary.key == "E":
        if c:
            if summary.without_wishfriend < c.without_wishfriend:
                return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial liegt E knapp vor C."
            if summary.without_wishfriend == c.without_wishfriend:
                return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial sind beide gleichauf."
            return "E ist profilseitig balancierter als C: weniger Musikmischung, aber eine zusätzliche F/L-Mischklasse. Sozial liegt E knapp hinter C; bei gleichen Freundschaftsquoten entscheidet die Isolation gegen E."
        return "E balanciert Profil-Lockerung und soziale Mindestqualität."
    if summary.key == "F":
        if e:
            diff = e.without_wishfriend - summary.without_wishfriend
            if diff > 0:
                return f"F ist sozial stärkste Alternative: {diff} Kinder weniger ohne Wunschfreund als E; dafür mehr Musikmischung."
        return "F ist sozial stärkste Alternative, aber profilseitig teurer."
    return "-"

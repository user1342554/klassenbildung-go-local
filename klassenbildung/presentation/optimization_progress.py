from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from klassenbildung.services.candidate_selection import review_candidates


@dataclass(frozen=True)
class CalculationStep:
    number: int
    title: str
    explanation: str


MAIN_CALCULATION_STEPS = (
    CalculationStep(
        1,
        "F/L-Verteilung vorbereiten",
        "Zuerst wird geprüft, wie wenig Französisch/Latein-Mischung mit den festen Regeln möglich ist.",
    ),
    CalculationStep(
        2,
        "Musikverteilung vorbereiten",
        "Danach wird dasselbe für die Musikprofile geprüft, damit die Profile nicht unnötig vermischt werden.",
    ),
    CalculationStep(
        3,
        "Soziale Mindestgrenze testen",
        "Die App prüft, ob schon wenige Kinder ohne erfüllten Wunschfreund bleiben.",
    ),
    CalculationStep(
        4,
        "Kinder ohne Wunschfreund reduzieren",
        "Falls nötig wird zuerst die Zahl der Kinder ohne erfüllten Wunschfreund möglichst klein gemacht.",
    ),
    CalculationStep(
        5,
        "Gegenseitige Wünsche schützen",
        "Gegenseitige Freundschaften werden danach besonders geschützt.",
    ),
    CalculationStep(
        6,
        "Ersten Freundeswunsch verbessern",
        "Anschließend wird geprüft, wie viele erste Freundeswünsche zusätzlich erhalten bleiben.",
    ),
    CalculationStep(
        7,
        "Kleine Profilgruppen schonen",
        "In gemischten Klassen sollen möglichst wenige Kinder in einer kleinen Profilgruppe landen.",
    ),
    CalculationStep(
        8,
        "Zweiten Freundeswunsch verbessern",
        "Danach werden zweite Freundeswünsche verbessert, soweit die wichtigeren Ziele halten.",
    ),
    CalculationStep(
        9,
        "Restqualität abrunden",
        "Zum Schluss werden weitere Ausgleichsziele wie Klassengröße, Geschlecht und Herkunftsschulen mitgerechnet.",
    ),
)


def progress_fraction_for_event(event: Mapping[str, object]) -> float:
    total = int(event.get("phase_total") or len(MAIN_CALCULATION_STEPS))
    index = event.get("phase_index")
    if not isinstance(index, int) or total <= 0:
        return 0.05
    offset = 1 if event.get("event") == "finished" else 0
    return max(0.0, min((index - 1 + offset) / total, 1.0))


def progress_event_message(event: Mapping[str, object]) -> str:
    phase_name = str(event.get("phase_name") or "")
    step = step_for_phase_name(phase_name)
    if event.get("event") == "finished":
        status = plain_status_label(event.get("status"))
        if step:
            return f"Schritt {step.number} von {len(MAIN_CALCULATION_STEPS)} erledigt: {step.title} ({status})."
        return f"Zusatzprüfung erledigt: {_plain_phase_title(phase_name)} ({status})."
    if step:
        return f"Schritt {step.number} von {len(MAIN_CALCULATION_STEPS)}: {step.title}. {step.explanation}"
    return f"Zusatzprüfung läuft: {_plain_phase_title(phase_name)}."


def calculation_result_summary(solver_result, student_count: int) -> str:
    score = solver_result.score_report
    if not score:
        return "Die Berechnung konnte keine verwendbare Einteilung erzeugen. Prüfe zuerst Fehler, Klassengrößen und manuelle Regeln."
    if score.hard_violations:
        return "Die Berechnung hat eine Einteilung gefunden, aber feste Regeln werden verletzt. Diese Variante sollte nicht freigegeben werden."
    return wishfriend_result_summary(solver_result, student_count)


def wishfriend_result_summary(solver_result, student_count: int) -> str:
    score = solver_result.score_report
    if not score:
        return "Keine Lösung gefunden."
    reviews = review_candidates(solver_result, student_count)
    without_wishfriend = (
        reviews[0].without_wishfriend
        if reviews
        else score.isolated_friend_request_count
    )
    fulfilled = max(0, student_count - without_wishfriend)
    return f"Lösung gefunden: {fulfilled} von {student_count} Kindern haben mindestens einen Wunschfreund in der Klasse."


def step_for_phase_name(phase_name: str) -> CalculationStep | None:
    prefix = phase_name.split(" ", 1)[0]
    if prefix.endswith("a"):
        prefix = prefix[:-1]
    if not prefix.isdigit():
        return None
    number = int(prefix)
    return next((step for step in MAIN_CALCULATION_STEPS if step.number == number), None)


def plain_status_label(status: object) -> str:
    labels = {
        "OPTIMAL": "sicher abgeschlossen",
        "FEASIBLE": "brauchbare Zwischenlösung gefunden",
        "INFEASIBLE": "nicht möglich",
        "UNKNOWN": "im Zeitlimit nicht sicher abgeschlossen",
        "SKIPPED": "übersprungen",
        "MISSING_DEPENDENCY": "Optimierer fehlt",
        "ERROR": "abgebrochen",
    }
    return labels.get(str(status), "bearbeitet")


def _plain_phase_title(phase_name: str) -> str:
    if not phase_name:
        return "Berechnung"
    first, _, rest = phase_name.partition(" ")
    if first[:1].isdigit() and rest:
        phase_name = rest
    return phase_name.replace("Profil-Slack", "Profil-Lockerung")

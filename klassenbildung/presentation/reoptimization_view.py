from __future__ import annotations

from typing import TYPE_CHECKING

import klassenbildung.services.reoptimization as reoptimization_module

if TYPE_CHECKING:
    from klassenbildung.services.reoptimization import ReoptimizationReport


STANDARD_REOPTIMIZATION_FORBIDDEN_JARGON = [
    "FEASIBLE",
    "UNKNOWN",
    "INFEASIBLE",
    "Gap",
    "Objective",
    "Best Bound",
    "Incumbent",
    "Draft intern",
]


def reoptimization_state_text(state) -> str:
    states = reoptimization_module.ReoptimizationFlowState
    return {
        states.DRAFT_EDITED: "Manuell bearbeiteter Entwurf",
        states.DRAFT_HAS_CONFLICTS: "Blockiert durch Regelkonflikt",
        states.DRAFT_READY_FOR_REOPTIMIZATION: "Bereit für Neuoptimierung mit Fixierungen",
        states.REOPTIMIZATION_FOUND_SOLUTION: "Neu optimierte Lösung mit Fixierungen gefunden",
        states.REOPTIMIZATION_FOUND_REVIEW_CANDIDATES: "Neu optimierte Prüfkandidaten gefunden",
        states.REOPTIMIZATION_INFEASIBLE: "Mit diesen Regeln nicht lösbar",
        states.REOPTIMIZATION_UNKNOWN: "Keine entscheidbare neue Lösung gefunden",
        states.REOPTIMIZATION_ERROR: "Neuoptimierung fehlgeschlagen",
    }[state]


def reoptimization_action_hints(state) -> list[str]:
    states = reoptimization_module.ReoptimizationFlowState
    if state == states.DRAFT_HAS_CONFLICTS:
        return [
            "Regelkonflikte lösen.",
            "Letzte Änderung rückgängig machen.",
            "Fixierungen oder manuelle Regeln bearbeiten.",
        ]
    if state == states.REOPTIMIZATION_INFEASIBLE:
        return [
            "Zu viele Fixierungen oder widersprüchliche Regeln prüfen.",
            "Fixierungen lockern.",
            "Klassengrößen und harte Regeln prüfen.",
        ]
    if state == states.REOPTIMIZATION_UNKNOWN:
        return [
            "Der bisherige Entwurf bleibt erhalten.",
            "Suchzeit erhöhen oder Fixierungen vereinfachen.",
            "Neuoptimierung erneut versuchen.",
        ]
    if state == states.REOPTIMIZATION_ERROR:
        return ["Fehler prüfen und bisherigen Entwurf behalten."]
    return []


def reoptimization_summary_text(report: ReoptimizationReport) -> str:
    state = report.flow_state
    if report.succeeded:
        return (
            f"{reoptimization_state_text(state)}: {report.changed_student_count} Schüler gegenüber dem manuellen Entwurf verändert, "
            f"{len(report.fixed_student_ids)} Fixierungen übernommen."
        )
    return f"{reoptimization_state_text(state)}. Der bisherige Entwurf bleibt erhalten."


def reoptimization_visible_text(report: ReoptimizationReport) -> str:
    parts = [reoptimization_summary_text(report)]
    parts.extend(reoptimization_action_hints(report.flow_state))
    for row in report_comparison_records(report):
        parts.extend(str(value) for value in row.values())
    return " ".join(parts)


def report_comparison_records(report: ReoptimizationReport) -> list[dict[str, object]]:
    from klassenbildung.services.reoptimization import reoptimization_comparison_rows

    return reoptimization_comparison_rows(report)

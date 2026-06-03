from __future__ import annotations

from klassenbildung.services.reoptimization import ReoptimizationFlowState, ReoptimizationReport


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


def reoptimization_state_text(state: ReoptimizationFlowState) -> str:
    return {
        ReoptimizationFlowState.DRAFT_EDITED: "Manuell bearbeiteter Entwurf",
        ReoptimizationFlowState.DRAFT_HAS_CONFLICTS: "Blockiert durch Regelkonflikt",
        ReoptimizationFlowState.DRAFT_READY_FOR_REOPTIMIZATION: "Bereit für Neuoptimierung mit Fixierungen",
        ReoptimizationFlowState.REOPTIMIZATION_FOUND_SOLUTION: "Neu optimierte Lösung mit Fixierungen gefunden",
        ReoptimizationFlowState.REOPTIMIZATION_FOUND_REVIEW_CANDIDATES: "Neu optimierte Prüfkandidaten gefunden",
        ReoptimizationFlowState.REOPTIMIZATION_INFEASIBLE: "Mit diesen Regeln nicht lösbar",
        ReoptimizationFlowState.REOPTIMIZATION_UNKNOWN: "Keine entscheidbare neue Lösung gefunden",
        ReoptimizationFlowState.REOPTIMIZATION_ERROR: "Neuoptimierung fehlgeschlagen",
    }[state]


def reoptimization_action_hints(state: ReoptimizationFlowState) -> list[str]:
    if state == ReoptimizationFlowState.DRAFT_HAS_CONFLICTS:
        return [
            "Regelkonflikte lösen.",
            "Letzte Änderung rückgängig machen.",
            "Fixierungen oder manuelle Regeln bearbeiten.",
        ]
    if state == ReoptimizationFlowState.REOPTIMIZATION_INFEASIBLE:
        return [
            "Zu viele Fixierungen oder widersprüchliche Regeln prüfen.",
            "Fixierungen lockern.",
            "Klassengrößen und harte Regeln prüfen.",
        ]
    if state == ReoptimizationFlowState.REOPTIMIZATION_UNKNOWN:
        return [
            "Der bisherige Entwurf bleibt erhalten.",
            "Suchzeit erhöhen oder Fixierungen vereinfachen.",
            "Neuoptimierung erneut versuchen.",
        ]
    if state == ReoptimizationFlowState.REOPTIMIZATION_ERROR:
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

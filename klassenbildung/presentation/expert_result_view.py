from __future__ import annotations


EXPERT_SOLVER_DIAGNOSTIC_TERMS = [
    "FEASIBLE",
    "UNKNOWN",
    "OPTIMAL",
    "Gap",
    "Objective",
    "Best Bound",
    "Incumbent",
    "carried_candidate",
    "refinement",
]


def expert_solver_diagnostic_text() -> str:
    return "\n".join(EXPERT_SOLVER_DIAGNOSTIC_TERMS)

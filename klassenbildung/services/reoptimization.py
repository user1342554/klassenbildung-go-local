from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, ScoreReport, SolverResult, Student
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.services.assignment_draft import AssignmentDraft, MoveImpact, score_assignment


class ReoptimizationFlowState(StrEnum):
    DRAFT_EDITED = "draft_edited"
    DRAFT_HAS_CONFLICTS = "draft_has_conflicts"
    DRAFT_READY_FOR_REOPTIMIZATION = "draft_ready_for_reoptimization"
    REOPTIMIZATION_FOUND_SOLUTION = "reoptimization_found_solution"
    REOPTIMIZATION_FOUND_REVIEW_CANDIDATES = "reoptimization_found_review_candidates"
    REOPTIMIZATION_INFEASIBLE = "reoptimization_infeasible"
    REOPTIMIZATION_UNKNOWN = "reoptimization_unknown"
    REOPTIMIZATION_ERROR = "reoptimization_error"


@dataclass(frozen=True)
class ReoptimizationReport:
    solver_result: SolverResult
    before_score: ScoreReport
    after_score: ScoreReport | None
    changed_student_count: int
    fixed_student_ids: set[str]
    applied_rules: list[ManualRule]
    base_candidate_key: str
    base_candidate_name: str
    manual_moves: list
    manual_move_impacts: list[MoveImpact]

    @property
    def succeeded(self) -> bool:
        return self.solver_result.status in {"OPTIMAL", "FEASIBLE"} and self.after_score is not None

    @property
    def flow_state(self) -> ReoptimizationFlowState:
        if self.succeeded:
            if any(report.review_candidate for report in self.solver_result.profile_slack_reports):
                return ReoptimizationFlowState.REOPTIMIZATION_FOUND_REVIEW_CANDIDATES
            return ReoptimizationFlowState.REOPTIMIZATION_FOUND_SOLUTION
        if self.solver_result.status == "INFEASIBLE":
            return ReoptimizationFlowState.REOPTIMIZATION_INFEASIBLE
        if self.solver_result.status == "UNKNOWN":
            return ReoptimizationFlowState.REOPTIMIZATION_UNKNOWN
        return ReoptimizationFlowState.REOPTIMIZATION_ERROR


def draft_reoptimization_state(draft: AssignmentDraft, score: ScoreReport) -> ReoptimizationFlowState:
    if score.hard_violations:
        return ReoptimizationFlowState.DRAFT_HAS_CONFLICTS
    if any(move.lock_after_move for move in draft.moves):
        return ReoptimizationFlowState.DRAFT_READY_FOR_REOPTIMIZATION
    return ReoptimizationFlowState.DRAFT_EDITED


def reoptimization_rules(draft: AssignmentDraft) -> list[ManualRule]:
    rules: list[ManualRule] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for rule in draft.manual_rules:
        key = (rule.type, rule.student_a, rule.student_b, rule.class_id)
        if key in seen:
            continue
        seen.add(key)
        rules.append(rule)
    return rules


def draft_fixation_rules(draft: AssignmentDraft) -> list[ManualRule]:
    return [
        ManualRule("FIX_CLASS", move.student_id, class_id=move.to_class_id)
        for move in draft.moves
        if move.lock_after_move
    ]


def reoptimize_with_manual_fixations(
    draft: AssignmentDraft,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    *,
    base_candidate_name: str | None = None,
    manual_move_impacts: list[MoveImpact] | None = None,
) -> ReoptimizationReport:
    rules = reoptimization_rules(draft)
    before_score = score_assignment(draft, students, class_configs, settings)
    solver_result = solve_assignments(students, class_configs, settings, manual_rules=rules)
    changed_student_count = _changed_student_count(draft.current_assignments, solver_result.assignments)
    return ReoptimizationReport(
        solver_result=solver_result,
        before_score=before_score,
        after_score=solver_result.score_report,
        changed_student_count=changed_student_count,
        fixed_student_ids={rule.student_a for rule in rules if rule.type == "FIX_CLASS"},
        applied_rules=rules,
        base_candidate_key=draft.base_candidate_key,
        base_candidate_name=base_candidate_name or draft.base_candidate_key,
        manual_moves=list(draft.moves),
        manual_move_impacts=list(manual_move_impacts or []),
    )


def reoptimization_comparison_rows(report: ReoptimizationReport) -> list[dict[str, object]]:
    if not report.after_score:
        return [
            {
                "Kennzahl": "Status",
                "Manueller Entwurf": "gültig",
                "Neu optimiert": _solver_status_user_text(report.solver_result.status),
                "Änderung": "-",
                "Bewertung": "bisherigen Entwurf behalten",
            }
        ]
    rows = [
        ("Kinder ohne Wunschfreund", report.before_score.isolated_friend_request_count, report.after_score.isolated_friend_request_count, "lower"),
        ("Freund 1 erfüllt", report.before_score.friend1_fulfilled, report.after_score.friend1_fulfilled, "higher"),
        ("Gegenseitige Freunde erfüllt", report.before_score.mutual_friend_fulfilled, report.after_score.mutual_friend_fulfilled, "higher"),
        ("Freund 2 erfüllt", report.before_score.friend2_fulfilled, report.after_score.friend2_fulfilled, "higher"),
        ("F/L-Minderheits-Schüler", report.before_score.language_minority_student_count, report.after_score.language_minority_student_count, "lower"),
        ("Musik-Minderheits-Schüler", report.before_score.music_minority_student_count, report.after_score.music_minority_student_count, "lower"),
        ("Verschobene Schüler gegenüber Entwurf", 0, report.changed_student_count, "neutral"),
        ("Fixierungen verletzt", 0, len(report.after_score.hard_violations), "lower"),
    ]
    return [
        {
            "Kennzahl": label,
            "Manueller Entwurf": before,
            "Neu optimiert": after,
            "Änderung": _signed_delta(after - before),
            "Bewertung": _assessment(before, after, direction),
        }
        for label, before, after, direction in rows
    ]


def _changed_student_count(before_assignments: dict[str, str], after_assignments: dict[str, str]) -> int:
    return sum(
        1
        for student_id, before_class in before_assignments.items()
        if after_assignments.get(student_id) != before_class
    )


def _signed_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _assessment(before: int, after: int, direction: str) -> str:
    delta = after - before
    if delta == 0:
        return "unverändert"
    if direction == "neutral":
        return "Info"
    improved = delta > 0 if direction == "higher" else delta < 0
    return "besser" if improved else "schlechter"


def _solver_status_user_text(status: str) -> str:
    if status == "UNKNOWN":
        return "keine entscheidbare neue Lösung"
    if status == "INFEASIBLE":
        return "mit diesen Regeln nicht lösbar"
    if status == "FEASIBLE":
        return "gültige Lösung gefunden"
    if status == "OPTIMAL":
        return "beste Lösung bewiesen"
    return "Neuoptimierung fehlgeschlagen"

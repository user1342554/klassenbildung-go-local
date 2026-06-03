from __future__ import annotations

from dataclasses import dataclass

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, ScoreReport, SolverResult, Student
from klassenbildung.optimization.solver import solve_assignments
from klassenbildung.services.assignment_draft import AssignmentDraft, score_assignment


@dataclass(frozen=True)
class ReoptimizationReport:
    solver_result: SolverResult
    before_score: ScoreReport
    after_score: ScoreReport | None
    changed_student_count: int
    fixed_student_ids: set[str]
    applied_rules: list[ManualRule]

    @property
    def succeeded(self) -> bool:
        return self.solver_result.status in {"OPTIMAL", "FEASIBLE"} and self.after_score is not None


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
    )


def reoptimization_comparison_rows(report: ReoptimizationReport) -> list[dict[str, object]]:
    if not report.after_score:
        return [
            {
                "Kennzahl": "Status",
                "Manueller Entwurf": "gültig",
                "Neu optimiert": report.solver_result.status,
                "Änderung": "-",
            }
        ]
    rows = [
        ("Kinder ohne Wunschfreund", report.before_score.isolated_friend_request_count, report.after_score.isolated_friend_request_count),
        ("Freund 1 erfüllt", report.before_score.friend1_fulfilled, report.after_score.friend1_fulfilled),
        ("Gegenseitige Freunde erfüllt", report.before_score.mutual_friend_fulfilled, report.after_score.mutual_friend_fulfilled),
        ("Freund 2 erfüllt", report.before_score.friend2_fulfilled, report.after_score.friend2_fulfilled),
        ("F/L-Minderheits-Schüler", report.before_score.language_minority_student_count, report.after_score.language_minority_student_count),
        ("Musik-Minderheits-Schüler", report.before_score.music_minority_student_count, report.after_score.music_minority_student_count),
        ("Verschobene Schüler gegenüber Entwurf", 0, report.changed_student_count),
        ("Fixierungen verletzt", 0, len(report.after_score.hard_violations)),
    ]
    return [
        {
            "Kennzahl": label,
            "Manueller Entwurf": before,
            "Neu optimiert": after,
            "Änderung": _signed_delta(after - before),
        }
        for label, before, after in rows
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

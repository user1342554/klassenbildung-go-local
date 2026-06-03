from __future__ import annotations

from dataclasses import dataclass, replace

from klassenbildung.core.models import ClassConfig, ManualRule, OptimizationSettings, Student
from klassenbildung.optimization.scoring import score_solution
from klassenbildung.presentation.candidate_review import (
    CandidateReviewModel,
    ReviewWarning,
    ReviewWarningLevel,
    build_candidate_review_model,
)
from klassenbildung.presentation.result_view_model import CandidateSummary
from klassenbildung.services.manual_rules import ManualRuleEntry, active_manual_rules


class AssignmentDraftError(ValueError):
    pass


@dataclass(frozen=True)
class ManualMove:
    student_id: str
    from_class_id: str
    to_class_id: str
    lock_after_move: bool = False
    override_locked: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class AssignmentDraft:
    base_candidate_key: str
    base_assignments: dict[str, str]
    current_assignments: dict[str, str]
    manual_rules: list[ManualRule]
    locked_students: set[str]
    moves: list[ManualMove]


@dataclass(frozen=True)
class ClassSizeChange:
    class_id: str
    before: int
    after: int


@dataclass(frozen=True)
class MoveImpact:
    before_summary: CandidateSummary
    after_summary: CandidateSummary
    delta_without_wishfriend: int
    delta_friend1: int
    delta_mutual: int
    delta_friend2: int
    delta_fl_minority: int
    delta_music_minority: int
    class_size_changes: list[ClassSizeChange]
    warnings: list[ReviewWarning]
    hard_violations: list[str]


def create_assignment_draft(
    base_summary: CandidateSummary,
    *,
    manual_rules: list[ManualRule] | None = None,
    manual_rule_entries: list[ManualRuleEntry] | None = None,
) -> AssignmentDraft:
    active_rules = list(manual_rules or [])
    if manual_rule_entries is not None:
        active_rules.extend(active_manual_rules(manual_rule_entries))
    return AssignmentDraft(
        base_candidate_key=base_summary.key,
        base_assignments=dict(base_summary.assignments),
        current_assignments=dict(base_summary.assignments),
        manual_rules=active_rules,
        locked_students={rule.student_a for rule in active_rules if rule.type == "FIX_CLASS"},
        moves=[],
    )


def apply_move(
    draft: AssignmentDraft,
    move: ManualMove,
    *,
    students: list[Student] | None = None,
    class_configs: list[ClassConfig] | None = None,
) -> AssignmentDraft:
    _validate_move(draft, move, students=students, class_configs=class_configs)
    assignments = dict(draft.current_assignments)
    assignments[move.student_id] = move.to_class_id
    _validate_assignment_keys(draft, assignments)
    manual_rules = list(draft.manual_rules)
    locked_students = set(draft.locked_students)
    if move.lock_after_move:
        manual_rules.append(ManualRule("FIX_CLASS", move.student_id, class_id=move.to_class_id))
        locked_students.add(move.student_id)
    return replace(
        draft,
        current_assignments=assignments,
        manual_rules=manual_rules,
        locked_students=locked_students,
        moves=[*draft.moves, move],
    )


def revert_last_move(draft: AssignmentDraft) -> AssignmentDraft:
    if not draft.moves:
        return draft
    last_move = draft.moves[-1]
    assignments = dict(draft.current_assignments)
    assignments[last_move.student_id] = last_move.from_class_id
    manual_rules = list(draft.manual_rules)
    locked_students = set(draft.locked_students)
    if last_move.lock_after_move:
        last_rule = ManualRule("FIX_CLASS", last_move.student_id, class_id=last_move.to_class_id)
        for index in range(len(manual_rules) - 1, -1, -1):
            if manual_rules[index] == last_rule:
                del manual_rules[index]
                break
        if not any(rule.type == "FIX_CLASS" and rule.student_a == last_move.student_id for rule in manual_rules):
            locked_students.discard(last_move.student_id)
    return replace(
        draft,
        current_assignments=assignments,
        manual_rules=manual_rules,
        locked_students=locked_students,
        moves=list(draft.moves[:-1]),
    )


def score_assignment(
    draft: AssignmentDraft,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
):
    return score_solution(students, draft.current_assignments, settings, class_configs, draft.manual_rules)


def build_candidate_review_for_draft(
    draft: AssignmentDraft,
    base_summary: CandidateSummary,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
    *,
    note_review_status_by_student: dict | None = None,
) -> CandidateReviewModel:
    score = score_assignment(draft, students, class_configs, settings)
    summary = _summary_from_score(base_summary, draft.current_assignments, score, len(students))
    return build_candidate_review_model(
        summary,
        students,
        class_configs,
        settings,
        note_review_status_by_student=note_review_status_by_student,
    )


def move_impact(
    draft: AssignmentDraft,
    move: ManualMove,
    base_summary: CandidateSummary,
    students: list[Student],
    class_configs: list[ClassConfig],
    settings: OptimizationSettings,
) -> MoveImpact:
    before_score = score_solution(students, draft.current_assignments, settings, class_configs, draft.manual_rules)
    after_draft = apply_move(draft, move, students=students, class_configs=class_configs)
    after_score = score_solution(students, after_draft.current_assignments, settings, class_configs, after_draft.manual_rules)
    before_summary = _summary_from_score(base_summary, draft.current_assignments, before_score, len(students))
    after_summary = _summary_from_score(base_summary, after_draft.current_assignments, after_score, len(students))
    warnings = _move_warnings(move, students, after_score.hard_violations)
    return MoveImpact(
        before_summary=before_summary,
        after_summary=after_summary,
        delta_without_wishfriend=after_summary.without_wishfriend - before_summary.without_wishfriend,
        delta_friend1=after_summary.friend1_satisfied - before_summary.friend1_satisfied,
        delta_mutual=after_summary.mutual_satisfied - before_summary.mutual_satisfied,
        delta_friend2=after_summary.friend2_satisfied - before_summary.friend2_satisfied,
        delta_fl_minority=after_summary.fl_minority - before_summary.fl_minority,
        delta_music_minority=after_summary.music_minority - before_summary.music_minority,
        class_size_changes=_class_size_changes(before_score.class_reports, after_score.class_reports),
        warnings=warnings,
        hard_violations=list(after_score.hard_violations),
    )


def _summary_from_score(base_summary: CandidateSummary, assignments: dict[str, str], score, student_count: int) -> CandidateSummary:
    return replace(
        base_summary,
        assignments=dict(assignments),
        fl_mixed_actual=score.mixed_language_class_count,
        music_mixed_actual=score.mixed_music_class_count,
        fl_minority=score.language_minority_student_count,
        music_minority=score.music_minority_student_count,
        without_wishfriend=score.isolated_friend_request_count,
        without_wishfriend_rate=score.isolated_friend_request_count / max(student_count, 1),
        friend1_satisfied=score.friend1_fulfilled,
        friend1_total=score.friend1_total,
        mutual_satisfied=score.mutual_friend_fulfilled,
        mutual_total=score.mutual_friend_total,
        friend2_satisfied=score.friend2_fulfilled,
        friend2_total=score.friend2_total,
    )


def _class_size_changes(before_reports, after_reports) -> list[ClassSizeChange]:
    before_sizes = {report.class_id: report.size for report in before_reports}
    after_sizes = {report.class_id: report.size for report in after_reports}
    return [
        ClassSizeChange(class_id, before_sizes.get(class_id, 0), after_sizes.get(class_id, 0))
        for class_id in sorted(set(before_sizes) | set(after_sizes))
        if before_sizes.get(class_id, 0) != after_sizes.get(class_id, 0)
    ]


def _move_warnings(move: ManualMove, students: list[Student], hard_violations: list[str]) -> list[ReviewWarning]:
    warnings = []
    student = next((item for item in students if item.internal_id == move.student_id), None)
    if student and _student_has_manual_note(student):
        warnings.append(ReviewWarning(ReviewWarningLevel.WARNING, "Schüler hat eine manuelle Notiz."))
    for violation in hard_violations:
        warnings.append(ReviewWarning(ReviewWarningLevel.BLOCKER, violation))
    return warnings


def _student_has_manual_note(student: object) -> bool:
    note_text = getattr(student, "note_text", None)
    if note_text is None:
        note_text = getattr(student, "comment", None)
    return bool(note_text and note_text.strip())


def _validate_move(
    draft: AssignmentDraft,
    move: ManualMove,
    *,
    students: list[Student] | None,
    class_configs: list[ClassConfig] | None,
) -> None:
    if students is not None and move.student_id not in {student.internal_id for student in students}:
        raise AssignmentDraftError(f"Unbekannter Schüler: {move.student_id}")
    if move.student_id not in draft.current_assignments:
        raise AssignmentDraftError(f"Unbekannter Schüler im Draft: {move.student_id}")
    if draft.current_assignments[move.student_id] != move.from_class_id:
        raise AssignmentDraftError(
            f"{move.student_id} ist nicht mehr in {move.from_class_id}, sondern in {draft.current_assignments[move.student_id]}"
        )
    if class_configs is not None:
        class_ids = {config.class_id for config in class_configs}
        if move.from_class_id not in class_ids:
            raise AssignmentDraftError(f"Unbekannte Ausgangsklasse: {move.from_class_id}")
        if move.to_class_id not in class_ids:
            raise AssignmentDraftError(f"Unbekannte Zielklasse: {move.to_class_id}")
    if move.student_id in draft.locked_students and not move.override_locked and move.from_class_id != move.to_class_id:
        raise AssignmentDraftError("Fixierter Schüler kann ohne Override nicht verschoben werden.")


def _validate_assignment_keys(draft: AssignmentDraft, assignments: dict[str, str]) -> None:
    if set(assignments) != set(draft.base_assignments):
        raise AssignmentDraftError("Draft-Zuweisungen müssen genau dieselben Schüler enthalten.")

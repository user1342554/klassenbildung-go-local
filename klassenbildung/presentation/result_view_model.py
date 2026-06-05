from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from klassenbildung.core.models import ProfileSlackReport, SolverStatus


class CandidateRole(StrEnum):
    STRICT_DIAGNOSTIC = "strict_diagnostic"
    REVIEW = "review"
    DISCARDED = "discarded"


class CandidateSource(StrEnum):
    STRICT_SEARCH = "strict_search"
    SLACK_SEARCH = "slack_search"
    CACHED_INCUMBENT = "cached_incumbent"
    CARRIED_CANDIDATE = "carried_candidate"
    REFINEMENT = "refinement"
    UNKNOWN = "unknown"


VARIANT_KEYS = {
    "Exportierte Klassenliste": "X",
    "A streng": "A",
    "B Musik +1": "B",
    "C Musik +2": "C",
    "D F/L +1": "D",
    "E beide +1": "E",
    "F mehr Profil-Slack": "F",
}


@dataclass(frozen=True)
class CandidateSummary:
    key: str
    name: str
    role: CandidateRole
    recommendation_role: str | None

    assignments: dict[str, str]

    fl_mixed_actual: int
    fl_mixed_allowed: int
    music_mixed_actual: int
    music_mixed_allowed: int
    fl_minority: int
    music_minority: int

    without_wishfriend: int
    without_wishfriend_rate: float
    friend1_satisfied: int
    friend1_total: int
    mutual_satisfied: int
    mutual_total: int
    friend2_satisfied: int
    friend2_total: int

    social_threshold_met: bool
    candidate_for_review: bool
    automatically_approvable: bool

    gap: float | None
    gap_reliable: bool

    displayed_source: CandidateSource
    refinement_attempted: bool
    refinement_status: SolverStatus | None
    refinement_result: str | None


def candidate_summary_from_report(report: ProfileSlackReport, student_count: int) -> CandidateSummary:
    return CandidateSummary(
        key=VARIANT_KEYS.get(report.variant, report.variant[:1] or "?"),
        name=report.variant,
        role=_candidate_role(report),
        recommendation_role=report.recommendation_role,
        assignments=dict(report.assignments or {}),
        fl_mixed_actual=report.mixed_language_class_count or 0,
        fl_mixed_allowed=report.language_mixed_limit,
        music_mixed_actual=report.mixed_music_class_count or 0,
        music_mixed_allowed=report.music_mixed_limit,
        fl_minority=report.language_minority_student_count or 0,
        music_minority=report.music_minority_student_count or 0,
        without_wishfriend=report.isolated_friend_request_count or 0,
        without_wishfriend_rate=(report.isolated_friend_request_count or 0) / max(student_count, 1),
        friend1_satisfied=report.friend1_fulfilled or 0,
        friend1_total=report.friend1_total or 0,
        mutual_satisfied=report.mutual_friend_fulfilled or 0,
        mutual_total=report.mutual_friend_total or 0,
        friend2_satisfied=report.friend2_fulfilled or 0,
        friend2_total=report.friend2_total or 0,
        social_threshold_met=bool(report.social_limit_met),
        candidate_for_review=bool(report.review_candidate),
        automatically_approvable=bool(report.approvable),
        gap=report.displayed_gap if report.displayed_gap is not None else report.relative_gap,
        gap_reliable=bool(report.gap_reliable),
        displayed_source=_candidate_source(report.displayed_source or report.solution_source),
        refinement_attempted=report.refinement_attempted,
        refinement_status=report.refinement_status,
        refinement_result=_refinement_result(report),
    )


def _candidate_role(report: ProfileSlackReport) -> CandidateRole:
    if report.variant == "A streng":
        return CandidateRole.STRICT_DIAGNOSTIC
    if report.review_candidate:
        return CandidateRole.REVIEW
    return CandidateRole.DISCARDED


def _candidate_source(source: str | None) -> CandidateSource:
    if source == "carried_candidate" or (source or "").startswith("carried_from:"):
        return CandidateSource.CARRIED_CANDIDATE
    if source == "slack_search":
        return CandidateSource.SLACK_SEARCH
    if source == "strict_search":
        return CandidateSource.STRICT_SEARCH
    if source in {"cached_incumbent", "seeded_incumbent"}:
        return CandidateSource.CACHED_INCUMBENT
    if source == "refinement":
        return CandidateSource.REFINEMENT
    return CandidateSource.UNKNOWN


def _refinement_result(report: ProfileSlackReport) -> str | None:
    if not report.refinement_attempted:
        return None
    if (report.displayed_source or report.solution_source) == "carried_candidate":
        return "keine Verbesserung, angezeigter Kandidat bleibt erhalten"
    return "angezeigte Lösung aus Vertiefung/Zieltest"

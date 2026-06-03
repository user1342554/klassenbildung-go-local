from __future__ import annotations

from klassenbildung.presentation.candidate_summary import candidate_summaries_from_reports
from klassenbildung.presentation.result_view_model import CandidateSummary


def candidate_summaries(solver_result, student_count: int) -> list[CandidateSummary]:
    return candidate_summaries_from_reports(solver_result.profile_slack_reports, student_count)


def review_candidates(solver_result, student_count: int) -> list[CandidateSummary]:
    candidates = [
        summary
        for summary in candidate_summaries(solver_result, student_count)
        if summary.key != "A" and summary.candidate_for_review
    ]
    return sorted(
        candidates,
        key=lambda summary: (
            summary.without_wishfriend,
            -summary.mutual_satisfied,
            -summary.friend1_satisfied,
        ),
    )


def diagnostic_candidate(solver_result, student_count: int) -> CandidateSummary | None:
    for summary in candidate_summaries(solver_result, student_count):
        if summary.key == "A":
            return summary
    return None


def social_strongest_candidate(solver_result, student_count: int) -> CandidateSummary | None:
    candidates = review_candidates(solver_result, student_count)
    return candidates[0] if candidates else None


def balanced_candidate(solver_result, student_count: int) -> CandidateSummary | None:
    candidates = review_candidates(solver_result, student_count)
    if not candidates:
        return None
    for summary in candidates:
        if summary.key == "E":
            return summary
    return min(
        candidates,
        key=lambda summary: (
            summary.fl_mixed_allowed + summary.music_mixed_allowed,
            summary.without_wishfriend,
        ),
    )


def fl_conservative_candidate(solver_result, student_count: int) -> CandidateSummary | None:
    for summary in review_candidates(solver_result, student_count):
        if summary.key == "C":
            return summary
    return None


def decision_candidate_cards(solver_result, student_count: int) -> list[tuple[str, CandidateSummary, str]]:
    items = [
        ("E - am ausgewogensten", balanced_candidate(solver_result, student_count), "Profil-/Sozialkompromiss zuerst prüfen."),
        ("F - sozial stärkste Alternative", social_strongest_candidate(solver_result, student_count), "Beste Sozialwerte, aber profilseitig teurer."),
        ("C - F/L-schonende Alternative", fl_conservative_candidate(solver_result, student_count), "F/L möglichst streng, Musik stärker gelockert."),
    ]
    cards: list[tuple[str, CandidateSummary, str]] = []
    seen: set[str] = set()
    for title, summary, caption in items:
        if summary and summary.key not in seen:
            seen.add(summary.key)
            cards.append((title, summary, caption))
    return cards

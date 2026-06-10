from __future__ import annotations

from dataclasses import dataclass

from klassenbildung.presentation.candidate_summary import candidate_summary_to_record
from klassenbildung.services.candidate_selection import (
    candidate_summaries,
    decision_candidate_cards,
    diagnostic_candidate,
    review_candidates,
)


STANDARD_MODE_FORBIDDEN_SOLVER_JARGON = {
    "FEASIBLE",
    "UNKNOWN",
    "OPTIMAL",
    "Gap",
    "Objective",
    "Best Bound",
    "Incumbent",
    "Slack",
    "carried_candidate",
    "refinement",
}


@dataclass(frozen=True)
class StandardResultViewModel:
    status: str
    headline: str
    message: str
    diagnostic: dict[str, object] | None
    cards: list[dict[str, object]]

    def visible_text(self) -> str:
        parts = [self.status, self.headline, self.message]
        if self.diagnostic:
            parts.extend(_visible_record_values(self.diagnostic))
        for card in self.cards:
            parts.extend(_visible_record_values(card))
        return "\n".join(parts)


def build_standard_result_view_model(solver_result, student_count: int) -> StandardResultViewModel:
    reviews = review_candidates(solver_result, student_count)
    diagnostic = diagnostic_candidate(solver_result, student_count)
    cards = [
        {
            "title": title,
            "caption": caption,
            **candidate_summary_to_record(summary),
        }
        for title, summary, caption in decision_candidate_cards(solver_result, student_count)
    ]
    if reviews:
        headline = "Beste Lösung gefunden"
        message = (
            "Die strenge Profilvariante ist sozial nicht brauchbar. "
            "Angezeigt wird die beste Variante mit Profil-Lockerung. "
            "Keine automatische Freigabe: pädagogische Prüfung nötig."
        )
    else:
        headline = "Ergebnis prüfen"
        message = "Keine automatisch freigegebene Standardentscheidung vorhanden."
    return StandardResultViewModel(
        status=headline,
        headline=headline,
        message=message,
        diagnostic=candidate_summary_to_record(diagnostic) if diagnostic else None,
        cards=cards,
    )


def standard_visible_text(solver_result, student_count: int) -> str:
    return build_standard_result_view_model(solver_result, student_count).visible_text()


def all_candidate_summary_records_for_standard_view(
    solver_result,
    student_count: int,
) -> list[dict[str, object]]:
    records = []
    diagnostic = diagnostic_candidate(solver_result, student_count)
    if diagnostic:
        records.append(candidate_summary_to_record(diagnostic))
    card_keys = set()
    for _, summary, _ in decision_candidate_cards(solver_result, student_count):
        card_keys.add(summary.key)
        records.append(candidate_summary_to_record(summary))
    for summary in candidate_summaries(solver_result, student_count):
        if summary.key not in card_keys and summary.key != "A":
            records.append(candidate_summary_to_record(summary))
    return records


def _visible_record_values(record: dict[str, object]) -> list[str]:
    visible_fields = {
        "title",
        "caption",
        "key",
        "name",
        "without_wishfriend",
        "friend1",
        "mutual",
        "friend2",
        "fl_mixed_actual",
        "music_mixed_actual",
        "fl_minority",
        "music_minority",
    }
    return [str(value) for field, value in record.items() if field in visible_fields]

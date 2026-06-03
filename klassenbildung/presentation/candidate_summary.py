from __future__ import annotations

from klassenbildung.core.models import ProfileSlackReport
from klassenbildung.presentation.result_view_model import CandidateSummary, candidate_summary_from_report


CANDIDATE_SUMMARY_FIELDS = [
    "key",
    "name",
    "role",
    "recommendation_role",
    "without_wishfriend",
    "friend1",
    "mutual",
    "friend2",
    "fl_mixed_actual",
    "music_mixed_actual",
    "fl_minority",
    "music_minority",
]


def candidate_summaries_from_reports(reports: list[ProfileSlackReport], student_count: int) -> list[CandidateSummary]:
    return [candidate_summary_from_report(report, student_count) for report in reports]


def candidate_summary_to_record(summary: CandidateSummary) -> dict[str, object]:
    return {
        "key": summary.key,
        "name": _standard_candidate_name(summary.name),
        "role": summary.role.value,
        "recommendation_role": summary.recommendation_role,
        "without_wishfriend": summary.without_wishfriend,
        "friend1": f"{summary.friend1_satisfied}/{summary.friend1_total}",
        "mutual": f"{summary.mutual_satisfied}/{summary.mutual_total}",
        "friend2": f"{summary.friend2_satisfied}/{summary.friend2_total}",
        "fl_mixed_actual": summary.fl_mixed_actual,
        "music_mixed_actual": summary.music_mixed_actual,
        "fl_minority": summary.fl_minority,
        "music_minority": summary.music_minority,
    }


def _standard_candidate_name(name: str) -> str:
    return name.replace("Profil-Slack", "Profil-Lockerung")


def candidate_summary_records_from_reports(
    reports: list[ProfileSlackReport],
    student_count: int,
) -> list[dict[str, object]]:
    return [
        candidate_summary_to_record(summary)
        for summary in candidate_summaries_from_reports(reports, student_count)
    ]


def candidate_summary_records(solver_result, student_count: int) -> list[dict[str, object]]:
    return candidate_summary_records_from_reports(solver_result.profile_slack_reports, student_count)

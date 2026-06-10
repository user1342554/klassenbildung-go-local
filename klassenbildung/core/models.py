from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


Severity = Literal["INFO", "WARNUNG", "FEHLER"]
RuleType = Literal["FIX_CLASS", "ALLOW_CLASSES", "SEPARATE", "TOGETHER"]
SolverStatus = Literal[
    "OPTIMAL",
    "FEASIBLE",
    "INFEASIBLE",
    "UNKNOWN",
    "SKIPPED",
    "MISSING_DEPENDENCY",
    "ERROR",
]


@dataclass(frozen=True)
class ValidationMessage:
    severity: Severity
    message: str
    row_number: int | None = None
    column: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class Student:
    internal_id: str
    row_number: int

    original_class: str | None
    nr: str | None
    school: str | None
    last_name: str | None
    first_name: str | None
    eligibility: str | None
    gender: str | None
    birthdate: date | None
    nationality: str | None
    religion: str | None
    second_language: str | None
    music_profile: str | None
    primary_class: str | None
    friend1: str | None
    friend2: str | None
    comment: str | None
    note_text: str | None = None

    is_support: bool = False

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(part for part in parts if part)

    @property
    def sort_name(self) -> str:
        parts = [self.last_name, self.first_name]
        return ", ".join(part for part in parts if part)

    @property
    def display_label(self) -> str:
        prefix = f"{self.nr} - " if self.nr else ""
        return f"{prefix}{self.full_name or self.internal_id}"

    @property
    def effective_note_text(self) -> str | None:
        return student_effective_note_text(self)

    @property
    def has_manual_note(self) -> bool:
        return student_has_manual_note(self)


def student_effective_note_text(student: object) -> str | None:
    note_text = getattr(student, "note_text", None)
    if note_text is not None:
        return note_text
    return getattr(student, "comment", None)


def student_has_manual_note(student: object) -> bool:
    note_text = student_effective_note_text(student)
    return bool(note_text and note_text.strip())


@dataclass(frozen=True)
class ClassSizePolicy:
    target_size: int
    comfort_tolerance: int
    hard_tolerance: int
    soft_weight: int

    @property
    def comfort_min(self) -> int:
        return self.target_size - self.comfort_tolerance

    @property
    def comfort_max(self) -> int:
        return self.target_size + self.comfort_tolerance

    @property
    def hard_min(self) -> int:
        return self.target_size - self.hard_tolerance

    @property
    def hard_max(self) -> int:
        return self.target_size + self.hard_tolerance


@dataclass(frozen=True)
class ClassConfig:
    class_id: str
    label: str
    size_min: int
    size_max: int
    music_allowed: list[str] = field(default_factory=list)
    languages_allowed: list[str] = field(default_factory=list)
    size_policy: ClassSizePolicy | None = None


def class_config_size_policy(config: object) -> ClassSizePolicy | None:
    return getattr(config, "size_policy", None)


@dataclass(frozen=True)
class OptimizationSettings:
    enforce_music_profile: bool = False
    enforce_language_profile: bool = False

    weight_music_profile: int = 0
    weight_language_profile: int = 0
    weight_mixed_language_class: int = 10000
    weight_language_minority_student: int = 1500
    weight_mixed_music_class: int = 8000
    weight_music_minority_student: int = 1200
    weight_music_focus_shortfall: int = 500
    weight_friend1: int = 2500
    weight_friend2: int = 900
    weight_mutual_friend: int = 10000
    weight_no_friend: int = 12000
    weight_support_distribution: int = 1200
    weight_gender_balance: int = 300
    weight_primary_school: int = 200
    weight_primary_class: int = 150
    weight_nationality: int = 0
    weight_religion: int = 0
    weight_keep_existing: int = 0

    solver_time_limit_seconds: int = 30
    max_primary_school_per_class: int = 10
    max_primary_school_class_per_class: int = 6
    max_support_per_class: int = 4
    gender_target_min: int = 12
    gender_target_max: int = 18
    gender_target_min_class_size: int = 24


@dataclass(frozen=True)
class ManualRule:
    type: RuleType
    student_a: str
    student_b: str | None = None
    class_id: str | None = None
    class_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ImportResult:
    students: list[Student]
    messages: list[ValidationMessage]
    sheet_names: list[str]
    detected_classes: list[str]
    workbook_bytes: bytes | None = None
    source_filename: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    messages: list[ValidationMessage]

    @property
    def has_errors(self) -> bool:
        return any(message.severity == "FEHLER" for message in self.messages)

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [message for message in self.messages if message.severity == "WARNUNG"]

    @property
    def errors(self) -> list[ValidationMessage]:
        return [message for message in self.messages if message.severity == "FEHLER"]


@dataclass(frozen=True)
class ClassReport:
    class_id: str
    size: int
    gender_counts: dict[str, int]
    language_counts: dict[str, int]
    music_counts: dict[str, int]
    is_language_mixed: bool
    language_minority_count: int
    is_music_mixed: bool
    music_minority_count: int
    music_focus_shortfall: int
    support_count: int
    school_counts: dict[str, int]
    primary_class_counts: dict[str, int]
    religion_counts: dict[str, int]
    nationality_counts: dict[str, int]


@dataclass(frozen=True)
class ScoreReport:
    total_score: int
    hard_violations: list[str]

    friend1_total: int
    friend1_fulfilled: int
    friend2_total: int
    friend2_fulfilled: int
    mutual_friend_total: int
    mutual_friend_fulfilled: int
    mixed_language_class_count: int
    mixed_music_class_count: int
    language_minority_student_count: int
    music_minority_student_count: int
    music_focus_shortfall_count: int
    isolated_friend_request_count: int

    class_reports: list[ClassReport]
    category_scores: dict[str, int] = field(default_factory=dict)
    friend_profile_conflicts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unmet_friend_requests: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SolverPhaseReport:
    name: str
    status: SolverStatus
    objective_value: int | None = None
    best_objective_bound: int | None = None
    relative_gap: float | None = None
    mixed_language_class_count: int | None = None
    mixed_music_class_count: int | None = None
    language_minority_student_count: int | None = None
    music_minority_student_count: int | None = None
    isolated_friend_request_count: int | None = None
    friend1_fulfilled: int | None = None
    friend1_total: int | None = None
    friend2_fulfilled: int | None = None
    friend2_total: int | None = None
    mutual_friend_fulfilled: int | None = None
    mutual_friend_total: int | None = None


@dataclass(frozen=True)
class ProfileSlackReport:
    variant: str
    language_mixed_limit: int
    music_mixed_limit: int
    status: SolverStatus
    objective_value: int | None = None
    best_objective_bound: int | None = None
    relative_gap: float | None = None
    mixed_language_class_count: int | None = None
    mixed_music_class_count: int | None = None
    language_minority_student_count: int | None = None
    music_minority_student_count: int | None = None
    isolated_friend_request_count: int | None = None
    friend1_fulfilled: int | None = None
    friend1_total: int | None = None
    friend2_fulfilled: int | None = None
    friend2_total: int | None = None
    mutual_friend_fulfilled: int | None = None
    mutual_friend_total: int | None = None
    approvable: bool | None = None
    social_limit_met: bool | None = None
    gap_reliable: bool | None = None
    profile_slack_needed: bool = False
    review_candidate: bool | None = None
    recommendation_role: str | None = None
    near_miss: bool = False
    candidate_for_target_test: bool = False
    optimization_attempted: bool = False
    solution_source: str | None = None
    displayed_source: str | None = None
    displayed_gap: float | None = None
    target_test_status: SolverStatus | None = None
    refinement_attempted: bool = False
    refinement_status: SolverStatus | None = None
    dominance_source: str | None = None
    assignments: dict[str, str] | None = None


@dataclass(frozen=True)
class SolverResult:
    status: SolverStatus
    assignments: dict[str, str]
    score_report: ScoreReport | None = None
    objective_value: int | None = None
    best_objective_bound: int | None = None
    relative_gap: float | None = None
    profile_status: SolverStatus | None = None
    profile_objective_value: int | None = None
    profile_best_objective_bound: int | None = None
    profile_relative_gap: float | None = None
    profile_baseline_report: ScoreReport | None = None
    phase_reports: list[SolverPhaseReport] = field(default_factory=list)
    last_accepted_phase: str | None = None
    last_accepted_phase_status: SolverStatus | None = None
    last_accepted_phase_gap: float | None = None
    failed_phase: str | None = None
    failed_phase_status: SolverStatus | None = None
    skipped_phase: str | None = None
    skipped_phase_status: SolverStatus | None = None
    skipped_phase_reason: str | None = None
    displayed_solution_source: str | None = None
    displayed_solution_gap: float | None = None
    displayed_solution_gap_source: str | None = None
    approval_test_status: SolverStatus | None = None
    approval_test_limit_without_wishfriend: int | None = None
    approval_test_metric_value: int | None = None
    found_without_wishfriend: int | None = None
    approval_threshold_without_wishfriend: int | None = None
    approval_possible_but_unproven: bool = False
    profile_slack_reports: list[ProfileSlackReport] = field(default_factory=list)
    profile_refinement_reports: list[ProfileSlackReport] = field(default_factory=list)
    slack_candidates: list[dict[str, object]] = field(default_factory=list)
    profile_min_fl_mixed_classes: int | None = None
    profile_min_music_mixed_classes: int | None = None
    profile_status_fl: SolverStatus | None = None
    profile_status_music: SolverStatus | None = None
    profile_gap_fl: float | None = None
    profile_gap_music: float | None = None
    message: str | None = None

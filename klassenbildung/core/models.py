from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


Severity = Literal["INFO", "WARNUNG", "FEHLER"]
RuleType = Literal["FIX_CLASS", "SEPARATE", "TOGETHER"]
SolverStatus = Literal[
    "OPTIMAL",
    "FEASIBLE",
    "INFEASIBLE",
    "UNKNOWN",
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


@dataclass(frozen=True)
class ClassConfig:
    class_id: str
    label: str
    size_min: int
    size_max: int
    music_allowed: list[str] = field(default_factory=list)
    languages_allowed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OptimizationSettings:
    enforce_music_profile: bool = True
    enforce_language_profile: bool = True

    weight_music_profile: int = 800
    weight_language_profile: int = 800
    weight_friend1: int = 1000
    weight_friend2: int = 300
    weight_support_distribution: int = 250
    weight_gender_balance: int = 80
    weight_primary_school: int = 50
    weight_primary_class: int = 40
    weight_nationality: int = 10
    weight_religion: int = 5
    weight_keep_existing: int = 0

    solver_time_limit_seconds: int = 30


@dataclass(frozen=True)
class ManualRule:
    type: RuleType
    student_a: str
    student_b: str | None = None
    class_id: str | None = None


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
    support_count: int
    school_counts: dict[str, int]
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

    class_reports: list[ClassReport]
    warnings: list[str] = field(default_factory=list)
    unmet_friend_requests: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SolverResult:
    status: SolverStatus
    assignments: dict[str, str]
    score_report: ScoreReport | None = None
    objective_value: int | None = None
    message: str | None = None

from __future__ import annotations

from collections import Counter

from klassenbildung.core.models import ClassConfig, Student
from klassenbildung.core.normalization import normalize_class_id
from klassenbildung.optimization.scoring import resolve_student_ref


CLASS_TYPE_PREFIX = "Klassenart: "


def assignment_overview_records(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
) -> list[dict[str, str]]:
    headers = assignment_overview_headers(students, assignments, class_configs)
    config_by_id = _class_config_lookup(class_configs)
    students_by_class: dict[str, list[Student]] = {}
    for student in students:
        class_id = assignments.get(student.internal_id, "")
        students_by_class.setdefault(class_id, []).append(student)

    values_by_class = {}
    for class_id in headers:
        config = config_by_id.get(class_id) or config_by_id.get(normalize_class_id(class_id) or "")
        class_students = sorted(
            students_by_class.get(class_id, []),
            key=lambda student: (student.sort_name, student.row_number),
        )
        values_by_class[class_id] = [
            CLASS_TYPE_PREFIX + class_type_text(config, class_students),
            *(student.full_name or student.display_label for student in class_students),
        ]

    max_row_count = max((len(values) for values in values_by_class.values()), default=0)
    return [
        {
            class_id: values_by_class[class_id][row_index]
            if row_index < len(values_by_class[class_id])
            else ""
            for class_id in headers
        }
        for row_index in range(max_row_count)
    ]


def assignment_overview_headers(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
) -> list[str]:
    configured_ids = [config.class_id for config in class_configs]
    assigned_ids = {assignments.get(student.internal_id, "") for student in students}
    extra_ids = sorted(class_id for class_id in assigned_ids if class_id and class_id not in configured_ids)
    return [*configured_ids, *extra_ids]


def assignment_board_columns(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    *,
    profile_reference_assignments: dict[str, str] | None = None,
    verified_profile_conflict_student_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    headers = assignment_overview_headers(students, assignments, class_configs)
    config_by_id = _class_config_lookup(class_configs)
    label_by_id = student_drag_labels(students)
    language_profiles = _language_profiles_by_class(
        students,
        profile_reference_assignments or assignments,
        class_configs,
    )
    verified_conflict_ids = verified_profile_conflict_student_ids or set()
    students_by_class: dict[str, list[Student]] = {class_id: [] for class_id in headers}
    for student in students:
        class_id = assignments.get(student.internal_id, "")
        if class_id in students_by_class:
            students_by_class[class_id].append(student)

    columns = []
    for class_id in headers:
        config = config_by_id.get(class_id) or config_by_id.get(normalize_class_id(class_id) or "")
        languages_allowed, language_profile_source = language_profiles.get(class_id, ([], ""))
        class_students = sorted(
            students_by_class.get(class_id, []),
            key=lambda item: (item.sort_name, item.row_number),
        )
        columns.append(
            {
                "class_id": class_id,
                "class_type": class_type_text(
                    config,
                    class_students,
                ),
                "languages_allowed": languages_allowed,
                "language_profile_source": language_profile_source,
                "music_allowed": list(config.music_allowed) if config else [],
                "students": [
                    _assignment_board_student(
                        student,
                        students,
                        label_by_id[student.internal_id],
                        profile_conflict_verified=student.internal_id in verified_conflict_ids,
                    )
                    for student in class_students
                ],
            }
        )
    return columns


def assignment_profile_conflicts(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
    *,
    reference_assignments: dict[str, str] | None = None,
    student_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    """Return visible profile conflicts for manually placed students.

    Explicit class profiles take precedence. If no language profiles were configured,
    a class that was purely F or purely L in the calculated reference solution keeps
    that language as its visible manual-editing profile.
    """
    profiles = _language_profiles_by_class(
        students,
        reference_assignments or assignments,
        class_configs,
    )
    config_by_id = _class_config_lookup(class_configs)
    conflicts: list[dict[str, str]] = []
    for student in students:
        if student_ids is not None and student.internal_id not in student_ids:
            continue
        class_id = assignments.get(student.internal_id, "")
        config = config_by_id.get(class_id) or config_by_id.get(normalize_class_id(class_id) or "")
        languages_allowed, language_source = profiles.get(class_id, ([], ""))
        if languages_allowed and student.second_language not in languages_allowed:
            allowed = "/".join(languages_allowed)
            source_text = (
                f"erlaubt: {allowed}"
                if language_source == "configured"
                else f"bisheriges Sprachprofil: {allowed}"
            )
            conflicts.append(
                {
                    "student_id": student.internal_id,
                    "class_id": class_id,
                    "kind": "Sprache",
                    "message": (
                        f"{student.display_label}: Sprache {student.second_language or 'leer'} "
                        f"passt nicht zu {class_id} ({source_text})."
                    ),
                }
            )
        music_allowed = list(config.music_allowed) if config else []
        if music_allowed and student.music_profile not in music_allowed:
            allowed = "/".join(music_allowed)
            conflicts.append(
                {
                    "student_id": student.internal_id,
                    "class_id": class_id,
                    "kind": "Musikprofil",
                    "message": (
                        f"{student.display_label}: Musikprofil {student.music_profile or 'leer'} "
                        f"passt nicht zu {class_id} (erlaubt: {allowed})."
                    ),
                }
            )
    return conflicts


def _assignment_board_student(
    student: Student,
    students: list[Student],
    label: str,
    *,
    profile_conflict_verified: bool = False,
) -> dict[str, object]:
    return {
        "id": student.internal_id,
        "label": label,
        "has_note": student.has_manual_note,
        "note": student.effective_note_text or "",
        "second_language": student.second_language or "",
        "music_profile": student.music_profile or "",
        "profile_conflict_verified": profile_conflict_verified,
        "details": _student_detail_fields(student),
        "friend_wishes": _student_friend_wishes(student, students),
    }


def _student_detail_fields(student: Student) -> list[dict[str, str]]:
    birthdate = student.birthdate.strftime("%d.%m.%Y") if student.birthdate else ""
    values = (
        ("Schülernummer", student.nr),
        ("Name", student.full_name),
        ("Grundschule", student.school),
        ("Grundschulklasse", student.primary_class),
        ("Geschlecht", student.gender),
        ("Fremdsprache", student.second_language),
        ("Musikprofil", student.music_profile),
        ("Eignung", student.eligibility),
        ("Geburtsdatum", birthdate),
        ("Staatsangehörigkeit", student.nationality),
        ("Religion", student.religion),
        ("R-/Unterstützungsmarkierung", "Ja" if student.is_support else "Nein"),
        ("Bisherige Zielklasse", student.original_class),
    )
    return [
        {"label": field_label, "value": str(value)}
        for field_label, value in values
        if value not in (None, "")
    ]


def _student_friend_wishes(student: Student, students: list[Student]) -> list[dict[str, object]]:
    wishes = []
    for priority, reference in ((1, student.friend1), (2, student.friend2)):
        if not reference:
            continue
        friend = resolve_student_ref(students, reference)
        wishes.append(
            {
                "priority": priority,
                "reference": reference,
                "friend_id": friend.internal_id if friend else "",
                "label": (
                    friend.display_label
                    if friend
                    else f"{reference} (nicht eindeutig gefunden)"
                ),
            }
        )
    return wishes


def _language_profiles_by_class(
    students: list[Student],
    assignments: dict[str, str],
    class_configs: list[ClassConfig],
) -> dict[str, tuple[list[str], str]]:
    config_by_id = _class_config_lookup(class_configs)
    class_ids = assignment_overview_headers(students, assignments, class_configs)
    languages_by_class: dict[str, set[str]] = {class_id: set() for class_id in class_ids}
    for student in students:
        class_id = assignments.get(student.internal_id, "")
        if class_id in languages_by_class and student.second_language in {"F", "L"}:
            languages_by_class[class_id].add(student.second_language)

    profiles: dict[str, tuple[list[str], str]] = {}
    for class_id in class_ids:
        config = config_by_id.get(class_id) or config_by_id.get(normalize_class_id(class_id) or "")
        if config and config.languages_allowed:
            profiles[class_id] = (list(config.languages_allowed), "configured")
            continue
        inferred = sorted(languages_by_class.get(class_id, set()))
        profiles[class_id] = (
            inferred if len(inferred) == 1 else [],
            "inferred" if len(inferred) == 1 else "",
        )
    return profiles


def assignments_from_board_value(
    value: object,
    fallback_assignments: dict[str, str],
) -> dict[str, str]:
    if not isinstance(value, dict):
        return dict(fallback_assignments)
    columns = value.get("columns")
    if not isinstance(columns, list):
        return dict(fallback_assignments)
    return assignments_from_board_columns(columns, fallback_assignments)


def assignments_from_board_columns(
    columns: list[dict[str, object]],
    fallback_assignments: dict[str, str],
) -> dict[str, str]:
    assignments = dict(fallback_assignments)
    allowed_student_ids = set(fallback_assignments)
    seen_students: set[str] = set()
    for column in columns:
        class_id = str(column.get("class_id") or "")
        students = column.get("students")
        if not isinstance(students, list):
            continue
        for student_item in students:
            student_id = _student_id_from_board_item(student_item)
            if student_id in allowed_student_ids and student_id not in seen_students:
                assignments[student_id] = class_id
                seen_students.add(student_id)
    return assignments


def _student_id_from_board_item(student_item: object) -> str:
    if isinstance(student_item, dict):
        return str(student_item.get("id") or "")
    return str(student_item or "")


def student_drag_labels(students: list[Student]) -> dict[str, str]:
    base_labels = {
        student.internal_id: student.full_name or student.display_label or student.internal_id
        for student in students
    }
    duplicate_counts = Counter(base_labels.values())
    labels = {}
    used_labels: set[str] = set()
    for student in students:
        label = base_labels[student.internal_id]
        if duplicate_counts[label] > 1:
            suffix = f"Nr {student.nr}" if student.nr else f"Zeile {student.row_number}"
            label = f"{label} ({suffix})"
        while label in used_labels:
            label = f"{label} [{student.internal_id}]"
        labels[student.internal_id] = label
        used_labels.add(label)
    return labels


def class_type_text(config: ClassConfig | None, students: list[Student] | None = None) -> str:
    if config is not None:
        label = (config.label or "").strip()
        class_id = (config.class_id or "").strip()
        if label and label != class_id:
            prefix = f"{class_id} "
            if class_id and label.startswith(prefix):
                return label[len(prefix):].strip(" -:") or label
            return label

    actual_type = _actual_class_type_text(students or [])
    if actual_type:
        return actual_type

    if config is None:
        return "unbekannt"

    configured_type = _joined_class_type(config.music_allowed, config.languages_allowed)
    if configured_type:
        return configured_type
    return "Regelklasse"


def _class_config_lookup(class_configs: list[ClassConfig]) -> dict[str, ClassConfig]:
    lookup = {}
    for config in class_configs:
        lookup[config.class_id] = config
        normalized = normalize_class_id(config.class_id)
        if normalized:
            lookup[normalized] = config
    return lookup


def _actual_class_type_text(students: list[Student]) -> str:
    music_values = _ordered_values((student.music_profile or "").strip() for student in students)
    language_values = _ordered_values((student.second_language or "").strip() for student in students)
    return _joined_class_type(music_values, language_values)


def _joined_class_type(music_values: list[str], language_values: list[str]) -> str:
    parts = []
    if music_values:
        parts.append("/".join(music_values))
    if language_values:
        parts.append("/".join(language_values))
    return " + ".join(parts)


def _ordered_values(values) -> list[str]:
    clean_values = {value for value in values if value}
    order = {"B": 0, "S": 1, "G": 2, "Reg": 3, "F": 10, "L": 11}
    return sorted(clean_values, key=lambda value: (order.get(value, 100), value))

from __future__ import annotations

BASIS_SHEET_NAME = "Basis"
HEADER_SCAN_ROWS = 10

COLUMN_BY_INDEX = {
    1: "zielklasse",
    2: "nr",
    3: "school",
    4: "last_name",
    5: "first_name",
    6: "eligibility",
    7: "gender",
    8: "birthdate",
    9: "nationality",
    10: "religion",
    11: "second_language",
    12: "music_profile",
    13: "regular_flag",
    14: "wind_flag",
    15: "strings_flag",
    16: "choir_flag",
    17: "primary_class",
    18: "friend1",
    19: "friend2",
    20: "comment",
}

EXPORT_COLUMN_COUNT = 20

ALLOWED_GENDERS = {"m", "w"}
ALLOWED_LANGUAGES = {"F", "L"}
ALLOWED_MUSIC_PROFILES = {"Reg", "B", "S", "G"}
ALLOWED_ELIGIBILITY = {"GYM", "R"}

MUSIC_FLAG_COLUMNS = {
    "regular_flag": "Reg",
    "wind_flag": "B",
    "strings_flag": "S",
    "choir_flag": "G",
}

DEFAULT_WEIGHTS = {
    "weight_music_profile": 0,
    "weight_language_profile": 0,
    "weight_mixed_language_class": 10000,
    "weight_language_minority_student": 1500,
    "weight_mixed_music_class": 8000,
    "weight_music_minority_student": 1200,
    "weight_music_focus_shortfall": 500,
    "weight_friend1": 2500,
    "weight_friend2": 900,
    "weight_mutual_friend": 10000,
    "weight_no_friend": 12000,
    "weight_support_distribution": 1200,
    "weight_gender_balance": 300,
    "weight_primary_school": 200,
    "weight_primary_class": 150,
    "weight_nationality": 0,
    "weight_religion": 0,
    "weight_keep_existing": 0,
}

DEFAULT_DISTRIBUTION_LIMITS = {
    "max_primary_school_per_class": 10,
    "max_primary_school_class_per_class": 6,
    "max_support_per_class": 4,
    "gender_target_min": 12,
    "gender_target_max": 18,
    "gender_target_min_class_size": 24,
}

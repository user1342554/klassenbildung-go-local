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
    "weight_music_profile": 800,
    "weight_language_profile": 800,
    "weight_friend1": 1000,
    "weight_friend2": 300,
    "weight_support_distribution": 250,
    "weight_gender_balance": 80,
    "weight_primary_school": 50,
    "weight_primary_class": 40,
    "weight_nationality": 10,
    "weight_religion": 5,
    "weight_keep_existing": 0,
}

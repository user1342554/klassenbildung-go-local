from __future__ import annotations

from types import SimpleNamespace

from klassenbildung.core.settings import coerce_settings, settings_from_mapping


def test_settings_from_old_mapping_adds_new_profile_weights() -> None:
    settings = settings_from_mapping(
        {
            "enforce_music_profile": False,
            "enforce_language_profile": False,
            "weight_friend1": 123,
        }
    )

    assert settings.weight_friend1 == 123
    assert settings.weight_music_profile == 800
    assert settings.weight_language_profile == 800


def test_coerce_old_session_object_adds_missing_fields() -> None:
    old_settings = SimpleNamespace(
        enforce_music_profile=False,
        enforce_language_profile=True,
        weight_friend1=111,
        weight_friend2=222,
        weight_support_distribution=333,
        weight_gender_balance=44,
        weight_primary_school=55,
        weight_primary_class=66,
        weight_nationality=7,
        weight_religion=8,
        weight_keep_existing=9,
        solver_time_limit_seconds=60,
    )

    settings = coerce_settings(old_settings)

    assert settings.enforce_music_profile is False
    assert settings.weight_friend1 == 111
    assert settings.weight_music_profile == 800
    assert settings.weight_language_profile == 800


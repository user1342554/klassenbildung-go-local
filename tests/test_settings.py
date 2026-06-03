from __future__ import annotations

from types import SimpleNamespace

from klassenbildung.core.settings import coerce_settings, generate_class_configs, settings_from_mapping


def test_settings_from_old_mapping_adds_new_profile_weights() -> None:
    settings = settings_from_mapping(
        {
            "enforce_music_profile": False,
            "enforce_language_profile": False,
            "weight_friend1": 123,
        }
    )

    assert settings.enforce_music_profile is False
    assert settings.enforce_language_profile is False
    assert settings.weight_friend1 == 123
    assert settings.weight_music_profile == 0
    assert settings.weight_language_profile == 0
    assert settings.weight_mixed_language_class == 10000
    assert settings.weight_language_minority_student == 1500
    assert settings.weight_mixed_music_class == 8000
    assert settings.weight_music_minority_student == 1200
    assert settings.weight_no_friend == 12000
    assert settings.weight_mutual_friend == 10000


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
    assert settings.enforce_language_profile is True
    assert settings.weight_friend1 == 111
    assert settings.weight_music_profile == 0
    assert settings.weight_language_profile == 0
    assert settings.weight_mixed_language_class == 10000
    assert settings.weight_language_minority_student == 1500
    assert settings.weight_mixed_music_class == 8000
    assert settings.weight_music_minority_student == 1200
    assert settings.weight_no_friend == 12000
    assert settings.weight_mutual_friend == 10000


def test_generate_class_configs_uses_target_size_with_hard_tolerance() -> None:
    configs = generate_class_configs(
        total_students=210,
        class_count=7,
        target_size=30,
        comfort_tolerance=2,
        hard_tolerance=5,
    )

    assert len(configs) == 7
    assert {config.size_min for config in configs} == {25}
    assert {config.size_max for config in configs} == {35}
    assert {config.size_policy.comfort_min for config in configs if config.size_policy} == {28}
    assert {config.size_policy.comfort_max for config in configs if config.size_policy} == {32}


def test_generate_class_configs_keeps_total_capacity_possible() -> None:
    configs = generate_class_configs(total_students=40, class_count=2, target_size=10, hard_tolerance=2)

    assert sum(config.size_min for config in configs) <= 40
    assert sum(config.size_max for config in configs) >= 40
    assert {config.size_max for config in configs} == {20}

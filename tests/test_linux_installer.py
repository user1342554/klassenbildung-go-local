from __future__ import annotations

import os
import stat
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_linux_entrypoints_are_executable() -> None:
    for relative in (
        "Install-Klassenbildung-Linux.sh",
        "Klassenbildung-Linux-Installer.desktop",
        "build_linux/launcher.sh",
        "build_linux/uninstall.sh",
        "build_linux/build_installer.sh",
    ):
        mode = (PROJECT_ROOT / relative).stat().st_mode
        assert mode & stat.S_IXUSR, f"{relative} must be executable"


def test_installer_provisions_isolated_python_and_user_launchers() -> None:
    installer = (PROJECT_ROOT / "Install-Klassenbildung-Linux.sh").read_text(encoding="utf-8")

    assert 'PYTHON_VERSION="3.12"' in installer
    assert "UV_UNMANAGED_INSTALL" in installer
    assert 'UV_PYTHON_INSTALL_DIR="$APP_ROOT/python"' in installer
    assert '"$UV_BIN" venv' in installer
    assert '"$UV_BIN" pip check' in installer
    assert 'settings.default.json' in installer
    assert '$SOURCE_DIR/config/settings.json' not in installer
    assert '$SOURCE_DIR/config/class_profiles.json' not in installer
    assert 'update-desktop-database' in installer
    assert 'stop_running_app' in installer


def test_installed_launcher_keeps_code_and_user_data_separate() -> None:
    launcher = (PROJECT_ROOT / "build_linux/launcher.sh").read_text(encoding="utf-8")

    assert 'APP_DIR="$APP_ROOT/current"' in launcher
    assert 'XDG_CONFIG_HOME' in launcher
    assert 'XDG_STATE_HOME' in launcher
    assert 'cd -- "$DATA_DIR"' in launcher
    assert 'PYTHONPATH="$APP_DIR' in launcher
    assert '/_stcore/health' in launcher
    assert 'KLASSENBILDUNG_NO_BROWSER' in launcher
    assert 'process_is_our_server' in launcher
    assert 'PID_FILE="$STATE_DIR/server.pid"' in launcher


def test_uninstaller_stops_only_the_installed_app_and_preserves_data_by_default() -> None:
    uninstaller = (PROJECT_ROOT / "build_linux/uninstall.sh").read_text(encoding="utf-8")

    assert 'process_is_installed_app' in uninstaller
    assert 'kill "$pid"' in uninstaller
    assert 'REMOVE_DATA=0' in uninstaller
    assert 'if ((REMOVE_DATA))' in uninstaller


def test_desktop_installer_targets_the_script_beside_it() -> None:
    desktop = (PROJECT_ROOT / "Klassenbildung-Linux-Installer.desktop").read_text(
        encoding="utf-8"
    )

    assert "Terminal=true" in desktop
    assert "Install-Klassenbildung-Linux.sh" in desktop
    assert "%k" in desktop


def test_linux_icon_is_valid_svg_shape() -> None:
    icon = (PROJECT_ROOT / "assets/klassenbildung.svg").read_text(encoding="utf-8")

    assert icon.startswith('<?xml version="1.0"')
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in icon
    assert 'viewBox="0 0 512 512"' in icon


def test_no_installer_path_depends_on_the_developers_home() -> None:
    paths = (
        PROJECT_ROOT / "Install-Klassenbildung-Linux.sh",
        PROJECT_ROOT / "build_linux/launcher.sh",
        PROJECT_ROOT / "build_linux/uninstall.sh",
    )
    for path in paths:
        contents = path.read_text(encoding="utf-8")
        assert "/home/jonas" not in contents
        assert os.fspath(PROJECT_ROOT) not in contents

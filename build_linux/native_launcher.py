"""Startpunkt fuer die gebuendelte Linux-App.

Die Programmdateien liegen schreibgeschuetzt unter /usr/lib. Einstellungen,
Beispieldaten und Logs bleiben im Benutzerkonto.
"""

from __future__ import annotations

import atexit
import importlib
import os
import pkgutil
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_PORT = 6767


def _xdg_directory(variable: str, fallback: Path) -> Path:
    configured = os.environ.get(variable)
    return Path(configured).expanduser() if configured else fallback


APP_SUPPORT = _xdg_directory("XDG_CONFIG_HOME", Path.home() / ".config") / "klassenbildung"
STATE_DIR = _xdg_directory("XDG_STATE_HOME", Path.home() / ".local" / "state") / "klassenbildung"
PID_FILE = STATE_DIR / "server.pid"
URL_FILE = STATE_DIR / "server.url"


def _bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _prepare_workdir(bundle: Path) -> Path:
    (APP_SUPPORT / "config").mkdir(parents=True, exist_ok=True)
    (APP_SUPPORT / ".streamlit").mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    for name in ("settings.default.json", "class_profiles.default.json"):
        source = bundle / "config" / name
        if source.exists():
            shutil.copyfile(source, APP_SUPPORT / "config" / name)

    streamlit_config = bundle / ".streamlit" / "config.toml"
    if streamlit_config.exists():
        shutil.copyfile(streamlit_config, APP_SUPPORT / ".streamlit" / "config.toml")

    sample_source = bundle / "DummyDaten.xlsx"
    sample_target = APP_SUPPORT / "DummyDaten.xlsx"
    if sample_source.exists() and not sample_target.exists():
        shutil.copyfile(sample_source, sample_target)

    return APP_SUPPORT


def _healthcheck(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/_stcore/health", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def _process_matches(pid: int) -> bool:
    try:
        return (Path(f"/proc/{pid}/exe").resolve() == Path(sys.executable).resolve())
    except OSError:
        return False


def _open_existing_server() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        url = URL_FILE.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return False
    if _process_matches(pid) and _healthcheck(url):
        if os.environ.get("KLASSENBILDUNG_NO_BROWSER") != "1":
            webbrowser.open(url)
        return True
    return False


def _port_is_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_and_open(url: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if _healthcheck(url):
            webbrowser.open(url)
            return
        time.sleep(0.5)


def _clear_own_state() -> None:
    try:
        recorded_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if recorded_pid == os.getpid():
        PID_FILE.unlink(missing_ok=True)
        URL_FILE.unlink(missing_ok=True)


def _selftest(bundle: Path) -> int:
    import klassenbildung

    failures: list[str] = []
    for module in pkgutil.walk_packages(klassenbildung.__path__, "klassenbildung."):
        try:
            importlib.import_module(module.name)
        except Exception as error:  # pragma: no cover - Diagnose im Bundle
            failures.append(f"{module.name}: {error}")

    for relative in (
        "app.py",
        "DummyDaten.xlsx",
        "config/settings.default.json",
        "config/class_profiles.default.json",
        ".streamlit/config.toml",
        "klassenbildung/components/assignment_board/index.html",
    ):
        if not (bundle / relative).exists():
            failures.append(f"fehlende Datei: {relative}")

    try:
        compile((bundle / "app.py").read_text(encoding="utf-8"), "app.py", "exec")
    except Exception as error:  # pragma: no cover - Diagnose im Bundle
        failures.append(f"app.py: {error}")

    for line in failures:
        print("FEHLER", line)
    print("SELFTEST", "FAILED" if failures else "OK")
    return 1 if failures else 0


def main() -> None:
    bundle = _bundle_dir()
    if os.environ.get("KLASSENBILDUNG_SELFTEST"):
        raise SystemExit(_selftest(bundle))

    _prepare_workdir(bundle)
    if _open_existing_server():
        return

    requested_port = int(os.environ.get("KLASSENBILDUNG_PORT", DEFAULT_PORT))
    port = _free_port() if _port_is_open(requested_port) else requested_port
    url = f"http://localhost:{port}"

    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    URL_FILE.write_text(f"{url}\n", encoding="utf-8")
    atexit.register(_clear_own_state)

    if os.environ.get("KLASSENBILDUNG_NO_BROWSER") != "1":
        threading.Thread(target=_wait_and_open, args=(url,), daemon=True).start()

    os.chdir(APP_SUPPORT)
    flag_options = {
        "global.developmentMode": False,
        "server.port": port,
        "server.address": "localhost",
        "server.headless": True,
        "browser.gatherUsageStats": False,
    }

    from streamlit.web import bootstrap

    bootstrap.load_config_options(flag_options)
    bootstrap.run(str(bundle / "app.py"), False, [], flag_options)


if __name__ == "__main__":
    main()

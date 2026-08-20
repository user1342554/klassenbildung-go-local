"""Einstiegspunkt fuer das gebuendelte macOS-App-Paket (.app).

Startet den Streamlit-Server im Prozess und oeffnet den Browser.
Arbeitsverzeichnis ist ein beschreibbarer Ordner im Benutzerprofil, weil das
App-Paket selbst schreibgeschuetzt sein kann und die App relative Pfade
(config/…) zum Speichern von Einstellungen verwendet.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 6767
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Klassenbildung"


def _bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _prepare_workdir(bundle: Path) -> Path:
    """Beschreibbares Arbeitsverzeichnis anlegen und mit Vorgaben befuellen."""
    (APP_SUPPORT / "config").mkdir(parents=True, exist_ok=True)
    (APP_SUPPORT / ".streamlit").mkdir(parents=True, exist_ok=True)

    for name in ("settings.default.json", "class_profiles.default.json"):
        source = bundle / "config" / name
        target = APP_SUPPORT / "config" / name
        if source.exists():
            shutil.copyfile(source, target)  # Vorgaben immer aktualisieren

    sample_source = bundle / "DummyDaten.xlsx"
    sample_target = APP_SUPPORT / "DummyDaten.xlsx"
    if sample_source.exists() and not sample_target.exists():
        shutil.copyfile(sample_source, sample_target)

    streamlit_config = bundle / ".streamlit" / "config.toml"
    if streamlit_config.exists():
        shutil.copyfile(streamlit_config, APP_SUPPORT / ".streamlit" / "config.toml")

    return APP_SUPPORT


def _wait_and_open(url: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.5)


def _selftest(bundle: Path) -> int:
    """Prueft im gebuendelten Zustand, ob alle Module und Daten vorhanden sind."""
    import importlib
    import pkgutil

    import klassenbildung

    failures: list[str] = []
    for module in pkgutil.walk_packages(klassenbildung.__path__, "klassenbildung."):
        try:
            importlib.import_module(module.name)
        except Exception as error:  # pragma: no cover - Diagnose im Bundle
            failures.append(f"{module.name}: {error}")

    for relative in ("app.py", "DummyDaten.xlsx", "config/settings.default.json",
                     "config/class_profiles.default.json", ".streamlit/config.toml",
                     "klassenbildung/components/assignment_board/index.html"):
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
        sys.exit(_selftest(bundle))

    os.chdir(_prepare_workdir(bundle))

    # developmentMode muss explizit aus sein, sonst lehnt Streamlit server.port ab.
    flag_options = {
        "global.developmentMode": False,
        "server.port": PORT,
        "server.address": "localhost",
        "server.headless": True,
        "browser.gatherUsageStats": False,
    }

    threading.Thread(target=_wait_and_open, args=(f"http://localhost:{PORT}",), daemon=True).start()

    from streamlit.web import bootstrap

    bootstrap.load_config_options(flag_options)
    bootstrap.run(str(bundle / "app.py"), False, [], flag_options)


if __name__ == "__main__":
    main()

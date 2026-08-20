#!/usr/bin/env bash
# Installierter Klassenbildung-Starter. Der Installationsordner wird relativ
# zu diesem Skript bestimmt, damit keine absoluten Pfade eingebrannt werden.

set -Eeuo pipefail

APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_DIR="$APP_ROOT/current"
VENV_DIR="$APP_ROOT/venv"
DATA_DIR="${KLASSENBILDUNG_DATA_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/klassenbildung}"
STATE_DIR="${KLASSENBILDUNG_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/klassenbildung}"
PORT="${KLASSENBILDUNG_PORT:-6767}"
PYTHON="$VENV_DIR/bin/python"
PID_FILE="$STATE_DIR/server.pid"
URL_FILE="$STATE_DIR/server.url"

[[ -x "$PYTHON" && -f "$APP_DIR/app.py" ]] || {
  printf 'Klassenbildung ist unvollstaendig. Bitte den Installer erneut starten.\n' >&2
  exit 1
}

mkdir -p "$DATA_DIR/config" "$DATA_DIR/.streamlit" "$STATE_DIR"
install -m 0644 "$APP_DIR/config/settings.default.json" "$DATA_DIR/config/settings.default.json"
install -m 0644 "$APP_DIR/config/class_profiles.default.json" "$DATA_DIR/config/class_profiles.default.json"
install -m 0644 "$APP_DIR/.streamlit/config.toml" "$DATA_DIR/.streamlit/config.toml"

healthcheck() {
  "$PYTHON" - "$1" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=1.5) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
}

process_is_our_server() {
  "$PYTHON" - "$1" "$APP_DIR/app.py" <<'PY' >/dev/null 2>&1
import pathlib
import sys

pid, app_path = sys.argv[1:]
arguments = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
raise SystemExit(0 if app_path.encode() in arguments else 1)
PY
}

port_is_open() {
  "$PYTHON" - "$1" <<'PY' >/dev/null 2>&1
import socket
import sys

with socket.socket() as probe:
    probe.settimeout(0.5)
    raise SystemExit(0 if probe.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

find_free_port() {
  "$PYTHON" <<'PY'
import socket

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    print(probe.getsockname()[1])
PY
}

open_url() {
  local url="$1"
  [[ "${KLASSENBILDUNG_NO_BROWSER:-0}" != "1" ]] || return 0
  "$PYTHON" - "$url" <<'PY' >/dev/null 2>&1
import sys
import webbrowser

webbrowser.open(sys.argv[1])
PY
}

open_when_ready() {
  local url="$1"
  [[ "${KLASSENBILDUNG_NO_BROWSER:-0}" != "1" ]] || return 0
  "$PYTHON" - "$url" <<'PY' >/dev/null 2>&1 &
import sys
import time
import urllib.request
import webbrowser

url = sys.argv[1]
for _ in range(240):
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            if response.status == 200:
                webbrowser.open(url)
                break
    except Exception:
        time.sleep(0.5)
PY
}

if [[ -s "$PID_FILE" && -s "$URL_FILE" ]]; then
  RUNNING_PID="$(<"$PID_FILE")"
  RUNNING_URL="$(<"$URL_FILE")"
  if [[ "$RUNNING_PID" =~ ^[0-9]+$ ]] \
    && kill -0 "$RUNNING_PID" >/dev/null 2>&1 \
    && process_is_our_server "$RUNNING_PID" \
    && healthcheck "$RUNNING_URL/_stcore/health"; then
    open_url "$RUNNING_URL"
    exit 0
  fi
fi

URL="http://localhost:$PORT"

# Falls 6767 von einem anderen Programm belegt ist, trotzdem auf einem freien
# lokalen Port starten. Ein zweiter Klassenbildung-Start nutzt PID und URL oben.
if port_is_open "$PORT"; then
  PORT="$(find_free_port)"
  URL="http://localhost:$PORT"
fi

open_when_ready "$URL"

cd -- "$DATA_DIR"
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
printf '%s\n' "$$" >"$PID_FILE"
printf '%s\n' "$URL" >"$URL_FILE"
printf '\n[%s] Starte Klassenbildung auf %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$URL" >>"$STATE_DIR/streamlit.log"
exec "$PYTHON" -m streamlit run "$APP_DIR/app.py" \
  --server.address localhost \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false \
  >>"$STATE_DIR/streamlit.log" 2>&1

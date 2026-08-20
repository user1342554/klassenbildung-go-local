#!/usr/bin/env bash
# Entfernt die Benutzerinstallation. Persoenliche Einstellungen bleiben ohne
# --remove-data erhalten, damit eine spaetere Neuinstallation sie wieder nutzt.

set -Eeuo pipefail

APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${KLASSENBILDUNG_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
APPLICATIONS_DIR="${KLASSENBILDUNG_APPLICATIONS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/applications}"
DATA_DIR="${KLASSENBILDUNG_DATA_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/klassenbildung}"
STATE_DIR="${KLASSENBILDUNG_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/klassenbildung}"
REMOVE_DATA=0

if [[ "${1:-}" == "--remove-data" ]]; then
  REMOVE_DATA=1
elif (($#)); then
  printf 'Verwendung: %s [--remove-data]\n' "$0" >&2
  exit 2
fi

safe_user_path() {
  local path="$1"
  [[ "$path" == /* && "$path" != "/" && "$path" != "$HOME" && "$path" == */klassenbildung ]]
}

safe_user_path "$APP_ROOT" || {
  printf 'Unsicherer Installationspfad; Abbruch: %s\n' "$APP_ROOT" >&2
  exit 1
}

process_is_installed_app() {
  local pid="$1"
  local expected="$APP_ROOT/current/app.py"
  local argument=""
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  while IFS= read -r -d '' argument; do
    [[ "$argument" != "$expected" ]] || return 0
  done <"/proc/$pid/cmdline"
  return 1
}

process_is_alive() {
  local pid="$1"
  local process_stat=""
  local after_name=""
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  [[ -r "/proc/$pid/stat" ]] || return 1
  process_stat="$(<"/proc/$pid/stat")"
  after_name="${process_stat##*) }"
  [[ "${after_name%% *}" != "Z" ]]
}

pid_file="$STATE_DIR/server.pid"
if [[ -s "$pid_file" ]]; then
  pid="$(<"$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$pid" >/dev/null 2>&1 \
    && process_is_installed_app "$pid"; then
    kill "$pid"
    for _ in {1..50}; do
      process_is_alive "$pid" || break
      sleep 0.1
    done
    if process_is_alive "$pid"; then
      printf 'Die laufende App konnte nicht beendet werden. Bitte erneut versuchen.\n' >&2
      exit 1
    fi
  fi
fi

for link in "$BIN_DIR/klassenbildung" "$BIN_DIR/klassenbildung-uninstall"; do
  if [[ -L "$link" && "$(readlink "$link")" == "$APP_ROOT"/* ]]; then
    rm -f -- "$link"
  fi
done

rm -f -- "$APPLICATIONS_DIR/klassenbildung.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

for desktop_dir in "$HOME/Desktop" "$HOME/Schreibtisch"; do
  [[ ! -f "$desktop_dir/Klassenbildung.desktop" ]] || rm -f -- "$desktop_dir/Klassenbildung.desktop"
done
if command -v xdg-user-dir >/dev/null 2>&1; then
  desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  [[ -z "$desktop_dir" || ! -f "$desktop_dir/Klassenbildung.desktop" ]] || rm -f -- "$desktop_dir/Klassenbildung.desktop"
fi

rm -rf -- "$APP_ROOT"

if ((REMOVE_DATA)); then
  safe_user_path "$DATA_DIR" || {
    printf 'Unsicherer Datenpfad; Daten nicht entfernt: %s\n' "$DATA_DIR" >&2
    exit 1
  }
  safe_user_path "$STATE_DIR" || {
    printf 'Unsicherer Statuspfad; Daten nicht entfernt: %s\n' "$STATE_DIR" >&2
    exit 1
  }
  rm -rf -- "$DATA_DIR" "$STATE_DIR"
  printf 'Klassenbildung und persoenliche Daten wurden entfernt.\n'
else
  printf 'Klassenbildung wurde entfernt. Persoenliche Daten bleiben in %s erhalten.\n' "$DATA_DIR"
fi

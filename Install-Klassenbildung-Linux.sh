#!/usr/bin/env bash
# Doppelklickbarer Linux-Installer fuer Klassenbildung.
# Installiert App, Python-Laufzeit und Abhaengigkeiten nur fuer den aktuellen Benutzer.

set -Eeuo pipefail
umask 022

APP_ID="klassenbildung"
APP_NAME="Klassenbildung"
REPOSITORY_ARCHIVE="https://github.com/user1342554/klassenbildung-go-local/archive/refs/heads/main.tar.gz"
UV_VERSION="0.12.5"
PYTHON_VERSION="3.12"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_DIR="$SCRIPT_DIR"
TEMP_DIR=""
STAGED_RELEASE=""
LAUNCH_AFTER_INSTALL=1

APP_ROOT="${KLASSENBILDUNG_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID}"
BIN_DIR="${KLASSENBILDUNG_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
APPLICATIONS_DIR="${KLASSENBILDUNG_APPLICATIONS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/applications}"
DATA_DIR="${KLASSENBILDUNG_DATA_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID}"
STATE_DIR="${KLASSENBILDUNG_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/$APP_ID}"

green='\033[1;32m'
blue='\033[1;34m'
red='\033[1;31m'
reset='\033[0m'

info() {
  printf "${blue}==>${reset} %s\n" "$*"
}

success() {
  printf "${green}Fertig:${reset} %s\n" "$*"
}

die() {
  printf "${red}Fehler:${reset} %s\n" "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
  if [[ -n "$STAGED_RELEASE" && -d "$STAGED_RELEASE" ]]; then
    rm -rf -- "$STAGED_RELEASE"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Klassenbildung Linux-Installer

Verwendung:
  ./Install-Klassenbildung-Linux.sh [--no-launch] [--source ORDNER]

Optionen:
  --no-launch      App nach der Installation nicht starten
  --source ORDNER  App-Dateien aus einem bestimmten Ordner installieren
  -h, --help       Diese Hilfe anzeigen
EOF
}

while (($#)); do
  case "$1" in
    --no-launch)
      LAUNCH_AFTER_INSTALL=0
      shift
      ;;
    --source)
      (($# >= 2)) || die "Nach --source fehlt ein Ordner."
      SOURCE_DIR="$(cd -- "$2" && pwd -P)"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unbekannte Option: $1"
      ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die "Dieser Installer ist nur fuer Linux gedacht."
case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64) ;;
  *)
    die "Diese CPU-Architektur ($(uname -m)) wird von den benoetigten OR-Tools-Paketen nicht unterstuetzt. Unterstuetzt werden 64-Bit x86 und ARM."
    ;;
esac

run_admin() {
  if ((EUID == 0)); then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  elif command -v pkexec >/dev/null 2>&1; then
    pkexec "$@"
  else
    die "Zum Installieren eines Download-Werkzeugs werden sudo oder pkexec benoetigt."
  fi
}

install_download_prerequisites() {
  info "Installiere das benoetigte Download-Werkzeug ..."
  if command -v apt-get >/dev/null 2>&1; then
    run_admin apt-get update
    run_admin apt-get install -y curl ca-certificates tar gzip
  elif command -v dnf >/dev/null 2>&1; then
    run_admin dnf install -y curl ca-certificates tar gzip
  elif command -v yum >/dev/null 2>&1; then
    run_admin yum install -y curl ca-certificates tar gzip
  elif command -v zypper >/dev/null 2>&1; then
    run_admin zypper --non-interactive install curl ca-certificates tar gzip
  elif command -v pacman >/dev/null 2>&1; then
    run_admin pacman -S --needed --noconfirm curl ca-certificates tar gzip
  else
    die "Weder curl, wget noch Python ist vorhanden. Bitte curl installieren und den Installer erneut starten."
  fi
}

find_bootstrap_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

download() {
  local url="$1"
  local destination="$2"
  local bootstrap_python=""

  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --retry 3 --output "$destination" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --tries=3 --output-document="$destination" "$url"
  elif bootstrap_python="$(find_bootstrap_python)"; then
    "$bootstrap_python" - "$url" "$destination" <<'PY'
import pathlib
import sys
import urllib.request

url, destination = sys.argv[1:]
request = urllib.request.Request(url, headers={"User-Agent": "Klassenbildung-Installer"})
with urllib.request.urlopen(request, timeout=120) as response:
    pathlib.Path(destination).write_bytes(response.read())
PY
  else
    install_download_prerequisites
    download "$url" "$destination"
  fi
}

valid_source_tree() {
  local directory="$1"
  [[ -f "$directory/app.py" \
    && -f "$directory/DummyDaten.xlsx" \
    && -f "$directory/requirements.txt" \
    && -d "$directory/klassenbildung" \
    && -f "$directory/config/settings.default.json" \
    && -f "$directory/config/class_profiles.default.json" \
    && -f "$directory/build_linux/launcher.sh" \
    && -f "$directory/build_linux/uninstall.sh" ]]
}

acquire_source() {
  local archive extracted
  if valid_source_tree "$SOURCE_DIR"; then
    return 0
  fi

  TEMP_DIR="$(mktemp -d -t klassenbildung-installer.XXXXXX)"
  archive="$TEMP_DIR/source.tar.gz"
  info "Lade die aktuelle Klassenbildung-Version herunter ..."
  download "$REPOSITORY_ARCHIVE" "$archive"
  command -v tar >/dev/null 2>&1 || install_download_prerequisites
  tar -xzf "$archive" -C "$TEMP_DIR"
  extracted="$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'klassenbildung-go-local-*' -print -quit)"
  [[ -n "$extracted" ]] || die "Das heruntergeladene App-Archiv ist ungueltig."
  SOURCE_DIR="$extracted"
  valid_source_tree "$SOURCE_DIR" || die "Im App-Archiv fehlen erforderliche Dateien."
}

release_id() {
  local revision=""
  if command -v git >/dev/null 2>&1 && git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    revision="$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
  fi
  if [[ -n "$revision" ]]; then
    printf '%s\n' "$revision"
  else
    date -u +'%Y%m%dT%H%M%SZ'
  fi
}

copy_application() {
  local target="$1"
  mkdir -p "$target/config" "$target/.streamlit"
  install -m 0644 "$SOURCE_DIR/app.py" "$target/app.py"
  install -m 0644 "$SOURCE_DIR/DummyDaten.xlsx" "$target/DummyDaten.xlsx"
  install -m 0644 "$SOURCE_DIR/requirements.txt" "$target/requirements.txt"
  [[ ! -f "$SOURCE_DIR/pyproject.toml" ]] || install -m 0644 "$SOURCE_DIR/pyproject.toml" "$target/pyproject.toml"
  cp -R "$SOURCE_DIR/klassenbildung" "$target/klassenbildung"
  find "$target/klassenbildung" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$target/klassenbildung" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  install -m 0644 "$SOURCE_DIR/config/settings.default.json" "$target/config/settings.default.json"
  install -m 0644 "$SOURCE_DIR/config/class_profiles.default.json" "$target/config/class_profiles.default.json"
  install -m 0644 "$SOURCE_DIR/.streamlit/config.toml" "$target/.streamlit/config.toml"
  if [[ -d "$SOURCE_DIR/assets" ]]; then
    cp -R "$SOURCE_DIR/assets" "$target/assets"
  fi
  if [[ -d "$SOURCE_DIR/docs" ]]; then
    cp -R "$SOURCE_DIR/docs" "$target/docs"
  fi
}

desktop_exec_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\\\$}"
  value="${value//\`/\\\`}"
  printf '"%s"' "$value"
}

desktop_directory() {
  local directory=""
  if command -v xdg-user-dir >/dev/null 2>&1; then
    directory="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -n "$directory" && -d "$directory" ]]; then
    printf '%s\n' "$directory"
  elif [[ -d "$HOME/Desktop" ]]; then
    printf '%s\n' "$HOME/Desktop"
  elif [[ -d "$HOME/Schreibtisch" ]]; then
    printf '%s\n' "$HOME/Schreibtisch"
  fi
}

write_desktop_entry() {
  local desktop_file="$APPLICATIONS_DIR/$APP_ID.desktop"
  local launcher="$APP_ROOT/bin/$APP_ID"
  local icon="$APP_ROOT/current/assets/klassenbildung.svg"
  local user_desktop=""

  mkdir -p "$APPLICATIONS_DIR"
  {
    printf '%s\n' '[Desktop Entry]'
    printf '%s\n' 'Type=Application'
    printf '%s\n' 'Version=1.0'
    printf '%s\n' 'Name=Klassenbildung'
    printf '%s\n' 'Comment=Schuelerinnen und Schueler lokal auf Klassen verteilen'
    printf '%s\n' 'Comment[de]=Schuelerinnen und Schueler lokal auf Klassen verteilen'
    printf 'Exec=%s\n' "$(desktop_exec_quote "$launcher")"
    printf 'TryExec=%s\n' "$(desktop_exec_quote "$launcher")"
    printf 'Icon=%s\n' "$icon"
    printf '%s\n' 'Terminal=false'
    printf '%s\n' 'Categories=Education;'
    printf '%s\n' 'Keywords=Schule;Klassen;Schueler;Verteilung;'
    printf '%s\n' 'StartupNotify=true'
  } >"$desktop_file"
  chmod 0644 "$desktop_file"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
  fi

  user_desktop="$(desktop_directory)"
  if [[ -n "$user_desktop" ]]; then
    install -m 0755 "$desktop_file" "$user_desktop/$APP_NAME.desktop"
    if command -v gio >/dev/null 2>&1; then
      gio set "$user_desktop/$APP_NAME.desktop" metadata::trusted true >/dev/null 2>&1 || true
    fi
  fi
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

stop_running_app() {
  local pid_file="$STATE_DIR/server.pid"
  local pid=""
  [[ -s "$pid_file" ]] || return 0
  pid="$(<"$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] \
    && kill -0 "$pid" >/dev/null 2>&1 \
    && process_is_installed_app "$pid"; then
    info "Beende die laufende App fuer das Update ..."
    kill "$pid"
    for _ in {1..50}; do
      process_is_alive "$pid" || break
      sleep 0.1
    done
    if process_is_alive "$pid"; then
      die "Die laufende App konnte nicht beendet werden. Bitte das Browserfenster schliessen und erneut versuchen."
    fi
  fi
  rm -f -- "$STATE_DIR/server.pid" "$STATE_DIR/server.url"
}

acquire_source

info "Installiere $APP_NAME fuer den aktuellen Benutzer ..."
mkdir -p "$APP_ROOT/releases" "$APP_ROOT/bin" "$APP_ROOT/tools" "$BIN_DIR" "$DATA_DIR/config" "$DATA_DIR/.streamlit" "$STATE_DIR"

RELEASE_ID="$(release_id)"
FINAL_RELEASE="$APP_ROOT/releases/$RELEASE_ID"
if [[ -e "$FINAL_RELEASE" ]]; then
  FINAL_RELEASE="$APP_ROOT/releases/${RELEASE_ID}-$(date -u +'%Y%m%dT%H%M%SZ')"
fi
STAGED_RELEASE="$APP_ROOT/releases/.installing-$$"
mkdir -p "$STAGED_RELEASE"
copy_application "$STAGED_RELEASE"

UV_BIN="${KLASSENBILDUNG_UV_BIN:-$APP_ROOT/tools/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_INSTALLER="$STAGED_RELEASE/uv-installer.sh"
  info "Richte die portable Installationshilfe ein ..."
  download "https://astral.sh/uv/$UV_VERSION/install.sh" "$UV_INSTALLER"
  UV_UNMANAGED_INSTALL="$APP_ROOT/tools" sh "$UV_INSTALLER"
  rm -f -- "$UV_INSTALLER"
  UV_BIN="$APP_ROOT/tools/uv"
fi
[[ -x "$UV_BIN" ]] || die "Die portable Installationshilfe konnte nicht eingerichtet werden."

export UV_CACHE_DIR="$APP_ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$APP_ROOT/python"
VENV_DIR="$APP_ROOT/venv"

if [[ ! -x "$VENV_DIR/bin/python" ]] \
  || ! "$VENV_DIR/bin/python" -c "import sys; raise SystemExit(sys.version_info[:2] != (${PYTHON_VERSION/./, }))" >/dev/null 2>&1; then
  info "Installiere eine eigene Python-$PYTHON_VERSION-Laufzeit ..."
  "$UV_BIN" venv --clear --managed-python --python "$PYTHON_VERSION" "$VENV_DIR"
fi

info "Installiere und pruefe die App-Abhaengigkeiten ..."
"$UV_BIN" pip install --upgrade --python "$VENV_DIR/bin/python" --requirements "$STAGED_RELEASE/requirements.txt"
"$UV_BIN" pip check --python "$VENV_DIR/bin/python"
"$VENV_DIR/bin/python" -m compileall -q "$STAGED_RELEASE/app.py" "$STAGED_RELEASE/klassenbildung"

stop_running_app
mv -- "$STAGED_RELEASE" "$FINAL_RELEASE"
STAGED_RELEASE=""
ln -sfn -- "$FINAL_RELEASE" "$APP_ROOT/current"

install -m 0755 "$SOURCE_DIR/build_linux/launcher.sh" "$APP_ROOT/bin/$APP_ID"
install -m 0755 "$SOURCE_DIR/build_linux/uninstall.sh" "$APP_ROOT/bin/$APP_ID-uninstall"
ln -sfn -- "$APP_ROOT/bin/$APP_ID" "$BIN_DIR/$APP_ID"
ln -sfn -- "$APP_ROOT/bin/$APP_ID-uninstall" "$BIN_DIR/$APP_ID-uninstall"

# Vorgaben werden aktualisiert; persoenliche settings.json/class_profiles.json bleiben erhalten.
install -m 0644 "$FINAL_RELEASE/config/settings.default.json" "$DATA_DIR/config/settings.default.json"
install -m 0644 "$FINAL_RELEASE/config/class_profiles.default.json" "$DATA_DIR/config/class_profiles.default.json"
install -m 0644 "$FINAL_RELEASE/.streamlit/config.toml" "$DATA_DIR/.streamlit/config.toml"

write_desktop_entry

success "$APP_NAME ist installiert."
printf '  App-Menue: %s\n' "$APP_NAME"
printf '  Programm:  %s\n' "$BIN_DIR/$APP_ID"
printf '  Entfernen: %s\n' "$BIN_DIR/$APP_ID-uninstall"

if ((LAUNCH_AFTER_INSTALL)); then
  info "Starte $APP_NAME ..."
  nohup "$APP_ROOT/bin/$APP_ID" >/dev/null 2>&1 &
fi

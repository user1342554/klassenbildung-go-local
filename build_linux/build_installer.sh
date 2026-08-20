#!/usr/bin/env bash
# Baut ein kleines tar.gz-Paket, dessen ausfuehrbare Dateirechte beim Entpacken
# erhalten bleiben. Python und Pakete werden erst auf dem Zielrechner geladen.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="$PROJECT_DIR/build_linux/dist"
PACKAGE_NAME="Klassenbildung-Linux-Installer"
STAGING_ROOT="$(mktemp -d -t klassenbildung-linux-build.XXXXXX)"
PACKAGE_DIR="$STAGING_ROOT/$PACKAGE_NAME"

cleanup() {
  rm -rf -- "$STAGING_ROOT"
}
trap cleanup EXIT

mkdir -p "$PACKAGE_DIR/config" "$PACKAGE_DIR/.streamlit" "$PACKAGE_DIR/build_linux" "$DIST_DIR"
install -m 0755 "$PROJECT_DIR/Install-Klassenbildung-Linux.sh" "$PACKAGE_DIR/Install-Klassenbildung-Linux.sh"
install -m 0755 "$PROJECT_DIR/Klassenbildung-Linux-Installer.desktop" "$PACKAGE_DIR/Klassenbildung-Linux-Installer.desktop"
install -m 0644 "$PROJECT_DIR/app.py" "$PACKAGE_DIR/app.py"
install -m 0644 "$PROJECT_DIR/requirements.txt" "$PACKAGE_DIR/requirements.txt"
install -m 0644 "$PROJECT_DIR/pyproject.toml" "$PACKAGE_DIR/pyproject.toml"
install -m 0644 "$PROJECT_DIR/config/settings.default.json" "$PACKAGE_DIR/config/settings.default.json"
install -m 0644 "$PROJECT_DIR/config/class_profiles.default.json" "$PACKAGE_DIR/config/class_profiles.default.json"
install -m 0644 "$PROJECT_DIR/.streamlit/config.toml" "$PACKAGE_DIR/.streamlit/config.toml"
install -m 0755 "$PROJECT_DIR/build_linux/launcher.sh" "$PACKAGE_DIR/build_linux/launcher.sh"
install -m 0755 "$PROJECT_DIR/build_linux/uninstall.sh" "$PACKAGE_DIR/build_linux/uninstall.sh"
cp -R "$PROJECT_DIR/klassenbildung" "$PACKAGE_DIR/klassenbildung"
cp -R "$PROJECT_DIR/assets" "$PACKAGE_DIR/assets"
cp -R "$PROJECT_DIR/docs" "$PACKAGE_DIR/docs"
find "$PACKAGE_DIR" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$PACKAGE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

tar --owner=0 --group=0 --numeric-owner -czf "$DIST_DIR/$PACKAGE_NAME.tar.gz" \
  -C "$STAGING_ROOT" "$PACKAGE_NAME"
(
  cd -- "$DIST_DIR"
  sha256sum "$PACKAGE_NAME.tar.gz" >"$PACKAGE_NAME.tar.gz.sha256"
)

printf 'Gebaut: %s\n' "$DIST_DIR/$PACKAGE_NAME.tar.gz"
printf 'SHA-256: '
cut -d' ' -f1 "$DIST_DIR/$PACKAGE_NAME.tar.gz.sha256"

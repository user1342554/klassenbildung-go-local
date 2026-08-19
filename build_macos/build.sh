#!/usr/bin/env bash
# Baut das unsignierte macOS-App-Paket (Klassenbildung.app) und ein ZIP fuer Releases.
set -euo pipefail
cd "$(dirname "$0")"

VENV="../.venv"
if [ ! -d "$VENV" ]; then
  echo "Bitte zuerst ../start_klassenbildung.sh ausfuehren (legt .venv an)." >&2
  exit 1
fi

"$VENV/bin/python" -m pip install --upgrade pyinstaller
"$VENV/bin/python" -m PyInstaller --noconfirm --clean Klassenbildung.spec

# Selbsttest im gebuendelten Zustand: importiert alle Module, prueft Datendateien.
KLASSENBILDUNG_SELFTEST=1 dist/Klassenbildung.app/Contents/MacOS/Klassenbildung

if [ -n "${KB_CODESIGN_IDENTITY:-}" ]; then
  # Signieren (und bei gesetztem KB_NOTARY_PROFILE auch notarisieren).
  ./sign_and_notarize.sh
else
  # ditto statt zip: erhaelt Symlinks und Rechte im App-Paket.
  rm -f dist/Klassenbildung-macOS.zip
  ditto -c -k --sequesterRsrc --keepParent dist/Klassenbildung.app dist/Klassenbildung-macOS.zip
  echo "Fertig (unsigniert): dist/Klassenbildung.app und dist/Klassenbildung-macOS.zip"
  echo "Zum Signieren: KB_CODESIGN_IDENTITY=... KB_NOTARY_PROFILE=... ./build.sh"
fi

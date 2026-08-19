#!/usr/bin/env bash
# Signiert Klassenbildung.app mit einer Developer-ID und notarisiert sie bei Apple.
#
# Voraussetzungen:
#   1. Apple Developer Program (99 USD/Jahr), Zertifikatstyp
#      "Developer ID Application" im Schluesselbund.
#      Pruefen mit:  security find-identity -v -p codesigning
#   2. Notar-Zugang einmalig im Schluesselbund ablegen:
#      xcrun notarytool store-credentials "klassenbildung" \
#          --apple-id "DEINE@APPLE.ID" --team-id "DEINETEAMID" \
#          --password "app-spezifisches-passwort"
#      (App-spezifisches Passwort: https://account.apple.com -> Anmeldung & Sicherheit)
#
# Aufruf:
#   KB_CODESIGN_IDENTITY="Developer ID Application: Dein Name (TEAMID)" \
#   KB_NOTARY_PROFILE="klassenbildung" ./sign_and_notarize.sh
#
# Ohne KB_NOTARY_PROFILE wird nur signiert, nicht notarisiert.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/Klassenbildung.app"
ZIP="dist/Klassenbildung-macOS.zip"
ENTITLEMENTS="entitlements.plist"

if [ -z "${KB_CODESIGN_IDENTITY:-}" ]; then
  echo "KB_CODESIGN_IDENTITY ist nicht gesetzt." >&2
  echo "Verfuegbare Identitaeten:" >&2
  security find-identity -v -p codesigning >&2 || true
  exit 1
fi

if [ ! -d "$APP" ]; then
  echo "$APP fehlt - bitte zuerst ./build.sh ausfuehren." >&2
  exit 1
fi

echo "==> Signiere verschachtelte Binaries (innen nach aussen)"
# Apple empfiehlt, jedes Mach-O einzeln zu signieren statt --deep zu nutzen.
find "$APP" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -print0 \
  | while IFS= read -r -d '' file; do
      if file -b "$file" | grep -q "Mach-O"; then
        codesign --force --timestamp --options runtime \
                 --entitlements "$ENTITLEMENTS" \
                 --sign "$KB_CODESIGN_IDENTITY" "$file" >/dev/null
      fi
    done

echo "==> Signiere das App-Paket"
codesign --force --timestamp --options runtime \
         --entitlements "$ENTITLEMENTS" \
         --sign "$KB_CODESIGN_IDENTITY" "$APP"

echo "==> Pruefe Signatur"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Packe fuer die Notarisierung"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

if [ -z "${KB_NOTARY_PROFILE:-}" ]; then
  echo "KB_NOTARY_PROFILE nicht gesetzt - Notarisierung uebersprungen."
  echo "Fertig (nur signiert): $ZIP"
  exit 0
fi

echo "==> Notarisierung laeuft (dauert meist wenige Minuten)"
xcrun notarytool submit "$ZIP" --keychain-profile "$KB_NOTARY_PROFILE" --wait

echo "==> Hefte das Ticket an die App (funktioniert dann auch offline)"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> Gatekeeper-Urteil"
spctl -a -vvv -t exec "$APP"

echo "==> Packe die notarisierte App neu"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "Fertig: $ZIP ist signiert, notarisiert und gestapelt."

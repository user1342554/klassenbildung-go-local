# Klassenbildung (lokal)

Streamlit-App zur Klassenbildung. Laeuft lokal unter Windows, macOS und Linux.

## Linux: per Doppelklick installieren

Fuer Fedora, Nobara und openSUSE die Datei `Klassenbildung-1.0.0-1.x86_64.rpm`
herunterladen und doppelklicken. Fuer Ubuntu, Debian und Linux Mint die Datei
`Klassenbildung_1.0.0-1_amd64.deb` nehmen. Der jeweilige Software-Installer zeigt danach
den normalen **Installieren**-Knopf.

Beide Pakete enthalten Python 3.12, Streamlit, OR-Tools und alle weiteren Module. Nach der
Installation steht **Klassenbildung** im App-Menue. Beim ersten Start wird keine
Internetverbindung gebraucht. Einstellungen und Klassenprofile bleiben im Benutzerkonto.

Die Pakete sind fuer 64-Bit-x86-Linux mit glibc 2.28 oder neuer gebaut. Die RPM-Datei wird
auf Nobara getestet. Fuer andere Architekturen bleibt das Quellpaket
`Klassenbildung-Linux-Installer.tar.gz` als technischer Ausweichweg. Dieses Archiv muss vor
dem Start vollstaendig entpackt werden; ein Archivmanager kann daraus keine Programme
ausfuehren.

### Native Linux-Pakete bauen

```bash
./build_linux/build_native_packages.sh
```

Der Standard-Build nutzt einen `manylinux_2_28`-Container und erzeugt RPM, DEB und
`SHA256SUMS` unter `build_linux/packages/`. Mit `KB_NATIVE_LOCAL=1` kann lokal gebaut werden,
das Ergebnis benoetigt dann unter Umstaenden eine neuere glibc-Version.

### Technisches Benutzerkonto-Installationspaket bauen

```bash
./build_linux/build_installer.sh
```

Ergebnis: `build_linux/dist/Klassenbildung-Linux-Installer.tar.gz` plus SHA-256-Datei. Dieser
Weg installiert eine eigene Python-Laufzeit beim ersten Durchlauf und benoetigt Internet.

## Manueller Start unter macOS / Linux

```bash
./start_klassenbildung.sh
```

Unter macOS kann alternativ `start_klassenbildung.command` im Finder doppelgeklickt werden.

Das Skript legt beim ersten Start eine virtuelle Umgebung (`.venv`) an, installiert die
Abhaengigkeiten und oeffnet http://localhost:6767 im Browser.

**Voraussetzung fuer diesen manuellen Weg:** Python 3.11 oder neuer. Das mit macOS ausgelieferte Python 3.9 reicht
nicht aus. Installation z. B. per Homebrew:

```bash
brew install python@3.13
```

## Fertige macOS-App (.app)

Unter [Releases](https://github.com/user1342554/klassenbildung-go-local/releases) liegt
`Klassenbildung-macOS.zip`. Entpacken, `Klassenbildung.app` nach `/Programme` ziehen, fertig —
Python muss dafuer **nicht** installiert sein.

Die App ist **nicht signiert und nicht notarisiert**. macOS zeigt deshalb beim ersten Start:

> „Klassenbildung“ konnte nicht geöffnet werden. Apple kann nicht überprüfen, ob
> „Klassenbildung“ frei von Malware ist …

Das ist erwartet und kein Fehler der App. Zwei Wege:

**Terminal (zuverlässig, empfohlen):**

```bash
xattr -dr com.apple.quarantine /Applications/Klassenbildung.app
```

Danach startet die App normal per Doppelklick.

**Systemeinstellungen (ab macOS 13):** App doppelklicken, Meldung mit *Fertig* schließen, dann
*Systemeinstellungen* → *Datenschutz & Sicherheit* → nach unten scrollen → bei
„Klassenbildung wurde blockiert…“ auf *Dennoch öffnen* klicken.

> Der frühere Weg „Rechtsklick → Öffnen“ funktioniert ab macOS 15 (Sequoia) nicht mehr.

Einstellungen und Klassenprofile werden unter
`~/Library/Application Support/Klassenbildung/` gespeichert.

### App selbst bauen

```bash
./build_macos/build.sh
```

Ergebnis: `build_macos/dist/Klassenbildung.app` und `build_macos/dist/Klassenbildung-macOS.zip`.

### Signieren und notarisieren (optional)

Damit die Gatekeeper-Meldung dauerhaft verschwindet, muss die App mit einer Apple-Developer-ID
signiert und von Apple notarisiert werden. Voraussetzung ist das
[Apple Developer Program](https://developer.apple.com/programs/) (99 USD/Jahr).

**Einmalig einrichten:**

1. Zertifikat vom Typ **„Developer ID Application"** erstellen und in den Schluesselbund laden.
   Nur dieser Typ funktioniert ausserhalb des App Store — „Apple Development" oder
   „Apple Distribution" werden von Gatekeeper abgelehnt. Vorhandene Identitaeten anzeigen:

   ```bash
   security find-identity -v -p codesigning
   ```

2. App-spezifisches Passwort auf https://account.apple.com erzeugen und den Notar-Zugang
   im Schluesselbund hinterlegen:

   ```bash
   xcrun notarytool store-credentials "klassenbildung" \
       --apple-id "DEINE@APPLE.ID" --team-id "DEINETEAMID" \
       --password "app-spezifisches-passwort"
   ```

**Bauen, signieren, notarisieren:**

```bash
KB_CODESIGN_IDENTITY="Developer ID Application: Dein Name (TEAMID)" \
KB_NOTARY_PROFILE="klassenbildung" \
./build_macos/build.sh
```

Das Skript signiert alle eingebetteten Bibliotheken einzeln, aktiviert die Hardened Runtime,
laedt die App bei Apple hoch, wartet auf das Ergebnis, heftet das Ticket an die App
(`stapler`) und packt sie neu. Die Notarisierung dauert meist wenige Minuten.

Die noetigen Ausnahmen fuer CPython (`allow-unsigned-executable-memory`, `allow-jit`,
`disable-library-validation`) stehen in `build_macos/entitlements.plist` — ohne sie startet
die App unter Hardened Runtime nicht.

## Start unter Windows

`start_klassenbildung.bat` doppelklicken.

## Tests

```bash
.venv/bin/python -m pytest
```

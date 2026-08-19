# Klassenbildung (lokal)

Streamlit-App zur Klassenbildung. Laeuft lokal unter Windows, macOS und Linux.

## Start unter macOS / Linux

```bash
./start_klassenbildung.sh
```

Unter macOS kann alternativ `start_klassenbildung.command` im Finder doppelgeklickt werden.

Das Skript legt beim ersten Start eine virtuelle Umgebung (`.venv`) an, installiert die
Abhaengigkeiten und oeffnet http://localhost:6767 im Browser.

**Voraussetzung:** Python 3.11 oder neuer. Das mit macOS ausgelieferte Python 3.9 reicht
nicht aus. Installation z. B. per Homebrew:

```bash
brew install python@3.13
```

## Fertige macOS-App (.app)

Unter [Releases](https://github.com/user1342554/klassenbildung-go-local/releases) liegt
`Klassenbildung-macOS.zip`. Entpacken, `Klassenbildung.app` nach `/Programme` ziehen, fertig —
Python muss dafuer **nicht** installiert sein.

Die App ist **nicht signiert und nicht notarisiert**. macOS blockiert sie deshalb beim ersten
Start. Einmalig entweder im Finder mit Rechtsklick → *Oeffnen* → *Oeffnen* bestaetigen, oder im
Terminal die Quarantaene entfernen:

```bash
xattr -dr com.apple.quarantine /Applications/Klassenbildung.app
```

Einstellungen und Klassenprofile werden unter
`~/Library/Application Support/Klassenbildung/` gespeichert.

### App selbst bauen

```bash
./build_macos/build.sh
```

Ergebnis: `build_macos/dist/Klassenbildung.app` und `build_macos/dist/Klassenbildung-macOS.zip`.

## Start unter Windows

`start_klassenbildung.bat` doppelklicken.

## Tests

```bash
.venv/bin/python -m pytest
```

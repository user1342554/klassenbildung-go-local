# Klassenbildungs-Tool

Lokale Web-App zur Unterstützung der Klassenbildung neuer 5. Klassen.
Das Tool liest eine bestehende Excel-Datei ein, prüft Schülerdaten, wendet
harte Klassenregeln und gewichtete weiche Wünsche an, berechnet mit OR-Tools
CP-SAT Klassenvorschläge und exportiert das Ergebnis wieder als Excel-Datei.

Die App läuft lokal auf dem PC. Es werden keine Schülerdaten in eine Cloud
hochgeladen. Bemerkungen werden nicht automatisch interpretiert, sondern nur
angezeigt und müssen pädagogisch/manuell geprüft werden.

## Start

Windows:

```bat
start_klassenbildung.bat
```

Linux/macOS für Entwicklung:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py --server.address localhost --server.port 8501
```

Danach im Browser öffnen:

```text
http://localhost:8501
```

## Aktueller Stand

Version 0.1 bis 0.3 sind als erster lauffähiger Kern angelegt:

- Excel-Import aus dem Blatt `Basis`
- robuste Erkennung von Schülerzeilen trotz fehlerhafter Schülernummern
- Warnungen für bekannte Datenprobleme
- Anzeige von Bemerkungen ohne automatische Interpretation
- konfigurierbare Klassenprofile und Gewichtungen über lokale JSON-Dateien
- einfacher Optimierer mit OR-Tools, plus Fallback ohne OR-Tools
- Excel-Export mit aktualisiertem `Basis`-Blatt und neuen Klassenblättern

## Datenschutzgrenzen

- Keine Cloud
- Kein Convex
- Kein Vercel
- Kein Login
- Keine Datenbank mit Schülerdaten
- Keine KI-Auswertung von Bemerkungen
- Keine echten Schülerdaten ins Git-Repo legen

## Projektstruktur

```text
app.py
klassenbildung/
  core/
  excel_io/
  validation/
  optimization/
  ui/
config/
tests/
start_klassenbildung.bat
requirements.txt
```

## Tests

```bash
python -m pytest
```

Die Tests erzeugen kleine künstliche Excel-Dateien im Speicher. Echte
Schülerdaten werden nicht benötigt.


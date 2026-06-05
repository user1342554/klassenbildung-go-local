# Klassenbildungs-Tool

Lokale Web-App zur Unterstützung der Klassenbildung neuer 5. Klassen.
Das Tool liest eine bestehende Excel-Datei ein, prüft Schülerdaten, wendet
harte Klassenregeln und gewichtete weiche Wünsche an, berechnet mit OR-Tools
CP-SAT Klassenvorschläge und exportiert das Ergebnis wieder als Excel-Datei.

Die App läuft lokal auf dem PC. Es werden keine Schülerdaten in eine Cloud
hochgeladen. Bemerkungen werden lokal geprüft: eindeutige Hinweise werden als
Regelvorschlag vorbefüllt, unklare Hinweise müssen pädagogisch/manuell
entschieden werden.

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
streamlit run app.py --server.address localhost --server.port 6767
```

Danach im Browser öffnen:

```text
http://localhost:6767
```

## Aktueller Stand

Version 0.1 bis 0.3 sind als erster lauffähiger Kern angelegt:

- Excel-Import aus dem Blatt `Basis`
- robuste Erkennung von Schülerzeilen trotz fehlerhafter Schülernummern
- Warnungen für bekannte Datenprobleme
- Bemerkungsprüfung mit Regelvorschlägen für eindeutige Klassen- und Paarhinweise
- konfigurierbare Klassenprofile und Gewichtungen über lokale JSON-Dateien
- feste Klassenprofile können als harte Regeln erzwungen werden
- `Reg` ist in Musikprofilklassen nur erlaubt, wenn es im Klassenprofil ausdrücklich hinterlegt ist; B/S/G-Mischungen werden getrennt davon bewertet
- einfacher Optimierer mit OR-Tools, plus Fallback ohne OR-Tools
- Sprach- und Musikangaben bleiben beim Schueler erhalten; F/L- und Musik-Mischklassen sind moeglich und werden als weiche Praeferenzen bewertet
- Mischklassen werden nach Schwere bewertet: Grundstrafe pro Mischklasse plus Minderheits-Schueler in der Mischung
- Freundschaften werden als Paarbeziehungen bewertet; ein gegenseitiger Wunsch wird nicht zusaetzlich doppelt als Einzelwunsch addiert
- Kinder ohne einen einzigen Wunschfreund in der neuen Klasse erhalten eine eigene hohe Strafe
- R-Verteilung, Geschlecht und Grundschulballungen werden toleranz- bzw. schwellenbasiert und nicht mehr rein linear bewertet
- Staat/Nationalitaet und Religion sind keine aktiven Optimierungskriterien
- lexikografische Optimierung: erst F/L-Mischklassen, dann Musik-Mischklassen, dann Kinder ohne Wunschfreund, gegenseitige Freunde, Freund 1, danach Mischungs-Schwere, Freund 2 und Restkriterien
- Ergebnisbericht mit Profilminimum, Strafpunkten je Kategorie, Minderheitswerten, R-Verteilung, profilkonfliktigen Freundschaften und Solverstatus
- Excel-Export mit aktualisiertem `Basis`-Blatt und neuen Klassenblättern

## Datenschutzgrenzen

- Keine Cloud
- Kein Login
- Keine Datenbank mit Schülerdaten
- Keine KI-Auswertung von Bemerkungen; Regelvorschläge entstehen nur durch lokale Textmuster
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

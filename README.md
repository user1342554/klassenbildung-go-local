# Klassenbildung

Diese Streamlit-App unterstützt Schulen dabei, aus einer Excel-Schülerliste eine
prüfbare Klasseneinteilung zu erstellen. Die App ersetzt keine pädagogische
Freigabe: Sie berechnet einen Vorschlag, zeigt Risiken offen an und erzeugt
danach eine Excel-Datei für die weitere Prüfung.

## Start

```bash
./start_klassenbildung.sh
```

Unter Windows stattdessen `start_klassenbildung.bat` doppelklicken.

Die App läuft danach lokal unter <http://localhost:6767>. Beim ersten Start wird
eine lokale Python-Umgebung angelegt und die benötigten Pakete werden
installiert.

Die App verarbeitet personenbezogene Schülerdaten (Namen, Bemerkungen,
R-/Unterstützungsmarkierungen). Sie läuft ausschließlich lokal und sendet keine
Daten ins Internet. Der Excel-Export enthält dieselben sensiblen Daten und darf
nur an berechtigte Personen weitergegeben werden.

## Ablauf in der App

Die App führt in vier Reitern durch den Ablauf: `1 Excel prüfen`,
`2 Einstellungen`, `3 Berechnen`, `4 Ergebnis`. Der Schulablauf ist in
[docs/school_user_workflow.md](docs/school_user_workflow.md) Schritt für Schritt
beschrieben.

## Rechenweg auf einen Blick


```mermaid
flowchart TD
    A["Excel hochladen<br/>Blatt Basis"] --> B["Schülerdaten einlesen<br/>Name, Nr., Grundschule, Profile, Wünsche, Bemerkungen"]
    B --> C{"Blockierende Datenfehler?"}
    C -- "ja" --> C1["Datei oder Eingaben korrigieren<br/>z. B. fehlende Nr., mehrdeutiger Freund, unbekanntes Profil"]
    C1 --> A
    C -- "nein" --> D["Klassenrahmen festlegen<br/>Anzahl Klassen, Zielgröße, harter Spielraum"]
    D --> F["Aktive Regeln bilden<br/>zusammen, trennen, feste Klasse, erlaubte Klassen"]
    F --> G["Harte Grenzen setzen<br/>jedes Kind genau eine Klasse, Klassengröße, Regeln, Ballungsgrenzen"]

    G --> H1["1. F/L-Mischklassen minimieren"]
    H1 --> H2["2. Musik-Mischklassen B/S/G minimieren"]
    H2 --> H3["3. Freigabegrenze testen<br/>Kinder ohne Wunschfreund höchstens 15 Prozent"]
    H3 --> H4["4. Beste Zahl ohne Wunschfreund suchen"]
    H4 --> H4a{"Soziale Qualität schlecht?"}
    H4a -- "ja" --> H4b["Zusatzprüfung<br/>Profil-Lockerung als Diagnose"]
    H4a -- "nein" --> H5["5. Gegenseitige Freundschaften retten"]
    H4b --> H5
    H5 --> H6["6. Freund 1 retten"]
    H6 --> H7["7. Kleine Profilgruppen in Mischklassen verringern"]
    H7 --> H8["8. Freund 2 retten"]
    H8 --> H9["9. Restqualität optimieren<br/>Größe, Geschlecht, Grundschule, R-Verteilung, bestehende Einteilung"]

    H9 --> I["Vorschlag bewerten<br/>Strafpunkte, harte Verstöße, Warnungen, Wunschfreunde"]
    I --> J{"Noch fachlich offen?"}
    J -- "ja" --> K["Manuelle Regeln anpassen<br/>Ergebnis wird verworfen, danach neu berechnen"]
    K --> F
    J -- "nur kleine manuelle Korrektur" --> L["Alle Klassen bearbeiten<br/>Kinder zwischen Klassen verschieben"]
    L --> M["Liste prüfen<br/>harte Regelverstöße sichtbar machen"]
    J -- "nein" --> N["Excel exportieren"]
    M --> N
    N --> O["Export enthält<br/>Basis, Alle Klassen, einzelne Klassenblätter"]
```

## Was die App aus der Excel-Datei liest

Die wichtigste Wahrheit steht im Excel-Blatt `Basis`. Daraus werden pro Kind
unter anderem gelesen:

- Zielklasse aus der alten Datei, falls vorhanden
- Schülernummer und Name
- abgebende Grundschule und Grundschulklasse
- Geschlecht
- Fremdsprache F oder L
- Musikprofil B, S, G oder Reg
- Wunschfreund 1 und Wunschfreund 2
- Bemerkungen
- R- oder Unterstützungsmarkierungen

Andere Excel-Blätter können zur Ansicht vorhanden sein, die Berechnung richtet
sich aber nach dem importierten `Basis`-Blatt und den Einstellungen in der App.

## Harte Regeln

Harte Regeln sind Bedingungen, die eine Lösung nicht verletzen darf. Wenn eine
harte Regel nicht erfüllbar ist, ist die Einteilung fachlich nicht freigabefähig.

- Jedes Kind muss genau einer Klasse zugeordnet werden.
- Jede Klasse muss innerhalb der eingestellten Mindest- und Höchstgröße bleiben.
- Aktive manuelle Regeln werden eingehalten: zusammen, trennen, feste Klasse oder
  erlaubte Klassen.
- Ein Kind darf nur in Klassen landen, die grundsätzlich erlaubt sind.
- Die Freigabegrenzen prüfen Ballungen, zum Beispiel zu viele Kinder aus einer
  Grundschule, zu viele Kinder aus derselben Grundschulklasse oder zu viele
  R-/Unterstützungsmarkierungen in einer Klasse.

## Weiche Ziele und Strafpunkte

Weiche Ziele sind Wünsche, die gegeneinander abgewogen werden. Dafür nutzt die
App Strafpunkte: weniger Punkte bedeutet eine bessere Lösung. Eine Lösung mit
wenigen Strafpunkten kann trotzdem blockiert sein, wenn harte Regeln verletzt
werden.

Wichtige Strafpunkt-Bereiche sind:

- getrennte Freundschaften
- Kinder ohne einen Wunschfreund in der Klasse
- F/L-Mischklassen und kleine F/L-Minderheiten
- Musik-Mischklassen zwischen B, S und G
- zu kleine oder zu große Abweichungen vom Wunschbereich der Klassengröße
- ungleich verteilte R-/Unterstützungsmarkierungen
- starke Geschlechter-Schieflage
- Ballungen nach Grundschule oder Grundschulklasse
- Abweichungen von einer bestehenden Einteilung, falls diese gewichtet wird

## Warum die Berechnung mehrere Phasen hat

Die App rechnet nicht alles in einem einzigen Schritt durcheinander. Sie arbeitet
in Phasen, damit wichtige Ziele nicht später wieder kaputtoptimiert werden.

Beispiel: Wenn die App in Phase 1 die bestmögliche Zahl an F/L-Mischklassen
gefunden hat, wird diese Zahl als Grenze festgehalten. Danach sucht die nächste
Phase innerhalb dieser Grenze weiter. So entsteht ein Vorschlag, der zuerst die
groben Profil- und Sozialziele absichert und danach die Restqualität verbessert.

Wenn eine spätere Phase im Zeitlimit keine bessere gültige Lösung findet, nimmt
die App die letzte gültige Lösung weiter. Das Ergebnis zeigt dann, welche Phase
die sichtbare Einteilung geliefert hat.

## Bemerkungen und manuelle Regeln

Bemerkungen aus der Excel-Datei werden eingelesen, im Klassenboard markiert und
in den Export geschrieben. Die App interpretiert diesen Freitext aber nicht und
wandelt ihn nicht automatisch in Regeln um.

Manuelle Regeln sind harte Bedingungen und werden im Bereich
`Aktive manuelle Regeln` verwaltet:

- Trennen
- Zusammen
- Klassenfixierung
- erlaubte Klassen

Nur aktive Regeln gehen in die nächste Berechnung ein. Wird eine Regel geändert,
verwirft die App das bisherige Ergebnis und bittet um eine neue Berechnung.

## Prüfung und Export

Nach der Berechnung zeigt die App genau eine beste Lösung. Der Abschnitt
`Prüfung` nennt die fachlichen Kennzahlen: harte Verstöße, Kinder ohne
Wunschfreund, erfüllte Freundeswünsche sowie F/L- und Musik-Mischklassen.

Unter `Alle Klassen` lässt sich die Einteilung per Drag-and-drop nachbearbeiten.
Diese manuelle Änderung gilt für den Excel-Download. Der Button `Liste prüfen`
zeigt, ob die bearbeitete Liste harte Regeln verletzt.

Der Export schreibt:

- `Basis`: ursprüngliches Basisblatt mit aktualisierter Zielklasse
- `Alle Klassen`: alle Klassen nebeneinander als schnelle Gesamtübersicht
- einzelne Klassenblätter wie `5a`, `5b`, `5c`

Offene Datenprobleme, ungeklärte Bemerkungen oder Warnungen bleiben fachlich
relevant. Ein Download allein bedeutet deshalb noch keine endgültige Freigabe.

## Entwicklerprüfung

Vor einem Commit sollte mindestens diese lokale Prüfung laufen:

```bash
.venv/bin/python -m compileall app.py klassenbildung
.venv/bin/python -m ruff check app.py klassenbildung tests --select F
.venv/bin/python -m pytest
git diff --check
```

`tests/test_app_structure.py` prüft dabei, dass jede Funktion in `app.py` von
`main()` aus erreichbar ist. Damit fällt auf, wenn ein Umbau eine Ansicht
abhängt und toten Code zurücklässt.

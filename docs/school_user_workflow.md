# Schulablauf: Klassenbildung prüfen und bearbeiten

Diese Anleitung beschreibt den normalen Arbeitsablauf für die Schule. Technische
Solverdetails stehen im Expertenmodus und sind für diesen Ablauf nicht nötig.

Die App hat vier Schritte, die den vier Reitern entsprechen:

1. Excel prüfen
2. Einstellungen
3. Berechnen
4. Ergebnis

## 1. Excel prüfen

Lade die Schülerliste hoch und klicke auf `Datei prüfen`. Die App liest das Blatt
`Basis` und zeigt danach einen Dateiüberblick, die Freundeswünsche und die
Verteilungen nach Sprache, Geschlecht und Musikprofil.

Blockierende Fehler, zum Beispiel eine fehlende Schülernummer oder ein
mehrdeutiger Freundeseintrag, werden hier rot angezeigt. Solange sie bestehen,
lässt sich in Schritt 3 nichts berechnen. Nicht kritische Warnungen stehen in
einem eigenen Aufklappbereich.

Wenn sich die Schülerdaten seit dem letzten Lauf geändert haben, setzt die App
manuelle Regeln zurück. Das verhindert, dass alte Entscheidungen auf neue Daten
angewendet werden.

## 2. Einstellungen

Hier legst du den Klassenrahmen fest: Anzahl Klassen, Wunschgröße und den harten
Spielraum. Die Klassengröße ist standardmäßig hart auf 28-32 Kinder begrenzt,
29-31 ist der bevorzugte Zielbereich ohne Zusatzstrafe.

Die App arbeitet ohne feste Klassenprofile. Musik- und Sprachverteilung
entscheidet die Berechnung; Klassennamen wie 5a oder 5e erzwingen keine
vorgegebene S-, B-, G-, F- oder L-Klasse. `Reg` ist dabei ein neutraler Füller:
Die Musik-Mischklassen-Kennzahl zählt nur Mischungen zwischen B, S und G.

Darunter stehen die Gewichtungen. Sie steuern, wie stark einzelne Ziele
gegeneinander abgewogen werden. `Empfohlene Gewichtungen laden` stellt die
Standardwerte wieder her.

Unter `Weitere Gewichtungen` stehen die harten Freigabegrenzen: gleiche
Grundschule höchstens 10 Kinder je Klasse, gleiche Grundschule plus alte Klasse
höchstens 6 Kinder je Klasse, R-/Unterstützungsmarkierungen höchstens 4 je
Klasse. Wird eine Grenze überschritten, zeigt die App den Befund im Ergebnis und
im Export.

**Achtung:** Jede Änderung in diesem Reiter verwirft ein bereits berechnetes
Ergebnis. Die App weist darauf hin und du musst in Schritt 3 neu berechnen.

Der Schalter `Expertenmodus` öffnet `Technische Details` automatisch und schreibt
zusätzliche Diagnoseblätter in den Excel-Export.

## 3. Berechnen

Starte die Berechnung mit `Klassen vorschlagen`. Ein Fortschrittsbalken zeigt,
welcher Prüfschritt gerade läuft. Die eingestellte Rechenzeit gilt pro
Prüfschritt, ein vollständiger Lauf über rund 210 Kinder dauert deshalb einige
Minuten.

Danach zeigt die App, wie viele Kinder mindestens einen Wunschfreund haben und ob
harte Regelverletzungen vorliegen. Die App zeigt genau eine beste Lösung; ein
Vergleich mehrerer Varianten gehört nicht zum Schulablauf.

## 4. Ergebnis

Der Ergebnisreiter enthält drei Bereiche.

### Prüfung

Die Kennzahlen, auf die es fachlich ankommt: harte Regelverletzungen, Kinder ohne
Wunschfreund, erfüllte Freundeswünsche, F/L- und Musik-Mischklassen. Aufklappbar
stehen darunter die Zahlen je Klasse und die nicht erfüllten Freundeswünsche.

### Alle Klassen

Die Klassen als Spalten, die Kinder als verschiebbare Zeilen. Ein Klick auf ein
Kind öffnet eine Detailkarte; per Drag-and-drop oder über die Karte lässt sich
ein Kind in eine andere Klasse verschieben. Notizen und Profilkonflikte sind
markiert.

`Liste prüfen` zeigt, ob die manuell bearbeitete Liste harte Regeln verletzt.
`Zur berechneten Lösung zurücksetzen` verwirft die manuellen Verschiebungen.
Manuelle Änderungen gelten für den Excel-Download.

### Aktive manuelle Regeln

Jede Regel zeigt Typ, Schüler, Partner oder Zielklasse, Quelle und ob sie aktiv
ist. Regeln lassen sich bearbeiten, deaktivieren oder löschen. Deaktivierte
Regeln wirken nicht auf die nächste Berechnung. Widersprüchliche oder zu enge
Regeln meldet die App als blockierenden Fehler.

Eine manuelle Regel ist eine harte Bedingung. Wird eine Regel geändert, verwirft
die App das bisherige Ergebnis und bittet dich, in Schritt 3 neu zu berechnen.

Bemerkungen aus der Excel-Datei werden weiterhin eingelesen, im Klassenboard
markiert und in den Export geschrieben. Sie werden aber nicht automatisch in
Regeln umgewandelt: Die App interpretiert keinen Freitext.

## Export

`Excel exportieren` schreibt das Blatt `Basis` mit aktualisierter Zielklasse, das
Sammelblatt `Alle Klassen` und je ein Klassenblatt für 5a, 5b, 5c und so weiter.
Grundlage ist die aktuell angezeigte Liste, inklusive manueller Verschiebungen.

Die App vergleicht lokal gespeicherte Bestkandidaten mit neu berechneten
Kandidaten. Dadurch geht eine früher bessere Einteilung nicht verloren, solange
Eingabedaten, Einstellungen und aktive Regeln gleich bleiben.

Offene Bemerkungen, Datenprobleme und Warnungen bleiben in der App sichtbar. Ein
Download allein bedeutet keine endgültige Freigabe.

## Datenschutz

Die Datei enthält personenbezogene Daten von Kindern, darunter Namen,
Bemerkungen und R-/Unterstützungsmarkierungen. Die App läuft ausschließlich lokal
auf deinem Rechner und sendet nichts ins Internet. Der Export enthält dieselben
sensiblen Daten: Teile ihn nur mit berechtigten Personen und lösche Kopien, die
nicht mehr gebraucht werden.

## Was nicht automatisch passiert

- Bemerkungen werden nicht interpretiert und nicht automatisch in Regeln
  umgewandelt. Wer eine Bemerkung umsetzen will, legt die Regel bewusst selbst an.
- Eine Lösung wird nicht automatisch pädagogisch freigegeben.
- Technische Solverdetails sind für den Standardablauf nicht nötig.

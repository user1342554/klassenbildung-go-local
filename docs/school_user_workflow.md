# Schulablauf: Klassenbildung pruefen und bearbeiten

Diese Anleitung beschreibt den normalen Arbeitsablauf fuer die Schule. Technische Solverdetails gehoeren in den Expertenmodus und sind fuer diesen Ablauf nicht noetig.

## 1. Datei laden

Oeffne die App und lade die Schuelerliste hoch. Wenn sich die Schuelerdaten seit dem letzten Lauf geaendert haben, setzt die App manuelle Regeln zurueck. Das verhindert, dass alte Entscheidungen auf neue Daten angewendet werden.

## 2. Profile und Bemerkungen pruefen

Die App arbeitet ohne feste Klassenprofile. Musik- und Sprachverteilung werden
von der Berechnung entschieden; Klassennamen wie 5a oder 5e erzwingen keine
vorgegebene S-, B-, G-, F- oder L-Klasse.

Reg bedeutet dabei einen neutralen Fueller. Die Musik-Mischklassen-Kennzahl
zaehlt nur Mischungen zwischen B, S und G; Reg ist keine zweite Profilgruppe.

Pruefe danach die Bemerkungen. Eindeutige Hinweise werden vorbefuellt, zum
Beispiel:

- nur 5e moeglich -> Klassenfixierung
- nicht mit Nr. 23 -> Trennregel
- mit Nr. 23 zusammen -> Zusammenregel

Unklare Hinweise wie "nicht mit Schwester" muessen bewusst geklaert werden,
weil die App den zweiten Schueler nicht erraten soll.

Die V18-Freigabegrenzen werden dokumentiert: gleiche Grundschule hoechstens 10 Kinder je
Klasse, gleiche Grundschule plus alte Klasse hoechstens 6 Kinder je Klasse, und
R-/Unterstuetzungsmarkierungen hoechstens 4 je Klasse. Wird eine Grenze
ueberschritten, zeigt die App den Befund im Ergebnis und im Export.
Die Klassengroesse ist standardmaessig hart auf 28-32 Kinder begrenzt; 29-31
ist der bevorzugte Zielbereich.

## 3. Ergebnis berechnen

Starte die Berechnung. Die Standardansicht zeigt danach, ob die strenge Profilvariante brauchbar ist und welche beste Loesung verwendet werden soll.

Normalerweise gilt:

- Die App zeigt nur eine beste Loesung.
- Weitere Vergleichsvarianten sind kein normaler Schulablauf.
- Diese Loesung wird als Grundlage fuer Pruefung und Export verwendet.

Die Loesung wird nicht automatisch freigegeben, wenn eine paedagogische Pruefung noetig ist.

## 4. Loesung oeffnen

Oeffne die vorgeschlagene Loesung. In der Pruefung stehen die wichtigen Listen:

- Kinder ohne Wunschfreund
- getrennte gegenseitige Freundschaften
- Schueler mit manueller Notiz
- F/L-Mischklassen
- Musik-Mischklassen
- Klassenbelastung

Notizen sind sichtbar markiert. Eine Notiz wird nicht automatisch interpretiert.

## 5. Notizen pruefen

Im Notizbereich entscheidest du bewusst, was mit einer Notiz passiert:

- als Trennregel anlegen
- als Zusammenregel anlegen
- als Klassenfixierung anlegen
- nur als Hinweis behalten

Bei Trenn- und Zusammenregeln muss der zweite Schueler bewusst ausgewaehlt werden. Die App kann eindeutige Treffer vorbefuellen, die Entscheidung bleibt aber sichtbar.

## 6. Aktive Regeln kontrollieren

Pruefe den Bereich fuer aktive manuelle Regeln. Jede Regel zeigt:

- Typ
- Schueler
- Partner oder Zielklasse
- Quelle
- aktiv oder deaktiviert

Regeln koennen deaktiviert oder geloescht werden. Deaktivierte Regeln wirken nicht auf die naechste Berechnung.

## 7. Nach Regeländerungen neu berechnen

Starte die Berechnung erneut, wenn die aktiven manuellen Regeln fachlich passen. Die App gibt aktive Regeln als harte Bedingungen an den Solver weiter.

Wenn die Regeln widerspruechlich oder zu eng sind, zeigt die App blockierende Fehler. Dann muessen Regeln geloescht, deaktiviert oder angepasst werden.

## 8. Ergebnis erneut pruefen

Pruefe die neue Loesung wieder in der Loesungspruefung:

- Kinder ohne Wunschfreund
- getrennte gegenseitige Freundschaften
- manuelle Notizen
- F/L- und Musik-Mischklassen
- Klassenbelastung

Entscheide anhand dieser Listen, ob die neue Loesung besser pruefbar ist als das vorherige Ergebnis.

## 9. Export erzeugen

Die App nimmt automatisch die beste dokumentierte Loesung als Exportgrundlage.
Der Excel-Export enthaelt nur noch das Blatt `Basis` und je ein Klassenblatt
fuer 5a, 5b, 5c und so weiter.

Offene Notizen, Datenprobleme und Warnungen bleiben in der App sichtbar. Sie
werden nicht mehr als eigene Excel-Blaetter exportiert.

Die App vergleicht lokal gespeicherte Bestkandidaten mit neu berechneten
Kandidaten. Dadurch geht eine frueher bessere Einteilung nicht verloren,
solange Eingabedaten, Profile, Einstellungen und aktive Regeln gleich bleiben.

Der Export enthaelt sensible Schuelerdaten. Teile ihn nur mit berechtigten Personen.

## Was nicht automatisch passiert

- Unklare Notizen werden nicht geraten oder automatisch angewendet.
- Technische Solverdetails sind fuer den Standardablauf nicht noetig.

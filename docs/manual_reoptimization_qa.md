# Manuelle Reoptimierung: Release-QA

Diese Checkliste gilt fuer den Release Candidate mit manuellen Regeln, manuellem Entwurf und Neuoptimierung mit Fixierungen. In diesem Stand werden keine neuen Features bewertet, sondern nur Bedienbarkeit, Fehlerzustand, Export, Performance und Datenschutz.

## Akzeptanzkriterium

Ein normaler Nutzer muss ohne Entwicklerwissen:

1. Datei laden.
2. Ergebnis berechnen.
3. Kandidat E, F oder C oeffnen.
4. Notizen sehen.
5. Eine Notiz bewusst in eine Regel umwandeln.
6. Einen Schueler testweise verschieben.
7. Die Auswirkung verstehen.
8. Eine harte Verletzung blockiert bekommen.
9. Eine Verschiebung uebernehmen, rueckgaengig machen oder fixieren.
10. Mit Fixierungen neu optimieren.
11. Vorher und Nachher vergleichen.
12. Einen Export erzeugen, der Herkunft, Regeln, Notizen, Moves und Neuoptimierung dokumentiert.

## Manueller Happy Path

1. App oeffnen.
2. Datei laden.
3. Ergebnis berechnen.
4. Pruefkandidat E oeffnen.
5. Kind ohne Wunschfreund mit Notiz finden.
6. Notiz als Trennregel umwandeln.
7. Pruefen: Regel erscheint unter aktive manuelle Regeln.
8. Pruefen: Regel ist aktiv, deaktivierbar und loeschbar.
9. Schueler temporaer in eine andere Klasse verschieben.
10. Pruefen: temporaerer Move wird nicht als Fixierung behandelt.
11. Zweiten Schueler verschieben und fixieren.
12. Pruefen: Fixierung erscheint als harte manuelle Vorgabe.
13. Neuoptimierung mit Fixierungen starten.
14. Pruefen: fixierter Schueler bleibt in der Zielklasse.
15. Pruefen: Trennregel wird eingehalten.
16. Vergleich vorher/nachher lesen.
17. Export erzeugen.
18. Export oeffnen.
19. Pruefen: Ausgangskandidat, Moves, Fixierungen, Regeln, Notizstatus und Reoptimierungsstatus sind dokumentiert.
20. Gleiche Datei erneut laden.
21. Pruefen: Regeln bleiben bei gleichem Datenhash wie vorgesehen erhalten.
22. Datei mit geaenderten Schuelerdaten laden.
23. Pruefen: Regeln und Entwuerfe werden zurueckgesetzt und die UI meldet den Reset.

## Fehlerfaelle

### Widerspruechliche Fixierungen

Fall: Ein Schueler ist gleichzeitig auf zwei Klassen fixiert.

Erwartung:

- Neuoptimierung ist blockiert.
- Kein gueltiger Entwurf wird ueberschrieben.
- Der Fehlertext nennt die betroffenen Fixierungen.

### Zusammenregel widerspricht Fixierung

Fall: A und B muessen zusammen sein, A ist in 5a fixiert und B in 5b.

Erwartung:

- Blocker wird sofort angezeigt.
- Neuoptimierung ist deaktiviert.
- UI nennt als Loesungswege: Fixierung entfernen oder Zusammenregel deaktivieren.

### Trennregel widerspricht Fixierung

Fall: A und B muessen getrennt sein, beide sind in 5a fixiert.

Erwartung:

- Blocker wird sofort angezeigt.
- Neuoptimierung ist deaktiviert.
- UI nennt die verletzte Trennregel.

### Harte Klassengroesse verletzt

Fall: Harte Obergrenze ist 35, ein Move erzeugt 36 Schueler in einer Klasse.

Erwartung:

- Move wird als harte Verletzung markiert.
- Uebernehmen und Fixieren ist nicht moeglich, solange der Blocker besteht.
- Keine Neuoptimierung wird mit diesem blockierten Zustand gestartet.

### Neuoptimierung nicht loesbar

Erwartung:

- Bisheriger manueller Entwurf bleibt erhalten.
- Keine leere Loesung wird angezeigt.
- Moves und Regeln gehen nicht verloren.
- UI nennt konkrete Schritte: Fixierung entfernen, Regel deaktivieren, Klassengroesse lockern oder Profilgrenzen lockern.

### Neuoptimierung nicht entscheidbar

Erwartung:

- Bisheriger manueller Entwurf bleibt erhalten.
- Standardtext sagt: Keine entscheidbare neue Loesung gefunden.
- Keine Solverbegriffe erscheinen im Standardflow.

## Standardtext ohne Solverjargon

Im Standardflow duerfen diese Begriffe nicht erscheinen:

- FEASIBLE
- UNKNOWN
- INFEASIBLE
- Gap
- Objective
- Best Bound
- Incumbent
- Draft
- Slack
- Payload
- Solverphase

Zulaessige Nutzertexte:

- gueltige Loesung gefunden
- keine entscheidbare neue Loesung gefunden
- mit diesen Vorgaben nicht loesbar
- nicht bewiesen optimal
- manueller Entwurf
- Profil-Lockerung
- bisherige gueltige Loesung

## Vergleich nach Neuoptimierung

Nach jedem erfolgreichen Lauf muss oben sichtbar sein:

- Ausgangskandidat
- Anzahl manueller Moves
- Anzahl fixierter Schueler
- Anzahl aktiver manueller Regeln
- Status der Neuoptimierung

Der Vergleich muss mindestens zeigen:

- Kinder ohne Wunschfreund
- Freund 1 erfuellt
- gegenseitige Freunde erfuellt
- Freund 2 erfuellt
- F/L-Mischklassen
- Musik-Mischklassen
- F/L-Minderheits-Schueler
- Musik-Minderheits-Schueler
- harte Regelverletzungen

Jede Zeile muss als besser, schlechter, unveraendert oder Hinweis bewertet werden.

## Exportpruefung

Der Export muss eindeutig dokumentieren:

- Basis-Kandidat
- ob die Loesung manuell veraendert wurde
- Neuoptimierungsstatus
- aktive und deaktivierte manuelle Regeln
- Regeln aus Notizen
- Notizstatus: ungeprueft, als Hinweis behalten, in Regel umgewandelt
- temporaere Moves
- fixierte Moves
- Delta je manuellem Move
- Fixierungen, die in der Neuoptimierung galten

Ein Export nach manueller Bearbeitung darf nicht wie eine reine Solverloesung wirken.

## Performanceziele

- Datei laden: unter 2 Sekunden, soweit Dateigroesse normal ist.
- Validierung: unter 2 Sekunden.
- Kandidatenreview oeffnen: unter 1 Sekunde.
- manuellen Move bewerten: unter 1 Sekunde.
- Export erzeugen: unter 5 Sekunden.
- Solver- und Neuoptimierungslauf: Fortschritt und laufender Zustand muessen klar sichtbar sein.

## Datenschutzpruefung

- Keine Klarnamen im Incumbent-Cache.
- Cache-Dateien haben restriktive Dateirechte.
- Cache wird bei Datenhash-, Regel- oder Policy-Wechsel ignoriert.
- Notizen werden nicht in Debuglogs geschrieben.
- Manuelle Regeln und Entwuerfe werden bei geaendertem Datenhash zurueckgesetzt.
- Export enthaelt sensible Daten nur bewusst und nachvollziehbar.
- UI weist darauf hin, dass Notizen, Regeln und Exporte sensible Schuelerdaten enthalten.

## Release-Blocker

- Legacy-Payload-Felder im aktuellen Standardoutput: `primary_recommendation`, `balanced_recommendation`, `slack_candidates`.
- Neuoptimierung ueberschreibt bei Fehlern den letzten gueltigen Entwurf.
- Harte Blocker erlauben Uebernehmen, Fixieren oder Neuoptimieren.
- Export verschleiert, dass die Loesung manuell veraendert wurde.
- Standardflow zeigt Solverjargon.
- Notizen mit Status ungeprueft verschwinden aus Review oder Export.

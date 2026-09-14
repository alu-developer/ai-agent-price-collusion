# Experimentplan v0.1

## Frage

Senken ein öffentliches Kommunikationsprotokoll und zufällige Audits den Preisaufschlag in einem wiederholten, simulierten Markt mit KI-Agenten?

## Minimalpilot

- Drei gleichartige Verkäufer-Agenten.
- 20 Marktrunden pro Lauf.
- Drei Bedingungen: keine Kommunikation, private Kommunikation, öffentliches Protokoll mit Audit.
- Fünf Wiederholungen pro Bedingung als technische Prüfung; daraus wird noch kein allgemeiner Forschungsbefund abgeleitet.
- Keine realen Märkte, Preise, Kund:innen oder Unternehmensdaten.

## Agentenschnittstelle

Pro Runde erhält jeder Agent nur einen kompakten Marktstatus. Die Antwort muss einem JSON-Schema entsprechen:

```json
{"price": 1, "message": "optional, maximal 20 Wörter"}
```

`price` muss eine ganze Zahl von 1 bis 10 sein. Antworten außerhalb des Schemas werden als Fehler geloggt und nicht manuell verändert.

## Schutz vor Kosten- und Kontextwachstum

- Maximal 80 Ausgabe-Token je Anfrage.
- Niedrige Reasoning-Stufe, sofern das gewählte Modell sie anbietet.
- Kein vollständiger Gesprächsverlauf; nur verdichteter, versionskontrollierter Zustand.
- Globales Budget pro Pilotlauf: 0,10 US-Dollar.
- Abbruch bei Budgetüberschreitung oder wiederholten fehlerhaften Antworten.

## Messgrößen

Primär: durchschnittlicher niedrigster Marktpreis pro Runde, verglichen mit der Kontrollbedingung.

Sekundär: Dauer hoher Preisphasen, Preisgleichheit, simulierte Mehrkosten und Rate ungültiger Antworten.

## Grenzen

Dieses Projekt untersucht Erkennung und Reduktion von Koordination in einer Spielzeug-Simulation. Es entwickelt oder veröffentlicht keine Methoden, mit denen reale Preisabsprachen wirksamer oder schwerer erkennbar würden.

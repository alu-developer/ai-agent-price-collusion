# Preisabsprachen von KI-Agenten

Ein reproduzierbares Forschungsprojekt zur Frage, ob Kommunikation zwischen KI-Agenten in einem simulierten Markt zu überhöhten Preisen führt — und ob Transparenz und Audits das Risiko senken.

## Status

Die frühere Demo mit fest programmierten Testagenten wurde bewusst entfernt. Dieses Repository ist nun die saubere Basis für das echte, API-gestützte Experiment.

## Die erste echte Studie

Ein Minimalpilot soll drei Verkäufer-Agenten über 20 Runden in einem vollständig simulierten Markt vergleichen:

1. keine Kommunikation;
2. private Kommunikation;
3. öffentliche Kommunikation plus zufällige Prüfung.

Jeder Agent gibt nur strukturiertes JSON mit einem Preis von 1 bis 10 und optional einer sehr kurzen Nachricht zurück. Jeder Aufruf erhält strenge Token-, Zeit- und Kostengrenzen. Details stehen in [docs/experiment-plan.md](docs/experiment-plan.md).

## Aufbau

- `src/price_agents/` — später der eigentliche Versuchsleiter und Modelladapter
- `docs/` — Forschungsfrage, Hypothesen und Entscheidungen
- `data/` — lokale Rohdaten und aufbereitete Daten; standardmäßig nicht in Git
- `artifacts/` — Berichte, Diagramme und freigegebene Ergebnisse; standardmäßig nicht in Git

## Späterer Start

Die erste echte Version wird Python und die offiziellen SDKs der getesteten Anbieter nutzen. Zunächst starten wir mit einem günstigen OpenAI-Modell und fügen erst nach einem erfolgreichen Pilot eine zweite Modellfamilie hinzu.

Ein API-Schlüssel kommt nur lokal in eine `.env`-Datei. Als Vorlage dient `.env.example`; echte Schlüssel dürfen niemals in Git oder GitHub landen.

## Reproduzierbarkeit

Für jeden realen Lauf speichern wir Modellkennung, Prompt-Version, Parameter, Zufallsstart, Datum, Tokenverbrauch, Rohantworten und eine Prüfsumme der Konfiguration. Hypothesen und primäre Kennzahlen werden vor der Datensammlung festgelegt.

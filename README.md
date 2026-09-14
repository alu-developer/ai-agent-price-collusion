# Preisabsprachen von KI-Agenten

Ein reproduzierbares Forschungsprojekt zur Frage, ob Kommunikation zwischen KI-Agenten in einem simulierten Markt zu überhöhten Preisen führt — und ob ein öffentliches Protokoll oder zufällige Audits dieses Risiko tatsächlich senken, oder nur scheinbar.

## Status

Das Projekt ist vollständig aufgesetzt und lauffertig. Es fehlen nur echte API-Schlüssel in einer lokalen `.env`-Datei — der Rest (Versuchsdesign, Modelladapter, Budgetgrenze, Auswertung, Bericht) ist fertig.

## Das Versuchsdesign in Kürze

- 3–5 Verkäufer-Agenten (Standard: 4) setzen 100 Runden lang Preise (1–10) für ein identisches, vollständig simuliertes Produkt; der niedrigste Preis bekommt die simulierten Kund:innen.
- Vier Bedingungen: keine Kommunikation · Kommunikation · Kommunikation + öffentliches, unveränderbares Protokoll · Kommunikation + zufällige, spürbar bestrafte Audits.
- Mindestens 10 Wiederholungen je Bedingung mit unterschiedlichen Zufallsstarts, mit mindestens zwei Modellen aus mindestens zwei Anbietern.
- Volles Detail inklusive aller Kennzahlen, Modellannahmen und Grenzen: [docs/experiment-plan.md](docs/experiment-plan.md).

## Aufbau

- `src/price_agents/types.py` — die vier Bedingungen (fest, vorregistriert)
- `src/price_agents/prompts.py` — Grundanweisung, Marktstatus-Prompt, JSON-Schema
- `src/price_agents/models.py` — Modelladapter (OpenAI, Anthropic, optional Google) + Budgetwächter
- `src/price_agents/runner.py` — führt die volle Studie aus, stoppt sauber bei Budgetlimit
- `src/price_agents/analyze.py` — Kennzahlen, Bootstrap-Vergleiche, `report.md`
- `src/price_agents/cli.py` — `validate` / `run` / `analyze`
- `docs/` — Forschungsfrage, Design, Entscheidungen
- `data/` — lokale Rohdaten; standardmäßig nicht in Git
- `artifacts/` — Studienergebnisse je Lauf; standardmäßig nicht in Git

## In drei Schritten zum ersten echten Lauf

1. Python-Umgebung und Abhängigkeiten installieren (OpenAI + Anthropic sind Pflicht, Google optional):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e .
   # Nur falls du ein gemini-... Modell nutzen willst:
   python -m pip install -e ".[google]"
   ```

2. `.env.example` nach `.env` kopieren und dort `OPENAI_API_KEY` und `ANTHROPIC_API_KEY` ausfüllen (bzw. `GOOGLE_API_KEY`, wenn du ein drittes Modell hinzufügst). Die Datei wird durch `.gitignore` nie hochgeladen.

3. Konfiguration und Kostenschätzung ohne Modellaufruf prüfen, dann die volle Studie starten:

   ```powershell
   price-agents validate
   price-agents run
   ```

`validate` kostet nichts und zeigt dir die geplante Anzahl Modellaufrufe sowie eine konservative Kostenschätzung gegen dein Budget. `run` führt die echten Modellaufrufe aus und bricht automatisch ab, bevor `EXPERIMENT_MAX_COST_USD` überschritten wird — dabei gehen keine bereits gesammelten Daten verloren. Ergebnisse landen in einem zeitgestempelten Ordner unter `artifacts/`.

## Kosten realistisch einschätzen

Der Standardumfang (100 Runden × 4 Verkäufer:innen × 4 Bedingungen × 10 Wiederholungen × 2 Modelle) sind 32.000 Modellaufrufe. `price-agents validate` rechnet dir vor dem ersten echten Aufruf eine konservative obere Schranke aus deiner aktuellen `.env`-Konfiguration vor. Willst du zuerst günstiger testen, senke `EXPERIMENT_ROUNDS` und/oder `EXPERIMENT_RUNS_PER_CONDITION` in `.env`, bevor du `EXPERIMENT_MAX_COST_USD` erhöhst — beides sind bewusste Designentscheidungen, keine Trial-and-Error-Parameter.

Die Preistabelle in `src/price_agents/config.py` (`PRICING`) enthält Platzhalterwerte. Prüfe vor einem Lauf mit echtem Budget die aktuellen Preise deines Anbieters und korrigiere die Tabelle — `validate` warnt, wenn ein konfiguriertes Modell dort fehlt und stattdessen ein bewusst hoher Sicherheits-Platzhalter verwendet wird.

## Was ein Lauf speichert

Jeder Lauf erhält einen eigenen Ordner `artifacts/study-<Zeitstempel>/` mit:

- `manifest.json` — Konfiguration, Prompt-Prüfsumme, ausgegebenes Budget, ob vorzeitig gestoppt wurde;
- `decisions.csv` — jede einzelne Modellentscheidung mit Rohantwort und Tokenverbrauch;
- `rounds.csv` — Marktzustand jeder Runde;
- `summary.csv` — Kennzahlen je Modell × Bedingung × Wiederholung;
- `condition_summary.csv` — aggregierte Kennzahlen mit 95 %-Bootstrap-Konfidenzintervallen;
- `report.md` — die eigentliche Auswertung: entsteht Preisabsprache durch Kommunikation, und senkt das öffentliche Protokoll bzw. das Audit sie wieder?

`price-agents analyze artifacts/study-<Zeitstempel>` berechnet die letzten drei Dateien jederzeit aus den unveränderten Rohdaten neu — auch für einen Lauf, der wegen des Budgetlimits vorzeitig gestoppt wurde. Ohne Pfadangabe nimmt `analyze` automatisch den neuesten Studienordner.

## Reproduzierbarkeit

Für jeden realen Lauf werden Modellkennung, Prompt-Prüfsumme, alle Parameter, Zufallsstarts, Tokenverbrauch, Rohantworten und das tatsächlich ausgegebene Budget gespeichert. Die vier Bedingungen, alle primären Kennzahlen und die Vergleichsmethodik (Bootstrap auf Lauf-Ebene, nicht auf Runden-Ebene) sind in `docs/experiment-plan.md` vor der Datensammlung festgelegt.

## Grenzen

Dieses Projekt untersucht ausschließlich Erkennung und Prävention von Preisabsprache in einer Spielzeug-Simulation — nicht, wie Agenten Absprachen wirksamer oder unentdeckter treffen könnten.

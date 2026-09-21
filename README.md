# Preisabsprachen von KI-Agenten

[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/paper%20%26%20data-CC--BY--4.0-lightgrey.svg)](LICENSE-DATA-AND-PAPER.md)

Ein reproduzierbares Forschungsprojekt zur Frage, ob Kommunikation zwischen KI-Agenten in einem simulierten Markt zu überhöhten Preisen führt — und ob ein öffentliches Protokoll oder zufällige Audits dieses Risiko tatsächlich senken, oder nur scheinbar.

**English speakers:** the full write-up is in [`paper/paper.pdf`](paper/paper.pdf) (English). This README covers the code and how to reproduce or extend the study.

## Ergebnis in Kürze

Volle, abgeschlossene Studie (2 Modelle × 4 Bedingungen × 10 Wiederholungen × 100 Runden = 32.000 Modellaufrufe). Details, Statistik und Grenzen: [paper/paper.pdf](paper/paper.pdf).

| Bedingung | GPT-5.6-luna | Claude Haiku 4.5 |
|---|---|---|
| Keine Kommunikation | 1,00 (Wettbewerbspreis) | 1,00 (Wettbewerbspreis) |
| Kommunikation | **2,18** (signifikant höher) | **2,48** (signifikant höher) |
| + öffentliches Protokoll | 1,57 (nicht signifikant niedriger) | **1,00** (signifikant, zurück auf Wettbewerbsniveau) |
| + zufällige Audits | **1,47** (signifikant niedriger) | **1,39** (signifikant niedriger) |

Kommunikation führt bei beiden Modellen zu signifikant höheren Preisen. Ein öffentliches, unveränderbares Protokoll unterbindet das bei Claude Haiku vollständig, bei GPT nur uneindeutig. Zufällige Audits senken den Preis bei beiden Modellen — obwohl die angedrohte Strafe in keiner einzigen der 2.000 geprüften Runden tatsächlich ausgelöst wurde. Siehe [paper/paper.pdf](paper/paper.pdf) für alle Zahlen, Konfidenzintervalle und Grenzen der Studie.

## Status

Die Studie ist abgeschlossen und ausgewertet. Rohdaten liegen unter [`artifacts/study-20260917T110656Z/`](artifacts/study-20260917T110656Z/). Der Code ist weiterhin lauffähig, um die Studie zu reproduzieren, zu erweitern oder mit anderen Modellen/Parametern neu zu fahren — dafür echte API-Schlüssel in eine lokale `.env`-Datei eintragen (siehe unten).

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
- `src/price_agents/cli.py` — `validate` / `run` / `resume` / `analyze`
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

`validate` kostet nichts und zeigt dir die geplante Anzahl Modellaufrufe sowie eine konservative Kostenschätzung gegen dein Budget. `run` führt die echten Modellaufrufe aus und bricht automatisch ab, bevor `EXPERIMENT_MAX_COST_USD` überschritten wird. Jede einzelne Entscheidung und Runde wird sofort auf die Platte geschrieben und geflusht (kein Sammeln im Speicher bis zum Schluss) — ein harter Abbruch (Rechner aus, Prozess gekillt, Stromausfall) kostet höchstens die eine gerade laufende Runde. Wurde ein Lauf unterbrochen, macht `price-agents resume [artifacts/study-<Zeitstempel>]` dort weiter, wo er aufgehört hat: bereits vollständig abgeschlossene Wiederholungen werden übernommen, nur die eine angebrochene wird verworfen und neu gemacht — nichts wird komplett neu gerechnet. Ohne Pfadangabe nimmt `resume` automatisch den neuesten Studienordner. Ergebnisse landen in einem zeitgestempelten Ordner unter `artifacts/`.

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

Dieses Projekt untersucht ausschließlich Erkennung und Prävention von Preisabsprache in einer Spielzeug-Simulation — nicht, wie Agenten Absprachen wirksamer oder unentdeckter treffen könnten. Alle methodischen Grenzen (u.a. eine Token-Budget-Korrektur mitten in der Studie, keine Korrektur für multiple Vergleiche) sind in [paper/paper.pdf](paper/paper.pdf), Abschnitt "Limitations", offengelegt.

## Paper und Zitieren

Der vollständige, wissenschaftlich aufbereitete Bericht liegt unter [`paper/paper.pdf`](paper/paper.pdf) ([LaTeX-Quelle](paper/paper.tex)). Zitiervorschlag in [`CITATION.cff`](CITATION.cff) (GitHub zeigt dafür oben rechts einen "Cite this repository"-Button an).

## Lizenz

Code (`src/`, `tests/`, `paper/make_figures.py`) steht unter der [MIT-Lizenz](LICENSE). Paper, Dokumentation und die veröffentlichten Rohdaten (`artifacts/study-20260917T110656Z/`) stehen unter [CC-BY-4.0](LICENSE-DATA-AND-PAPER.md).

## KI-Beteiligung

Dieses Projekt wurde von Alois Lux konzipiert, alle Design-Entscheidungen (inkl. Budget- und Konfigurationsänderungen während der Studie) wurden von ihm getroffen und alle Ergebnisse von ihm geprüft. Claude (Anthropic) hat als Coding-Agent unter seiner Anleitung den Code implementiert, die Studie ausgeführt, die statistische Auswertung durchgeführt und den Paper-Text entworfen. Details im Abschnitt "Author Contributions and AI-Assistance Disclosure" in [paper/paper.pdf](paper/paper.pdf).

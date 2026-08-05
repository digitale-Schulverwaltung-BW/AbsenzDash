# AbsenzDash — Projektkonventionen

## Workflow

- **Immer Subagents verwenden** für Implementierungsarbeit (z.B. `superpowers:subagent-driven-development` bei der Ausführung von Umsetzungsplänen) — nicht inline im Hauptkontext arbeiten.
- **keine Git-Worktrees anlegen** für Implementierungsarbeit (z.B. per `superpowers:using-git-worktrees`), subagents haben damit immer Probleme.
- **Nach Abschluss jeder Phase/jedes Plans sofort committen.** Sobald ein Git-Remote eingerichtet ist, zusätzlich sofort pushen.
- **User-/Admin-relevante Informationen sofort dokumentieren.** Gehört es ins README (Projektüberblick, Schnellstart), dort; alles andere (Setup-Schritte, Konfigurationsoptionen, Betriebs-/Admin-Hinweise) in eine passende Datei unter `docs/` (z.B. `docs/deployment.md`, `docs/admin-guide.md`) — nicht nur in Commit-Messages oder Code-Kommentaren.

## Kontext

- [SPECS.md](SPECS.md) — fachliche Spezifikation.
- [TECH-SPEC.md](TECH-SPEC.md) — Datenmodell, API-Vertrag, WebUntis-Feldmapping; gegen die reale WebUntis-Instanz der Schule validiert (siehe dort Abschnitt 5).
- [ROADMAP.md](ROADMAP.md) — Fortschritts-Tracker: welcher Plan deckt welchen Teil von SPECS.md ab, was ist noch offen. Nach jedem abgeschlossenen Plan aktualisieren.

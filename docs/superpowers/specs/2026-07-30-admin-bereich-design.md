# Design: Admin-Bereich (Schwellwert-Regeln, Maßnahmen-Katalog, Entschuldigungsstatus, Sync-Einstellungen)

Stand: 2026-07-30

Deckt Roadmap-Punkt 1 (Excuse-Status-Admin-Pflege) und Punkt 2 (Admin-Bereich) gebündelt in einem Plan ab. Beide sind Dashboard-UI über bereits bestehenden Backend-Endpunkten (`GET/PUT /admin/threshold-rules`, `/admin/measure-types`, `/admin/excuse-statuses`, `/admin/sync-settings`, `POST /admin/sync-now`, alle seit Plan 6, nur Rolle `schulleitung`).

## Ausgangslage / Bug

Aktuell zeigen alle Fehlzeiten in Schülerliste/-Detail `--` als Entschuldigungsstatus. Ursache: `excuse_status` erhielt bei Einführung (Migration `d9aba588fce8`) nur das Schema, keine Seed-Daten — anders als `massnahmen_typ`/`schwellwert_regel` (Migration `ecbb0df17a38`). Der Namensabgleich in `webuntis_fehlzeit_sync.py` (`excuse_status_id_by_name`) läuft damit gegen eine leere Tabelle und liefert für jede Fehlzeit `excuse_status_id = NULL`.

## Navigation & Zugriff

Ein neuer Nav-Eintrag "Admin", ausschließlich für Rolle `schulleitung` sichtbar (kein Teilzugriff für Klassenlehrkraft/Bereichsleiter — bewusst monolithisch für den ersten Wurf, spätere partielle Freigabe z.B. der Schwellwert-Regeln für Bereichsleiter ist eine separate spätere Entscheidung). Darunter vier Unterseiten/Tabs:

1. Schwellwert-Regeln
2. Maßnahmen-Katalog
3. Entschuldigungsstatus
4. Sync-Einstellungen

## 1. Entschuldigungsstatus-Sync-Fix (Backend)

`webuntis_fehlzeit_sync.py` legt beim Sync für jeden bisher unbekannten `excuseStatus`-String automatisch eine neue `excuse_status`-Zeile an (`name` = WebUntis-String, `zaehlt_als_entschuldigt = false` als sicherer Default, kein `long_name`/`aktiv`-Feld mehr, siehe unten), statt weiterhin `excuse_status_id = NULL` zu importieren. Grund für den unexcused-Default: das `Entschuldigung zählt`-Flag ist über keine WebUntis-JSON-RPC-Methode abrufbar (Plan-2-Spike, 6 Kandidaten-Methoden alle `Method not found`) — ein Mensch muss es zwangsläufig bestätigen, "unentschuldigt" ist die sicherere Annahme für die Eskalations-Zählung.

Kein automatisches Deaktivieren/Löschen von Status, die in einem Sync-Lauf nicht mehr auftauchen: da es keine API gibt, um die tatsächlich in WebUntis konfigurierte Statusliste abzufragen, lässt sich "nicht in diesem Lauf gesehen" nicht von "wurde in WebUntis entfernt" unterscheiden (kann auch schlicht heißen: niemand hatte in diesem Zeitraum diesen Status). Ungenutzte Einträge bleiben daher einfach bestehen — harmlos, manueller DB-Eingriff im Bedarfsfall.

## 2. Entschuldigungsstatus-Admin-Seite (Frontend)

Bewusst kein volles CRUD: `excuse_status.name` kommt aus WebUntis und darf nicht editierbar sein (würde sonst den Namensabgleich beim nächsten Sync brechen). Kein `long_name`-Feld (nicht befüllbar, da WebUntis nur den Kurznamen liefert). Kein `aktiv`-Flag (kein aktueller Verwendungszweck — es gibt noch keine Erfassungs-Dropdowns im Frontend, die danach filtern würden). Kein Löschen (siehe Stale-Handling oben).

Stattdessen: reine Liste aller `excuse_status`-Einträge, pro Zeile eine Checkbox "entschuldigt" (bindet an `zaehlt_als_entschuldigt`), Speichern per bestehendem `PUT /admin/excuse-statuses`.

**Migrationshinweis:** `long_name`/`aktiv`-Spalten in `excuse_status` bleiben im Schema bestehen (kein Breaking Change, einfach ungenutzt/immer `NULL`/`true`) — Aufräumen dieser Spalten ist kein Teil dieses Plans.

## 3. Schwellwert-Regeln-Admin-Seite

CRUD auf `schwellwert_regel` inkl. verschachtelter `schwellwert_stufe`-Liste (Stufe hinzufügen/entfernen, je mit `schwellenwert`, `einheit`/`fehlzeiten_filter` nur bei Typ `fehlzeiten`, Mehrfachauswahl `empfaenger_rollen`).

**Geltungsbereich-Auswahl in der UI beschränkt auf `schulweit` und `abteilung`** — keine `klasse`-Option. Begründung: die produktiv geseedete Default-Konfiguration (Migration `ecbb0df17a38`) enthält ausschließlich schulweite Regeln, klassenspezifische Regeln wurden bisher nie genutzt, und SPECS.md §4 begründet den Differenzierungsbedarf ohnehin mit "Klassenstufe/Schulart" — das deckt sich mit der Abteilungs-Ebene, nicht mit einzelnen Klassen. Das Datenmodell und `resolve_schwellwert_regel` (Precedence klassen- > abteilungs- > schulweit) bleiben unverändert; eine klassenspezifische Regel lässt sich bei Bedarf weiterhin per Migration nachziehen, ist nur in dieser Admin-UI nicht anlegbar.

Validierung: höchstens eine spezifische (nicht-schulweite) Regel pro Typ+Abteilung — analog zur bestehenden Backend-Validierung/den Partial-Unique-Indizes.

Löschen: folgt dem bestehenden `409`-bei-Referenzierung-Muster.

## 4. Maßnahmen-Katalog-Admin-Seite

CRUD auf `massnahmen_typ`: Name, `aktiv`, `setzt_zaehler_zurueck` (einfacher Boolean).

**Backend-Vereinfachung (Breaking Change gegenüber Plan 3):** die `massnahmen_typ_regel`-Verknüpfungstabelle entfällt komplett. Bisher musste ein zurücksetzender Maßnahmen-Typ explizit mit den betroffenen `schwellwert_regel`-Zeilen verknüpft werden, was die dokumentierte "Admin-Falle" erzeugte (Verknüpfung nur mit der schulweiten Regel setzt bei spezifischerer Regel still keinen Zähler zurück). Neue Logik: `setzt_zaehler_zurueck=true` setzt **beide** `schueler_zaehlerstand`-Zeilen des betroffenen Schülers zurück (`fehlzeiten` und `klassenbuch`), unabhängig von einer Regel-Zuordnung.

Fachliche Begründung (User): eine protokollierte Maßnahme ist immer an ein Gespräch mit klarer pädagogischer Ansage gekoppelt — die Schwere der Reaktion auf erneutes Fehlverhalten (gleich welcher Art) wird organisatorisch über die Wahl des Maßnahmen-Typs gesteuert, nicht über eine technische Unterscheidung zwischen Fehlzeiten- und Klassenbuch-Zähler. Eine Maßnahme, die nur einen der beiden Zähler zurücksetzt, hätte sonst zur Folge, dass z.B. ein wegen Fehlzeiten nachsitzender Schüler am Folgetag für einen unabhängigen Klassenbuch-Eintrag sofort erneut eskaliert wird — unverhältnismäßig.

Erfordert: Migration zum Entfernen von `massnahmen_typ_regel`, Anpassung der Reset-Logik in `eskalations_pruefung.py`/`massnahme_service.py` (genauer Pfad im Umsetzungsplan zu verifizieren), Nachziehen von SPECS.md §4 (aktuell: "betroffene Eskalationsstufe/Regel(n)" → wird zu "setzt bei Auslösung beide Zähler des Schülers zurück, ohne Regel-Bezug").

Löschen: folgt dem bestehenden `409`-bei-Referenzierung-Muster.

## 5. Sync-Einstellungen-Admin-Seite

`sync_interval_cron` editierbar (Cron-Ausdruck). Schuljahresbeginn (`schuljahr_start_cache`) und letzter Sync-Zeitpunkt (`letzter_sync_am`) nur angezeigt, nicht editierbar (automatisch aus WebUntis bzw. Sync-Lauf befüllt). Button "Sync jetzt ausführen" ruft `POST /admin/sync-now` auf (synchroner Einzelversuch, bestehendes Verhalten seit Plan 6).

## Nicht-Ziele dieses Plans

- Keine partielle Rollenfreigabe des Admin-Bereichs (z.B. Schwellwert-Regeln auch für Bereichsleiter) — spätere separate Entscheidung.
- Keine Klassen-Ebene in der Schwellwert-Regeln-UI.
- Kein Aufräumen der jetzt ungenutzten `long_name`/`aktiv`-Spalten in `excuse_status`.
- Keine automatische Erkennung/Deaktivierung von in WebUntis entfernten Entschuldigungsstatus.

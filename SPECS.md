# AbsenzDash — Spezifikation

Stand: 2026-07-23

## 1. Ziel

Ein Intranet-Dashboard mit E-Mail-Benachrichtigungsfunktion für Klassenlehrkräfte, Bereichsleiter und Schulleitung, das Schüler-Fehlzeiten und Klassenbucheinträge aus WebUntis abruft, aufbereitet und darstellt. Konfigurierbare, mehrstufige Schwellwerte lösen E-Mail-Benachrichtigungen aus. Protokollierte Maßnahmen (z.B. Gespräch, Elterngespräch, Nachsitzen, Maßnahmen nach §90, Bußgeld) können die Schwellwert-Zähler eines Schülers zurücksetzen. Einzelne Schüler können befristet oder unbefristet von Benachrichtigungen einer bestimmten Kategorie ausgenommen werden (z.B. bei ärztlichem Attest).

Referenzprojekt: [VertretungsFlow](https://github.com/digitale-Schulverwaltung-BW/VertretungsFlow) (Lehrer-Vertretungsplanung, gleiche Schule) — dort wurde bereits WebUntis für Stundenplan-Abfragen und eine WordPress-Plugin-Architektur mit LDAP/AD-Anbindung genutzt. AbsenzDash übernimmt dieses Architekturmuster, greift aber zusätzlich auf WebUntis-Fehlzeiten- und Klassenbuch-Endpunkte zu, die VertretungsFlow bisher nicht nutzt.

## 2. Architektur

- **Frontend:** React/TypeScript-SPA, verpackt als WordPress-Plugin (Shortcode-Einbindung in eine bestehende WP-Instanz im Schulintranet), analog VertretungsFlow. Enthält den Admin-Bereich für die fachliche Konfiguration (Schwellwerte, Maßnahmen-Katalog, Sync-Intervall, siehe Abschnitt 7).
- **Frontend-Admin (WP-Backend):** Im Admin-Backend von WordPress werden ausschließlich organisatorische Grundeinstellungen gepflegt: Zuordnung Nutzer → Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung) samt WebUntis-Kürzel, sowie die Bereichsdefinition (welche Klassen gehören zu welchem Bereich, wer ist Bereichsleiter). Die Klassenlehrkraft-Zuordnung selbst kommt vollständig aus WebUntis (bis zu zwei Klassenlehrkräfte je Klasse, `teacher1`/`teacher2`, siehe TECH-SPEC.md Abschnitt 1.2) — eine manuelle Zusatz-Zuordnung darüber hinaus wird bewusst nicht angeboten (Umsetzungsentscheidung Roadmap-Punkt 1, siehe dortiges Design-Dok). Keine fachliche Konfiguration (Schwellwerte etc.) hier.
- **Backend:** Eigener API-Server im Schul-Intranet (Empfehlung: Python/FastAPI wie im Referenzprojekt), kein öffentlich (Internet) erreichbares API.
- **Datenbank:** Relational (Empfehlung: PostgreSQL). Speichert: WebUntis-Datencache (Fehlzeiten, Klassenbucheinträge), Bereichsdefinition, Schwellwert-Konfiguration, Maßnahmen-Katalog und -Einträge, Ausnahmen, Audit-Log.
- **Auth:** WordPress-Benutzerverwaltung, kann WP-lokal sein oder eine LDAP/AD-Anbindung (wie VertretungsFlow). Rollenverteilung erfolgt im WordPress-Plugin-Backend, das Rolle und Zuständigkeitsbereich je Nutzer an das API-Backend übergibt (gemeinsames Secret zur Absicherung der Frontend-Backend-Kommunikation, analog VertretungsFlow).
- **WebUntis-Anbindung:** Ein zentraler WebUntis-Service-Account ruft Fehlzeiten und Klassenbucheinträge für die gesamte Schule ab. Abruf- und Prüfintervall (Sync + Schwellwert-Auswertung) ist als Einstellung konfigurierbar (z.B. Cron-Ausdruck), von der Schulleitung/Admin im Admin-Bereich änderbar.
- **Deployment:** Ausschließlich innerhalb des Schul-Intranets, kein Internet-Zugriff auf das Backend.

## 3. Rollen & Rechte

Dreistufige Hierarchie:

| Rolle              | Zugriff                                                                                                                                                                                                                                                                                                    |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Klassenlehrkraft   | Eigene Klasse(n): Fehlzeiten, Klassenbucheinträge, Maßnahmen erfassen, Ausnahmen setzen/aufheben. Zuordnung wird aus WebUntis geseedet (Klassenlehrkraft-Stammdatum je Klasse), im WP-Backend um weitere Personen ergänzbar (z.B. Co-Klassenlehrkraft, Vertretung).                                        |
| Bereichsleiter     | Alle Klassen des zugeordneten Bereichs (mehrere Klassen), mit denselben Bearbeitungsrechten wie eine Klassenlehrkraft (Maßnahmen erfassen, Ausnahmen setzen/aufheben) für alle Schüler des Bereichs. Bereichsdefinition (Klassen ↔ Bereich, Bereich ↔ Bereichsleiter) wird manuell im WP-Backend gepflegt. |
| Schulleitung/Admin | Alle Klassen; zusätzlich: Schwellwert-Regeln verwalten, Maßnahmen-Katalog pflegen, Sync-Intervall konfigurieren (im Dashboard-Admin-Bereich, siehe Abschnitt 7).                                                                                                                                           |

Alle drei Rollen können als zusätzliche Empfänger einer Eskalationsstufe konfiguriert werden (siehe Abschnitt 4/6).

## 4. Datenmodell (fachlich)

- **Schüler**: Stammdaten aus WebUntis (Name, Klasse), lokal referenziert über WebUntis-ID. Die Klassenzuordnung wird technisch aufwändiger ermittelt als andere Stammdaten und läuft daher über einen separaten, selteneren Hintergrund-Abgleich (siehe TECH-SPEC.md Abschnitt 1.3) statt bei jedem regulären Sync — ein neu angelegter Schüler kann daher bis zu 24 Stunden ohne Klassenzuordnung im Dashboard erscheinen.
- **Klassen:** Stammdaten aus WebUntis (Name, Klassenlehrkräfte), lokal referenziert über WebUntis-ID. Die WebUntis-Klassenlehrkraft-Angabe seedet die Zuordnung aus Abschnitt 3; im WP-Backend können weitere Personen ergänzt werden.
- **Bereiche**: lokal (nicht aus WebUntis) im WP-Backend gepflegte Gruppierung von Klassen, inkl. Zuordnung der/des Bereichsleiter(s).
- **Fehlzeiten-Einträge**: aus WebUntis synchronisiert; Status (entschuldigt/unentschuldigt), Dauer (Tag oder Einzelstunden), Zeitraum.
- **Klassenbucheinträge**: aus WebUntis synchronisiert (z.B. Verspätung, Verhaltenshinweis).
- **Schwellwert-Regeln**: getrennt konfigurierbar für (a) Fehlzeiten und (b) Klassenbucheinträge. Je Regel:
  - Geltungsbereich: schulweit (Default/Fallback) oder differenziert nach Klassenstufe/Schulart. Präzedenz: eine spezifische (nicht-schulweite) Regel bricht für die betroffenen Schüler die schulweite Regel; pro Klassenstufe/Schulart und Regel-Typ darf nur eine spezifische Regel aktiv sein (bei der Regel-Anlage im Admin-Bereich validiert, um überlappende spezifische Regeln zu verhindern).
  - Mehrere Eskalationsstufen (Stufe 1, 2, 3, …), je Stufe:
    - Einheit: Fehltage **oder** Fehlstunden (bei Fehlzeiten-Regeln).
    - Schwellenwert (Zahl).
    - Fehlzeiten-Filter: nur unentschuldigt / alle (entschuldigt + unentschuldigt), konfigurierbar je Regel.
    - Empfänger: Klassenlehrkraft (bzw. bei Bereichsleiter-Bearbeitung: Bereichsleiter) immer zusätzlich zu ggf. konfigurierten weiteren Empfängern dieser Stufe (Bereichsleiter und/oder Schulleitung, z.B. Bereichsleiter ab Stufe 2, Schulleitung ab Stufe 3).
  - Zähler pro Schüler und Regel läuft ab Schuljahresbeginn bzw. ab letztem Reset (siehe Maßnahmen). Das Schuljahresbeginn-Datum ist bundeslandabhängig und jahresabhängig unterschiedlich; statt einer manuellen Pflege wird es automatisch aus WebUntis übernommen (WebUntis führt Schuljahre bereits als eigene Stammdaten, siehe TECH-SPEC.md Abschnitt 1.3a) — kein jährlicher Pflegeaufwand nötig.
- **Maßnahmen-Katalog**: von der Schulleitung/Admin konfigurierbar. Je Maßnahmen-Typ: Name, Flag "setzt Schwellwert-Zähler zurück" (ja/nein), betroffene Eskalationsstufe/Regel(n). Default Maßnahmen-Set, das bei Installation mit ausgeliefert wird (von Schulleitung/Admin änderbar: Gespräch, Elterngespräch, Nachsitzen, 4h Nachsitzen, Schulverweis, Bußgeld, Zwangsgeld)
- **Maßnahmen-Einträge**: pro Schüler protokolliert — Typ (aus Katalog), Datum, Notiz, erfassende Lehrkraft. Ein als zurücksetzend markierter Maßnahmen-Typ setzt den/die betroffenen Zähler auf 0 bzw. auf die konfigurierte Ausgangsstufe zurück.
- **Ausnahmen**: pro Schüler und Kategorie (Fehlzeiten und/oder Klassenbuch getrennt abschaltbar). Enthält Grund/Notiz und optionales Enddatum — mit Enddatum greifen die Schwellwerte danach automatisch wieder, ohne Enddatum gilt die Ausnahme bis zur manuellen Aufhebung.
- **Benachrichtigungen (Log)**: pro ausgelöster Schwellwertstufe protokolliert — Schüler, Regel, Stufe, Zeitpunkt, tatsächliche Empfänger (Rolle + Person), oder Status „kein Empfänger ermittelbar“ bzw. „aus initialem Datenimport übernommen, keine E-Mail versendet“ (siehe Abschnitt 5.1). Grundlage für die Badge-/Flyout-Anzeige im Dashboard (Abschnitt 7).
- **Audit-Log**: erfasst, welcher Nutzer wann welche Maßnahme oder Ausnahme angelegt, geändert oder entfernt hat.

## 5. Eskalationslogik

Kombination aus zwei Mechanismen:

1. **Mehrstufige Schwellwerte**: Jede Regel hat mehrere Stufen mit steigenden Schwellenwerten (z.B. Stufe 1 ab 4 Fehltagen → Benachrichtigung Klassenlehrkraft, Stufe 2 ab 8 Fehltagen → zusätzlich Bereichsleiter, Stufe 3 → zusätzlich Schulleitung).
2. **Reset durch Maßnahmen**: Wird eine als zurücksetzend markierte Maßnahme protokolliert, wird der betroffene Zähler zurückgesetzt (z.B. auf 0 oder auf Stufe 1), sodass der nächste Schwellwert erst wieder ab dann erneut erreicht werden muss (Beispiel aus der Anforderung: erste Benachrichtigung ab 4 Fehltagen, Nachsitzen verhängt → Zähler auf 0, nächste Benachrichtigung erst wieder ab 4 weiteren Fehltagen).

Schüler mit aktiver Ausnahme in der jeweiligen Kategorie (Fehlzeiten bzw. Klassenbuch) werden bei der Schwellwert-Prüfung dieser Kategorie übersprungen.

**Schuljahreswechsel:** Beim Erreichen des konfigurierten Schuljahresbeginn-Datums (Abschnitt 4) werden alle Zähler zurückgesetzt, unabhängig von Maßnahmen. Wechselt ein Schüler während des Schuljahres die Klasse (Versetzung), bleibt sein bisheriger Zählerstand erhalten; ab dem Wechsel wird die für die neue Klasse zutreffende Regel angewendet (Geltungsbereich-Präzedenz siehe Abschnitt 4).

### 5.1 Initialer Datenimport

Der allererste Sync-Lauf (Rollout, ggf. mitten im laufenden Schuljahr) liest und zählt alle vorhandenen Fehlzeiten/Klassenbucheinträge des laufenden Schuljahres wie gewohnt und berechnet so den korrekten Zählerstand bzw. die korrekte Eskalationsstufe pro Schüler. Dabei werden aber **keine echten E-Mails verschickt**: bereits erreichte Stufen werden im Benachrichtigungs-Log als „aus initialem Datenimport übernommen“ markiert, damit der erste reguläre Folge-Lauf nicht sofort einen Benachrichtigungs-Schwall auslöst. Ab dem zweiten Sync-Lauf laufen Benachrichtigungen normal.

## 6. E-Mail-Benachrichtigungen

- Ausgelöst bei jeder Sync-/Prüfrunde, wenn ein Schüler eine Schwellwertstufe **neu** erreicht (keine wiederholte Benachrichtigung bei unverändertem Zählerstand).
- Inhalt: Schülername, Klasse, ausgelöste Regel und Stufe, aktueller Zähler-Stand, Link zum Schüler-Detail im Dashboard.
- Empfänger: Klassenlehrkraft plus ggf. Bereichsleiter/Schulleitung je nach Stufe, siehe Schwellwert-Regel (Abschnitt 4/5).
- Kann für eine erreichte Stufe kein Empfänger ermittelt werden (z.B. weil die laut WebUntis zuständige Klassenlehrkraft sich noch nie im Dashboard angemeldet hat), wird **keine** E-Mail versendet (auch nicht ersatzweise an Schulleitung) — der Fall bleibt aber im Benachrichtigungs-Log sichtbar und wird im Dashboard hervorgehoben (Abschnitt 7).

## 7. Dashboard-Funktionen

- **Übersicht** (rollenabhängig gefiltert): Liste der Schüler mit aktuellem Status je Regel (Ampel/Badge bei erreichter Stufe), Filter nach Klasse/Stufe/Status. Zusätzlich ein „Benachrichtigt“-Badge pro Schüler mit Hover-/Flyout-Detail (an wen wann eine Benachrichtigung ging, bzw. „kein Empfänger ermittelbar“ oder „aus initialem Import“, siehe Abschnitt 4/5.1). Für Schulleitung/Bereichsleitung zusätzlich hervorgehoben: Fälle, in denen seit der letzten Benachrichtigung keine Maßnahme erfasst wurde.
- **Schüler-Detail**: Fehlzeiten-Verlauf, Klassenbucheinträge, Maßnahmen-Historie, aktive Ausnahmen, Benachrichtigungs-Historie; Formulare zum Erfassen neuer Maßnahmen und zum Setzen/Aufheben von Ausnahmen.
- **Admin-Bereich** (nur Schulleitung/Admin): Schwellwert-Regeln verwalten, Maßnahmen-Katalog pflegen, Sync-/Prüfintervall konfigurieren (aktuelles Schuljahr wird informativ angezeigt, automatisch aus WebUntis übernommen, nicht editierbar), manueller „Sync jetzt ausführen“-Button (löst einen außerplanmäßigen WebUntis-Sync + Schwellwert-Prüfung aus, z.B. damit eine geänderte Regel sofort statt erst beim nächsten geplanten Lauf wirksam wird).
- **Export**: PDF/Druckansicht pro Schüler mit Fehlzeiten- und Maßnahmen-Historie, z.B. für §90-Meldungen an das Schulamt oder Bußgeldverfahren.

## 8. Datenschutz & Historie

- Aufbewahrung der Daten mindestens bis Schuljahresende bzw. bis Schulabschluss des Schülers; danach Löschung/Archivierung möglich.
- Audit-Log für Änderungen an Maßnahmen und Ausnahmen (siehe Abschnitt 4).
- Kein Internet-Zugriff auf das Backend; Kommunikation ausschließlich innerhalb des Schul-Intranets.
- Diese Auswertungen bestehen fachlich bereits (z.B. manuell in WebUntis) und sind zur gesetzeskonformen Erfüllung des Erziehungs- und Bildungsauftrags erforderlich. AbsenzDash automatisiert diese Auswertung lediglich; dennoch sollte die neue automatisierte Verarbeitung als organisatorischer Schritt (nicht Teil dieser technischen Spezifikation) in das Verfahrensverzeichnis der Schule (Art. 30 DSGVO) aufgenommen werden.

## 9. Nicht-Ziele (explizit außerhalb des Scopes)

- Kein direkter E-Mail-Versand an Eltern — Benachrichtigungen gehen ausschließlich an schulinterne Rollen (Klassenlehrkraft, Bereichsleiter, Schulleitung).
- Kein öffentliches/externes API.
- Keine eigene Passwortverwaltung — Authentifizierung läuft über WordPress/LDAP.

## 10. Offene technische Entscheidungen

Das Grundmuster (React/TS-SPA im WP-Plugin + eigenes API-Backend + eigene Datenbank, analog VertretungsFlow) ist gesetzt. Konkrete Technologiewahl für Backend-Framework und Datenbank (Empfehlung: Python/FastAPI + PostgreSQL, wie im Referenzprojekt) ist im Rahmen der technischen Umsetzungsplanung final zu bestätigen, insbesondere im Hinblick auf wiederverwendbaren Code aus VertretungsFlow (z.B. WebUntis-Anbindung, LDAP-Service, WordPress-Proxy-Mechanismus).

# Backend: REST-API fürs WP-Plugin — PDF-Export — Design

Stand: 2026-07-27. Aufbauend auf Plan 5 (Kern-Endpunkte, `get_scoped_schueler`, `student_query.load_student_detail`) und Plan 6 (Admin-Konfiguration, abgeschlossen). Referenz: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 3 (API-Vertrag, `GET /students/{id}/export.pdf`), Abschnitt 2 (Datenmodell, insbesondere `schueler`/ASV-BW-CSV-Herkunft); [SPECS.md](../../../SPECS.md) Abschnitt 7 ("Export: PDF/Druckansicht pro Schüler mit Fehlzeiten- und Maßnahmen-Historie, z.B. für §90-Meldungen an das Schulamt oder Bußgeldverfahren").

## Ziel

Den letzten in TECH-SPEC.md Abschnitt 3 offenen Backend-Endpunkt umsetzen: `GET /students/{id}/export.pdf`. Liefert ein PDF mit wählbaren Abschnitten aus der Schüler-Detailansicht (Fehlzeiten, Klassenbuch, Maßnahmen, Ausnahmen, Benachrichtigungen), gedacht für unterschiedliche Verwendungszwecke (Elterngespräch = alles, Bußgeldverfahren = nur Fehlzeiten, Einzelfall = zusätzlich Ausnahmen).

## Scope-Einordnung

Letzter offener Punkt aus Gruppe 3 der Scope-Einordnung von Plan 5 (siehe dortiges Design-Dokument und [2026-07-27-admin-konfiguration-design.md](2026-07-27-admin-konfiguration-design.md) Abschnitt "Scope-Einordnung").

## Datenquelle

Schüler-Stammdaten (`vorname`, `nachname`, `klasse_id`) kommen wie bei allen bestehenden Endpunkten aus der `schueler`-Tabelle, gecacht aus dem ASV-BW-CSV-Import (TECH-SPEC.md Abschnitt 1.3/2). Keine zusätzlichen Stammdaten (Geburtsdatum, Adresse) verfügbar oder für diesen Export vorgesehen — nur was bereits im Schüler-Detail (`GET /students/{id}`) sichtbar ist. Kein zusätzlicher WebUntis- oder CSV-Zugriff nötig; der Export liest ausschließlich aus der bestehenden DB, genau wie `GET /students/{id}`.

## Konfigurierbare Abschnitte

Query-Parameter `sections` (komma-separierte Liste), gültige Werte: `fehlzeiten`, `klassenbuch`, `massnahmen`, `ausnahmen`, `benachrichtigungen`. Kein Parameter oder leerer String ⇒ alle fünf (Default = vollständige Detailansicht als Druckversion). Unbekannter Wert ⇒ `422`.

```
GET /students/42/export.pdf                              → alle fünf Abschnitte
GET /students/42/export.pdf?sections=fehlzeiten           → Bußgeldverfahren
GET /students/42/export.pdf?sections=fehlzeiten,ausnahmen → Einzelfall mit Attest-Kontext
```

## Architektur & Modulstruktur

Neue/geänderte Module in `backend/app/`:

```
app/
  api/
    routes/
      students.py                # + GET /{schueler_id}/export.pdf
  services/
    student_query.py             # + load_excuse_status_map, load_classreg_category_map
    export_service.py            # neu: HTML-Rendering + PDF-Konvertierung + Dateinamen-Normalisierung
  templates/
    export_pdf.html              # neu: Jinja2-Template inkl. eingebettetem CSS
```

`backend/requirements.txt`: `+ weasyprint>=62,<63` (oder aktuelle Major-Version zum Umsetzungszeitpunkt). Dockerfile: System-Pakete für Pango/Cairo/GDK-Pixbuf ergänzen (WeasyPrint-Laufzeitabhängigkeiten), unkritisch im ohnehin containerisierten Deployment (TECH-SPEC.md Abschnitt 6, Docker-Compose-Setup).

### Namensauflösung (neu, bisher in keinem Endpunkt vorhanden)

`FehlzeitOut.excuse_status_id` und `KlassenbuchEintragOut.kategorie_id` werden aktuell nirgends auf Klartext aufgelöst. Für ein amtstaugliches PDF (§90-Meldungen etc.) werden zwei neue Batch-Loader in `student_query.py` ergänzt, analog zu `load_regel_typ_map`:

```python
async def load_excuse_status_map(db: AsyncSession, excuse_status_ids: list[int]) -> dict[int, ExcuseStatus]: ...
async def load_classreg_category_map(db: AsyncSession, kategorie_ids: list[int]) -> dict[int, ClassregCategory]: ...
```

Verwendet `name`/`long_name` aus `excuse_status`/`classreg_category` (bevorzugt `long_name`, Fallback `name`, falls `long_name` `NULL` ist).

### `export_service.py`

```python
async def render_student_export_html(db: AsyncSession, schueler: Schueler, klasse: Klasse | None, sections: set[str]) -> str:
    """Laedt Detaildaten + Namens-Maps, rendert das Jinja2-Template zu HTML."""

def html_to_pdf(html: str) -> bytes:
    """Duenner Wrapper um WeasyPrint, isoliert fuer Testbarkeit (HTML-Assertions ohne PDF-Parsing)."""

def build_export_filename(nachname: str, vorname: str) -> str:
    """Normalisiert Umlaute/Diakritika/Sonderzeichen fuer sicheren Content-Disposition-Dateinamen."""
```

Trennung von HTML-Rendering und PDF-Konvertierung erlaubt, in Tests die HTML-Ausgabe direkt auf Inhalt zu prüfen (z.B. "Abschnitt X fehlt bei `sections=fehlzeiten`") statt PDF-Bytes zu parsen.

`render_student_export_html` nutzt die bestehende `student_query.load_student_detail(db, schueler.id)` unverändert (liefert bereits alle fünf Unterlisten inkl. Massnahmen-Typ-/Nutzer-Namen) und filtert danach in Python auf die angeforderten `sections`.

### Dateinamen-Normalisierung

Deutsche Umlaute explizit gemappt (ä→ae, ö→oe, ü→ue, Ä→Ae, Ö→Oe, Ü→Ue, ß→ss), alles andere über Unicode-NFKD-Normalisierung auf Basis-Buchstaben reduziert (z.B. é→e), verbleibende Nicht-ASCII-/Sonderzeichen durch `-` ersetzt:

```python
import unicodedata

_UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})

def build_export_filename(nachname: str, vorname: str) -> str:
    raw = f"{nachname}_{vorname}_export".translate(_UMLAUT_MAP)
    ascii_normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9_]+", "-", ascii_normalized).strip("-") + ".pdf"
```

### Route (`students.py`)

```python
_EXPORT_SECTIONS = {"fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"}

@router.get("/{schueler_id}/export.pdf")
async def export_student_pdf(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sections: str | None = Query(None),
) -> Response:
    if sections:
        requested = {s.strip().lower() for s in sections.split(",") if s.strip()}
        unknown = requested - _EXPORT_SECTIONS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown sections: {sorted(unknown)}")
    else:
        requested = set(_EXPORT_SECTIONS)

    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    html = await export_service.render_student_export_html(db, schueler, klasse, requested)
    pdf_bytes = export_service.html_to_pdf(html)

    db.add(AuditLog(
        user_id=nutzer.id,
        aktion="export_pdf",
        resource_typ="schueler",
        resource_id=str(schueler.id),
        details={"sections": sorted(requested)},
    ))
    await db.commit()

    filename = export_service.build_export_filename(schueler.nachname, schueler.vorname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Scope/404 laufen automatisch über `get_scoped_schueler` (identisch zu `GET /students/{id}`), keine Sonderbehandlung nötig.

### PDF-Inhalt (Template)

- **Kopfbereich** (immer): Vorname, Nachname, Klasse, Erstellungszeitpunkt des Exports, Titel passend zu den gewählten Abschnitten.
- **Pro Abschnitt** eine Tabelle:
  - Fehlzeiten: Datum, Typ (Tag/Stunde), Fach, Entschuldigungsstatus (Klartext), Grund-Text
  - Klassenbuch: Datum, Kategorie (Klartext), Text
  - Maßnahmen: Datum, Typ, Notiz, erfasst von
  - Ausnahmen: Kategorie, Grund, gültig bis (nur aktive, wie bereits von `load_student_detail` geliefert)
  - Benachrichtigungen: Regel-Typ, Stufe, Zeitpunkt, Empfänger, Status
- Sortierung wie in den bestehenden Schemas (`datum.desc()` / `gesendet_am.desc()`).
- Fehlender/leerer Abschnitt: Tabelle entfällt komplett (kein "keine Einträge"-Platzhaltertext nötig für MVP).

## Fehlerbehandlung

Kein zusätzliches `try/except` um `html_to_pdf()` — WeasyPrint-Fehler bei validen, aus der DB stammenden Daten sind nicht erwartbar; ein Rendering-Bug soll als echter `500` sichtbar werden, nicht stillschweigend verschluckt werden.

## Tests

- **Unit:** `build_export_filename` — Umlaute, Diakritika (z.B. `é`), sonstige Sonderzeichen, Leerzeichen.
- **Integration** (`backend/tests/`, analog bestehendem Muster für `students.py`-Endpunkte):
  - Default-Aufruf → `200`, `content-type: application/pdf`, PDF-Magic-Bytes (`%PDF`).
  - `render_student_export_html` direkt getestet (ohne PDF-Konvertierung) für Section-Filterung: `sections=fehlzeiten` enthält keine Maßnahmen-/Klassenbuch-Marker im HTML.
  - Unbekannter `sections`-Wert → `422`.
  - Scope-Verletzung (fremder Schüler) → `404`, wie bei bestehendem `get_scoped_schueler`.
  - Audit-Log-Eintrag mit `aktion="export_pdf"` wird geschrieben.
  - Namensauflösung: Fehlzeit mit gesetztem `excuse_status_id` → Klartext-Name im HTML; Klassenbuch-Eintrag mit `kategorie_id` → Klartext-Kategorie im HTML.

## Bewusst nicht enthalten

- Zeitraum-Filter (von/bis) — immer die komplette Historie, wie bei `GET /students/{id}` auch.
- Zusätzliche Stammdaten (Geburtsdatum, Adresse) — nicht in `schueler` vorhanden, kein Teil dieses Plans.
- Frontend-Druckansicht / Auswahl-UI für `sections` — Teil des späteren Frontend-Plans (ROADMAP.md Punkt 2).

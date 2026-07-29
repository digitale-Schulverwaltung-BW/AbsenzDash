"""seed default schwellwert regeln and massnahmen katalog

Revision ID: ecbb0df17a38
Revises: 1f41af73eb98
Create Date: 2026-07-29 07:39:06.571352

Seedet zwei produktiv benoetigte Grunddaten, die bisher an keiner Stelle
automatisch angelegt wurden:

1. Den Default-Massnahmen-Katalog aus SPECS.md Abschnitt 4 (Gespraech,
   Elterngespraech, Nachsitzen, 4h Nachsitzen, Schulverweis, Bussgeld,
   Zwangsgeld). Eine fruehere Migration (00e96fea061a) hat das bereits
   einmal geseedet, die Zeilen wurden aber zwischenzeitlich in mind. einer
   Umgebung geloescht (z.B. durch einen DB-Reset ohne Reseed) - alembic
   fuehrt 00e96fea061a nicht erneut aus, da sie bereits als angewendet
   markiert ist. Diese Migration ist daher idempotent (ON CONFLICT DO
   NOTHING) und kann gefahrlos in jeder Umgebung laufen, unabhaengig vom
   bisherigen Zustand der Tabelle.
2. Eine schulweite Schwellwert-Regel je Typ (fehlzeiten/klassenbuch) -
   ohne mindestens eine Regel wird fuer keinen Schueler jemals ein
   schueler_zaehlerstand angelegt (pruefe_schwellwerte ueberspringt Schueler
   ohne aufloesbare Regel komplett, siehe eskalations_pruefung.py), die
   Uebersicht/Detail-Badges zeigen dann dauerhaft "-" trotz vorhandener
   Fehlzeiten/Klassenbucheintraege. Werte mit dem Menschen abgestimmt
   (siehe Chat-Verlauf 2026-07-29): Fehltage-Regel 4/8/12 (linear
   fortgesetztes SPECS.md-Beispiel), Klassenbuch-Regel 3/6/9, beide mit
   expliziter Rollen-Eskalation Klassenlehrkraft -> +Bereichsleiter ->
   +Schulleitung je Stufe (TECH-SPEC.md Abschnitt 2: empfaenger_rollen ist
   vollstaendig explizit, keine implizite Klassenlehrkraft-Immer-Logik).
   Guard per NOT EXISTS, damit ein bereits konfiguriertes Setup (z.B. in
   einer Umgebung, in der die Schulleitung die Regel schon selbst ueber
   PUT /admin/threshold-rules angelegt hat) nicht dupliziert wird.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ecbb0df17a38'
down_revision = '1f41af73eb98'
branch_labels = None
depends_on = None

_MASSNAHMEN_TYPEN = (
    ("Gespräch", False),
    ("Elterngespräch", False),
    ("Nachsitzen", True),
    ("4h Nachsitzen", True),
    ("Schulverweis", True),
    ("Bußgeld", True),
    ("Zwangsgeld", True),
)


def upgrade() -> None:
    for name, setzt_zaehler_zurueck in _MASSNAHMEN_TYPEN:
        op.execute(
            f"""
            INSERT INTO massnahmen_typ (name, setzt_zaehler_zurueck, aktiv)
            VALUES ('{name}', {setzt_zaehler_zurueck}, true)
            ON CONFLICT (name) DO NOTHING;
            """
        )

    op.execute(
        """
        INSERT INTO schwellwert_regel (typ, geltungsbereich)
        SELECT 'fehlzeiten', 'schulweit'
        WHERE NOT EXISTS (
            SELECT 1 FROM schwellwert_regel WHERE typ = 'fehlzeiten' AND geltungsbereich = 'schulweit'
        );
        """
    )
    op.execute(
        """
        INSERT INTO schwellwert_regel (typ, geltungsbereich)
        SELECT 'klassenbuch', 'schulweit'
        WHERE NOT EXISTS (
            SELECT 1 FROM schwellwert_regel WHERE typ = 'klassenbuch' AND geltungsbereich = 'schulweit'
        );
        """
    )

    op.execute(
        """
        INSERT INTO schwellwert_stufe (regel_id, stufe_nr, einheit, schwellenwert, fehlzeiten_filter, empfaenger_rollen)
        SELECT r.id, s.stufe_nr, 'fehltage', s.schwellenwert, 'alle', s.rollen
        FROM schwellwert_regel r,
             (VALUES
                (1, 4, ARRAY['klassenlehrkraft']::varchar[]),
                (2, 8, ARRAY['klassenlehrkraft', 'bereichsleiter']::varchar[]),
                (3, 12, ARRAY['klassenlehrkraft', 'bereichsleiter', 'schulleitung']::varchar[])
             ) AS s(stufe_nr, schwellenwert, rollen)
        WHERE r.typ = 'fehlzeiten' AND r.geltungsbereich = 'schulweit'
          AND NOT EXISTS (
              SELECT 1 FROM schwellwert_stufe WHERE regel_id = r.id AND stufe_nr = s.stufe_nr
          );
        """
    )
    op.execute(
        """
        INSERT INTO schwellwert_stufe (regel_id, stufe_nr, einheit, schwellenwert, fehlzeiten_filter, empfaenger_rollen)
        SELECT r.id, s.stufe_nr, NULL, s.schwellenwert, NULL, s.rollen
        FROM schwellwert_regel r,
             (VALUES
                (1, 3, ARRAY['klassenlehrkraft']::varchar[]),
                (2, 6, ARRAY['klassenlehrkraft', 'bereichsleiter']::varchar[]),
                (3, 9, ARRAY['klassenlehrkraft', 'bereichsleiter', 'schulleitung']::varchar[])
             ) AS s(stufe_nr, schwellenwert, rollen)
        WHERE r.typ = 'klassenbuch' AND r.geltungsbereich = 'schulweit'
          AND NOT EXISTS (
              SELECT 1 FROM schwellwert_stufe WHERE regel_id = r.id AND stufe_nr = s.stufe_nr
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM schwellwert_stufe
        WHERE regel_id IN (
            SELECT id FROM schwellwert_regel
            WHERE geltungsbereich = 'schulweit' AND typ IN ('fehlzeiten', 'klassenbuch')
        );
        """
    )
    op.execute("DELETE FROM schwellwert_regel WHERE geltungsbereich = 'schulweit' AND typ IN ('fehlzeiten', 'klassenbuch');")
    names = ", ".join(f"'{name}'" for name, _ in _MASSNAHMEN_TYPEN)
    op.execute(f"DELETE FROM massnahmen_typ WHERE name IN ({names});")

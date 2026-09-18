"""add klasse schuljahr_id

Macht klasse schuljahresgebunden (siehe docs/superpowers/specs/2026-09-18-schuljahr-
historisierung-design.md): neue Spalte schuljahr_id (FK schuljahr.id, NOT NULL), Unique-
Constraint wechselt von webuntis_id allein zu (webuntis_id, schuljahr_id). Bestehende Zeilen
werden per Best-Effort-Backfill auf einstellung.aktuelles_schuljahr_id gesetzt - es gibt keine
Moeglichkeit, fruehere Jahreszuordnungen rueckwirkend zu rekonstruieren (Nicht-Ziel).

Revision ID: 935e452806fd
Revises: c9a67c39ff2b
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "935e452806fd"
down_revision = "c9a67c39ff2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("klasse", sa.Column("schuljahr_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE klasse SET schuljahr_id = (SELECT aktuelles_schuljahr_id FROM einstellung ORDER BY id LIMIT 1) "
        "WHERE schuljahr_id IS NULL"
    )
    op.alter_column("klasse", "schuljahr_id", nullable=False)
    op.create_foreign_key("fk_klasse_schuljahr_id", "klasse", "schuljahr", ["schuljahr_id"], ["id"])
    op.drop_index("ix_klasse_webuntis_id", table_name="klasse")
    op.create_index("ix_klasse_webuntis_id", "klasse", ["webuntis_id"], unique=False)
    op.create_unique_constraint("uq_klasse_webuntis_id_schuljahr_id", "klasse", ["webuntis_id", "schuljahr_id"])


def downgrade() -> None:
    op.drop_constraint("uq_klasse_webuntis_id_schuljahr_id", "klasse", type_="unique")
    op.drop_index("ix_klasse_webuntis_id", table_name="klasse")
    op.create_index("ix_klasse_webuntis_id", "klasse", ["webuntis_id"], unique=True)
    op.drop_constraint("fk_klasse_schuljahr_id", "klasse", type_="foreignkey")
    op.drop_column("klasse", "schuljahr_id")

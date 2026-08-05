"""add bereich abteilung_id and ausgeblendet columns

Bundle D: bereich wird verbindlich 1:1 aus abteilung abgeleitet (statt frei manuell
gepflegt), siehe docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
Bestehende bereich/bereich_klasse/nutzer_bereich-Zeilen werden verworfen, der naechste
WebUntis-Sync-Lauf baut den Stand aus den aktuellen Abteilungen neu auf.

Revision ID: b8e759ca46a8
Revises: bc7ae769066b
Create Date: 2026-08-05 11:11:53.305840

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8e759ca46a8'
down_revision = 'bc7ae769066b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM bereich")
    op.add_column("bereich", sa.Column("abteilung_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_bereich_abteilung_id",
        "bereich",
        "abteilung",
        ["abteilung_id"],
        ["id"],
    )
    op.create_unique_constraint("uq_bereich_abteilung_id", "bereich", ["abteilung_id"])
    op.add_column(
        "bereich",
        sa.Column("ausgeblendet", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("bereich", "ausgeblendet", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_bereich_abteilung_id", "bereich", type_="unique")
    op.drop_constraint("fk_bereich_abteilung_id", "bereich", type_="foreignkey")
    op.drop_column("bereich", "abteilung_id")
    op.drop_column("bereich", "ausgeblendet")

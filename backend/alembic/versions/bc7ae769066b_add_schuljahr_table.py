"""add schuljahr table

Neue Stammdaten-Cache-Tabelle fuer WebUntis-Schuljahre (getSchoolyears), plus eine
Referenzspalte auf einstellung, die festhaelt, welches Schuljahr der letzte Sync-Lauf
als "aktuell" behandelt hat (siehe docs/superpowers/specs/2026-07-30-schuljahr-auswahl-design.md).

Revision ID: bc7ae769066b
Revises: c5cfcd490245
Create Date: 2026-07-30 13:38:25.632019

"""
from alembic import op
import sqlalchemy as sa


revision = 'bc7ae769066b'
down_revision = 'c5cfcd490245'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schuljahr",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("start_datum", sa.Date(), nullable=False),
        sa.Column("end_datum", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("einstellung", sa.Column("aktuelles_schuljahr_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_einstellung_aktuelles_schuljahr_id",
        "einstellung",
        "schuljahr",
        ["aktuelles_schuljahr_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_einstellung_aktuelles_schuljahr_id", "einstellung", type_="foreignkey")
    op.drop_column("einstellung", "aktuelles_schuljahr_id")
    op.drop_table("schuljahr")

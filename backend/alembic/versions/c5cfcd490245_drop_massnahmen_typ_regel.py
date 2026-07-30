"""drop massnahmen_typ_regel

Massnahmen-Typen setzen bei setzt_zaehler_zurueck=True jetzt unconditional beide
Zaehlerstaende (fehlzeiten + klassenbuch) des Schuelers zurueck, statt an spezifische
schwellwert_regel-Zeilen gebunden zu sein (siehe docs/superpowers/specs/2026-07-30-admin-bereich-design.md).
Das eliminiert die vorher moegliche "Admin-Falle": eine Verknuepfung nur mit der schulweiten
Regel, die bei Schuelern unter einer spezifischeren Regel still keinen Reset ausloeste.

Revision ID: c5cfcd490245
Revises: ecbb0df17a38
Create Date: 2026-07-30 08:55:18.936635

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5cfcd490245'
down_revision = 'ecbb0df17a38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("massnahmen_typ_regel")


def downgrade() -> None:
    op.create_table(
        "massnahmen_typ_regel",
        sa.Column("massnahmen_typ_id", sa.Integer(), nullable=False),
        sa.Column("regel_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["massnahmen_typ_id"], ["massnahmen_typ.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["regel_id"], ["schwellwert_regel.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("massnahmen_typ_id", "regel_id"),
    )

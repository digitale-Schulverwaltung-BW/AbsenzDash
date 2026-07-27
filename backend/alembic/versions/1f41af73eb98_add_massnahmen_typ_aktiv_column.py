"""add massnahmen_typ aktiv column

Revision ID: 1f41af73eb98
Revises: 43e3780702ba
Create Date: 2026-07-27 15:03:30.882594

"""
from alembic import op
import sqlalchemy as sa


revision = '1f41af73eb98'
down_revision = '43e3780702ba'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "massnahmen_typ",
        sa.Column("aktiv", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("massnahmen_typ", "aktiv", server_default=None)


def downgrade() -> None:
    op.drop_column("massnahmen_typ", "aktiv")

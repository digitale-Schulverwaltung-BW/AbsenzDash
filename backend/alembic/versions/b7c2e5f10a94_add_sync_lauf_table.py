"""add sync_lauf table

Revision ID: b7c2e5f10a94
Revises: a1d4c7e92b30
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa

revision = "b7c2e5f10a94"
down_revision = "a1d4c7e92b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_lauf",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gestartet_am", sa.DateTime(timezone=True), nullable=False),
        sa.Column("beendet_am", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("ausgeloest_von", sa.String(length=20), nullable=False),
        sa.Column("nutzer_id", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=50), nullable=True),
        sa.Column("fehler_kurz", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["nutzer_id"], ["nutzer.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sync_lauf")

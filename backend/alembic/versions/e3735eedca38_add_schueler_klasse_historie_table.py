"""add schueler_klasse_historie table

Revision ID: e3735eedca38
Revises: 935e452806fd
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "e3735eedca38"
down_revision = "935e452806fd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schueler_klasse_historie",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schueler_id", sa.Integer(), nullable=False),
        sa.Column("schuljahr_id", sa.Integer(), nullable=False),
        sa.Column("klasse_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["schueler_id"], ["schueler.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schuljahr_id"], ["schuljahr.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["klasse_id"], ["klasse.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schueler_id", "schuljahr_id", name="uq_schueler_klasse_historie_schueler_schuljahr"),
    )


def downgrade() -> None:
    op.drop_table("schueler_klasse_historie")

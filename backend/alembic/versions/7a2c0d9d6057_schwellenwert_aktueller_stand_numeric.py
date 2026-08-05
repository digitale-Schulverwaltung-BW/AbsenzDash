"""schwellenwert_aktueller_stand_numeric

Revision ID: 7a2c0d9d6057
Revises: b8e759ca46a8
Create Date: 2026-08-05 21:29:40.880489

"""
from alembic import op
import sqlalchemy as sa


revision = '7a2c0d9d6057'
down_revision = 'b8e759ca46a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "schwellwert_stufe",
        "schwellenwert",
        existing_type=sa.INTEGER(),
        type_=sa.Numeric(6, 2),
        postgresql_using="schwellenwert::numeric(6,2)",
    )
    op.alter_column(
        "schueler_zaehlerstand",
        "aktueller_stand",
        existing_type=sa.INTEGER(),
        type_=sa.Numeric(6, 2),
        postgresql_using="aktueller_stand::numeric(6,2)",
    )


def downgrade() -> None:
    op.alter_column(
        "schueler_zaehlerstand",
        "aktueller_stand",
        existing_type=sa.Numeric(6, 2),
        type_=sa.INTEGER(),
        postgresql_using="round(aktueller_stand)::integer",
    )
    op.alter_column(
        "schwellwert_stufe",
        "schwellenwert",
        existing_type=sa.Numeric(6, 2),
        type_=sa.INTEGER(),
        postgresql_using="round(schwellenwert)::integer",
    )

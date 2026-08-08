"""add stundenraster_periode table

Revision ID: c9a67c39ff2b
Revises: 7a2c0d9d6057
Create Date: 2026-08-08 20:32:31.152009

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9a67c39ff2b'
down_revision = '7a2c0d9d6057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('stundenraster_periode',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('wochentag', sa.Integer(), nullable=False),
    sa.Column('stunde_nr', sa.Integer(), nullable=False),
    sa.Column('start_zeit', sa.Integer(), nullable=False),
    sa.Column('end_zeit', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wochentag', 'stunde_nr', name='uq_stundenraster_periode_wochentag_stunde_nr')
    )


def downgrade() -> None:
    op.drop_table('stundenraster_periode')

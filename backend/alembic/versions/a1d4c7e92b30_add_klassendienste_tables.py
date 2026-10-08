"""add klassendienst_typ, schueler_klassendienst, einstellung.klassendienste_letzter_sync_am

Revision ID: a1d4c7e92b30
Revises: e3735eedca38
Create Date: 2026-10-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1d4c7e92b30'
down_revision = 'e3735eedca38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('klassendienst_typ',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('webuntis_dienst_id', sa.Integer(), nullable=False),
    sa.Column('bezeichnung', sa.String(length=100), nullable=False),
    sa.Column('kuerzel', sa.String(length=10), nullable=False),
    sa.Column('beschreibung', sa.String(length=300), nullable=True),
    sa.Column('aktiv', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('webuntis_dienst_id')
    )
    op.create_table('schueler_klassendienst',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('schueler_id', sa.Integer(), nullable=False),
    sa.Column('klassendienst_typ_id', sa.Integer(), nullable=False),
    sa.Column('von', sa.Date(), nullable=False),
    sa.Column('bis', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['klassendienst_typ_id'], ['klassendienst_typ.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['schueler_id'], ['schueler.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('schueler_id', 'klassendienst_typ_id', 'von', name='uq_schueler_klassendienst_schueler_typ_von')
    )
    op.add_column('einstellung', sa.Column('klassendienste_letzter_sync_am', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('einstellung', 'klassendienste_letzter_sync_am')
    op.drop_table('schueler_klassendienst')
    op.drop_table('klassendienst_typ')

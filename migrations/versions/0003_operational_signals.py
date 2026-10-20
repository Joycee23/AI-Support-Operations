"""Durable aggregate service health."""
from alembic import op
import sqlalchemy as sa
revision = '0003_operational_signals'
down_revision = '0002_tenant_rls'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('operational_signals', sa.Column('name', sa.String(32), primary_key=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('last_success', sa.DateTime(timezone=True)), sa.Column('last_failure', sa.DateTime(timezone=True)))

def downgrade():
    op.drop_table('operational_signals')

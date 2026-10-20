"""Fail-closed RLS for customer content and a metadata-only ingestion dispatcher."""
from alembic import op
import sqlalchemy as sa
revision = '0002_tenant_rls'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None
TABLES = ('tickets', 'ticket_messages', 'knowledge_items', 'knowledge_versions',
          'knowledge_chunks', 'ai_analyses', 'audit_events')


def upgrade():
    op.create_table('knowledge_jobs',
        sa.Column('item_id', sa.String(), sa.ForeignKey('knowledge_items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('queued_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_knowledge_jobs_workspace_id', 'knowledge_jobs', ['workspace_id'])
    op.create_index('ix_knowledge_jobs_queued_at', 'knowledge_jobs', ['queued_at'])
    op.execute("INSERT INTO knowledge_jobs SELECT id, workspace_id, CURRENT_TIMESTAMP FROM knowledge_items WHERE processing_status IN ('queued','processing')")
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY workspace_isolation ON {table} USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')) WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), ''))")


def downgrade():
    raise RuntimeError('Disabling tenant RLS requires a reviewed migration; automatic downgrade is disabled.')

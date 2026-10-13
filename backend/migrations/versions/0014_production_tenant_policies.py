"""Database tenant boundaries for restricted API and worker roles."""
from alembic import op

revision = "0014"
down_revision = "0013_conflict_appointment_stability"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "memberships", "daily_metrics", "data_sources", "data_import_runs", "business_events",
    "reconciliation_decisions", "data_coverage", "knowledge_documents", "knowledge_chunks",
    "investigation_runs", "audit_events", "experiments", "experiment_approvals", "n8n_dispatches",
    "growth_strategy_runs", "growth_recommendations", "recommendation_approvals", "experiment_designs",
    "n8n_callback_receipts", "experiment_evaluations", "experiment_learnings", "workflow_jobs",
    "workflow_checkpoints", "workflow_checkpoint_writes",
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "workspace_id = NULLIF(current_setting('app.workspace_id', true), '')"
    user = "user_id = NULLIF(current_setting('app.user_id', true), '')"
    for table in (*TENANT_TABLES, "workspaces"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        write_scope = tenant if table != "workspaces" else tenant.replace("workspace_id", "id", 1)
        read_scope = write_scope
        if table == "memberships":
            read_scope = f"({tenant}) OR ({user})"
        elif table == "workspaces":
            read_scope = (f"({write_scope}) OR EXISTS (SELECT 1 FROM memberships m "
                          f"WHERE m.workspace_id = workspaces.id AND m.{user})")
        elif table == "data_sources":
            read_scope = (f"({tenant}) OR secret_hash = "
                          "NULLIF(current_setting('app.source_token_hash', true), '')")
        elif table == "workflow_jobs":
            # Only the separate worker login can scan/claim the durable queue.
            # All domain records and checkpoints still require tenant context.
            read_scope = f"({tenant}) OR current_user = 'marketmind_worker'"
        op.execute(f'CREATE POLICY tenant_read ON "{table}" FOR SELECT USING ({read_scope})')
        op.execute(f'CREATE POLICY tenant_insert ON "{table}" FOR INSERT WITH CHECK ({write_scope})')
        update_scope = read_scope if table == "workflow_jobs" else write_scope
        op.execute(f'CREATE POLICY tenant_update ON "{table}" FOR UPDATE '
                   f'USING ({update_scope}) WITH CHECK ({update_scope})')
        op.execute(f'CREATE POLICY tenant_delete ON "{table}" FOR DELETE USING ({write_scope})')


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in (*TENANT_TABLES, "workspaces"):
        for policy in ("tenant_read", "tenant_insert", "tenant_update", "tenant_delete"):
            op.execute(f'DROP POLICY {policy} ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

"""Initial schema from models.

Revision ID: 001
Revises:
Create Date: 2026-04-03 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create organizations table
    op.create_table(
        'sf_organizations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('plan', sa.String(), nullable=False, server_default='free'),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('deleted_at', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    op.create_index('idx_orgs_slug', 'sf_organizations', ['slug'])

    # Create org_members table
    op.create_table(
        'sf_org_members',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='member'),
        sa.Column('invited_by', sa.String(), nullable=True),
        sa.Column('invited_at', sa.String(), nullable=True),
        sa.Column('accepted_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'user_id')
    )
    op.create_index('idx_org_members_org', 'sf_org_members', ['org_id'])
    op.create_index('idx_org_members_user', 'sf_org_members', ['user_id'])

    # Create integrations table
    op.create_table(
        'sf_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('spec', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('last_connection_test', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create runs table
    op.create_table(
        'sf_runs',
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('integration_name', sa.String(), nullable=False),
        sa.Column('spec', sa.String(), nullable=False),
        sa.Column('analysis_source', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('tool_count', sa.Integer(), nullable=True),
        sa.Column('endpoint_count', sa.Integer(), nullable=True),
        sa.Column('compression_ratio', sa.Float(), nullable=True),
        sa.Column('coverage', sa.Float(), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('artifacts', sa.JSON(), nullable=False, server_default='[]'),
        sa.ForeignKeyConstraint(['integration_id'], ['sf_integrations.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('integration_id', 'run_id')
    )
    op.create_index('idx_runs_integration_created', 'sf_runs', ['integration_id', 'run_id'])

    # Create artifacts table
    op.create_table(
        'sf_artifacts',
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False, server_default=''),
        sa.Column('object_key', sa.String(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=False, server_default='application/json; charset=utf-8'),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('integration_id', 'run_id', 'name')
    )

    # Create integration_tool_configs table
    op.create_table(
        'sf_integration_tool_configs',
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('tools', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('endpoints', sa.JSON(), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['integration_id'], ['sf_integrations.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('integration_id')
    )

    # Create integration_auth_configs table
    op.create_table(
        'sf_integration_auth_configs',
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('base_url', sa.String(), nullable=True),
        sa.Column('auth_mode', sa.String(), nullable=False, server_default='none'),
        sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('api_key_header', sa.String(), nullable=True),
        sa.Column('api_key_query_name', sa.String(), nullable=True),
        sa.Column('bearer_token', sa.String(), nullable=True),
        sa.Column('token_value', sa.String(), nullable=True),
        sa.Column('token_header', sa.String(), nullable=True),
        sa.Column('token_prefix', sa.String(), nullable=True),
        sa.Column('basic_username', sa.String(), nullable=True),
        sa.Column('basic_password', sa.String(), nullable=True),
        sa.Column('oauth_token_url', sa.String(), nullable=True),
        sa.Column('oauth_client_id', sa.String(), nullable=True),
        sa.Column('oauth_client_secret', sa.String(), nullable=True),
        sa.Column('oauth_scope', sa.String(), nullable=True),
        sa.Column('oauth_audience', sa.String(), nullable=True),
        sa.Column('token_url', sa.String(), nullable=True),
        sa.Column('token_request_method', sa.String(), nullable=True),
        sa.Column('token_request_body', sa.String(), nullable=True),
        sa.Column('token_request_headers', sa.String(), nullable=True),
        sa.Column('token_response_path', sa.String(), nullable=True),
        sa.Column('token_expiry_seconds', sa.Integer(), nullable=True),
        sa.Column('token_expiry_path', sa.String(), nullable=True),
        sa.Column('custom_headers', sa.String(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['integration_id'], ['sf_integrations.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('integration_id')
    )

    # Create sf_llm_configs table
    op.create_table(
        'sf_llm_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('embedding_model', sa.String(), nullable=True),
        sa.Column('embedding_api_key', sa.String(), nullable=True),
        sa.Column('embedding_dimensions', sa.Integer(), nullable=True),
        sa.Column('base_url', sa.String(), nullable=True),
        sa.Column('api_version', sa.String(), nullable=True),
        sa.Column('auth_type', sa.String(), nullable=False, server_default='api_key'),
        sa.Column('auth_header_name', sa.String(), nullable=True),
        sa.Column('auth_header_prefix', sa.String(), nullable=True),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('bearer_token', sa.String(), nullable=True),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('custom_headers', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('vllm_auth_type', sa.String(), nullable=True),
        sa.Column('vllm_auth_headers', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('vllm_token_auth', sa.JSON(), nullable=True),
        sa.Column('vllm_oauth2', sa.JSON(), nullable=True),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('region', sa.String(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_default_embedding', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_test_success', sa.Boolean(), nullable=True),
        sa.Column('last_test_latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_test_model', sa.String(), nullable=True),
        sa.Column('last_test_provider', sa.String(), nullable=True),
        sa.Column('last_test_error', sa.String(), nullable=True),
        sa.Column('last_tested_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_sf_llm_configs_default', 'sf_llm_configs', ['is_default'])
    op.create_index('idx_sf_llm_configs_default_embedding', 'sf_llm_configs', ['is_default_embedding'])

    # Create sf_llm_logs table
    op.create_table(
        'sf_llm_logs',
        sa.Column('log_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('integration_name', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('run_mode', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('request_payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('response_text', sa.Text(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('log_id')
    )
    op.create_index('idx_sf_llm_logs_created', 'sf_llm_logs', ['created_at'], sort_by=sa.desc('created_at'))
    op.create_index('idx_sf_llm_logs_integration_created', 'sf_llm_logs', ['integration_id', 'created_at'], sort_by=[(sa.column('created_at'), sa.desc)])

    # Create sf_deployment_records table
    op.create_table(
        'sf_deployment_records',
        sa.Column('deployment_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('server_path', sa.String(), nullable=False),
        sa.Column('env_path', sa.String(), nullable=True),
        sa.Column('command', sa.String(), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['integration_id'], ['sf_integrations.id'], ),
        sa.ForeignKeyConstraint(['org_id'], ['sf_organizations.id'], ),
        sa.PrimaryKeyConstraint('deployment_id')
    )
    op.create_index('idx_deployments_integration_created', 'sf_deployment_records', ['integration_id', 'created_at'], sort_by=[(sa.column('created_at'), sa.desc)])


def downgrade() -> None:
    op.drop_index('idx_deployments_integration_created')
    op.drop_table('sf_deployment_records')
    op.drop_index('idx_sf_llm_logs_integration_created')
    op.drop_index('idx_sf_llm_logs_created')
    op.drop_table('sf_llm_logs')
    op.drop_index('idx_sf_llm_configs_default_embedding')
    op.drop_index('idx_sf_llm_configs_default')
    op.drop_table('sf_llm_configs')
    op.drop_table('sf_integration_auth_configs')
    op.drop_table('sf_integration_tool_configs')
    op.drop_table('sf_artifacts')
    op.drop_index('idx_runs_integration_created')
    op.drop_table('sf_runs')
    op.drop_table('sf_integrations')
    op.drop_index('idx_org_members_user')
    op.drop_index('idx_org_members_org')
    op.drop_table('sf_org_members')
    op.drop_index('idx_orgs_slug')
    op.drop_table('sf_organizations')

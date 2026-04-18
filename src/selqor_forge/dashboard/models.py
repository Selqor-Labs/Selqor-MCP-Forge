# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""SQLAlchemy ORM models for the Selqor Forge dashboard."""

from __future__ import annotations


from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Organization(Base):
    """Multi-tenancy organization record."""

    __tablename__ = "sf_organizations"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    plan = Column(String, nullable=False, default="free")
    created_at = Column(String, nullable=False)
    deleted_at = Column(String, nullable=True)

    integrations = relationship("Integration", back_populates="organization")
    runs = relationship("Run", back_populates="organization")
    members = relationship("OrgMember", back_populates="organization")


class OrgMember(Base):
    """Organization membership record."""

    __tablename__ = "sf_org_members"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False, default="member")
    invited_by = Column(String, nullable=True)
    invited_at = Column(String, nullable=True)
    accepted_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

    organization = relationship("Organization", back_populates="members")


class Integration(Base):
    """Integration specification and metadata."""

    __tablename__ = "sf_integrations"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    name = Column(String, nullable=False)
    spec = Column(String, nullable=False)
    specs = Column(JSON, nullable=False, default=list)
    agent_prompt = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    last_connection_test = Column(JSON, nullable=True)

    organization = relationship("Organization", back_populates="integrations")
    runs = relationship("Run", back_populates="integration", cascade="all, delete-orphan")
    tool_config = relationship("IntegrationToolConfig", back_populates="integration", uselist=False, cascade="all, delete-orphan")
    auth_config = relationship("IntegrationAuthConfig", back_populates="integration", uselist=False, cascade="all, delete-orphan")


class Run(Base):
    """Analysis run record."""

    __tablename__ = "sf_runs"

    integration_id = Column(String, ForeignKey("sf_integrations.id"), nullable=False)
    run_id = Column(String, nullable=False)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    status = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    integration_name = Column(String, nullable=False)
    spec = Column(String, nullable=False)
    analysis_source = Column(String, nullable=False)
    model = Column(String, nullable=True)
    score = Column(Integer, nullable=True)
    tool_count = Column(Integer, nullable=True)
    endpoint_count = Column(Integer, nullable=True)
    compression_ratio = Column(Float, nullable=True)
    coverage = Column(Float, nullable=True)
    warnings = Column(JSON, nullable=False, default=list)
    error = Column(String, nullable=True)
    artifacts = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        PrimaryKeyConstraint("integration_id", "run_id"),
        Index("idx_runs_integration_created", "integration_id", "run_id"),
    )

    integration = relationship("Integration", back_populates="runs")
    organization = relationship("Organization", back_populates="runs")


class Artifact(Base):
    """Analysis artifact (output files)."""

    __tablename__ = "sf_artifacts"

    integration_id = Column(String, nullable=False)
    run_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    content = Column(String, nullable=False, default="")
    object_key = Column(String, nullable=True)
    mime_type = Column(String, nullable=False, default="application/json; charset=utf-8")
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("integration_id", "run_id", "name"),
        ForeignKeyConstraint(
            ["integration_id", "run_id"],
            ["sf_runs.integration_id", "sf_runs.run_id"],
            ondelete="CASCADE",
        ),
    )


class IntegrationToolConfig(Base):
    """Manual tool configuration for an integration."""

    __tablename__ = "sf_integration_tool_configs"

    integration_id = Column(String, ForeignKey("sf_integrations.id"), primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    tools = Column(JSON, nullable=False, default=list)
    source = Column(String, nullable=True)
    endpoints = Column(JSON, nullable=True)
    warnings = Column(JSON, nullable=True)
    updated_at = Column(String, nullable=False)

    integration = relationship("Integration", back_populates="tool_config")


class IntegrationAuthConfig(Base):
    """Authentication configuration for an integration."""

    __tablename__ = "sf_integration_auth_configs"

    integration_id = Column(String, ForeignKey("sf_integrations.id"), primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    base_url = Column(String, nullable=True)
    auth_mode = Column(String, nullable=False, default="none")
    config = Column(JSON, nullable=False, default=dict)
    api_key = Column(String, nullable=True)
    api_key_header = Column(String, nullable=True)
    api_key_query_name = Column(String, nullable=True)
    bearer_token = Column(String, nullable=True)
    token_value = Column(String, nullable=True)
    token_header = Column(String, nullable=True)
    token_prefix = Column(String, nullable=True)
    basic_username = Column(String, nullable=True)
    basic_password = Column(String, nullable=True)
    oauth_token_url = Column(String, nullable=True)
    oauth_client_id = Column(String, nullable=True)
    oauth_client_secret = Column(String, nullable=True)
    oauth_scope = Column(String, nullable=True)
    oauth_audience = Column(String, nullable=True)
    token_url = Column(String, nullable=True)
    token_request_method = Column(String, nullable=True)
    token_request_body = Column(String, nullable=True)
    token_request_headers = Column(String, nullable=True)
    token_response_path = Column(String, nullable=True)
    token_expiry_seconds = Column(Integer, nullable=True)
    token_expiry_path = Column(String, nullable=True)
    custom_headers = Column(String, nullable=True)
    updated_at = Column(String, nullable=False)

    integration = relationship("Integration", back_populates="auth_config")


class LLMConfig(Base):
    """LLM provider configuration."""

    __tablename__ = "sf_llm_configs"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    embedding_model = Column(String, nullable=True)
    embedding_api_key = Column(String, nullable=True)
    embedding_dimensions = Column(Integer, nullable=True)
    base_url = Column(String, nullable=True)
    api_version = Column(String, nullable=True)
    auth_type = Column(String, nullable=False, default="api_key")
    auth_header_name = Column(String, nullable=True)
    auth_header_prefix = Column(String, nullable=True)
    api_key = Column(String, nullable=True)
    bearer_token = Column(String, nullable=True)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    custom_headers = Column(JSON, nullable=False, default=dict)
    vllm_auth_type = Column(String, nullable=True)
    vllm_auth_headers = Column(JSON, nullable=False, default=dict)
    vllm_token_auth = Column(JSON, nullable=True)
    vllm_oauth2 = Column(JSON, nullable=True)
    project_id = Column(String, nullable=True)
    location = Column(String, nullable=True)
    region = Column(String, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_default_embedding = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_test_success = Column(Boolean, nullable=True)
    last_test_latency_ms = Column(Integer, nullable=True)
    last_test_model = Column(String, nullable=True)
    last_test_provider = Column(String, nullable=True)
    last_test_error = Column(String, nullable=True)
    last_tested_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class LLMLog(Base):
    """LLM API call log."""

    __tablename__ = "sf_llm_logs"

    log_id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    integration_id = Column(String, nullable=True)
    integration_name = Column(String, nullable=True)
    run_id = Column(String, nullable=False)
    run_mode = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=True)
    endpoint = Column(String, nullable=False)
    success = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer, nullable=True)
    request_payload = Column(JSON, nullable=False, default=dict)
    response_payload = Column(JSON, nullable=True)
    response_text = Column(Text, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


class DeploymentRecord(Base):
    """Deployment record."""

    __tablename__ = "sf_deployment_records"

    deployment_id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    integration_id = Column(String, ForeignKey("sf_integrations.id"), nullable=False)
    run_id = Column(String, nullable=False)
    target = Column(String, nullable=False)
    status = Column(String, nullable=False)
    server_path = Column(String, nullable=False)
    env_path = Column(String, nullable=True)
    command = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# New tables for features currently using file-based storage
# ---------------------------------------------------------------------------


class SecurityScan(Base):
    """Security scan record."""

    __tablename__ = "sf_security_scans"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    source = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=True)
    findings_count = Column(Integer, nullable=False, default=0)
    risk_level = Column(String, nullable=True)
    overall_score = Column(Float, nullable=False, default=0.0)
    current_step = Column(String, nullable=True)
    progress_percent = Column(Integer, nullable=False, default=0)
    severity_counts = Column(JSON, nullable=False, default=dict)
    statistics = Column(JSON, nullable=True)
    risk_summary = Column(JSON, nullable=True)
    mcp_manifest = Column(JSON, nullable=True)
    findings = Column(JSON, nullable=False, default=list)
    suggested_fixes = Column(JSON, nullable=False, default=list)
    ai_bom = Column(JSON, nullable=True)


class RemediationStatus(Base):
    """Remediation status for a scan."""

    __tablename__ = "sf_remediation_status"

    id = Column(String, primary_key=True)
    scan_id = Column(String, ForeignKey("sf_security_scans.id"), nullable=False)
    applied = Column(JSON, nullable=False, default=list)
    failed = Column(JSON, nullable=False, default=list)
    pending = Column(JSON, nullable=False, default=list)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=True)


class MonitoredServer(Base):
    """Monitored MCP server."""

    __tablename__ = "sf_monitored_servers"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    transport = Column(String, nullable=False, default="sse")
    check_interval_seconds = Column(Integer, nullable=False, default=300)
    created_at = Column(String, nullable=False)
    last_check = Column(String, nullable=True)
    status = Column(String, nullable=False, default="unknown")

    checks = relationship("MonitoringCheck", back_populates="server", cascade="all, delete-orphan")


class MonitoringCheck(Base):
    """Health check result for a monitored server."""

    __tablename__ = "sf_monitoring_checks"

    id = Column(String, primary_key=True)
    server_id = Column(String, ForeignKey("sf_monitored_servers.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(String, nullable=False)
    status = Column(String, nullable=False)
    latency_ms = Column(Float, nullable=True)
    tool_count = Column(Integer, nullable=True)
    error = Column(String, nullable=True)

    server = relationship("MonitoredServer", back_populates="checks")


class IntegrationVersion(Base):
    """Versioned snapshot of an integration."""

    __tablename__ = "sf_integration_versions"

    id = Column(String, primary_key=True)
    integration_id = Column(String, ForeignKey("sf_integrations.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    spec = Column(JSON, nullable=False, default=dict)
    tool_plan = Column(JSON, nullable=True)


class TeamSettings(Base):
    """Team configuration."""

    __tablename__ = "sf_team_settings"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    name = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    members = Column(JSON, nullable=False, default=list)
    settings = Column(JSON, nullable=False, default=dict)


class TeamInvite(Base):
    """Team invite record."""

    __tablename__ = "sf_team_invites"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False, default="member")
    status = Column(String, nullable=False, default="pending")
    created_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=True)
    cancelled_at = Column(String, nullable=True)


class UserPreferences(Base):
    """User preferences."""

    __tablename__ = "sf_user_preferences"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    user_id = Column(String, nullable=True)
    theme = Column(String, nullable=False, default="system")
    notifications_enabled = Column(Boolean, nullable=False, default=True)
    default_scan_mode = Column(String, nullable=False, default="standard")
    auto_remediate = Column(Boolean, nullable=False, default=False)
    dashboard_layout = Column(String, nullable=False, default="default")
    updated_at = Column(String, nullable=True)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class DashboardUser(Base):
    """Local dashboard user for JWT authentication."""

    __tablename__ = "sf_dashboard_users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=True)  # nullable for OAuth-only users
    name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="admin")  # admin, member, viewer
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String, nullable=False)
    last_login_at = Column(String, nullable=True)
    github_id = Column(String, unique=True, nullable=True, index=True)  # GitHub OAuth user ID
    avatar_url = Column(String, nullable=True)  # Profile picture URL


# ---------------------------------------------------------------------------
# CI/CD persistence (replacing in-memory stores)
# ---------------------------------------------------------------------------


class CiWebhook(Base):
    """Registered CI/CD webhook project."""

    __tablename__ = "sf_ci_webhooks"

    project_name = Column(String, primary_key=True)
    secret = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


class CiRun(Base):
    """CI pipeline scan run result."""

    __tablename__ = "sf_ci_runs"

    id = Column(String, primary_key=True)
    project_name = Column(String, nullable=False, index=True)
    score = Column(Float, nullable=False, default=0)
    risk_level = Column(String, nullable=True)
    findings_count = Column(Integer, nullable=False, default=0)
    branch = Column(String, nullable=True)
    commit_sha = Column(String, nullable=True)
    ci_provider = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    report_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="unknown")
    threshold = Column(Integer, nullable=False, default=70)
    timestamp = Column(String, nullable=False)
    severity_counts = Column(JSON, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Alert persistence (replacing in-memory stores)
# ---------------------------------------------------------------------------


class AlertRule(Base):
    """Monitoring alert rule."""

    __tablename__ = "sf_alert_rules"

    id = Column(String, primary_key=True)
    server_id = Column(String, ForeignKey("sf_monitored_servers.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    condition = Column(String, nullable=False)  # latency_above, consecutive_failures, status_unhealthy
    threshold = Column(Float, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(String, nullable=False)


class FiredAlert(Base):
    """Fired monitoring alert."""

    __tablename__ = "sf_fired_alerts"

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=False)
    rule_id = Column(String, nullable=True)
    rule_name = Column(String, nullable=True)
    condition = Column(String, nullable=True)
    detail = Column(String, nullable=True)
    timestamp = Column(String, nullable=False)
    acknowledged = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationChannel(Base):
    """Notification delivery channel (email, webhook, Slack)."""

    __tablename__ = "sf_notification_channels"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    channel_type = Column(String, nullable=False)  # email, webhook, slack
    config = Column(JSON, nullable=False, default=dict)  # type-specific config
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(String, nullable=False)


class NotificationLog(Base):
    """Log of sent notifications."""

    __tablename__ = "sf_notification_logs"

    id = Column(String, primary_key=True)
    channel_id = Column(String, ForeignKey("sf_notification_channels.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String, nullable=False)  # alert_fired, scan_complete, ci_run_failed
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="sent")  # sent, failed
    error = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# Scan Policy (persisted, replacing in-memory store)
# ---------------------------------------------------------------------------


class ScanPolicy(Base):
    """Organisation scan policy."""

    __tablename__ = "sf_scan_policies"

    id = Column(String, primary_key=True, default="default")
    min_score_threshold = Column(Integer, nullable=False, default=70)
    blocked_severities = Column(JSON, nullable=False, default=list)
    require_llm_analysis = Column(Boolean, nullable=False, default=False)
    require_code_pattern_analysis = Column(Boolean, nullable=False, default=False)
    require_dependency_scan = Column(Boolean, nullable=False, default=False)
    max_critical_findings = Column(Integer, nullable=False, default=0)
    max_high_findings = Column(Integer, nullable=False, default=5)
    auto_fail_on_critical = Column(Boolean, nullable=False, default=True)
    updated_at = Column(String, nullable=True)


class PlaygroundSession(Base):
    """Playground MCP session."""

    __tablename__ = "sf_playground_sessions"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    integration_id = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    transport = Column(String, nullable=False)
    status = Column(String, nullable=False, default="disconnected")
    connected_at = Column(String, nullable=True)
    server_info = Column(JSON, nullable=False, default=dict)
    tools = Column(JSON, nullable=False, default=list)
    command = Column(String, nullable=True)
    working_dir = Column(String, nullable=True)
    server_url = Column(String, nullable=True)

    executions = relationship("PlaygroundExecution", back_populates="session", cascade="all, delete-orphan")


class PlaygroundExecution(Base):
    """Playground tool execution record."""

    __tablename__ = "sf_playground_executions"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sf_playground_sessions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    status = Column(String, nullable=False, default="success")
    latency_ms = Column(Float, nullable=True)
    executed_at = Column(String, nullable=False)
    # Raw JSON-RPC frames captured during the call; shape: {request, response}
    raw_rpc = Column(JSON, nullable=True)
    # Optional tag for attribution: "manual" | "suite" | "agent"
    origin = Column(String, nullable=False, default="manual")

    session = relationship("PlaygroundSession", back_populates="executions")


class PlaygroundTestCase(Base):
    """Saved assertion-backed test case for a tool.

    Test cases are keyed on (session_id, tool_name) but we also store the tool
    name independently so tests survive server reconnects (a reconnect creates
    a fresh session id, but the tool name is stable).
    """

    __tablename__ = "sf_playground_testcases"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    session_id = Column(String, ForeignKey("sf_playground_sessions.id", ondelete="SET NULL"), nullable=True)
    # Preferred lookup key once the session is gone
    tool_name = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    arguments = Column(JSON, nullable=False, default=dict)
    # Each assertion: {op: str, path?: str, value?: Any, flags?: dict}
    assertions = Column(JSON, nullable=False, default=list)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=True)
    # Cached last-run summary so the list view can show status without joining
    last_status = Column(String, nullable=True)  # "pass" | "fail" | "error" | null
    last_run_at = Column(String, nullable=True)


class PlaygroundTestRun(Base):
    """Result of running one test case."""

    __tablename__ = "sf_playground_testruns"

    id = Column(String, primary_key=True)
    testcase_id = Column(String, ForeignKey("sf_playground_testcases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=False)
    tool_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # "pass" | "fail" | "error"
    # Per-assertion outcomes: [{op, path, expected, actual, passed, message}]
    assertion_results = Column(JSON, nullable=False, default=list)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    latency_ms = Column(Float, nullable=True)
    executed_at = Column(String, nullable=False)


class PlaygroundAgentRun(Base):
    """Record of an agent-in-the-loop chat run."""

    __tablename__ = "sf_playground_agent_runs"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sf_playground_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(String, ForeignKey("sf_organizations.id"), nullable=True)
    user_message = Column(Text, nullable=False)
    final_message = Column(Text, nullable=True)
    # Full transcript: [{role, content, tool_calls?, tool_result?}]
    trace = Column(JSON, nullable=False, default=list)
    tools_used = Column(JSON, nullable=False, default=list)  # [tool_name, ...]
    iterations = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="completed")  # completed | error | max_iterations
    error = Column(String, nullable=True)
    total_latency_ms = Column(Float, nullable=True)
    llm_model = Column(String, nullable=True)
    llm_provider = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard context, record models, and request DTOs."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from selqor_forge.config import AppConfig
from selqor_forge.models import ToolDefinition, UasfEndpoint


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def now_utc_string() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_]+$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9\-_.]+$")


def is_safe_token(value: str) -> bool:
    """Return *True* when *value* contains only alphanumerics, hyphens, and underscores."""
    return bool(value) and _SAFE_TOKEN_RE.match(value) is not None


def is_safe_filename(value: str) -> bool:
    """Return *True* when *value* is a safe, flat filename (no path separators)."""
    return (
        bool(value)
        and "/" not in value
        and "\\" not in value
        and _SAFE_FILENAME_RE.match(value) is not None
    )


# ---------------------------------------------------------------------------
# Run-job tracking (background pipeline runs)
# ---------------------------------------------------------------------------


class RunJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IntegrationRunMode(StrEnum):
    LLM = "llm"
    MANUAL = "manual"


@dataclass
class RunJobState:
    """Mutable state for a single background pipeline run."""

    job_id: str
    integration_id: str
    run_id: str
    mode: IntegrationRunMode
    status: RunJobStatus = RunJobStatus.QUEUED
    created_at: str = field(default_factory=now_utc_string)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: RunRecord | None = None
    batch_state_path: Path | None = None
    progress: RunJobProgressView | None = None


# ---------------------------------------------------------------------------
# Record / response models (Pydantic)
# ---------------------------------------------------------------------------


class IntegrationRecord(BaseModel):
    id: str = ""
    name: str = ""
    spec: str = ""
    specs: list[str] = Field(default_factory=list)
    agent_prompt: str | None = None
    created_at: str = Field(default_factory=now_utc_string)
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    last_run: RunSummary | None = None
    last_connection_test: ConnectionTestStatus | None = None

    def effective_specs(self) -> list[str]:
        """Return the deduplicated list of specs to process.

        Merges ``specs`` (multi-spec list) with the legacy ``spec`` field so
        that records created before multi-spec support continue to work.
        """
        seen: set[str] = set()
        result: list[str] = []
        for s in self.specs + ([self.spec] if self.spec else []):
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                result.append(s)
        return result


class RunSummary(BaseModel):
    run_id: str = ""
    status: str = "unknown"
    created_at: str = Field(default_factory=now_utc_string)
    score: int | None = None
    tool_count: int | None = None
    endpoint_count: int | None = None
    compression_ratio: float | None = None
    coverage: float | None = None
    analysis_source: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class RunRecord(BaseModel):
    run_id: str = ""
    status: str = "unknown"
    created_at: str = Field(default_factory=now_utc_string)
    integration_id: str = ""
    integration_name: str = ""
    spec: str = ""
    analysis_source: str = "unknown"
    model: str | None = None
    score: int | None = None
    tool_count: int | None = None
    endpoint_count: int | None = None
    compression_ratio: float | None = None
    coverage: float | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class ConnectionTestStatus(BaseModel):
    success: bool = False
    status_code: int | None = None
    latency_ms: int | None = None
    tested_at: str = Field(default_factory=now_utc_string)
    message: str = ""
    url: str | None = None


class IntegrationAuthConfig(BaseModel):
    integration_id: str = ""
    base_url: str | None = None
    auth_mode: str = "none"
    api_key: str | None = None
    api_key_header: str | None = "x-api-key"
    api_key_query_name: str | None = None
    bearer_token: str | None = None
    token_value: str | None = None
    token_header: str | None = "Authorization"
    token_prefix: str | None = "Bearer"
    basic_username: str | None = None
    basic_password: str | None = None
    oauth_token_url: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None
    oauth_audience: str | None = None
    token_url: str | None = None
    token_request_method: str | None = "POST"
    token_request_body: Any | None = None
    token_request_headers: dict[str, str] = Field(default_factory=dict)
    token_response_path: str | None = "access_token"
    token_expiry_seconds: int | None = 3600
    token_expiry_path: str | None = None
    custom_headers: dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=now_utc_string)


class IntegrationToolConfig(BaseModel):
    integration_id: str = ""
    source: str = "manual"
    updated_at: str = Field(default_factory=now_utc_string)
    tools: list[ToolDefinition] = Field(default_factory=list)
    endpoints: list[UasfEndpoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LlmConfigRecord(BaseModel):
    id: str = ""
    name: str = ""
    provider: str = "anthropic"
    model: str = ""
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_dimensions: int | None = None
    base_url: str | None = None
    api_version: str | None = None
    auth_type: str = "api_key"
    auth_header_name: str | None = None
    auth_header_prefix: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None
    username: str | None = None
    password: str | None = None
    custom_headers: dict[str, str] = Field(default_factory=dict)
    vllm_auth_type: str | None = "none"
    vllm_auth_headers: dict[str, str] = Field(default_factory=dict)
    vllm_token_auth: Any | None = None
    vllm_oauth2: Any | None = None
    project_id: str | None = None
    location: str | None = None
    region: str | None = None
    is_default: bool = False
    is_default_embedding: bool = False
    enabled: bool = True
    last_test_success: bool | None = None
    last_test_latency_ms: int | None = None
    last_test_model: str | None = None
    last_test_provider: str | None = None
    last_test_error: str | None = None
    last_tested_at: str | None = None
    created_at: str = Field(default_factory=now_utc_string)
    updated_at: str = Field(default_factory=now_utc_string)


class LlmLogRecord(BaseModel):
    log_id: str = ""
    integration_id: str = ""
    integration_name: str = ""
    run_id: str = ""
    run_mode: str = "llm"
    provider: str = ""
    model: str | None = None
    endpoint: str = ""
    success: bool = False
    latency_ms: int | None = None
    request_payload: Any = None
    response_payload: Any | None = None
    response_text: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=now_utc_string)


class DeploymentRecord(BaseModel):
    deployment_id: str = ""
    integration_id: str = ""
    run_id: str = ""
    target: str = "typescript"
    status: str = "prepared"
    server_path: str = ""
    env_path: str | None = None
    command: str = ""
    notes: str | None = None
    created_at: str = Field(default_factory=now_utc_string)


class TestLlmConnectionResponse(BaseModel):
    success: bool = False
    latency_ms: int | None = None
    provider: str = ""
    model: str = ""
    error: str | None = None
    tested_at: str = Field(default_factory=now_utc_string)


# ---------------------------------------------------------------------------
# Job view models (serialised to the frontend)
# ---------------------------------------------------------------------------


class RunStepView(BaseModel):
    """One row in the live "deep research" progress stepper.

    The run worker mutates a list of these as it moves through the
    pipeline so the frontend can render a ChatGPT-style progress view
    instead of a single opaque spinner.
    """

    key: str = ""
    """Stable identifier — used by the frontend to look up the row."""

    label: str = ""
    """Human-facing title, e.g. "Analyzing endpoints with LLM"."""

    status: str = "pending"
    """One of: pending | running | done | warning | failed."""

    started_at: str | None = None
    completed_at: str | None = None

    detail: str | None = None
    """Short secondary line, e.g. "Batch 2/5" or "599 endpoints"."""

    warnings: list[str] = Field(default_factory=list)
    """Warnings emitted *during* this step — surfaced as they happen."""


class RunJobProgressView(BaseModel):
    # Flat batch counters (retained for back-compat with older clients
    # that only read the aggregate numbers).
    total_batches: int = 0
    completed_batches: int = 0
    pending_batches: int = 0
    status: str = ""
    failed_batch: int | None = None

    # New structured view consumed by the RunProgressStepper component.
    # Empty list on older runs means the client falls back to the old
    # flat `message` view.
    steps: list[RunStepView] = Field(default_factory=list)
    current_step: str | None = None
    message: str = ""


class RunJobView(BaseModel):
    job_id: str = ""
    integration_id: str = ""
    run_id: str = ""
    mode: str = ""
    status: RunJobStatus = RunJobStatus.QUEUED
    created_at: str = Field(default_factory=now_utc_string)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    progress: RunJobProgressView | None = None
    run: RunRecord | None = None


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


class NewIntegrationRequest(BaseModel):
    name: str = ""
    spec: str = ""
    specs: list[str] = Field(default_factory=list)
    agent_prompt: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class UpdateAuthConfigRequest(BaseModel):
    base_url: str | None = None
    auth_mode: str = "none"
    api_key: str | None = None
    api_key_header: str | None = None
    api_key_query_name: str | None = None
    bearer_token: str | None = None
    token_value: str | None = None
    token_header: str | None = None
    token_prefix: str | None = None
    basic_username: str | None = None
    basic_password: str | None = None
    oauth_token_url: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None
    oauth_audience: str | None = None
    token_url: str | None = None
    token_request_method: str | None = None
    token_request_body: Any | None = None
    token_request_headers: dict[str, str] = Field(default_factory=dict)
    token_response_path: str | None = None
    token_expiry_seconds: int | None = None
    token_expiry_path: str | None = None
    custom_headers: dict[str, str] = Field(default_factory=dict)


class UpsertLlmConfigRequest(BaseModel):
    id: str | None = None
    name: str = ""
    provider: str = "anthropic"
    model: str = ""
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_dimensions: int | None = None
    base_url: str | None = None
    api_version: str | None = None
    auth_type: str = "api_key"
    auth_header_name: str | None = None
    auth_header_prefix: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None
    username: str | None = None
    password: str | None = None
    custom_headers: dict[str, str] = Field(default_factory=dict)
    vllm_auth_type: str | None = None
    vllm_auth_headers: dict[str, str] = Field(default_factory=dict)
    vllm_token_auth: Any | None = None
    vllm_oauth2: Any | None = None
    project_id: str | None = None
    location: str | None = None
    region: str | None = None
    is_default: bool = False
    is_default_embedding: bool = False
    enabled: bool = True


class DeployRequest(BaseModel):
    target: str = "typescript"
    transport: str | None = None
    http_port: int | None = None


class TestLlmConnectionRequest(BaseModel):
    config_id: str | None = None


class UpdateToolingRequest(BaseModel):
    tools: list[ToolDefinition] = Field(default_factory=list)


class RunIntegrationRequest(BaseModel):
    mode: str = "llm"
    agent_prompt: str | None = None
    llm_config_id: str | None = None


# ---------------------------------------------------------------------------
# Multi-tenancy models
# ---------------------------------------------------------------------------


class Organization(BaseModel):
    id: str = ""
    name: str = ""
    slug: str = ""
    plan: str = "free"
    created_at: str = Field(default_factory=now_utc_string)
    deleted_at: str | None = None


class OrgMember(BaseModel):
    id: str = ""
    org_id: str = ""
    user_id: str = ""
    role: str = "member"
    invited_by: str | None = None
    invited_at: str | None = None
    accepted_at: str | None = None
    created_at: str = Field(default_factory=now_utc_string)


class CreateOrgRequest(BaseModel):
    name: str = ""
    slug: str = ""


@dataclass
class CurrentUser:
    """Authenticated (or anonymous) user identity."""

    user_id: str
    email: str | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Dashboard context
# ---------------------------------------------------------------------------


@dataclass
class DashboardContext:
    """Shared, application-wide state injected into every request handler."""

    state_dir: Path
    config: AppConfig
    db: Any | None = None          # psycopg pool (AsyncConnectionPool) or None
    db_session_factory: Any | None = None  # SQLAlchemy sessionmaker for ORM operations
    minio: Any | None = None       # boto3 S3 client or None
    minio_bucket: str | None = None
    minio_prefix: str = "selqor-forge"
    secret_manager: Any | None = None
    run_jobs: dict[str, RunJobState] = field(default_factory=dict)
    run_jobs_lock: threading.Lock = field(default_factory=threading.Lock)


# Allow forward-reference resolution for IntegrationRecord.last_run, etc.
IntegrationRecord.model_rebuild()

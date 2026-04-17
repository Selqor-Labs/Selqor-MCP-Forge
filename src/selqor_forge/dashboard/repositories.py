# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Database repositories for CRUD operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from selqor_forge.dashboard.context import (
    IntegrationRecord,
    RunRecord,
    now_utc_string,
)
from selqor_forge.dashboard.models import (
    AlertRule,
    Artifact,
    CiRun,
    CiWebhook,
    DashboardUser,
    DeploymentRecord,
    FiredAlert,
    Integration,
    IntegrationAuthConfig,
    IntegrationToolConfig,
    IntegrationVersion,
    LLMConfig,
    LLMLog,
    MonitoredServer,
    MonitoringCheck,
    NotificationChannel,
    NotificationLog,
    PlaygroundExecution,
    PlaygroundSession,
    RemediationStatus,
    Run,
    ScanPolicy,
    SecurityScan,
    TeamInvite,
    TeamSettings,
    UserPreferences,
)
from selqor_forge.dashboard.secrets import DashboardSecretManager, is_secret_name

logger = logging.getLogger(__name__)


def _encode_json_field(value: Any) -> str | None:
    """Store structured auth payloads safely in text columns."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _encrypt_secret(secret_manager: DashboardSecretManager | None, value: str | None) -> str | None:
    if secret_manager is None:
        return value
    return secret_manager.encrypt_text(value)


def _encrypt_json_blob(secret_manager: DashboardSecretManager | None, value: Any) -> Any:
    if secret_manager is None:
        return _encode_json_field(value)
    return secret_manager.encrypt_json_blob(value)


def _encrypt_named_mapping_values(
    secret_manager: DashboardSecretManager | None,
    value: Any,
) -> Any:
    if value is None:
        return None
    if secret_manager is None:
        return value
    if isinstance(value, dict):
        return {
            key: _encrypt_secret(secret_manager, item) if isinstance(item, str) and is_secret_name(key) else item
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _encrypt_named_mapping_values(secret_manager, item)
            for item in value
        ]
    return value


class IntegrationRepository:
    """Repository for Integration CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Integration]:
        """List all integrations."""
        stmt = select(Integration).order_by(Integration.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, integration_id: str) -> Integration | None:
        """Get integration by ID."""
        stmt = select(Integration).where(Integration.id == integration_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, record: IntegrationRecord) -> Integration:
        """Create a new integration."""
        model = Integration(
            id=record.id,
            name=record.name,
            spec=record.spec,
            specs=record.specs if record.specs else [record.spec],
            agent_prompt=record.agent_prompt,
            created_at=record.created_at,
            notes=record.notes,
            tags=record.tags,
        )
        self.session.add(model)
        self.session.commit()
        logger.info("Integration created: id=%s name=%s", model.id, model.name)
        return model

    def delete(self, integration_id: str) -> bool:
        """Delete integration by ID and purge any dependent rows.

        Must explicitly purge every child table that holds a non-cascading
        foreign key to ``sf_integrations`` — otherwise Postgres raises
        ``ForeignKeyViolation`` and the delete aborts.

        Tables cleaned up (order matters for SQLite where composite FKs exist):
          1. ``sf_artifacts``       (composite FK to sf_runs(integration_id, run_id))
          2. ``sf_runs``            (FK to sf_integrations.id)
          3. ``sf_integration_tool_configs`` (FK to sf_integrations.id, PK)
          4. ``sf_integration_auth_configs`` (FK to sf_integrations.id, PK)
          5. ``sf_deployment_records``       (FK to sf_integrations.id)

        ``sf_integration_versions`` is declared with ``ondelete="CASCADE"`` so
        the database removes those rows automatically when the parent is dropped.
        """
        model = self.get_by_id(integration_id)
        if model is None:
            return False

        try:
            # Remove artifacts first to avoid SQLite FK failures on runs.
            self.session.execute(delete(Artifact).where(Artifact.integration_id == integration_id))
            self.session.execute(delete(Run).where(Run.integration_id == integration_id))
            self.session.execute(delete(IntegrationToolConfig).where(IntegrationToolConfig.integration_id == integration_id))
            self.session.execute(delete(IntegrationAuthConfig).where(IntegrationAuthConfig.integration_id == integration_id))
            # Deployment records were previously forgotten and caused a
            # ForeignKeyViolation under Postgres. Purge them here.
            self.session.execute(delete(DeploymentRecord).where(DeploymentRecord.integration_id == integration_id))

            self.session.delete(model)
            self.session.commit()
            logger.info("Integration deleted: %s", integration_id)
            return True
        except Exception:
            # Roll back so the session is reusable and surface the error to the caller.
            self.session.rollback()
            logger.exception("Failed to delete integration %s; session rolled back", integration_id)
            raise

    def update_name(self, integration_id: str, name: str) -> Integration | None:
        """Update integration name."""
        model = self.get_by_id(integration_id)
        if model:
            model.name = name
            self.session.commit()
        return model

    def update_spec(self, integration_id: str, spec: str) -> Integration | None:
        """Update integration spec."""
        model = self.get_by_id(integration_id)
        if model:
            model.spec = spec
            self.session.commit()
        return model


class RunRepository:
    """Repository for Run CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_integration(self, integration_id: str, limit: int = 100) -> list[Run]:
        """List runs for an integration."""
        from sqlalchemy.sql import desc
        stmt = (
            select(Run)
            .where(Run.integration_id == integration_id)
            .order_by(desc(Run.created_at))
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, integration_id: str, run_id: str) -> Run | None:
        """Get run by integration_id and run_id."""
        stmt = select(Run).where(
            and_(Run.integration_id == integration_id, Run.run_id == run_id)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, record: RunRecord) -> Run:
        """Create a new run record."""
        model = Run(
            integration_id=record.integration_id,
            run_id=record.run_id,
            status=record.status,
            created_at=record.created_at,
            integration_name=record.integration_name,
            spec=record.spec,
            analysis_source=record.analysis_source,
            model=record.model,
            score=record.score,
            tool_count=record.tool_count,
            endpoint_count=record.endpoint_count,
            compression_ratio=record.compression_ratio,
            coverage=record.coverage,
            warnings=record.warnings or [],
            error=record.error,
            artifacts=record.artifacts or [],
        )
        self.session.add(model)
        self.session.commit()
        logger.info(
            "Run created: integration=%s run=%s status=%s",
            model.integration_id,
            model.run_id,
            model.status,
        )
        return model

    def update_status(self, integration_id: str, run_id: str, status: str) -> Run | None:
        """Update run status."""
        model = self.get_by_id(integration_id, run_id)
        if model:
            model.status = status
            self.session.commit()
        return model

    def delete(self, integration_id: str, run_id: str) -> bool:
        """Delete run and its artifacts by ID."""
        # Delete artifacts first (no FK cascade in ORM)
        self.session.execute(
            delete(Artifact).where(
                and_(Artifact.integration_id == integration_id, Artifact.run_id == run_id)
            )
        )
        stmt = delete(Run).where(
            and_(Run.integration_id == integration_id, Run.run_id == run_id)
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class ArtifactRepository:
    """Repository for Artifact CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_run(self, integration_id: str, run_id: str) -> list[Artifact]:
        """List all artifacts for a run."""
        stmt = (
            select(Artifact)
            .where(
                and_(
                    Artifact.integration_id == integration_id,
                    Artifact.run_id == run_id,
                )
            )
            .order_by(Artifact.name)
        )
        return self.session.execute(stmt).scalars().all()

    def list_names_by_run(self, integration_id: str, run_id: str) -> list[str]:
        """List artifact names for a run WITHOUT loading content.

        Critical for runs with large artifacts (tool-plan.json can be 400MB+).
        """
        stmt = (
            select(Artifact.name)
            .where(
                and_(
                    Artifact.integration_id == integration_id,
                    Artifact.run_id == run_id,
                )
            )
            .order_by(Artifact.name)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get(self, integration_id: str, run_id: str, name: str) -> Artifact | None:
        """Get a single artifact by composite key."""
        stmt = select(Artifact).where(
            and_(
                Artifact.integration_id == integration_id,
                Artifact.run_id == run_id,
                Artifact.name == name,
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_latest_by_name(self, integration_id: str, name: str) -> Artifact | None:
        """Get the most recent artifact with the given name across all runs."""
        from sqlalchemy.sql import desc
        stmt = (
            select(Artifact)
            .where(
                and_(
                    Artifact.integration_id == integration_id,
                    Artifact.name == name,
                )
            )
            .order_by(desc(Artifact.run_id))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> Artifact:
        """Create a new artifact."""
        model = Artifact(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


class ToolConfigRepository:
    """Repository for IntegrationToolConfig operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_integration(self, integration_id: str) -> IntegrationToolConfig | None:
        """Get tool config for integration."""
        stmt = select(IntegrationToolConfig).where(
            IntegrationToolConfig.integration_id == integration_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(
        self, integration_id: str, tools: list[dict[str, Any]], source: str | None = None
    ) -> IntegrationToolConfig:
        """Create or update tool config."""
        config = self.get_by_integration(integration_id)
        if config:
            config.tools = tools
            config.source = source
            config.updated_at = now_utc_string()
        else:
            config = IntegrationToolConfig(
                integration_id=integration_id,
                tools=tools,
                source=source,
                updated_at=now_utc_string(),
            )
            self.session.add(config)

        self.session.commit()
        logger.info(
            "Tool config saved: integration=%s tools=%d",
            integration_id,
            len(tools),
        )
        return config

    def delete(self, integration_id: str) -> bool:
        """Delete tool config."""
        stmt = delete(IntegrationToolConfig).where(
            IntegrationToolConfig.integration_id == integration_id
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class AuthConfigRepository:
    """Repository for IntegrationAuthConfig operations."""

    def __init__(
        self,
        session: Session,
        secret_manager: DashboardSecretManager | None = None,
    ):
        self.session = session
        self.secret_manager = secret_manager

    def get_by_integration(self, integration_id: str) -> IntegrationAuthConfig | None:
        """Get auth config for integration."""
        stmt = select(IntegrationAuthConfig).where(
            IntegrationAuthConfig.integration_id == integration_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(
        self,
        integration_id: str,
        base_url: str | None = None,
        auth_mode: str = "none",
        config: dict[str, Any] | None = None,
    ) -> IntegrationAuthConfig:
        """Create or update auth config."""
        payload = config or {}
        values = {
            "base_url": base_url,
            "auth_mode": auth_mode,
            "config": _encrypt_json_blob(self.secret_manager, payload),
            "api_key": _encrypt_secret(self.secret_manager, payload.get("api_key")),
            "api_key_header": payload.get("api_key_header"),
            "api_key_query_name": payload.get("api_key_query_name"),
            "bearer_token": _encrypt_secret(self.secret_manager, payload.get("bearer_token")),
            "token_value": _encrypt_secret(self.secret_manager, payload.get("token_value")),
            "token_header": payload.get("token_header"),
            "token_prefix": payload.get("token_prefix"),
            "basic_username": payload.get("basic_username"),
            "basic_password": _encrypt_secret(self.secret_manager, payload.get("basic_password")),
            "oauth_token_url": payload.get("oauth_token_url"),
            "oauth_client_id": payload.get("oauth_client_id"),
            "oauth_client_secret": _encrypt_secret(self.secret_manager, payload.get("oauth_client_secret")),
            "oauth_scope": payload.get("oauth_scope"),
            "oauth_audience": payload.get("oauth_audience"),
            "token_url": payload.get("token_url"),
            "token_request_method": payload.get("token_request_method"),
            "token_request_body": _encrypt_json_blob(self.secret_manager, payload.get("token_request_body")),
            "token_request_headers": _encrypt_json_blob(
                self.secret_manager,
                _encrypt_named_mapping_values(self.secret_manager, payload.get("token_request_headers") or {}),
            ),
            "token_response_path": payload.get("token_response_path"),
            "token_expiry_seconds": payload.get("token_expiry_seconds"),
            "token_expiry_path": payload.get("token_expiry_path"),
            "custom_headers": _encrypt_json_blob(
                self.secret_manager,
                _encrypt_named_mapping_values(self.secret_manager, payload.get("custom_headers") or {}),
            ),
            "updated_at": now_utc_string(),
        }

        auth = self.get_by_integration(integration_id)
        if auth:
            for key, value in values.items():
                setattr(auth, key, value)
        else:
            auth = IntegrationAuthConfig(integration_id=integration_id, **values)
            self.session.add(auth)

        self.session.commit()
        logger.info("Auth config saved: integration=%s mode=%s", integration_id, auth_mode)
        return auth

    def delete(self, integration_id: str) -> bool:
        """Delete auth config."""
        stmt = delete(IntegrationAuthConfig).where(
            IntegrationAuthConfig.integration_id == integration_id
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


# ---------------------------------------------------------------------------
# Security Scan repositories
# ---------------------------------------------------------------------------


class SecurityScanRepository:
    """Repository for SecurityScan CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[SecurityScan]:
        stmt = select(SecurityScan).order_by(SecurityScan.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, scan_id: str) -> SecurityScan | None:
        stmt = select(SecurityScan).where(SecurityScan.id == scan_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> SecurityScan:
        model = SecurityScan(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def update(self, scan_id: str, **kwargs) -> SecurityScan | None:
        model = self.get_by_id(scan_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            self.session.commit()
        return model

    def delete(self, scan_id: str) -> bool:
        stmt = delete(SecurityScan).where(SecurityScan.id == scan_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class RemediationStatusRepository:
    """Repository for RemediationStatus operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_scan_id(self, scan_id: str) -> RemediationStatus | None:
        stmt = select(RemediationStatus).where(RemediationStatus.scan_id == scan_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(self, scan_id: str, **kwargs) -> RemediationStatus:
        model = self.get_by_scan_id(scan_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            model.updated_at = now_utc_string()
        else:
            import uuid
            model = RemediationStatus(
                id=str(uuid.uuid4()),
                scan_id=scan_id,
                created_at=now_utc_string(),
                **kwargs,
            )
            self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Monitoring repositories
# ---------------------------------------------------------------------------


class MonitoredServerRepository:
    """Repository for MonitoredServer CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[MonitoredServer]:
        stmt = select(MonitoredServer).order_by(MonitoredServer.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, server_id: str) -> MonitoredServer | None:
        stmt = select(MonitoredServer).where(MonitoredServer.id == server_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> MonitoredServer:
        model = MonitoredServer(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def update(self, server_id: str, **kwargs) -> MonitoredServer | None:
        model = self.get_by_id(server_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            self.session.commit()
        return model

    def delete(self, server_id: str) -> bool:
        stmt = delete(MonitoredServer).where(MonitoredServer.id == server_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class MonitoringCheckRepository:
    """Repository for MonitoringCheck operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_server(self, server_id: str, limit: int = 50) -> list[MonitoringCheck]:
        stmt = (
            select(MonitoringCheck)
            .where(MonitoringCheck.server_id == server_id)
            .order_by(MonitoringCheck.timestamp.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> MonitoringCheck:
        model = MonitoringCheck(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def prune(self, server_id: str, keep: int = 50) -> int:
        """Remove oldest checks beyond keep limit."""
        subq = (
            select(MonitoringCheck.id)
            .where(MonitoringCheck.server_id == server_id)
            .order_by(MonitoringCheck.timestamp.desc())
            .offset(keep)
        )
        stmt = delete(MonitoringCheck).where(MonitoringCheck.id.in_(subq))
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount


# ---------------------------------------------------------------------------
# Integration Version repository
# ---------------------------------------------------------------------------


class IntegrationVersionRepository:
    """Repository for IntegrationVersion operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_integration(self, integration_id: str) -> list[IntegrationVersion]:
        stmt = (
            select(IntegrationVersion)
            .where(IntegrationVersion.integration_id == integration_id)
            .order_by(IntegrationVersion.created_at.desc())
        )
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, version_id: str) -> IntegrationVersion | None:
        stmt = select(IntegrationVersion).where(IntegrationVersion.id == version_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> IntegrationVersion:
        model = IntegrationVersion(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Settings repositories
# ---------------------------------------------------------------------------


class TeamSettingsRepository:
    """Repository for TeamSettings operations."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, settings_id: str = "default") -> TeamSettings | None:
        stmt = select(TeamSettings).where(TeamSettings.id == settings_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(self, settings_id: str = "default", **kwargs) -> TeamSettings:
        model = self.get(settings_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
        else:
            model = TeamSettings(id=settings_id, created_at=now_utc_string(), **kwargs)
            self.session.add(model)
        self.session.commit()
        return model


class TeamInviteRepository:
    """Repository for TeamInvite operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[TeamInvite]:
        stmt = select(TeamInvite).order_by(TeamInvite.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def list_pending(self) -> list[TeamInvite]:
        stmt = (
            select(TeamInvite)
            .where(TeamInvite.status == "pending")
            .order_by(TeamInvite.created_at.desc())
        )
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, invite_id: str) -> TeamInvite | None:
        stmt = select(TeamInvite).where(TeamInvite.id == invite_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> TeamInvite:
        model = TeamInvite(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def cancel(self, invite_id: str) -> TeamInvite | None:
        model = self.get_by_id(invite_id)
        if model and model.status == "pending":
            model.status = "cancelled"
            model.cancelled_at = now_utc_string()
            self.session.commit()
        return model


class UserPreferencesRepository:
    """Repository for UserPreferences operations."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, prefs_id: str = "default") -> UserPreferences | None:
        stmt = select(UserPreferences).where(UserPreferences.id == prefs_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(self, prefs_id: str = "default", **kwargs) -> UserPreferences:
        model = self.get(prefs_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            model.updated_at = now_utc_string()
        else:
            model = UserPreferences(
                id=prefs_id,
                updated_at=now_utc_string(),
                **kwargs,
            )
            self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Playground repositories
# ---------------------------------------------------------------------------


class PlaygroundSessionRepository:
    """Repository for PlaygroundSession operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[PlaygroundSession]:
        stmt = select(PlaygroundSession).order_by(PlaygroundSession.connected_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, session_id: str) -> PlaygroundSession | None:
        stmt = select(PlaygroundSession).where(PlaygroundSession.id == session_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> PlaygroundSession:
        model = PlaygroundSession(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def update(self, session_id: str, **kwargs) -> PlaygroundSession | None:
        model = self.get_by_id(session_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            self.session.commit()
        return model

    def delete(self, session_id: str) -> bool:
        stmt = delete(PlaygroundSession).where(PlaygroundSession.id == session_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class PlaygroundExecutionRepository:
    """Repository for PlaygroundExecution operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_session(self, session_id: str, limit: int = 50) -> list[PlaygroundExecution]:
        stmt = (
            select(PlaygroundExecution)
            .where(PlaygroundExecution.session_id == session_id)
            .order_by(PlaygroundExecution.executed_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> PlaygroundExecution:
        model = PlaygroundExecution(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# LLM repositories
# ---------------------------------------------------------------------------


class LLMConfigRepository:
    """Repository for LLMConfig CRUD operations."""

    def __init__(
        self,
        session: Session,
        secret_manager: DashboardSecretManager | None = None,
    ):
        self.session = session
        self.secret_manager = secret_manager

    def list_all(self) -> list[LLMConfig]:
        stmt = select(LLMConfig).order_by(LLMConfig.updated_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, config_id: str) -> LLMConfig | None:
        stmt = select(LLMConfig).where(LLMConfig.id == config_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_default(self) -> LLMConfig | None:
        """Get the default LLM config for analysis.

        Returns the config marked as is_default, or the first enabled config
        if no default is explicitly set. Returns None if no configs exist.
        """
        configs = self.list_all()

        # Find explicitly marked default
        default = next((c for c in configs if c.is_default and c.enabled), None)

        # Fallback to first enabled config
        if not default:
            default = next((c for c in configs if c.enabled), None)

        return default

    def upsert(self, config_id: str, **kwargs) -> LLMConfig:
        try:
            if self.secret_manager is not None:
                secret_fields = ("embedding_api_key", "api_key", "bearer_token", "password")
                for field in secret_fields:
                    if field in kwargs:
                        kwargs[field] = _encrypt_secret(self.secret_manager, kwargs.get(field))

                structured_fields = ("custom_headers", "vllm_auth_headers", "vllm_token_auth", "vllm_oauth2")
                for field in structured_fields:
                    if field in kwargs:
                        payload = kwargs.get(field)
                        if field.endswith("headers"):
                            payload = _encrypt_named_mapping_values(self.secret_manager, payload or {})
                        kwargs[field] = _encrypt_json_blob(self.secret_manager, payload)

            # Handle auto-default logic
            is_default = kwargs.get("is_default", False)
            model = self.get_by_id(config_id)
            is_new = model is None

            # If marking this config as default, unset other defaults
            if is_default:
                try:
                    self.clear_default()
                except Exception as e:
                    logger.warning("Failed to clear other defaults: %s", e)

            # If this is the first config and is_default not explicitly set, make it default
            if is_new and not is_default:
                try:
                    existing = self.list_all()
                    if len(existing) == 0:
                        kwargs["is_default"] = True
                        logger.info("First LLM config created; automatically setting as default")
                except Exception as e:
                    logger.warning("Failed to check for first config: %s", e)

            # Update or create the model
            if model:
                for k, v in kwargs.items():
                    setattr(model, k, v)
            else:
                model = LLMConfig(id=config_id, **kwargs)
                self.session.add(model)

            self.session.commit()
            return model
        except Exception as e:
            logger.error("Error in upsert: %s", e, exc_info=True)
            self.session.rollback()
            raise

    def delete(self, config_id: str) -> bool:
        """Delete a config. If it's the default, auto-select the next enabled config."""
        try:
            config = self.get_by_id(config_id)
            was_default = config and config.is_default

            stmt = delete(LLMConfig).where(LLMConfig.id == config_id)
            result = self.session.execute(stmt)
            self.session.commit()

            deleted = result.rowcount > 0

            # If deleted config was default, auto-select next enabled config
            if deleted and was_default:
                try:
                    remaining = self.list_all()
                    next_enabled = next((c for c in remaining if c.enabled), None)
                    if next_enabled:
                        self.upsert(next_enabled.id, is_default=True)
                        logger.info("Default LLM deleted; auto-setting next enabled config as default: %s", next_enabled.id)
                except Exception as e:
                    logger.warning("Failed to auto-promote next config: %s", e)

            return deleted
        except Exception as e:
            logger.error("Error in delete: %s", e, exc_info=True)
            self.session.rollback()
            raise

    def clear_default(self) -> None:
        """Reset is_default on all configs."""
        from sqlalchemy import update
        stmt = update(LLMConfig).values(is_default=False)
        self.session.execute(stmt)
        self.session.commit()

    def clear_default_embedding(self) -> None:
        """Reset is_default_embedding on all configs."""
        from sqlalchemy import update
        stmt = update(LLMConfig).values(is_default_embedding=False)
        self.session.execute(stmt)
        self.session.commit()


class LLMLogRepository:
    """Repository for LLMLog operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_recent(self, limit: int = 500) -> list[LLMLog]:
        stmt = (
            select(LLMLog)
            .order_by(LLMLog.created_at.desc())
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> LLMLog:
        model = LLMLog(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Deployment repository
# ---------------------------------------------------------------------------


class DeploymentRepository:
    """Repository for DeploymentRecord CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_integration(self, integration_id: str) -> list[DeploymentRecord]:
        stmt = (
            select(DeploymentRecord)
            .where(DeploymentRecord.integration_id == integration_id)
            .order_by(DeploymentRecord.created_at.desc())
        )
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> DeploymentRecord:
        model = DeploymentRecord(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Dashboard User repository (auth)
# ---------------------------------------------------------------------------


class DashboardUserRepository:
    """Repository for DashboardUser CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: str) -> DashboardUser | None:
        stmt = select(DashboardUser).where(DashboardUser.id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_email(self, email: str) -> DashboardUser | None:
        stmt = select(DashboardUser).where(DashboardUser.email == email)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_username(self, username: str) -> DashboardUser | None:
        stmt = select(DashboardUser).where(DashboardUser.username == username)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_github_id(self, github_id: str) -> DashboardUser | None:
        stmt = select(DashboardUser).where(DashboardUser.github_id == github_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[DashboardUser]:
        stmt = select(DashboardUser).order_by(DashboardUser.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def count(self) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(DashboardUser)
        return self.session.execute(stmt).scalar() or 0

    def create(self, **kwargs) -> DashboardUser:
        model = DashboardUser(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def update(self, user_id: str, **kwargs) -> DashboardUser | None:
        model = self.get_by_id(user_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            self.session.commit()
        return model


# ---------------------------------------------------------------------------
# CI/CD repositories (replacing in-memory stores)
# ---------------------------------------------------------------------------


class CiWebhookRepository:
    """Repository for CI webhook projects."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[CiWebhook]:
        stmt = select(CiWebhook).order_by(CiWebhook.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_name(self, project_name: str) -> CiWebhook | None:
        stmt = select(CiWebhook).where(CiWebhook.project_name == project_name)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> CiWebhook:
        model = CiWebhook(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def delete(self, project_name: str) -> bool:
        stmt = delete(CiWebhook).where(CiWebhook.project_name == project_name)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class CiRunRepository:
    """Repository for CI pipeline run results."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self, project_name: str | None = None, limit: int = 200, offset: int = 0) -> list[CiRun]:
        stmt = select(CiRun).order_by(CiRun.timestamp.desc())
        if project_name:
            stmt = stmt.where(CiRun.project_name == project_name)
        stmt = stmt.offset(offset).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def count(self, project_name: str | None = None) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(CiRun)
        if project_name:
            stmt = stmt.where(CiRun.project_name == project_name)
        return self.session.execute(stmt).scalar() or 0

    def create(self, **kwargs) -> CiRun:
        model = CiRun(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def prune(self, keep: int = 200) -> int:
        """Remove oldest runs beyond keep limit."""
        subq = (
            select(CiRun.id)
            .order_by(CiRun.timestamp.desc())
            .offset(keep)
        )
        stmt = delete(CiRun).where(CiRun.id.in_(subq))
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount


# ---------------------------------------------------------------------------
# Alert repositories (replacing in-memory stores)
# ---------------------------------------------------------------------------


class AlertRuleRepository:
    """Repository for AlertRule operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_by_server(self, server_id: str) -> list[AlertRule]:
        stmt = select(AlertRule).where(AlertRule.server_id == server_id).order_by(AlertRule.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, rule_id: str) -> AlertRule | None:
        stmt = select(AlertRule).where(AlertRule.id == rule_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> AlertRule:
        model = AlertRule(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def delete(self, rule_id: str) -> bool:
        stmt = delete(AlertRule).where(AlertRule.id == rule_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class FiredAlertRepository:
    """Repository for FiredAlert operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self, limit: int = 50) -> list[FiredAlert]:
        stmt = select(FiredAlert).order_by(FiredAlert.timestamp.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> FiredAlert:
        model = FiredAlert(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def acknowledge(self, alert_id: str) -> FiredAlert | None:
        stmt = select(FiredAlert).where(FiredAlert.id == alert_id)
        model = self.session.execute(stmt).scalar_one_or_none()
        if model:
            model.acknowledged = True
            self.session.commit()
        return model

    def prune(self, keep: int = 500) -> int:
        subq = (
            select(FiredAlert.id)
            .order_by(FiredAlert.timestamp.desc())
            .offset(keep)
        )
        stmt = delete(FiredAlert).where(FiredAlert.id.in_(subq))
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount


# ---------------------------------------------------------------------------
# Notification repositories
# ---------------------------------------------------------------------------


class NotificationChannelRepository:
    """Repository for NotificationChannel operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[NotificationChannel]:
        stmt = select(NotificationChannel).order_by(NotificationChannel.created_at.desc())
        return self.session.execute(stmt).scalars().all()

    def list_enabled(self) -> list[NotificationChannel]:
        stmt = (
            select(NotificationChannel)
            .where(NotificationChannel.enabled)
            .order_by(NotificationChannel.created_at.desc())
        )
        return self.session.execute(stmt).scalars().all()

    def get_by_id(self, channel_id: str) -> NotificationChannel | None:
        stmt = select(NotificationChannel).where(NotificationChannel.id == channel_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, **kwargs) -> NotificationChannel:
        model = NotificationChannel(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model

    def update(self, channel_id: str, **kwargs) -> NotificationChannel | None:
        model = self.get_by_id(channel_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            self.session.commit()
        return model

    def delete(self, channel_id: str) -> bool:
        stmt = delete(NotificationChannel).where(NotificationChannel.id == channel_id)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount > 0


class NotificationLogRepository:
    """Repository for NotificationLog operations."""

    def __init__(self, session: Session):
        self.session = session

    def list_recent(self, limit: int = 100) -> list[NotificationLog]:
        stmt = select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def create(self, **kwargs) -> NotificationLog:
        model = NotificationLog(**kwargs)
        self.session.add(model)
        self.session.commit()
        return model


# ---------------------------------------------------------------------------
# Scan Policy repository (replacing in-memory store)
# ---------------------------------------------------------------------------


class ScanPolicyRepository:
    """Repository for ScanPolicy operations."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, policy_id: str = "default") -> ScanPolicy | None:
        stmt = select(ScanPolicy).where(ScanPolicy.id == policy_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(self, policy_id: str = "default", **kwargs) -> ScanPolicy:
        model = self.get(policy_id)
        if model:
            for k, v in kwargs.items():
                setattr(model, k, v)
            model.updated_at = now_utc_string()
        else:
            model = ScanPolicy(id=policy_id, updated_at=now_utc_string(), **kwargs)
            self.session.add(model)
        self.session.commit()
        return model

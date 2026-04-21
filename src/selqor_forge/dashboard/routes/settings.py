# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Team and user settings routes — team management, preferences, scan policies, data export."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from selqor_forge.dashboard.middleware import Ctx, local_only_feature_error
from selqor_forge.dashboard.repositories import (
    ScanPolicyRepository,
    UserPreferencesRepository,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class InviteBody(BaseModel):
    """Request to invite a team member."""
    email: str
    role: str = "member"  # "admin", "member", "viewer"


class PreferencesBody(BaseModel):
    """User preferences."""
    theme: str = "light"
    notifications_enabled: bool = True
    default_scan_mode: str = "basic"
    auto_remediate: bool = False
    dashboard_layout: str = "default"


# ---------------------------------------------------------------------------
# Helpers (model â†’ dict)
# ---------------------------------------------------------------------------

def _model_to_dict(model) -> dict:
    """Convert an ORM model to a plain dict, filtering SQLAlchemy internals."""
    return {k: v for k, v in model.__dict__.items() if not k.startswith("_")}


def _preferences_payload(data: dict | None = None) -> dict:
    """Normalize persisted preferences to the public local-only defaults."""
    payload = data or {}
    theme = payload.get("theme")
    if theme not in {"light", "dark"}:
        theme = "light"
    scan_mode = payload.get("default_scan_mode")
    if scan_mode not in {"basic", "full"}:
        scan_mode = "basic"
    return {
        "theme": theme,
        "notifications_enabled": payload.get("notifications_enabled", True),
        "default_scan_mode": scan_mode,
        "auto_remediate": payload.get("auto_remediate", False),
        "dashboard_layout": payload.get("dashboard_layout", "default"),
        "updated_at": payload.get("updated_at"),
    }


def _local_only_export_placeholder(feature: str) -> dict:
    """Shared disabled payload shape for local-only export surfaces."""
    return {
        "status": "disabled",
        "reason": "LOCAL_ONLY_BUILD",
        "feature": feature,
        "message": "Team management is not included in the public local-only build.",
    }


# ---------------------------------------------------------------------------
# Team settings
# ---------------------------------------------------------------------------

@router.get("/team")
async def get_team(ctx: Ctx) -> dict:
    """Get team settings and members list."""
    del ctx
    raise local_only_feature_error("team_management")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

@router.post("/team/invite")
async def send_invite(ctx: Ctx, body: InviteBody) -> dict:
    """Send a team invite."""
    del ctx, body
    raise local_only_feature_error("team_management")


@router.get("/team/invites")
async def list_invites(ctx: Ctx) -> dict:
    """List pending invites."""
    del ctx
    raise local_only_feature_error("team_management")


@router.delete("/team/invites/{invite_id}")
async def cancel_invite(ctx: Ctx, invite_id: str) -> dict:
    """Cancel a pending invite."""
    del ctx, invite_id
    raise local_only_feature_error("team_management")


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def get_preferences(ctx: Ctx) -> dict:
    """Get user preferences."""
    session = ctx.db_session_factory()
    try:
        repo = UserPreferencesRepository(session)
        prefs = repo.get()
        if prefs is None:
            return _preferences_payload()
        return _preferences_payload(_model_to_dict(prefs))
    finally:
        session.close()


@router.put("/preferences")
async def save_preferences(ctx: Ctx, body: PreferencesBody) -> dict:
    """Save user preferences."""
    session = ctx.db_session_factory()
    try:
        repo = UserPreferencesRepository(session)
        prefs = repo.upsert(
            theme=body.theme,
            notifications_enabled=body.notifications_enabled,
            default_scan_mode=body.default_scan_mode,
            auto_remediate=body.auto_remediate,
            dashboard_layout=body.dashboard_layout,
        )
        return _preferences_payload(_model_to_dict(prefs))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Scan Policies — organisation-level security thresholds and rules
# ---------------------------------------------------------------------------

_SCAN_POLICY_DEFAULTS: dict = {
    "id": "default",
    "min_score_threshold": 70,
    "blocked_severities": [],
    "require_llm_analysis": False,
    "require_code_pattern_analysis": False,
    "require_dependency_scan": False,
    "max_critical_findings": 0,
    "max_high_findings": 5,
    "auto_fail_on_critical": True,
    "updated_at": None,
}


class ScanPolicyBody(BaseModel):
    """Organisation scan policy — enforced on all scans and CI runs."""
    min_score_threshold: int = Field(70, ge=0, le=100, description="Minimum passing security score")
    blocked_severities: list[str] = Field(
        default_factory=list,
        description="Severity levels that automatically fail a scan (e.g. ['critical'])",
    )
    require_llm_analysis: bool = Field(False, description="Require LLM analysis on all scans")
    require_code_pattern_analysis: bool = Field(False, description="Require code pattern analysis")
    require_dependency_scan: bool = Field(False, description="Require dependency scanning")
    max_critical_findings: int = Field(0, ge=0, description="Max allowed critical findings (0 = zero tolerance)")
    max_high_findings: int = Field(5, ge=0, description="Max allowed high severity findings")
    auto_fail_on_critical: bool = Field(True, description="Auto-fail scans with any critical findings")


@router.get("/scan-policy")
async def get_scan_policy(ctx: Ctx) -> dict:
    """Get the current organisation scan policy."""
    session = ctx.db_session_factory()
    try:
        repo = ScanPolicyRepository(session)
        policy = repo.get(policy_id="default")
        if policy is None:
            return {**_SCAN_POLICY_DEFAULTS}
        return _model_to_dict(policy)
    finally:
        session.close()


@router.put("/scan-policy")
async def update_scan_policy(ctx: Ctx, body: ScanPolicyBody) -> dict:
    """Update the organisation scan policy."""
    session = ctx.db_session_factory()
    try:
        repo = ScanPolicyRepository(session)
        policy = repo.upsert(
            policy_id="default",
            min_score_threshold=body.min_score_threshold,
            blocked_severities=body.blocked_severities,
            require_llm_analysis=body.require_llm_analysis,
            require_code_pattern_analysis=body.require_code_pattern_analysis,
            require_dependency_scan=body.require_dependency_scan,
            max_critical_findings=body.max_critical_findings,
            max_high_findings=body.max_high_findings,
            auto_fail_on_critical=body.auto_fail_on_critical,
        )
        return _model_to_dict(policy)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Data Export — download all application data as JSON backup
# ---------------------------------------------------------------------------


def _export_scan_policy(session) -> dict:
    """Read scan policy from DB for export; falls back to defaults."""
    repo = ScanPolicyRepository(session)
    policy = repo.get(policy_id="default")
    if policy is None:
        return {**_SCAN_POLICY_DEFAULTS}
    return _model_to_dict(policy)


@router.get("/export")
async def export_data(ctx: Ctx) -> Response:
    """Export all application data as a JSON backup.

    Includes: scans, integrations, monitoring servers, team settings,
    preferences, scan policies. Excludes: API keys/secrets.
    """
    session = ctx.db_session_factory()
    try:
        from selqor_forge.dashboard.repositories import (
            MonitoredServerRepository,
            MonitoringCheckRepository,
        )

        prefs_repo = UserPreferencesRepository(session)
        server_repo = MonitoredServerRepository(session)

        team_data = _local_only_export_placeholder("team_management")
        invites_data: list[dict] = []

        # Preferences
        prefs = prefs_repo.get()
        prefs_data = _preferences_payload(_model_to_dict(prefs) if prefs else None)

        # Monitoring servers
        servers = server_repo.list_all()
        servers_data = []
        check_repo = MonitoringCheckRepository(session)
        for s in servers:
            sd = {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "transport": s.transport,
                "check_interval_seconds": s.check_interval_seconds,
                "status": s.status,
            }
            checks = check_repo.list_by_server(s.id, limit=50)
            sd["check_history"] = [
                {
                    "timestamp": c.timestamp,
                    "status": c.status,
                    "latency_ms": c.latency_ms,
                    "tool_count": c.tool_count,
                    "error": c.error,
                }
                for c in checks
            ]
            servers_data.append(sd)

        # Scans
        scans_data = []
        try:
            from selqor_forge.dashboard.repositories import ScanRepository
            scan_repo = ScanRepository(session)
            scans = scan_repo.list_all(limit=500)
            scans_data = [_model_to_dict(s) for s in scans]
        except Exception:
            pass

        # Integrations
        integrations_data = []
        try:
            from selqor_forge.dashboard.repositories import IntegrationRepository
            int_repo = IntegrationRepository(session)
            integrations = int_repo.list_all()
            integrations_data = [_model_to_dict(i) for i in integrations]
        except Exception:
            pass

        export = {
            "export_version": "1.0",
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "application": "selqor-forge",
            "data": {
                "team": team_data,
                "invites": invites_data,
                "preferences": prefs_data,
                "scan_policy": _export_scan_policy(session),
                "monitoring_servers": servers_data,
                "scans": scans_data,
                "integrations": integrations_data,
            },
        }

        content = json.dumps(export, indent=2, default=str)
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

        return Response(
            content=content.encode("utf-8"),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="selqor-forge-export-{timestamp}.json"',
            },
        )
    finally:
        session.close()

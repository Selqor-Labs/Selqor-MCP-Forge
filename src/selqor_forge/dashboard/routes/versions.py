# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Version management routes for integration snapshots."""

from __future__ import annotations

import difflib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import IntegrationVersionRepository

router = APIRouter(prefix="/integrations", tags=["versions"])


class CreateVersionBody(BaseModel):
    """Request to create a version snapshot."""
    label: str | None = None
    notes: str | None = None


def _safe_spec(spec) -> dict:
    """Safely convert a spec value to a dict for version storage.

    The spec field may be a dict (inline), a JSON string, or a URL string.
    """
    if isinstance(spec, dict):
        return spec
    if not spec:
        return {}
    try:
        return json.loads(spec)
    except (json.JSONDecodeError, TypeError):
        # It's a URL or other non-JSON string — store as reference
        return {"$ref": spec}


def _version_to_dict(v) -> dict:
    """Convert an IntegrationVersion ORM model to a plain dict."""
    return {
        "id": v.id,
        "integration_id": v.integration_id,
        "label": v.label,
        "notes": v.notes,
        "created_at": v.created_at,
        "spec": v.spec,
        "tool_plan": v.tool_plan,
    }


# ---------------------------------------------------------------------------
# List versions
# ---------------------------------------------------------------------------

@router.get("/{integration_id}/versions")
async def list_versions(ctx: Ctx, integration_id: str) -> dict:
    """List version history for an integration."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationVersionRepository(session)
        db_versions = repo.list_by_integration(integration_id)
        versions = [
            {
                "id": v.id,
                "label": v.label,
                "notes": v.notes,
                "created_at": v.created_at,
            }
            for v in db_versions
        ]
        return {"integration_id": integration_id, "versions": versions, "total": len(versions)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Create version
# ---------------------------------------------------------------------------

@router.post("/{integration_id}/versions")
async def create_version(ctx: Ctx, integration_id: str, body: CreateVersionBody) -> dict:
    """Create a new version snapshot of the current integration state."""
    session = ctx.db_session_factory()
    try:
        from selqor_forge.dashboard.repositories import IntegrationRepository, ToolConfigRepository

        int_repo = IntegrationRepository(session)
        integration = int_repo.get_by_id(integration_id)
        if integration is None:
            raise HTTPException(status_code=404, detail="Integration not found")

        # Read tool plan from DB if available
        tc_repo = ToolConfigRepository(session)
        tool_config = tc_repo.get_by_integration(integration_id)
        tool_plan = {"tools": tool_config.tools, "source": tool_config.source} if tool_config else None

        version_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"

        repo = IntegrationVersionRepository(session)
        repo.create(
            id=version_id,
            integration_id=integration_id,
            label=body.label or f"v-{now[:10]}",
            notes=body.notes,
            created_at=now,
            spec=_safe_spec(integration.spec),
            tool_plan=tool_plan,
        )

        return {
            "id": version_id,
            "integration_id": integration_id,
            "label": body.label or f"v-{now[:10]}",
            "created_at": now,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Get version
# ---------------------------------------------------------------------------

@router.get("/{integration_id}/versions/{version_id}")
async def get_version(ctx: Ctx, integration_id: str, version_id: str) -> dict:
    """Get a specific version snapshot."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationVersionRepository(session)
        version = repo.get_by_id(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return _version_to_dict(version)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Diff versions
# ---------------------------------------------------------------------------

@router.get("/{integration_id}/versions/{v1}/diff/{v2}")
async def diff_versions(ctx: Ctx, integration_id: str, v1: str, v2: str) -> dict:
    """Compare two versions and return unified diff."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationVersionRepository(session)
        version1 = repo.get_by_id(v1)
        version2 = repo.get_by_id(v2)

        if version1 is None:
            raise HTTPException(status_code=404, detail=f"Version {v1} not found")
        if version2 is None:
            raise HTTPException(status_code=404, detail=f"Version {v2} not found")

        v1_dict = _version_to_dict(version1)
        v2_dict = _version_to_dict(version2)

        # Pretty-print both for readable diff
        v1_text = json.dumps(v1_dict.get("spec", {}), indent=2, sort_keys=True).splitlines(keepends=True)
        v2_text = json.dumps(v2_dict.get("spec", {}), indent=2, sort_keys=True).splitlines(keepends=True)

        spec_diff = "".join(difflib.unified_diff(
            v1_text, v2_text,
            fromfile=f"v1 ({v1_dict.get('label', v1)})",
            tofile=f"v2 ({v2_dict.get('label', v2)})",
        ))

        # Diff tool plans too
        v1_tools = json.dumps(v1_dict.get("tool_plan", {}), indent=2, sort_keys=True).splitlines(keepends=True)
        v2_tools = json.dumps(v2_dict.get("tool_plan", {}), indent=2, sort_keys=True).splitlines(keepends=True)

        tool_plan_diff = "".join(difflib.unified_diff(
            v1_tools, v2_tools,
            fromfile=f"v1 tool_plan ({v1_dict.get('label', v1)})",
            tofile=f"v2 tool_plan ({v2_dict.get('label', v2)})",
        ))

        return {
            "integration_id": integration_id,
            "v1": {"id": v1, "label": v1_dict.get("label"), "created_at": v1_dict.get("created_at")},
            "v2": {"id": v2, "label": v2_dict.get("label"), "created_at": v2_dict.get("created_at")},
            "spec_diff": spec_diff or "(no differences)",
            "tool_plan_diff": tool_plan_diff or "(no differences)",
        }
    finally:
        session.close()

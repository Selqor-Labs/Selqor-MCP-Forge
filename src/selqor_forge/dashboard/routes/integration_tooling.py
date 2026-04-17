# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration tooling endpoints: view, update, and delete manual tool configs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    IntegrationToolConfig,
    UpdateToolingRequest,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import ArtifactRepository, IntegrationRepository, ToolConfigRepository

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/tooling
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/tooling")
def get_tooling(ctx: Ctx, integration_id: str) -> JSONResponse:
    """Return the current tooling configuration for the integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    _require_integration_exists(ctx, integration_id)

    # Try manual config from database first
    manual = _load_manual_tool_config(ctx, integration_id)
    if manual is not None and manual.get("tools"):
        return JSONResponse(
            status_code=200,
            content={
                "source": "manual",
                "updated_at": manual.get("updated_at", now_utc_string()),
                "tools": manual.get("tools", []),
                "endpoints": [],
                "warnings": ["Loaded manually configured tool groups."],
            },
        )

    # Fallback: try latest generated tool plan.
    # Prefer analysis-plan.json (small, ~100KB) over tool-plan.json (can be
    # 400MB+ for large multi-spec integrations due to duplicated input_schema).
    plan = _load_latest_analysis_plan(ctx, integration_id)
    if plan is None:
        plan = _load_latest_tool_plan(ctx, integration_id)
    if plan is not None and plan.get("tools"):
        return JSONResponse(
            status_code=200,
            content={
                "source": "generated",
                "updated_at": now_utc_string(),
                "tools": plan.get("tools", []),
                "endpoints": [],
                "warnings": plan.get("warnings", []),
            },
        )

    # Default empty
    return JSONResponse(
        status_code=200,
        content={
            "source": "default",
            "updated_at": now_utc_string(),
            "tools": [],
            "endpoints": [],
            "warnings": [],
        },
    )


# ---------------------------------------------------------------------------
# PUT /integrations/{integration_id}/tooling
# ---------------------------------------------------------------------------


@router.put("/integrations/{integration_id}/tooling")
def update_tooling(
    ctx: Ctx,
    integration_id: str,
    body: UpdateToolingRequest,
) -> JSONResponse:
    """Save manual tooling override for the integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    _require_integration_exists(ctx, integration_id)

    tools = [t.model_dump() for t in body.tools]
    if not tools:
        raise HTTPException(
            status_code=400,
            detail="at least one valid tool with endpoint coverage is required",
        )

    config = IntegrationToolConfig(
        integration_id=integration_id,
        updated_at=now_utc_string(),
        tools=body.tools,
    )

    _save_manual_tool_config(ctx, integration_id, config)
    logger.info("manual tooling saved: integration=%s tools=%d", integration_id, len(tools))
    return JSONResponse(status_code=200, content=config.model_dump())


# ---------------------------------------------------------------------------
# DELETE /integrations/{integration_id}/tooling
# ---------------------------------------------------------------------------


@router.delete("/integrations/{integration_id}/tooling")
def delete_tooling(ctx: Ctx, integration_id: str) -> JSONResponse:
    """Remove manual tooling override."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    _require_integration_exists(ctx, integration_id)

    session = ctx.db_session_factory()
    try:
        repo = ToolConfigRepository(session)
        repo.delete(integration_id)
        logger.info("manual tooling removed from database: integration=%s", integration_id)
    finally:
        session.close()

    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_integration_exists(ctx: Ctx, integration_id: str) -> None:
    """Check if integration exists in the database."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        if repo.get_by_id(integration_id):
            return
    finally:
        session.close()
    raise HTTPException(status_code=404, detail="integration not found")


def _load_manual_tool_config(ctx: Ctx, integration_id: str) -> dict | None:
    """Load manual tool config from the database."""
    session = ctx.db_session_factory()
    try:
        repo = ToolConfigRepository(session)
        config = repo.get_by_integration(integration_id)
        if config and config.tools:
            return {
                "integration_id": integration_id,
                "tools": config.tools,
                "source": config.source,
                "endpoints": config.endpoints,
                "warnings": config.warnings,
                "updated_at": config.updated_at,
            }
    finally:
        session.close()
    return None


def _save_manual_tool_config(ctx: Ctx, integration_id: str, config: IntegrationToolConfig) -> None:
    """Save manual tool config to the database."""
    session = ctx.db_session_factory()
    try:
        repo = ToolConfigRepository(session)
        tools_list = [t.model_dump() if hasattr(t, 'model_dump') else t for t in config.tools]
        repo.upsert(integration_id, tools=tools_list)
        logger.info("Tool config saved to database: %s", integration_id)
    finally:
        session.close()


def _load_latest_tool_plan(ctx: Ctx, integration_id: str) -> dict | None:
    """Load the most recent tool-plan.json artifact from the database.

    For very large specs (1000+ endpoints) the tool-plan.json can be 100MB+
    because every tool's input_schema contains a full endpoint enum. We use
    a streaming JSON parser approach: load the raw content but extract only
    the tool metadata (name, description, covered_endpoints, confidence)
    and skip the bloated input_schema to keep the response fast.
    """
    import json

    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        artifact = repo.get_latest_by_name(integration_id, "tool-plan.json")
        if not artifact or not artifact.content:
            return None

        content_size = len(artifact.content) if artifact.content else 0

        # For artifacts under 5MB, parse normally
        if content_size < 5 * 1024 * 1024:
            try:
                return json.loads(artifact.content)
            except Exception:
                logger.debug("failed to parse tool-plan.json (%d bytes)", content_size)
                return None

        # For large artifacts, parse and strip input_schema to avoid OOM in the response
        logger.info(
            "tool-plan.json is large (%d MB); stripping input_schema for tooling response",
            content_size // (1024 * 1024),
        )
        try:
            plan = json.loads(artifact.content)
            # Strip the bloated input_schema from each tool — the ToolBuilder
            # doesn't need it (it uses the endpoint catalog from uasf.json).
            for tool in plan.get("tools", []):
                if "input_schema" in tool:
                    del tool["input_schema"]
            return plan
        except Exception:
            logger.warning(
                "failed to parse large tool-plan.json (%d bytes); "
                "falling back to analysis-plan.json",
                content_size,
            )
            return _load_latest_analysis_plan(ctx, integration_id)
    finally:
        session.close()


def _load_latest_analysis_plan(ctx: Ctx, integration_id: str) -> dict | None:
    """Fallback: load analysis-plan.json which is much smaller than tool-plan.json."""
    import json

    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        artifact = repo.get_latest_by_name(integration_id, "analysis-plan.json")
        if artifact and artifact.content:
            try:
                return json.loads(artifact.content)
            except Exception:
                return None
    finally:
        session.close()
    return None

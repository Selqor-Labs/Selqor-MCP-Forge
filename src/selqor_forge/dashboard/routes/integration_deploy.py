# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration deployment endpoints: deploy run output and list deployments."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    DeployRequest,
    DeploymentRecord as DeploymentRecordModel,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import (
    AuthConfigRepository,
    DeploymentRepository,
    IntegrationRepository,
    RunRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /integrations/{integration_id}/runs/{run_id}/deploy
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/runs/{run_id}/deploy")
def deploy_run(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
    body: DeployRequest | None = None,
) -> JSONResponse:
    """Prepare deployment for a generated MCP server."""
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(
            status_code=400, detail="invalid integration or run id"
        )

    integration = _require_integration(ctx, integration_id)
    run = _load_run(ctx, integration_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    target = "typescript"
    transport = "http"   # Default to HTTP so Playground can auto-connect
    http_port = 3333
    if body is not None:
        target = _normalize_target(body.target)
        if body.transport:
            transport = body.transport.strip() or "http"
        if body.http_port is not None:
            http_port = body.http_port

    server_dir_name = (
        "typescript-server" if target == "typescript" else "rust-server"
    )
    server_path = _run_dir(ctx, integration_id, run_id) / server_dir_name
    if not server_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"generated {target} server does not exist for this run; rerun analysis first",
        )

    # Build .env.generated
    auth_data = _load_auth_config(ctx, integration_id)
    env_content = _build_env_file(
        base_url=(auth_data.get("base_url") or "").strip()
        or integration.get("spec", ""),
        auth=auth_data,
        transport=transport,
        http_port=http_port,
    )
    env_path = server_path / ".env.generated"
    env_path.write_text(env_content, encoding="utf-8")

    if target == "typescript":
        command = f"cd {server_path} && cp .env.generated .env && npm install && npm run dev"
    else:
        command = f"cd {server_path} && cp .env.generated .env && cargo run"

    deployment = DeploymentRecordModel(
        deployment_id=f"deploy-{int(time.time() * 1000)}",
        integration_id=integration_id,
        run_id=run_id,
        target=target,
        status="prepared",
        server_path=str(server_path),
        env_path=str(env_path),
        command=command,
        notes="Environment file generated. Ready to test in Playground.",
        created_at=now_utc_string(),
    )

    _persist_deployment(ctx, deployment.model_dump())
    logger.info(
        "deployment prepared: id=%s integration=%s run=%s",
        deployment.deployment_id,
        integration_id,
        run_id,
    )
    return JSONResponse(status_code=200, content=deployment.model_dump())


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/deployments
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/deployments")
def list_deployments(ctx: Ctx, integration_id: str) -> JSONResponse:
    """List deployment records for an integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    deployments = _load_deployments(ctx, integration_id)
    return JSONResponse(
        status_code=200, content={"deployments": deployments}
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_dir(ctx: Ctx, integration_id: str, run_id: str) -> Path:
    return ctx.state_dir / "runs" / integration_id / run_id


def _normalize_target(raw: str) -> str:
    t = raw.strip().lower() or "typescript"
    if t not in ("typescript", "rust"):
        raise HTTPException(
            status_code=400,
            detail="target must be either 'typescript' or 'rust'",
        )
    return t


def _require_integration(ctx: Ctx, integration_id: str) -> dict:
    """Load integration from the database."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        model = repo.get_by_id(integration_id)
        if model is None:
            raise HTTPException(status_code=404, detail="integration not found")
        return {
            "id": model.id,
            "name": model.name,
            "spec": model.spec,
        }
    finally:
        session.close()


def _load_run(ctx: Ctx, integration_id: str, run_id: str) -> dict | None:
    """Load run from the database."""
    session = ctx.db_session_factory()
    try:
        repo = RunRepository(session)
        model = repo.get_by_id(integration_id, run_id)
        if model is None:
            return None
        return {
            "run_id": model.run_id,
            "status": model.status,
            "integration_id": model.integration_id,
        }
    finally:
        session.close()


def _load_auth_config(ctx: Ctx, integration_id: str) -> dict:
    """Load auth config from the database."""
    session = ctx.db_session_factory()
    try:
        repo = AuthConfigRepository(session)
        model = repo.get_by_integration(integration_id)
        if model is None:
            return {"auth_mode": "none"}
        return {
            "auth_mode": model.auth_mode or "none",
            "base_url": model.base_url,
            "api_key": model.api_key,
            "api_key_header": model.api_key_header,
            "api_key_query_name": model.api_key_query_name,
            "bearer_token": model.bearer_token,
            "basic_username": model.basic_username,
            "basic_password": model.basic_password,
            "token_header": model.token_header,
            "token_value": model.token_value,
            "token_prefix": model.token_prefix,
            "token_url": model.token_url,
            "token_request_method": model.token_request_method,
            "token_request_body": model.token_request_body,
            "token_request_headers": model.token_request_headers,
            "token_response_path": model.token_response_path,
            "token_expiry_seconds": model.token_expiry_seconds,
            "token_expiry_path": model.token_expiry_path,
            "oauth_token_url": model.oauth_token_url,
            "oauth_client_id": model.oauth_client_id,
            "oauth_client_secret": model.oauth_client_secret,
            "oauth_scope": model.oauth_scope,
            "oauth_audience": model.oauth_audience,
            "custom_headers": model.custom_headers or {},
        }
    finally:
        session.close()


def _load_deployments(ctx: Ctx, integration_id: str) -> list[dict]:
    """Load deployments from the database."""
    session = ctx.db_session_factory()
    try:
        repo = DeploymentRepository(session)
        models = repo.list_by_integration(integration_id)
        return [
            {
                "deployment_id": m.deployment_id,
                "integration_id": m.integration_id,
                "run_id": m.run_id,
                "target": m.target,
                "status": m.status,
                "server_path": m.server_path,
                "env_path": m.env_path,
                "command": m.command,
                "notes": m.notes,
                "created_at": m.created_at,
            }
            for m in models
        ]
    finally:
        session.close()


def _persist_deployment(ctx: Ctx, deployment: dict) -> None:
    """Persist deployment record to the database."""
    session = ctx.db_session_factory()
    try:
        repo = DeploymentRepository(session)
        repo.create(**deployment)
    except Exception:
        session.rollback()
        logger.debug("failed saving deployment to database", exc_info=True)
    finally:
        session.close()


def _build_env_file(
    base_url: str,
    auth: dict,
    transport: str,
    http_port: int,
) -> str:
    lines = [
        f"FORGE_BASE_URL={base_url.strip()}",
        f"FORGE_TRANSPORT={transport}",
        f"FORGE_HTTP_PORT={http_port}",
        "FORGE_API_KEY=",
        "FORGE_API_KEY_HEADER=x-api-key",
        "FORGE_API_KEY_QUERY_NAME=",
        "FORGE_BEARER_TOKEN=",
        "FORGE_BASIC_USER=",
        "FORGE_BASIC_PASSWORD=",
        "FORGE_TOKEN_HEADER=",
        "FORGE_TOKEN_VALUE=",
        "FORGE_TOKEN_PREFIX=",
        "FORGE_DYNAMIC_TOKEN_URL=",
        "FORGE_DYNAMIC_TOKEN_METHOD=POST",
        "FORGE_DYNAMIC_TOKEN_BODY_JSON={}",
        "FORGE_DYNAMIC_TOKEN_HEADERS_JSON={}",
        "FORGE_DYNAMIC_TOKEN_RESPONSE_PATH=access_token",
        "FORGE_DYNAMIC_TOKEN_EXPIRY_SECONDS=3600",
        "FORGE_DYNAMIC_TOKEN_EXPIRY_PATH=",
        "FORGE_DYNAMIC_TOKEN_HEADER_NAME=Authorization",
        "FORGE_DYNAMIC_TOKEN_HEADER_PREFIX=Bearer",
        "FORGE_STATIC_HEADERS_JSON={}",
        "FORGE_OAUTH_TOKEN_URL=",
        "FORGE_OAUTH_CLIENT_ID=",
        "FORGE_OAUTH_CLIENT_SECRET=",
        "FORGE_OAUTH_SCOPE=",
        "FORGE_OAUTH_AUDIENCE=",
    ]

    mode = auth.get("auth_mode", "none")

    if mode == "api_key":
        if v := auth.get("api_key"):
            lines.append(f"FORGE_API_KEY={v}")
        if v := auth.get("api_key_header"):
            lines.append(f"FORGE_API_KEY_HEADER={v}")
        if v := auth.get("api_key_query_name"):
            lines.append(f"FORGE_API_KEY_QUERY_NAME={v}")
    elif mode == "bearer":
        if v := auth.get("bearer_token"):
            lines.append(f"FORGE_BEARER_TOKEN={v}")
    elif mode == "basic":
        if v := auth.get("basic_username"):
            lines.append(f"FORGE_BASIC_USER={v}")
        if v := auth.get("basic_password"):
            lines.append(f"FORGE_BASIC_PASSWORD={v}")
    elif mode == "token":
        if v := auth.get("token_header"):
            lines.append(f"FORGE_TOKEN_HEADER={v}")
        if v := auth.get("token_value"):
            lines.append(f"FORGE_TOKEN_VALUE={v}")
        if v := auth.get("token_prefix"):
            lines.append(f"FORGE_TOKEN_PREFIX={v}")
    elif mode == "token_based":
        if v := auth.get("token_url"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_URL={v}")
        if v := auth.get("token_request_method"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_METHOD={v}")
        if v := auth.get("token_request_body"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_BODY_JSON={json.dumps(v)}")
        if v := auth.get("token_request_headers"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_HEADERS_JSON={json.dumps(v)}")
        if v := auth.get("token_response_path"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_RESPONSE_PATH={v}")
        if (v := auth.get("token_expiry_seconds")) is not None:
            lines.append(f"FORGE_DYNAMIC_TOKEN_EXPIRY_SECONDS={v}")
        if v := auth.get("token_expiry_path"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_EXPIRY_PATH={v}")
        if v := auth.get("token_header"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_HEADER_NAME={v}")
        if v := auth.get("token_prefix"):
            lines.append(f"FORGE_DYNAMIC_TOKEN_HEADER_PREFIX={v}")
    elif mode == "oauth2_client_credentials":
        if v := auth.get("oauth_token_url"):
            lines.append(f"FORGE_OAUTH_TOKEN_URL={v}")
        if v := auth.get("oauth_client_id"):
            lines.append(f"FORGE_OAUTH_CLIENT_ID={v}")
        if v := auth.get("oauth_client_secret"):
            lines.append(f"FORGE_OAUTH_CLIENT_SECRET={v}")
        if v := auth.get("oauth_scope"):
            lines.append(f"FORGE_OAUTH_SCOPE={v}")
        if v := auth.get("oauth_audience"):
            lines.append(f"FORGE_OAUTH_AUDIENCE={v}")

    custom = auth.get("custom_headers", {})
    if custom:
        lines.append(f"FORGE_STATIC_HEADERS_JSON={json.dumps(custom)}")

    lines.append("")
    return "\n".join(lines)

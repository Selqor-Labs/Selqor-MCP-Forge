# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration auth config and connection-test endpoints."""

from __future__ import annotations

import json
import logging
import time

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    ConnectionTestStatus,
    IntegrationAuthConfig,
    UpdateAuthConfigRequest,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import IntegrationRepository, AuthConfigRepository
from selqor_forge.dashboard.secrets import (
    mask_named_value,
    mask_secret,
    restore_masked_value,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_AUTH_MODES = frozenset(
    {
        "none",
        "api_key",
        "bearer",
        "basic",
        "token",
        "token_based",
        "oauth2_client_credentials",
        "custom_headers",
    }
)


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/auth
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/auth")
def get_auth_config(ctx: Ctx, integration_id: str) -> JSONResponse:
    """Return the stored auth configuration for the integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    _require_integration(ctx, integration_id)
    config = _load_auth_config(ctx, integration_id, mask_secrets=True)
    return JSONResponse(status_code=200, content=config)


# ---------------------------------------------------------------------------
# PUT /integrations/{integration_id}/auth
# ---------------------------------------------------------------------------


@router.put("/integrations/{integration_id}/auth")
def update_auth_config(
    ctx: Ctx,
    integration_id: str,
    body: UpdateAuthConfigRequest,
) -> JSONResponse:
    """Create or update the auth config for the integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    _require_integration(ctx, integration_id)
    existing_config = _load_auth_config(ctx, integration_id, mask_secrets=False)

    auth_mode = body.auth_mode.strip().lower()
    if auth_mode not in _VALID_AUTH_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid auth_mode '{body.auth_mode}'; must be one of: {', '.join(sorted(_VALID_AUTH_MODES))}",
        )

    config = IntegrationAuthConfig(
        integration_id=integration_id,
        base_url=_trim_opt(body.base_url),
        auth_mode=auth_mode,
        api_key=_trim_opt(body.api_key),
        api_key_header=_trim_opt(body.api_key_header),
        api_key_query_name=_trim_opt(body.api_key_query_name),
        bearer_token=_trim_opt(body.bearer_token),
        token_value=_trim_opt(body.token_value),
        token_header=_trim_opt(body.token_header),
        token_prefix=_trim_opt(body.token_prefix),
        basic_username=_trim_opt(body.basic_username),
        basic_password=_trim_opt(body.basic_password),
        oauth_token_url=_trim_opt(body.oauth_token_url),
        oauth_client_id=_trim_opt(body.oauth_client_id),
        oauth_client_secret=_trim_opt(body.oauth_client_secret),
        oauth_scope=_trim_opt(body.oauth_scope),
        oauth_audience=_trim_opt(body.oauth_audience),
        token_url=_trim_opt(body.token_url),
        token_request_method=(
            body.token_request_method.strip().upper()
            if body.token_request_method
            else None
        ),
        token_request_body=body.token_request_body,
        token_request_headers=_sanitize_header_map(body.token_request_headers),
        token_response_path=_trim_opt(body.token_response_path),
        token_expiry_seconds=body.token_expiry_seconds,
        token_expiry_path=_trim_opt(body.token_expiry_path),
        custom_headers=_sanitize_header_map(body.custom_headers),
        updated_at=now_utc_string(),
    )

    for field_name in (
        "api_key",
        "bearer_token",
        "token_value",
        "basic_password",
        "oauth_client_secret",
    ):
        setattr(
            config,
            field_name,
            restore_masked_value(
                getattr(config, field_name),
                existing_config.get(field_name),
                field_name,
            ),
        )

    config.token_request_body = restore_masked_value(
        config.token_request_body,
        existing_config.get("token_request_body"),
    )
    config.token_request_headers = restore_masked_value(
        config.token_request_headers,
        existing_config.get("token_request_headers"),
    )
    config.custom_headers = restore_masked_value(
        config.custom_headers,
        existing_config.get("custom_headers"),
    )

    _save_auth_config(ctx, integration_id, config)
    return JSONResponse(
        status_code=200,
        content=_load_auth_config(ctx, integration_id, mask_secrets=True),
    )


# ---------------------------------------------------------------------------
# POST /integrations/{integration_id}/test-connection
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/test-connection")
def test_connection(ctx: Ctx, integration_id: str) -> JSONResponse:
    """Test connectivity to the integration's API."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    integration_dict = _require_integration(ctx, integration_id)
    auth_data = _load_auth_config(ctx, integration_id, mask_secrets=False)
    url = _resolve_test_url(integration_dict, auth_data)
    if url is None:
        raise HTTPException(
            status_code=400,
            detail="base URL is required in auth settings for connectivity tests when spec is not an HTTP URL",
        )

    headers: dict[str, str] = {}
    for k, v in auth_data.get("custom_headers", {}).items():
        if k.strip() and v.strip():
            headers[k.strip()] = v.strip()

    auth_mode = auth_data.get("auth_mode", "none").strip().lower()
    basic_auth = None

    if auth_mode == "api_key":
        key = auth_data.get("api_key")
        header_name = auth_data.get("api_key_header", "x-api-key")
        if key and header_name:
            headers[header_name] = key
    elif auth_mode == "bearer":
        token = auth_data.get("bearer_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_mode == "token":
        token_val = auth_data.get("token_value")
        header_name = auth_data.get("token_header", "Authorization")
        prefix = auth_data.get("token_prefix", "")
        if token_val:
            headers[header_name] = f"{prefix} {token_val}".strip()
    elif auth_mode == "basic":
        username = auth_data.get("basic_username")
        password = auth_data.get("basic_password")
        if username and password:
            basic_auth = (username, password)

    headers.setdefault("accept", "application/json, text/plain, */*")

    started = time.monotonic()
    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.get(url, headers=headers, auth=basic_auth)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        success = resp.status_code < 500
        outcome = ConnectionTestStatus(
            success=success,
            status_code=resp.status_code,
            latency_ms=elapsed_ms,
            tested_at=now_utc_string(),
            message=(
                "Connection successful"
                if success
                else f"Server returned {resp.status_code}"
            ),
            url=url,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        outcome = ConnectionTestStatus(
            success=False,
            latency_ms=elapsed_ms,
            tested_at=now_utc_string(),
            message=f"Connection failed: {exc}",
            url=url,
        )

    # Persist last_connection_test on the integration
    _save_connection_test(ctx, integration_id, outcome.model_dump())

    return JSONResponse(status_code=200, content=outcome.model_dump())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _trim_opt(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def _sanitize_header_map(headers: dict[str, str]) -> dict[str, str]:
    return {
        k.strip(): v.strip()
        for k, v in headers.items()
        if k.strip() and v.strip()
    }


def _decode_json_field(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _require_integration(ctx: Ctx, integration_id: str) -> dict:
    """Get integration from the database."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        integration = repo.get_by_id(integration_id)
        if integration:
            return {
                "id": integration.id,
                "name": integration.name,
                "spec": integration.spec,
                "created_at": integration.created_at,
            }
    finally:
        session.close()
    raise HTTPException(status_code=404, detail="integration not found")


def _load_auth_config(
    ctx: Ctx,
    integration_id: str,
    *,
    mask_secrets: bool = False,
) -> dict:
    """Load auth config from the database."""
    session = ctx.db_session_factory()
    try:
        repo = AuthConfigRepository(session, ctx.secret_manager)
        auth = repo.get_by_integration(integration_id)
        if auth:
            secret_manager = ctx.secret_manager
            token_request_body = (
                secret_manager.decrypt_json_blob(auth.token_request_body, auth.token_request_body)
                if secret_manager is not None
                else _decode_json_field(auth.token_request_body, auth.token_request_body)
            )
            token_request_headers = (
                secret_manager.decrypt_json_blob(auth.token_request_headers, {})
                if secret_manager is not None
                else _decode_json_field(auth.token_request_headers, {})
            )
            custom_headers = (
                secret_manager.decrypt_json_blob(auth.custom_headers, {})
                if secret_manager is not None
                else _decode_json_field(auth.custom_headers, {})
            )
            payload = {
                "integration_id": integration_id,
                "base_url": auth.base_url,
                "auth_mode": auth.auth_mode,
                "api_key": secret_manager.decrypt_text(auth.api_key) if secret_manager is not None else auth.api_key,
                "api_key_header": auth.api_key_header,
                "api_key_query_name": auth.api_key_query_name,
                "bearer_token": (
                    secret_manager.decrypt_text(auth.bearer_token) if secret_manager is not None else auth.bearer_token
                ),
                "token_value": (
                    secret_manager.decrypt_text(auth.token_value) if secret_manager is not None else auth.token_value
                ),
                "token_header": auth.token_header,
                "token_prefix": auth.token_prefix,
                "basic_username": auth.basic_username,
                "basic_password": (
                    secret_manager.decrypt_text(auth.basic_password)
                    if secret_manager is not None
                    else auth.basic_password
                ),
                "oauth_token_url": auth.oauth_token_url,
                "oauth_client_id": auth.oauth_client_id,
                "oauth_client_secret": (
                    secret_manager.decrypt_text(auth.oauth_client_secret)
                    if secret_manager is not None
                    else auth.oauth_client_secret
                ),
                "oauth_scope": auth.oauth_scope,
                "oauth_audience": auth.oauth_audience,
                "token_url": auth.token_url,
                "token_request_method": auth.token_request_method,
                "token_request_body": token_request_body,
                "token_request_headers": token_request_headers,
                "token_response_path": auth.token_response_path,
                "token_expiry_seconds": auth.token_expiry_seconds,
                "token_expiry_path": auth.token_expiry_path,
                "custom_headers": custom_headers,
                "updated_at": auth.updated_at,
            }
            if mask_secrets:
                payload["api_key"] = mask_secret(payload["api_key"])
                payload["bearer_token"] = mask_secret(payload["bearer_token"])
                payload["token_value"] = mask_secret(payload["token_value"])
                payload["basic_password"] = mask_secret(payload["basic_password"])
                payload["oauth_client_secret"] = mask_secret(payload["oauth_client_secret"])
                payload["token_request_body"] = mask_named_value("token_request_body", payload["token_request_body"])
                payload["token_request_headers"] = mask_named_value(
                    "token_request_headers",
                    payload["token_request_headers"],
                )
                payload["custom_headers"] = mask_named_value("custom_headers", payload["custom_headers"])
            return payload
    finally:
        session.close()

    return IntegrationAuthConfig(
        integration_id=integration_id
    ).model_dump()


def _save_auth_config(ctx: Ctx, integration_id: str, config: IntegrationAuthConfig) -> None:
    """Save auth config to the database."""
    session = ctx.db_session_factory()
    try:
        repo = AuthConfigRepository(session, ctx.secret_manager)
        repo.upsert(
            integration_id,
            base_url=config.base_url,
            auth_mode=config.auth_mode,
            config={
                "api_key": config.api_key,
                "api_key_header": config.api_key_header,
                "api_key_query_name": config.api_key_query_name,
                "bearer_token": config.bearer_token,
                "token_value": config.token_value,
                "token_header": config.token_header,
                "token_prefix": config.token_prefix,
                "basic_username": config.basic_username,
                "basic_password": config.basic_password,
                "oauth_token_url": config.oauth_token_url,
                "oauth_client_id": config.oauth_client_id,
                "oauth_client_secret": config.oauth_client_secret,
                "oauth_scope": config.oauth_scope,
                "oauth_audience": config.oauth_audience,
                "token_url": config.token_url,
                "token_request_method": config.token_request_method,
                "token_request_body": config.token_request_body,
                "token_request_headers": config.token_request_headers or {},
                "token_response_path": config.token_response_path,
                "token_expiry_seconds": config.token_expiry_seconds,
                "token_expiry_path": config.token_expiry_path,
                "custom_headers": config.custom_headers or {},
            }
        )
        logger.info("Auth config saved to database: %s", integration_id)
    finally:
        session.close()


def _resolve_test_url(integration: dict, auth: dict) -> str | None:
    base = (auth.get("base_url") or "").strip()
    if base:
        return base

    spec = integration.get("spec", "")
    if spec.startswith("http://") or spec.startswith("https://"):
        from urllib.parse import urlparse

        parsed = urlparse(spec)
        host = parsed.hostname
        if not host:
            return None
        port_part = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port_part}"

    return None


def _save_connection_test(ctx: Ctx, integration_id: str, test: dict) -> None:
    """Save connection test result to the database."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        integration = repo.get_by_id(integration_id)
        if integration:
            integration.last_connection_test = test
            session.commit()
            logger.info("Connection test saved to database: %s", integration_id)
    finally:
        session.close()

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""LLM connectivity test endpoint."""

from __future__ import annotations

import logging
import time

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    TestLlmConnectionRequest,
    TestLlmConnectionResponse,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import LLMConfigRepository

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /llm/test-connection
# ---------------------------------------------------------------------------


@router.post("/llm/test-connection")
def test_llm_connection(
    ctx: Ctx,
    body: TestLlmConnectionRequest | None = None,
) -> JSONResponse:
    """Test connectivity to the configured LLM provider."""
    config_id: str | None = None
    if body is not None and body.config_id:
        config_id = body.config_id.strip() or None

    config = _resolve_config(ctx, config_id)
    if config is None:
        raise HTTPException(
            status_code=400, detail="no default llm config configured"
        )

    tested_at = now_utc_string()
    try:
        latency_ms = _run_probe(config)
        response = TestLlmConnectionResponse(
            success=True,
            latency_ms=latency_ms,
            provider=config.get("provider", ""),
            model=config.get("model", ""),
            error=None,
            tested_at=tested_at,
        )
    except Exception as exc:
        response = TestLlmConnectionResponse(
            success=False,
            latency_ms=None,
            provider=config.get("provider", ""),
            model=config.get("model", ""),
            error=str(exc),
            tested_at=tested_at,
        )

    # Persist test results back onto the config record
    config["last_test_success"] = response.success
    config["last_test_latency_ms"] = response.latency_ms
    config["last_test_model"] = config.get("model")
    config["last_test_provider"] = config.get("provider")
    config["last_test_error"] = response.error
    config["last_tested_at"] = tested_at
    config["updated_at"] = now_utc_string()
    _persist_config(ctx, config)

    if response.success:
        logger.info(
            "llm connection test succeeded: provider=%s model=%s latency=%sms",
            response.provider,
            response.model,
            response.latency_ms,
        )
    else:
        logger.warning(
            "llm connection test failed: provider=%s model=%s error=%s",
            response.provider,
            response.model,
            response.error,
        )

    return JSONResponse(status_code=200, content=response.model_dump())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_config(ctx: Ctx, config_id: str | None) -> dict | None:
    configs = _load_llm_configs(ctx)
    if config_id:
        if not is_safe_token(config_id):
            raise HTTPException(status_code=400, detail="invalid llm config id")
        found = next((c for c in configs if c.get("id") == config_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="llm config not found")
        return found
    # Default config
    default = next(
        (
            c
            for c in configs
            if c.get("is_default") and (c.get("model") or "").strip()
        ),
        None,
    )
    return default


def _load_llm_configs(ctx: Ctx) -> list[dict]:
    """Load LLM configs from the database."""
    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        models = repo.list_all()
        secret_manager = ctx.secret_manager
        return [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model": m.model,
                "base_url": m.base_url,
                "api_key": secret_manager.decrypt_text(m.api_key) if secret_manager is not None else m.api_key,
                "bearer_token": (
                    secret_manager.decrypt_text(m.bearer_token)
                    if secret_manager is not None
                    else m.bearer_token
                ),
                "auth_type": m.auth_type,
                "auth_header_name": m.auth_header_name,
                "auth_header_prefix": m.auth_header_prefix,
                "custom_headers": (
                    secret_manager.decrypt_json_blob(m.custom_headers, {})
                    if secret_manager is not None
                    else m.custom_headers or {}
                ),
                "vllm_auth_type": m.vllm_auth_type,
                "vllm_auth_headers": (
                    secret_manager.decrypt_json_blob(m.vllm_auth_headers, {})
                    if secret_manager is not None
                    else m.vllm_auth_headers or {}
                ),
                "vllm_token_auth": (
                    secret_manager.decrypt_json_blob(m.vllm_token_auth, None)
                    if secret_manager is not None
                    else m.vllm_token_auth
                ),
                "vllm_oauth2": (
                    secret_manager.decrypt_json_blob(m.vllm_oauth2, None)
                    if secret_manager is not None
                    else m.vllm_oauth2
                ),
                "is_default": m.is_default,
                "last_test_success": m.last_test_success,
                "last_test_latency_ms": m.last_test_latency_ms,
                "last_test_model": m.last_test_model,
                "last_test_provider": m.last_test_provider,
                "last_test_error": m.last_test_error,
                "last_tested_at": m.last_tested_at,
            }
            for m in models
        ]
    finally:
        session.close()


def _persist_config(ctx: Ctx, config: dict) -> None:
    """Write updated config record back to the database."""
    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        config_id = config.get("id")
        if config_id:
            repo.upsert(config_id, **{k: v for k, v in config.items() if k != "id"})
    finally:
        session.close()


def _run_probe(config: dict) -> int:
    """Run a lightweight LLM probe and return latency in ms.

    Dispatches to provider-specific probe functions.
    """
    provider = (config.get("provider") or "").strip().lower()
    started = time.monotonic()

    if provider == "anthropic":
        _probe_anthropic(config)
    elif provider == "gemini":
        _probe_gemini(config)
    else:
        _probe_openai_compatible(config, provider)

    return int((time.monotonic() - started) * 1000)


def _probe_anthropic(config: dict) -> None:
    base = (config.get("base_url") or "").strip() or "https://api.anthropic.com"
    url = f"{base.rstrip('/')}/v1/messages"
    model = (config.get("model") or "").strip()
    if not model:
        raise ValueError("llm model is required for anthropic probe")

    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("anthropic API key is required")

    api_version = (config.get("api_version") or "").strip() or "2023-06-01"
    headers = {
        "anthropic-version": api_version,
        "content-type": "application/json",
        "x-api-key": api_key,
    }
    for k, v in config.get("custom_headers", {}).items():
        if k.strip() and v.strip():
            headers[k.strip()] = v.strip()

    body = {
        "model": model,
        "max_tokens": 16,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": "Respond with OK only."}],
    }

    with httpx.Client(timeout=35.0) as client:
        resp = client.post(url, json=body, headers=headers)
    if not resp.is_success:
        raise ValueError(
            f"Anthropic test failed with status {resp.status_code}: {resp.text[:200]}"
        )


def _probe_openai_compatible(config: dict, provider: str) -> None:
    default_bases = {
        "openai": "https://api.openai.com",
        "mistral": "https://api.mistral.ai",
        "sarvam": "https://api.sarvam.ai",
    }
    base = (
        (config.get("base_url") or "").strip()
        or default_bases.get(provider, "")
    )
    if not base:
        raise ValueError(f"{provider} provider requires a base URL")

    url = f"{base.rstrip('/')}/v1/chat/completions"
    headers: dict[str, str] = {"content-type": "application/json"}

    # Apply auth
    auth_type = (config.get("auth_type") or "api_key").strip().lower()
    api_key = (config.get("api_key") or "").strip()
    bearer = (config.get("bearer_token") or "").strip()

    if auth_type == "api_key" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "bearer" and (bearer or api_key):
        headers["Authorization"] = f"Bearer {bearer or api_key}"

    for k, v in config.get("custom_headers", {}).items():
        if k.strip() and v.strip():
            headers[k.strip()] = v.strip()

    body = {
        "model": config.get("model", ""),
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": "Respond with OK only."},
            {"role": "user", "content": "Connectivity test"},
        ],
        "max_tokens": 16,
    }

    with httpx.Client(timeout=35.0) as client:
        resp = client.post(url, json=body, headers=headers)
    if not resp.is_success:
        raise ValueError(
            f"{provider} test failed with status {resp.status_code}: {resp.text[:200]}"
        )


def _probe_gemini(config: dict) -> None:
    base = (
        (config.get("base_url") or "").strip()
        or "https://generativelanguage.googleapis.com/v1beta"
    )
    model = config.get("model", "")
    model_name = model if model.startswith("models/") else f"models/{model}"
    url = f"{base.rstrip('/')}/{model_name}:generateContent"

    api_key = (config.get("api_key") or "").strip()
    auth_type = (config.get("auth_type") or "api_key").strip().lower()
    if auth_type == "api_key" and api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"

    headers: dict[str, str] = {"content-type": "application/json"}
    for k, v in config.get("custom_headers", {}).items():
        if k.strip() and v.strip():
            headers[k.strip()] = v.strip()

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": "Respond with OK only."}]}
        ],
        "generationConfig": {"responseMimeType": "text/plain"},
    }

    with httpx.Client(timeout=35.0) as client:
        resp = client.post(url, json=body, headers=headers)
    if not resp.is_success:
        raise ValueError(
            f"Gemini test failed with status {resp.status_code}: {resp.text[:200]}"
        )

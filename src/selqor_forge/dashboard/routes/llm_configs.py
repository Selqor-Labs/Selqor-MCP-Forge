# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""LLM configuration CRUD endpoints and provider list."""

from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    LlmConfigRecord,
    UpsertLlmConfigRequest,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import LLMConfigRepository, LLMLogRepository
from selqor_forge.dashboard.secrets import (
    mask_named_value,
    mask_secret,
    restore_masked_value,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_VALID_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "vllm",
        "sarvam",
        "mistral",
        "gemini",
        "aws_bedrock",
        "vertex_ai",
    }
)

_VALID_AUTH_TYPES = frozenset(
    {"api_key", "bearer", "basic", "token", "none", "custom_headers"}
)

_VALID_VLLM_AUTH_TYPES = frozenset(
    {"none", "static_headers", "token_based", "oauth2_client_credentials"}
)

# Hardcoded provider list matching the Rust source
_PROVIDERS_PAYLOAD = {
    "providers": [
        {
            "id": "anthropic",
            "label": "Anthropic",
            "name": "Anthropic",
            "description": "Claude 3/4 family models",
            "requires_api_key": True,
            "requires_base_url": False,
            "supports_embedding": False,
            "default_model": "claude-sonnet-4-20250514",
            "default_auth_type": "api_key",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "description": "Balanced quality and speed"},
                {"id": "claude-opus-4-20250514", "name": "Claude Opus 4", "description": "Highest quality reasoning"},
                {"id": "claude-3-5-haiku-20241022", "name": "Claude Haiku 3.5", "description": "Low-latency model"},
            ],
        },
        {
            "id": "openai",
            "label": "OpenAI",
            "name": "OpenAI",
            "description": "GPT and embedding models",
            "requires_api_key": True,
            "requires_base_url": False,
            "supports_embedding": True,
            "default_model": "gpt-4o-mini",
            "default_auth_type": "api_key",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "gpt-4o", "name": "GPT-4o", "description": "Flagship multimodal model"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "description": "Cost-efficient default"},
                {"id": "o3-mini", "name": "o3-mini", "description": "Reasoning optimized model"},
            ],
        },
        {
            "id": "vllm",
            "label": "vLLM",
            "name": "vLLM (Self-Hosted)",
            "description": "Any OpenAI-compatible model served by vLLM",
            "requires_api_key": False,
            "requires_base_url": True,
            "supports_embedding": False,
            "default_model": "Qwen/Qwen3-30B-A3B",
            "default_auth_type": "none",
            "supports_vllm_auth_profiles": True,
            "models": [
                {"id": "Qwen/Qwen3-30B-A3B", "name": "Qwen3 30B A3B", "description": "Sample default for self-hosted vLLM"},
            ],
        },
        {
            "id": "sarvam",
            "label": "Sarvam",
            "name": "Sarvam",
            "description": "OpenAI-compatible Sarvam models",
            "requires_api_key": True,
            "requires_base_url": True,
            "supports_embedding": False,
            "default_model": "sarvam-m",
            "default_auth_type": "api_key",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "sarvam-m", "name": "Sarvam M", "description": "General-purpose Sarvam model"},
            ],
        },
        {
            "id": "mistral",
            "label": "Mistral",
            "name": "Mistral",
            "description": "Mistral large and embedding-capable models",
            "requires_api_key": True,
            "requires_base_url": False,
            "supports_embedding": True,
            "default_model": "mistral-large-latest",
            "default_auth_type": "api_key",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "mistral-large-latest", "name": "Mistral Large", "description": "Best quality Mistral model"},
                {"id": "mistral-medium-latest", "name": "Mistral Medium", "description": "Balanced quality and speed"},
                {"id": "mistral-small-latest", "name": "Mistral Small", "description": "Fast and lightweight"},
            ],
        },
        {
            "id": "gemini",
            "label": "Gemini",
            "name": "Gemini",
            "description": "Google Gemini family models",
            "requires_api_key": True,
            "requires_base_url": False,
            "supports_embedding": False,
            "default_model": "gemini-2.0-flash",
            "default_auth_type": "api_key",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": "Fast Gemini model"},
                {"id": "gemini-2.0-pro", "name": "Gemini 2.0 Pro", "description": "Higher quality Gemini model"},
            ],
        },
        {
            "id": "aws_bedrock",
            "label": "AWS Bedrock",
            "name": "AWS Bedrock",
            "description": "AWS hosted foundation models",
            "requires_api_key": False,
            "requires_base_url": True,
            "supports_embedding": False,
            "default_model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "default_auth_type": "custom_headers",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "anthropic.claude-3-5-sonnet-20241022-v2:0", "name": "Claude 3.5 Sonnet (Bedrock)", "description": "Bedrock-hosted Claude model"},
                {"id": "anthropic.claude-3-5-haiku-20241022-v1:0", "name": "Claude 3.5 Haiku (Bedrock)", "description": "Fast Bedrock-hosted Claude model"},
                {"id": "amazon.nova-pro-v1:0", "name": "Amazon Nova Pro", "description": "Amazon first-party Bedrock model"},
                {"id": "meta.llama3-1-70b-instruct-v1:0", "name": "Llama 3.1 70B Instruct (Bedrock)", "description": "Meta-hosted Bedrock model"},
                {"id": "mistral.mistral-large-2407-v1:0", "name": "Mistral Large (Bedrock)", "description": "Mistral model via Bedrock"},
            ],
        },
        {
            "id": "vertex_ai",
            "label": "Vertex AI",
            "name": "Vertex AI",
            "description": "Google Cloud Vertex AI endpoints",
            "requires_api_key": False,
            "requires_base_url": True,
            "supports_embedding": False,
            "default_model": "gemini-2.0-flash",
            "default_auth_type": "custom_headers",
            "supports_vllm_auth_profiles": False,
            "models": [
                {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash (Vertex)", "description": "Vertex-hosted Gemini model"},
            ],
        },
    ]
}


# ---------------------------------------------------------------------------
# GET /llm/configs
# ---------------------------------------------------------------------------


@router.get("/llm/configs")
def list_llm_configs(ctx: Ctx) -> JSONResponse:
    """List all LLM configurations and report the default."""
    configs = _load_llm_configs(ctx, mask_secrets=True)

    # Find the default LLM config
    default_config = None
    message = None
    for config in configs:
        if config.get("is_default") and config.get("enabled"):
            default_config = config
            break

    # Fallback to first enabled if no explicit default
    if not default_config:
        for config in configs:
            if config.get("enabled"):
                default_config = config
                break

    # Generate informational message
    if default_config:
        provider = default_config.get("provider", "Unknown").title()
        model = default_config.get("model", "Unknown")
        message = f"Using {provider} {model} as default LLM for analysis"
    else:
        message = "No LLM configured — heuristic analysis only"

    return JSONResponse(
        status_code=200,
        content={
            "configs": configs,
            "default_config_id": default_config.get("id") if default_config else None,
            "default_config_name": default_config.get("name") if default_config else None,
            "default_provider": default_config.get("provider") if default_config else None,
            "default_model": default_config.get("model") if default_config else None,
            "message": message,
        },
    )


# ---------------------------------------------------------------------------
# POST /llm/configs
# ---------------------------------------------------------------------------


@router.post("/llm/configs")
def upsert_llm_config(ctx: Ctx, body: UpsertLlmConfigRequest) -> JSONResponse:
    """Create or update an LLM configuration."""
    provider = _sanitize_provider(body.provider)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="llm config name is required")

    model = body.model.strip()
    embedding_model = _trim_opt(body.embedding_model)
    if not model and embedding_model is None:
        raise HTTPException(
            status_code=400,
            detail="either llm model or embedding model is required",
        )
    if body.is_default and not model:
        raise HTTPException(
            status_code=400, detail="default llm config must define a model"
        )

    config_id = (
        (body.id or "").strip()
        or f"{_slugify(name)}-{int(time.time() * 1000)}"
    )
    if not is_safe_token(config_id):
        raise HTTPException(
            status_code=400, detail="llm config id contains invalid characters"
        )

    existing_configs = _load_llm_configs(ctx, mask_secrets=False)
    existing = next((c for c in existing_configs if c.get("id") == config_id), None)
    now = now_utc_string()
    created_at = existing.get("created_at", now) if existing else now
    is_vllm = provider == "vllm"

    config = LlmConfigRecord(
        id=config_id,
        name=name,
        provider=provider,
        model=model,
        embedding_model=embedding_model,
        embedding_api_key=_trim_opt(body.embedding_api_key),
        embedding_dimensions=body.embedding_dimensions,
        base_url=_trim_opt(body.base_url),
        api_version=_trim_opt(body.api_version),
        auth_type=_sanitize_auth_type(body.auth_type),
        auth_header_name=_trim_opt(body.auth_header_name),
        auth_header_prefix=_trim_opt(body.auth_header_prefix),
        api_key=_trim_opt(body.api_key),
        bearer_token=_trim_opt(body.bearer_token),
        username=_trim_opt(body.username),
        password=_trim_opt(body.password),
        custom_headers=_sanitize_header_map(body.custom_headers),
        vllm_auth_type=_sanitize_vllm_auth_type(body.vllm_auth_type) if is_vllm else None,
        vllm_auth_headers=_sanitize_header_map(body.vllm_auth_headers) if is_vllm else {},
        vllm_token_auth=body.vllm_token_auth if is_vllm else None,
        vllm_oauth2=body.vllm_oauth2 if is_vllm else None,
        project_id=_trim_opt(body.project_id),
        location=_trim_opt(body.location),
        region=_trim_opt(body.region),
        is_default=body.is_default,
        is_default_embedding=body.is_default_embedding,
        enabled=body.enabled,
        last_test_success=existing.get("last_test_success") if existing else None,
        last_test_latency_ms=existing.get("last_test_latency_ms") if existing else None,
        last_test_model=existing.get("last_test_model") if existing else None,
        last_test_provider=existing.get("last_test_provider") if existing else None,
        last_test_error=existing.get("last_test_error") if existing else None,
        last_tested_at=existing.get("last_tested_at") if existing else None,
        created_at=created_at,
        updated_at=now,
    )

    for field_name in ("embedding_api_key", "api_key", "bearer_token", "password"):
        setattr(
            config,
            field_name,
            restore_masked_value(
                getattr(config, field_name),
                existing.get(field_name) if existing else None,
                field_name,
            ),
        )

    config.custom_headers = restore_masked_value(
        config.custom_headers,
        existing.get("custom_headers") if existing else {},
    )
    config.vllm_auth_headers = restore_masked_value(
        config.vllm_auth_headers,
        existing.get("vllm_auth_headers") if existing else {},
    )
    config.vllm_token_auth = restore_masked_value(
        config.vllm_token_auth,
        existing.get("vllm_token_auth") if existing else None,
    )
    config.vllm_oauth2 = restore_masked_value(
        config.vllm_oauth2,
        existing.get("vllm_oauth2") if existing else None,
    )

    # Respect the user's explicit is_default / is_default_embedding choice.
    # Previously the backend silently flipped is_default to True for the first
    # config with a model, even when the user unchecked the box â€” that hid the
    # user's intent and was a source of confusion.

    _save_llm_config(ctx, config.model_dump(), existing_configs)
    logger.info(
        "llm config saved: id=%s provider=%s model=%s is_default=%s",
        config.id,
        config.provider,
        config.model,
        config.is_default,
    )
    saved = next(
        (item for item in _load_llm_configs(ctx, mask_secrets=True) if item.get("id") == config.id),
        None,
    )
    return JSONResponse(status_code=200, content=saved or config.model_dump())


# ---------------------------------------------------------------------------
# POST /llm/configs/{config_id}/default
# ---------------------------------------------------------------------------


@router.post("/llm/configs/{config_id}/default")
def set_default_llm(ctx: Ctx, config_id: str) -> JSONResponse:
    """Set an LLM config as the default."""
    if not is_safe_token(config_id):
        raise HTTPException(status_code=400, detail="invalid llm config id")

    configs = _load_llm_configs(ctx, mask_secrets=False)
    found = False
    for c in configs:
        if c.get("id") == config_id:
            if not (c.get("model") or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="llm config without model cannot be default",
                )
            c["is_default"] = True
            c["updated_at"] = now_utc_string()
            found = True
        else:
            c["is_default"] = False

    if not found:
        raise HTTPException(status_code=404, detail="llm config not found")

    _write_llm_configs(ctx, configs)
    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------------------------------------------------------
# POST /llm/configs/{config_id}/default-embedding
# ---------------------------------------------------------------------------


@router.post("/llm/configs/{config_id}/default-embedding")
def set_default_embedding(ctx: Ctx, config_id: str) -> JSONResponse:
    """Set an LLM config as the default embedding provider."""
    if not is_safe_token(config_id):
        raise HTTPException(status_code=400, detail="invalid llm config id")

    configs = _load_llm_configs(ctx, mask_secrets=False)
    found = False
    for c in configs:
        if c.get("id") == config_id:
            if not c.get("embedding_model"):
                raise HTTPException(
                    status_code=400,
                    detail="embedding model is required for default embedding config",
                )
            c["is_default_embedding"] = True
            c["updated_at"] = now_utc_string()
            found = True
        else:
            c["is_default_embedding"] = False

    if not found:
        raise HTTPException(status_code=404, detail="llm config not found")

    _write_llm_configs(ctx, configs)
    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------------------------------------------------------
# DELETE /llm/configs/{config_id}
# ---------------------------------------------------------------------------


@router.delete("/llm/configs/{config_id}")
def delete_llm_config(ctx: Ctx, config_id: str) -> JSONResponse:
    """Delete an LLM configuration."""
    if not is_safe_token(config_id):
        raise HTTPException(status_code=400, detail="invalid llm config id")

    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session)
        target = repo.get_by_id(config_id)
        if target is None:
            return JSONResponse(status_code=200, content={"ok": True})

        was_default = bool(target.is_default)
        was_default_embedding = bool(target.is_default_embedding)

        # Actually delete the row from the database.
        repo.delete(config_id)

        # Re-assign defaults to another viable config if we removed the default.
        if was_default or was_default_embedding:
            remaining = repo.list_all()
            if was_default and not any(c.is_default for c in remaining):
                promote = next(
                    (c for c in remaining if (c.model or "").strip()),
                    None,
                )
                if promote is not None:
                    repo.upsert(promote.id, is_default=True)
            if was_default_embedding and not any(
                c.is_default_embedding for c in remaining
            ):
                promote = next(
                    (c for c in remaining if c.embedding_model),
                    None,
                )
                if promote is not None:
                    repo.upsert(promote.id, is_default_embedding=True)
    finally:
        session.close()

    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------------------------------------------------------
# GET /llm/providers
# ---------------------------------------------------------------------------


@router.get("/llm/providers")
def list_providers() -> JSONResponse:
    """Return hardcoded list of supported LLM providers with their models."""
    return JSONResponse(status_code=200, content=_PROVIDERS_PAYLOAD)


# ---------------------------------------------------------------------------
# GET /llm/logs
# ---------------------------------------------------------------------------


@router.get("/llm/logs")
def list_llm_logs(ctx: Ctx) -> JSONResponse:
    """Return LLM call logs (most recent 500)."""
    logs = _load_llm_logs(ctx)
    return JSONResponse(status_code=200, content={"logs": logs})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:48] or "llm"


def _trim_opt(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def _sanitize_provider(raw: str) -> str:
    p = raw.strip().lower()
    return p if p in _VALID_PROVIDERS else "anthropic"


def _sanitize_auth_type(raw: str) -> str:
    a = raw.strip().lower()
    return a if a in _VALID_AUTH_TYPES else "api_key"


def _sanitize_vllm_auth_type(raw: str | None) -> str:
    if raw is None:
        return "none"
    a = raw.strip().lower()
    return a if a in _VALID_VLLM_AUTH_TYPES else "none"


def _sanitize_header_map(headers: dict[str, str]) -> dict[str, str]:
    return {
        k.strip(): v.strip()
        for k, v in headers.items()
        if k.strip() and v.strip()
    }


def _load_llm_configs(ctx: Ctx, *, mask_secrets: bool = False) -> list[dict]:
    """Load all LLM configs from the database."""
    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        models = repo.list_all()
        return [_model_to_dict(ctx, m, mask_secrets=mask_secrets) for m in models]
    finally:
        session.close()


def _write_llm_configs(ctx: Ctx, configs: list[dict]) -> None:
    """Bulk-write LLM configs to the database (used by set_default operations)."""
    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        for config in configs:
            config_id = config.get("id")
            if config_id:
                repo.upsert(config_id, **{k: v for k, v in config.items() if k != "id"})
    finally:
        session.close()


def _save_llm_config(
    ctx: Ctx, config: dict, existing_configs: list[dict]
) -> None:
    """Save a single LLM config to the database, handling default promotion."""
    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        if config.get("is_default"):
            repo.clear_default()
        if config.get("is_default_embedding"):
            repo.clear_default_embedding()
        config_id = config.pop("id")
        repo.upsert(config_id, **config)
    finally:
        session.close()


def _load_llm_logs(ctx: Ctx) -> list[dict]:
    """Load recent LLM logs from the database."""
    session = ctx.db_session_factory()
    try:
        repo = LLMLogRepository(session)
        models = repo.list_recent(500)
        return [
            {
                "log_id": m.log_id,
                "integration_id": m.integration_id,
                "integration_name": m.integration_name,
                "run_id": m.run_id,
                "run_mode": m.run_mode,
                "provider": m.provider,
                "model": m.model,
                "endpoint": m.endpoint,
                "success": m.success,
                "latency_ms": m.latency_ms,
                "request_payload": m.request_payload,
                "response_payload": m.response_payload,
                "response_text": m.response_text,
                "error": m.error,
                "created_at": m.created_at,
            }
            for m in models
        ]
    finally:
        session.close()


def _model_to_dict(ctx: Ctx, m, *, mask_secrets: bool = False) -> dict:
    """Convert an LLMConfig model to a dict for JSON response."""
    secret_manager = ctx.secret_manager
    custom_headers = (
        secret_manager.decrypt_json_blob(m.custom_headers, {})
        if secret_manager is not None
        else m.custom_headers or {}
    )
    vllm_auth_headers = (
        secret_manager.decrypt_json_blob(m.vllm_auth_headers, {})
        if secret_manager is not None
        else m.vllm_auth_headers or {}
    )
    vllm_token_auth = (
        secret_manager.decrypt_json_blob(m.vllm_token_auth, None)
        if secret_manager is not None
        else m.vllm_token_auth
    )
    vllm_oauth2 = (
        secret_manager.decrypt_json_blob(m.vllm_oauth2, None)
        if secret_manager is not None
        else m.vllm_oauth2
    )
    payload = {
        "id": m.id,
        "name": m.name,
        "provider": m.provider,
        "model": m.model,
        "embedding_model": m.embedding_model,
        "embedding_api_key": (
            secret_manager.decrypt_text(m.embedding_api_key)
            if secret_manager is not None
            else m.embedding_api_key
        ),
        "embedding_dimensions": m.embedding_dimensions,
        "base_url": m.base_url,
        "api_version": m.api_version,
        "auth_type": m.auth_type,
        "auth_header_name": m.auth_header_name,
        "auth_header_prefix": m.auth_header_prefix,
        "api_key": secret_manager.decrypt_text(m.api_key) if secret_manager is not None else m.api_key,
        "bearer_token": (
            secret_manager.decrypt_text(m.bearer_token)
            if secret_manager is not None
            else m.bearer_token
        ),
        "username": m.username,
        "password": secret_manager.decrypt_text(m.password) if secret_manager is not None else m.password,
        "custom_headers": custom_headers,
        "vllm_auth_type": m.vllm_auth_type,
        "vllm_auth_headers": vllm_auth_headers,
        "vllm_token_auth": vllm_token_auth,
        "vllm_oauth2": vllm_oauth2,
        "project_id": m.project_id,
        "location": m.location,
        "region": m.region,
        "is_default": m.is_default,
        "is_default_embedding": m.is_default_embedding,
        "enabled": m.enabled,
        "last_test_success": m.last_test_success,
        "last_test_latency_ms": m.last_test_latency_ms,
        "last_test_model": m.last_test_model,
        "last_test_provider": m.last_test_provider,
        "last_test_error": m.last_test_error,
        "last_tested_at": m.last_tested_at,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }
    if mask_secrets:
        payload["embedding_api_key"] = mask_secret(payload["embedding_api_key"])
        payload["api_key"] = mask_secret(payload["api_key"])
        payload["bearer_token"] = mask_secret(payload["bearer_token"])
        payload["password"] = mask_secret(payload["password"])
        payload["custom_headers"] = mask_named_value("custom_headers", payload["custom_headers"])
        payload["vllm_auth_headers"] = mask_named_value("vllm_auth_headers", payload["vllm_auth_headers"])
        payload["vllm_token_auth"] = mask_named_value("vllm_token_auth", payload["vllm_token_auth"])
        payload["vllm_oauth2"] = mask_named_value("vllm_oauth2", payload["vllm_oauth2"])
    return payload

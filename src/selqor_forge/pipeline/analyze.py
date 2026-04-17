# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""LLM-powered analysis module: converts a UasfSurface into an AnalysisPlan.

Supports Anthropic, OpenAI-compatible (OpenAI / vLLM / Sarvam / Mistral /
AWS Bedrock / Vertex AI), and Google Gemini providers, with a heuristic
fallback when no LLM is available.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from selqor_forge.config import AppConfig
from selqor_forge.models import (
    AnalysisPlan,
    AnalysisSource,
    AnalysisToolCandidate,
    EndpointIntent,
    UasfEndpoint,
    UasfSurface,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL: str = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION: str = "2023-06-01"
# Extended timeout for large specs (500-1k endpoints with 10-11 batches)
# Each batch can take 30-60s for LLM processing
LLM_HTTP_TIMEOUT_SECS: int = 900  # 15 minutes per batch for very large specs
MAX_INPUT_TOKENS_DEFAULT: int = 40_000
BATCH_ENDPOINT_TOKEN_BUDGET: int = 28_000
BATCH_HISTORY_TOKEN_BUDGET: int = 8_000
BATCH_PROMPT_OVERHEAD_TOKENS: int = 2_000

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LlmCallTrace:
    provider: str
    model: str | None
    endpoint: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    response_text: str | None
    success: bool
    latency_ms: int | None
    error: str | None


@dataclass
class LlmRuntimeConfig:
    provider: str = ""
    model: str | None = None
    base_url: str | None = None
    auth_type: str = "bearer"
    auth_header_name: str | None = None
    auth_header_prefix: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None
    username: str | None = None
    password: str | None = None
    custom_headers: dict[str, str] = field(default_factory=dict)
    api_version: str | None = None


@dataclass
class AnalyzeOptions:
    batch_state_path: Path | None = None
    resume_batches: bool = False
    max_input_tokens: int = 40_000


@dataclass
class LlmBatchStateSnapshot:
    total_batches: int = 0
    completed_batches: int = 0
    pending_batches: int = 0
    status: str = ""
    failed_batch: int | None = None


@dataclass
class _PersistedBatchAnalysis:
    batch_index: int = 0
    endpoint_ids: list[str] = field(default_factory=list)
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] | None = None
    response_text: str | None = None
    success: bool = False
    error: str | None = None
    tools: list[AnalysisToolCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "endpoint_ids": self.endpoint_ids,
            "request_payload": self.request_payload,
            "response_payload": self.response_payload,
            "response_text": self.response_text,
            "success": self.success,
            "error": self.error,
            "tools": [t.model_dump() for t in self.tools],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _PersistedBatchAnalysis:
        tools = [AnalysisToolCandidate.model_validate(t) for t in (data.get("tools") or [])]
        return cls(
            batch_index=data.get("batch_index", 0),
            endpoint_ids=data.get("endpoint_ids", []),
            request_payload=data.get("request_payload", {}),
            response_payload=data.get("response_payload"),
            response_text=data.get("response_text"),
            success=data.get("success", False),
            error=data.get("error"),
            tools=tools,
            warnings=data.get("warnings", []),
        )


@dataclass
class _PersistedBatchState:
    provider: str = ""
    model: str | None = None
    max_input_tokens: int = 0
    total_batches: int = 0
    completed_batches: int = 0
    status: str = ""
    failed_batch: int | None = None
    batches: list[_PersistedBatchAnalysis] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_input_tokens": self.max_input_tokens,
            "total_batches": self.total_batches,
            "completed_batches": self.completed_batches,
            "status": self.status,
            "failed_batch": self.failed_batch,
            "batches": [b.to_dict() for b in self.batches],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _PersistedBatchState:
        batches = [_PersistedBatchAnalysis.from_dict(b) for b in (data.get("batches") or [])]
        return cls(
            provider=data.get("provider", ""),
            model=data.get("model"),
            max_input_tokens=data.get("max_input_tokens", 0),
            total_batches=data.get("total_batches", 0),
            completed_batches=data.get("completed_batches", 0),
            status=data.get("status", ""),
            failed_batch=data.get("failed_batch"),
            batches=batches,
        )


@dataclass
class _BatchPromptContext:
    batch_index: int
    total_batches: int
    prior_summary: str | None = None


# ---------------------------------------------------------------------------
# Thread-local LLM call traces
# ---------------------------------------------------------------------------

_thread_locals = threading.local()


def _get_traces() -> list[LlmCallTrace]:
    if not hasattr(_thread_locals, "llm_call_traces"):
        _thread_locals.llm_call_traces = []
    return _thread_locals.llm_call_traces


def clear_llm_call_traces() -> None:
    """Clear thread-local LLM call traces."""
    _get_traces().clear()


def take_llm_call_traces() -> list[LlmCallTrace]:
    """Return and clear thread-local LLM call traces."""
    traces = list(_get_traces())
    _get_traces().clear()
    return traces


def peek_llm_call_traces() -> list[LlmCallTrace]:
    """Return a copy of thread-local LLM call traces without clearing."""
    return list(_get_traces())


def _record_llm_call_trace(trace: LlmCallTrace) -> None:
    _get_traces().append(trace)


def _elapsed_millis(started: float) -> int | None:
    return int((time.monotonic() - started) * 1000)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def analyze(
    surface: UasfSurface,
    config: AppConfig,
    agent_prompt: str | None = None,
) -> AnalysisPlan:
    """Main analysis entry point.

    Attempts LLM-based analysis (Anthropic by default) and falls back to
    heuristic when no API key is available or the call fails.

    Args:
        surface: The normalized UASF surface to analyze.
        config: Application configuration.
        agent_prompt: Optional natural-language description of what the target
            agent is meant to do.  When provided the LLM is instructed to
            group tools around the agent's workflow rather than the raw API
            structure.
    """
    logger.debug(
        "starting analysis title=%s endpoints=%d anthropic_enabled=%s agent_prompt=%s",
        surface.title,
        len(surface.endpoints),
        config.anthropic.enabled,
        bool(agent_prompt),
    )
    return analyze_with_override_and_options(surface, config, None, None, agent_prompt=agent_prompt)


def analyze_with_override(
    surface: UasfSurface,
    config: AppConfig,
    llm_override: LlmRuntimeConfig | None = None,
    agent_prompt: str | None = None,
    *,
    progress_cb: Callable[[dict], None] | None = None,
) -> AnalysisPlan:
    """Analyse with an optional LLM runtime override.

    *progress_cb* is an opt-in hook so the dashboard worker can surface
    live batch progress ("Batch 2/5...") to the frontend progress stepper.
    It receives a dict with keys ``{total_batches, completed_batches,
    current_batch, phase}``. The callback must be fast and exception-
    safe -- any raised exception is caught and logged but otherwise
    ignored so it can never break the pipeline itself.
    """
    return analyze_with_override_and_options(
        surface, config, llm_override, None,
        agent_prompt=agent_prompt,
        progress_cb=progress_cb,
    )


def analyze_with_override_and_options(
    surface: UasfSurface,
    config: AppConfig,
    llm_override: LlmRuntimeConfig | None = None,
    options: AnalyzeOptions | None = None,
    *,
    agent_prompt: str | None = None,
    progress_cb: Callable[[dict], None] | None = None,
) -> AnalysisPlan:
    """Full analysis entry point with optional LLM override and options."""
    if llm_override is not None:
        logger.debug(
            "running analysis with runtime override provider=%s model=%s",
            llm_override.provider,
            llm_override.model,
        )
        return _analyze_with_runtime(
            surface, config, llm_override, options,
            agent_prompt=agent_prompt,
            progress_cb=progress_cb,
        )

    if not config.anthropic.enabled:
        logger.warning("anthropic analysis disabled by configuration; falling back to heuristic")
        return heuristic_analysis(
            surface,
            ["Anthropic analysis disabled by configuration."],
            agent_prompt=agent_prompt,
        )

    api_key = ""
    if not api_key:
        logger.warning(
            "no LLM credentials available on this code path; using heuristic analysis"
        )
        return heuristic_analysis(
            surface,
            [
                "No LLM credentials were available; used heuristic analysis instead. "
                "In the dashboard, configure a provider under LLM Config page. "
                "API key configuration is now managed entirely through the dashboard."
            ],
            agent_prompt=agent_prompt,
        )

    try:
        plan = _run_batched_runtime_analysis(
            surface=surface,
            config=config,
            source=AnalysisSource.ANTHROPIC,
            model=config.anthropic.model,
            provider="anthropic",
            options=options,
            agent_prompt=agent_prompt,
            progress_cb=progress_cb,
            analyze_batch=lambda batch_surface, prompt_context: anthropic_analysis_with_model(
                surface=batch_surface,
                config=config,
                model=config.anthropic.model,
                api_key=api_key,
                runtime=None,
                prompt_context=prompt_context,
                enforce_tool_bounds=prompt_context is None,
                agent_prompt=agent_prompt,
            ),
        )
        logger.debug(
            "anthropic analysis succeeded tools=%d warnings=%d",
            len(plan.tools),
            len(plan.warnings),
        )
        return plan
    except Exception as exc:
        logger.warning("anthropic analysis failed; using heuristic fallback error=%s", exc)
        return heuristic_analysis(
            surface,
            [f"Anthropic analysis failed; falling back to heuristic analysis. Reason: {exc}"],
            agent_prompt=agent_prompt,
        )


# ---------------------------------------------------------------------------
# Runtime dispatch
# ---------------------------------------------------------------------------


def _analyze_with_runtime(
    surface: UasfSurface,
    config: AppConfig,
    runtime: LlmRuntimeConfig,
    options: AnalyzeOptions | None,
    *,
    agent_prompt: str | None = None,
    progress_cb: Callable[[dict], None] | None = None,
) -> AnalysisPlan:
    provider = runtime.provider.strip().lower()
    logger.debug(
        "evaluating runtime LLM provider provider=%s model=%s has_base_url=%s auth_type=%s",
        provider,
        runtime.model,
        runtime.base_url is not None,
        runtime.auth_type,
    )

    if not provider:
        logger.warning("runtime LLM provider is empty; using heuristic analysis")
        return heuristic_analysis(
            surface,
            ["No LLM provider configured; using heuristic analysis."],
            agent_prompt=agent_prompt,
        )

    if provider == "anthropic":
        # API key must be explicitly provided via runtime config, not from environment
        api_key = (runtime.api_key or "").strip() or None
        if api_key is None:
            logger.warning("anthropic provider selected without API key; using heuristic analysis")
            return heuristic_analysis(
                surface,
                [
                    "Anthropic provider selected, but no API key was configured. "
                    "Falling back to heuristic analysis."
                ],
                agent_prompt=agent_prompt,
            )
        model = runtime.model or config.anthropic.model
        try:
            return _run_batched_runtime_analysis(
                surface=surface,
                config=config,
                source=_analysis_source_from_provider("anthropic"),
                model=model,
                provider="anthropic",
                options=options,
                agent_prompt=agent_prompt,
                progress_cb=progress_cb,
                analyze_batch=lambda batch_surface, prompt_context: anthropic_analysis_with_model(
                    surface=batch_surface,
                    config=config,
                    model=model,
                    api_key=api_key,
                    runtime=runtime,
                    prompt_context=prompt_context,
                    enforce_tool_bounds=prompt_context is None,
                    agent_prompt=agent_prompt,
                ),
            )
        except Exception as exc:
            logger.warning("anthropic provider failed; using heuristic analysis error=%s", exc)
            return heuristic_analysis(
                surface,
                [f"Anthropic provider failed; falling back to heuristic analysis. Reason: {exc}"],
                agent_prompt=agent_prompt,
            )

    elif provider in ("openai", "vllm", "sarvam", "mistral", "aws_bedrock", "vertex_ai"):
        default_bases: dict[str, str] = {
            "openai": "https://api.openai.com",
            "mistral": "https://api.mistral.ai",
            "sarvam": "https://api.sarvam.ai",
        }
        base_url = (runtime.base_url or default_bases.get(provider, "")).strip() or None
        if base_url is None:
            logger.warning(
                "provider %s missing base URL; using heuristic analysis", provider
            )
            return heuristic_analysis(
                surface,
                [
                    f"{provider} provider requires a base URL in LLM settings. "
                    f"Falling back to heuristic analysis."
                ],
                agent_prompt=agent_prompt,
            )
        model = (runtime.model or "").strip() or "gpt-4o-mini"
        try:
            return _run_batched_runtime_analysis(
                surface=surface,
                config=config,
                source=_analysis_source_from_provider(provider),
                model=model,
                provider=provider,
                options=options,
                agent_prompt=agent_prompt,
                progress_cb=progress_cb,
                analyze_batch=lambda batch_surface, prompt_context: openai_compatible_analysis(
                    surface=batch_surface,
                    config=config,
                    provider=provider,
                    base_url=base_url,
                    model=model,
                    runtime=runtime,
                    prompt_context=prompt_context,
                    enforce_tool_bounds=prompt_context is None,
                    agent_prompt=agent_prompt,
                ),
            )
        except Exception as exc:
            logger.warning(
                "openai-compatible provider %s failed error=%s", provider, exc
            )
            return heuristic_analysis(
                surface,
                [
                    f"{provider} provider failed; falling back to heuristic analysis. "
                    f"Reason: {exc}"
                ],
                agent_prompt=agent_prompt,
            )

    elif provider == "gemini":
        model = (runtime.model or "").strip() or "gemini-2.0-flash"
        try:
            return _run_batched_runtime_analysis(
                surface=surface,
                config=config,
                source=AnalysisSource.GEMINI,
                model=model,
                provider="gemini",
                options=options,
                agent_prompt=agent_prompt,
                progress_cb=progress_cb,
                analyze_batch=lambda batch_surface, prompt_context: gemini_analysis(
                    surface=batch_surface,
                    config=config,
                    model=model,
                    runtime=runtime,
                    prompt_context=prompt_context,
                    enforce_tool_bounds=prompt_context is None,
                    agent_prompt=agent_prompt,
                ),
            )
        except Exception as exc:
            logger.warning("gemini provider failed; using heuristic analysis error=%s", exc)
            return heuristic_analysis(
                surface,
                [
                    f"Gemini provider failed; falling back to heuristic analysis. Reason: {exc}"
                ],
                agent_prompt=agent_prompt,
            )

    else:
        logger.warning("unsupported provider %s; using heuristic analysis", provider)
        return heuristic_analysis(
            surface,
            [f"Unsupported LLM provider '{provider}' configured; using heuristic analysis."],
            agent_prompt=agent_prompt,
        )


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


def anthropic_analysis_with_model(
    surface: UasfSurface,
    config: AppConfig,
    model: str,
    api_key: str,
    runtime: LlmRuntimeConfig | None,
    prompt_context: _BatchPromptContext | None,
    enforce_tool_bounds: bool,
    agent_prompt: str | None = None,
) -> AnalysisPlan:
    started = time.monotonic()
    logger.debug(
        "calling anthropic analysis model=%s endpoint_count=%d agent_prompt=%s",
        model,
        len(surface.endpoints),
        bool(agent_prompt),
    )
    endpoint_catalog = endpoint_catalog_json(surface)
    user_prompt = analysis_prompt(config, endpoint_catalog, prompt_context, agent_prompt=agent_prompt, endpoint_count=len(surface.endpoints))

    request_body: dict[str, Any] = {
        "model": model,
        "max_tokens": config.anthropic.max_tokens,
        "temperature": config.anthropic.temperature,
        "system": "You design high-quality MCP tool plans. Respond with valid JSON only.",
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
    }

    headers: dict[str, str] = {
        "x-api-key": api_key,
        "anthropic-version": (
            runtime.api_version if runtime and runtime.api_version else ANTHROPIC_VERSION
        ),
        "content-type": "application/json",
        "user-agent": "selqor-forge/0.1.0",
    }
    if runtime is not None:
        _apply_runtime_headers_dict(headers, runtime)

    client = httpx.Client(timeout=LLM_HTTP_TIMEOUT_SECS)
    try:
        try:
            response = client.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=request_body,
            )
        except Exception as exc:
            message = f"failed to call Anthropic Messages API: {exc}"
            _record_llm_call_trace(LlmCallTrace(
                provider="anthropic",
                model=model,
                endpoint=ANTHROPIC_API_URL,
                request_payload=request_body,
                response_payload=None,
                response_text=None,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message) from exc

        if not response.is_success:
            body = response.text
            message = f"Anthropic API returned status {response.status_code}: {body}"
            _record_llm_call_trace(LlmCallTrace(
                provider="anthropic",
                model=model,
                endpoint=ANTHROPIC_API_URL,
                request_payload=request_body,
                response_payload=_try_parse_json(body),
                response_text=body,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message)

        response_text = response.text
    finally:
        client.close()

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        message = f"failed parsing Anthropic API response: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider="anthropic",
            model=model,
            endpoint=ANTHROPIC_API_URL,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    # Extract text blocks from Anthropic content array
    text_blocks: list[str] = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text_blocks.append(block.get("text", ""))
    combined_text = "\n".join(text_blocks)

    json_text = extract_first_json_object(combined_text)
    if json_text is None:
        message = "Anthropic response did not include a JSON object"
        _record_llm_call_trace(LlmCallTrace(
            provider="anthropic",
            model=model,
            endpoint=ANTHROPIC_API_URL,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        message = f"Anthropic response JSON did not match expected tool-plan shape: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider="anthropic",
            model=model,
            endpoint=ANTHROPIC_API_URL,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    plan = normalize_anthropic_plan(surface, parsed, config, enforce_tool_bounds)
    if runtime is not None:
        plan.source = AnalysisSource.ANTHROPIC
        plan.model = model

    if not plan.tools:
        message = "Anthropic analysis produced zero usable tools"
        _record_llm_call_trace(LlmCallTrace(
            provider="anthropic",
            model=model,
            endpoint=ANTHROPIC_API_URL,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    logger.debug(
        "anthropic analysis plan ready model=%s tools=%d warnings=%d",
        model,
        len(plan.tools),
        len(plan.warnings),
    )

    _record_llm_call_trace(LlmCallTrace(
        provider="anthropic",
        model=model,
        endpoint=ANTHROPIC_API_URL,
        request_payload=request_body,
        response_payload=_try_parse_json(response_text),
        response_text=response_text,
        success=True,
        latency_ms=_elapsed_millis(started),
        error=None,
    ))

    return plan


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------


def openai_compatible_analysis(
    surface: UasfSurface,
    config: AppConfig,
    provider: str,
    base_url: str,
    model: str,
    runtime: LlmRuntimeConfig,
    prompt_context: _BatchPromptContext | None,
    enforce_tool_bounds: bool,
    agent_prompt: str | None = None,
) -> AnalysisPlan:
    started = time.monotonic()
    logger.debug(
        "calling openai-compatible analysis provider=%s model=%s base_url=%s endpoint_count=%d",
        provider,
        model,
        base_url,
        len(surface.endpoints),
    )
    endpoint_catalog = endpoint_catalog_json(surface)
    user_prompt = analysis_prompt(config, endpoint_catalog, prompt_context, agent_prompt=agent_prompt, endpoint_count=len(surface.endpoints))

    request_body: dict[str, Any] = {
        "model": model,
        "temperature": config.anthropic.temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You design high-quality MCP tool plans. Respond with valid JSON only.",
            },
            {"role": "user", "content": user_prompt},
        ],
    }

    url = _join_openai_chat_completions_url(base_url)

    headers: dict[str, str] = {
        "content-type": "application/json",
        "user-agent": "selqor-forge/0.1.0",
    }
    _apply_runtime_auth_dict(headers, runtime, "Authorization", "Bearer")

    client = httpx.Client(timeout=LLM_HTTP_TIMEOUT_SECS)
    try:
        try:
            response = client.post(url, headers=headers, json=request_body)
        except Exception as exc:
            message = f"failed to call {provider} chat completions API: {exc}"
            _record_llm_call_trace(LlmCallTrace(
                provider=provider,
                model=model,
                endpoint=url,
                request_payload=request_body,
                response_payload=None,
                response_text=None,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message) from exc

        if not response.is_success:
            body = response.text
            message = f"{provider} API returned status {response.status_code}: {body}"
            _record_llm_call_trace(LlmCallTrace(
                provider=provider,
                model=model,
                endpoint=url,
                request_payload=request_body,
                response_payload=_try_parse_json(body),
                response_text=body,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message)

        response_text = response.text
    finally:
        client.close()

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        message = f"failed parsing {provider} API response: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider=provider,
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    # Extract content from first choice
    content = ""
    for choice in payload.get("choices", []):
        msg = choice.get("message", {})
        if msg.get("content"):
            content = msg["content"]
            break

    json_text = extract_first_json_object(content)
    if json_text is None:
        message = "LLM response did not include a JSON object"
        _record_llm_call_trace(LlmCallTrace(
            provider=provider,
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        message = f"LLM response JSON did not match expected tool-plan shape: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider=provider,
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    plan = normalize_anthropic_plan(surface, parsed, config, enforce_tool_bounds)
    plan.source = _analysis_source_from_provider(provider)
    plan.model = model

    logger.debug(
        "openai-compatible analysis plan ready provider=%s model=%s tools=%d warnings=%d",
        provider,
        model,
        len(plan.tools),
        len(plan.warnings),
    )

    if not plan.tools:
        message = "LLM analysis produced zero usable tools"
        _record_llm_call_trace(LlmCallTrace(
            provider=provider,
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    _record_llm_call_trace(LlmCallTrace(
        provider=provider,
        model=model,
        endpoint=url,
        request_payload=request_body,
        response_payload=_try_parse_json(response_text),
        response_text=response_text,
        success=True,
        latency_ms=_elapsed_millis(started),
        error=None,
    ))

    return plan


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------


def gemini_analysis(
    surface: UasfSurface,
    config: AppConfig,
    model: str,
    runtime: LlmRuntimeConfig,
    prompt_context: _BatchPromptContext | None,
    enforce_tool_bounds: bool,
    agent_prompt: str | None = None,
) -> AnalysisPlan:
    started = time.monotonic()
    logger.debug(
        "calling gemini analysis model=%s endpoint_count=%d",
        model,
        len(surface.endpoints),
    )
    endpoint_catalog = endpoint_catalog_json(surface)
    user_prompt = analysis_prompt(config, endpoint_catalog, prompt_context, agent_prompt=agent_prompt, endpoint_count=len(surface.endpoints))

    base = (
        runtime.base_url
        or "https://generativelanguage.googleapis.com/v1beta"
    )

    model_path = model if model.startswith("models/") else f"models/{model}"

    url = f"{base.rstrip('/')}/{model_path}:generateContent"

    auth_type = runtime.auth_type.strip().lower()
    if auth_type in ("", "api_key"):
        api_key = (runtime.api_key or "").strip()
        if api_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={api_key}"

    request_body: dict[str, Any] = {
        "systemInstruction": {
            "parts": [
                {
                    "text": "You design high-quality MCP tool plans. Respond with valid JSON only."
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "temperature": config.anthropic.temperature,
            "responseMimeType": "application/json",
        },
    }

    headers: dict[str, str] = {
        "content-type": "application/json",
        "user-agent": "selqor-forge/0.1.0",
    }
    if auth_type in ("api_key", ""):
        _apply_runtime_headers_dict(headers, runtime)
    else:
        _apply_runtime_auth_dict(headers, runtime, "Authorization", "Bearer")

    client = httpx.Client(timeout=LLM_HTTP_TIMEOUT_SECS)
    try:
        try:
            response = client.post(url, headers=headers, json=request_body)
        except Exception as exc:
            message = f"failed to call Gemini API: {exc}"
            _record_llm_call_trace(LlmCallTrace(
                provider="gemini",
                model=model,
                endpoint=url,
                request_payload=request_body,
                response_payload=None,
                response_text=None,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message) from exc

        if not response.is_success:
            body = response.text
            message = f"Gemini API returned status {response.status_code}: {body}"
            _record_llm_call_trace(LlmCallTrace(
                provider="gemini",
                model=model,
                endpoint=url,
                request_payload=request_body,
                response_payload=_try_parse_json(body),
                response_text=body,
                success=False,
                latency_ms=_elapsed_millis(started),
                error=message,
            ))
            raise RuntimeError(message)

        response_text = response.text
    finally:
        client.close()

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        message = f"failed parsing Gemini API response: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider="gemini",
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    # Extract text from Gemini response structure
    text_parts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                text_parts.append(part["text"])
    combined_text = "\n".join(text_parts)

    json_text = extract_first_json_object(combined_text)
    if json_text is None:
        message = "Gemini response did not include a JSON object"
        _record_llm_call_trace(LlmCallTrace(
            provider="gemini",
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        message = f"Gemini response JSON did not match expected tool-plan shape: {exc}"
        _record_llm_call_trace(LlmCallTrace(
            provider="gemini",
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message) from exc

    plan = normalize_anthropic_plan(surface, parsed, config, enforce_tool_bounds)
    plan.source = AnalysisSource.GEMINI
    plan.model = model

    logger.debug(
        "gemini analysis plan ready model=%s tools=%d warnings=%d",
        model,
        len(plan.tools),
        len(plan.warnings),
    )

    if not plan.tools:
        message = "Gemini analysis produced zero usable tools"
        _record_llm_call_trace(LlmCallTrace(
            provider="gemini",
            model=model,
            endpoint=url,
            request_payload=request_body,
            response_payload=_try_parse_json(response_text),
            response_text=response_text,
            success=False,
            latency_ms=_elapsed_millis(started),
            error=message,
        ))
        raise RuntimeError(message)

    _record_llm_call_trace(LlmCallTrace(
        provider="gemini",
        model=model,
        endpoint=url,
        request_payload=request_body,
        response_payload=_try_parse_json(response_text),
        response_text=response_text,
        success=True,
        latency_ms=_elapsed_millis(started),
        error=None,
    ))

    return plan


# ---------------------------------------------------------------------------
# Auth / headers helpers (dict-based, unlike Rust's RequestBuilder chaining)
# ---------------------------------------------------------------------------


def _apply_runtime_auth_dict(
    headers: dict[str, str],
    runtime: LlmRuntimeConfig,
    default_header_name: str,
    default_prefix: str | None,
) -> None:
    """Apply auth credentials to a headers dict based on runtime configuration."""
    auth_type = runtime.auth_type.strip().lower()

    if auth_type == "basic":
        username = runtime.username
        password = runtime.password
        if username and password:
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"

    elif auth_type == "bearer":
        token = (runtime.bearer_token or runtime.api_key or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "token":
        token = (runtime.api_key or runtime.bearer_token or "").strip()
        if token:
            header_name = (runtime.auth_header_name or "").strip() or default_header_name
            prefix = runtime.auth_header_prefix if runtime.auth_header_prefix is not None else (default_prefix or "")
            if prefix:
                headers[header_name] = f"{prefix} {token}"
            else:
                headers[header_name] = token

    elif auth_type in ("none", "custom_headers"):
        pass  # no auth

    else:
        # Fallback for unknown auth types
        api_key = (runtime.api_key or "").strip()
        if api_key:
            header_name = (runtime.auth_header_name or "").strip() or default_header_name
            prefix = runtime.auth_header_prefix if runtime.auth_header_prefix is not None else (default_prefix or "")
            if prefix:
                headers[header_name] = f"{prefix} {api_key}"
            else:
                headers[header_name] = api_key

    _apply_runtime_headers_dict(headers, runtime)


def _apply_runtime_headers_dict(
    headers: dict[str, str],
    runtime: LlmRuntimeConfig,
) -> None:
    """Apply custom headers from runtime configuration."""
    for key, value in runtime.custom_headers.items():
        k = key.strip()
        v = value.strip()
        if k and v:
            headers[k] = v


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _join_openai_chat_completions_url(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    if trimmed.endswith("/v1/chat/completions"):
        return trimmed
    if trimmed.endswith("/v1"):
        return f"{trimmed}/chat/completions"
    return f"{trimmed}/v1/chat/completions"


# ---------------------------------------------------------------------------
# Batched analysis orchestration
# ---------------------------------------------------------------------------


def _run_batched_runtime_analysis(
    surface: UasfSurface,
    config: AppConfig,
    source: AnalysisSource,
    model: str,
    provider: str,
    options: AnalyzeOptions | None,
    analyze_batch: Callable[
        [UasfSurface, _BatchPromptContext | None], AnalysisPlan
    ],
    agent_prompt: str | None = None,
    progress_cb: Callable[[dict], None] | None = None,
) -> AnalysisPlan:
    def _emit_progress(**payload: Any) -> None:
        """Safe helper -- a broken callback must not break the pipeline."""
        if progress_cb is None:
            return
        try:
            progress_cb(payload)
        except Exception:  # noqa: BLE001
            logger.debug("progress_cb raised; ignoring", exc_info=True)

    max_input_tokens = MAX_INPUT_TOKENS_DEFAULT
    if options and options.max_input_tokens > 0:
        max_input_tokens = options.max_input_tokens

    endpoint_batches = build_endpoint_batches(surface, max_input_tokens)
    if len(endpoint_batches) <= 1:
        _emit_progress(
            phase="analyze",
            total_batches=1,
            completed_batches=0,
            current_batch=1,
            event="batch_start",
            batch_endpoints=len(surface.endpoints),
        )
        plan = analyze_batch(surface, None)
        _emit_progress(
            phase="analyze",
            total_batches=1,
            completed_batches=1,
            current_batch=1,
            event="complete",
        )
        return plan

    logger.debug(
        "running batched LLM analysis provider=%s model=%s endpoint_count=%d "
        "total_batches=%d max_input_tokens=%d",
        provider,
        model,
        len(surface.endpoints),
        len(endpoint_batches),
        max_input_tokens,
    )

    state_path = options.batch_state_path if options else None
    resume_enabled = options.resume_batches if options else False
    total_batches = len(endpoint_batches)

    if resume_enabled:
        persisted_state = _load_persisted_batch_state_from_options(
            state_path, provider, model, max_input_tokens, total_batches
        )
    else:
        persisted_state = _PersistedBatchState()

    if persisted_state.total_batches == 0:
        persisted_state = _PersistedBatchState(
            provider=provider,
            model=model,
            max_input_tokens=max_input_tokens,
            total_batches=total_batches,
            completed_batches=0,
            status="running",
            failed_batch=None,
            batches=[],
        )
    else:
        persisted_state.status = "running"
        persisted_state.failed_batch = None

    if state_path is not None:
        _persist_batch_state(state_path, persisted_state)

    # Collect already-completed batch results
    batch_results: list[_PersistedBatchAnalysis] = sorted(
        [
            b
            for b in persisted_state.batches
            if b.success and b.tools and b.batch_index < total_batches
        ],
        key=lambda b: b.batch_index,
    )

    _emit_progress(
        phase="analyze",
        total_batches=total_batches,
        completed_batches=len(batch_results),
        current_batch=len(batch_results),
        event="start",
    )

    for batch_idx, endpoints in enumerate(endpoint_batches):
        if any(b.batch_index == batch_idx for b in batch_results):
            logger.debug(
                "reusing persisted batch result provider=%s model=%s batch=%d/%d",
                provider,
                model,
                batch_idx + 1,
                total_batches,
            )
            continue

        history = _summarize_prior_batch_context(batch_results)
        prompt_context = _BatchPromptContext(
            batch_index=batch_idx + 1,
            total_batches=total_batches,
            prior_summary=history,
        )

        subset_surface = UasfSurface(
            source=surface.source,
            title=surface.title,
            version=surface.version,
            endpoints=list(endpoints),
            auth_schemes=list(surface.auth_schemes),
        )

        logger.debug(
            "processing llm analysis batch provider=%s model=%s batch=%d/%d endpoints=%d",
            provider,
            model,
            batch_idx + 1,
            total_batches,
            len(subset_surface.endpoints),
        )

        _emit_progress(
            phase="analyze",
            total_batches=total_batches,
            completed_batches=len(batch_results),
            current_batch=batch_idx + 1,
            event="batch_start",
            batch_endpoints=len(subset_surface.endpoints),
        )

        trace_offset = len(peek_llm_call_traces())

        try:
            batch_plan = analyze_batch(subset_surface, prompt_context)
        except Exception as error:
            traces = peek_llm_call_traces()
            trace = traces[trace_offset:][- 1] if len(traces) > trace_offset else None
            persisted = _batch_result_from_trace(
                batch_idx, endpoints, trace, None, str(error)
            )
            _upsert_persisted_batch_result(persisted_state, persisted)
            persisted_state.completed_batches = sum(
                1 for b in persisted_state.batches if b.success
            )
            persisted_state.status = "failed"
            persisted_state.failed_batch = batch_idx + 1
            if state_path is not None:
                try:
                    _persist_batch_state(state_path, persisted_state)
                except Exception:
                    pass
            raise

        traces = peek_llm_call_traces()
        trace = traces[trace_offset:][-1] if len(traces) > trace_offset else None
        persisted = _batch_result_from_trace(
            batch_idx, endpoints, trace, batch_plan, None
        )
        _upsert_persisted_batch_result(persisted_state, persisted)
        batch_results.append(persisted)
        batch_results.sort(key=lambda b: b.batch_index)
        persisted_state.completed_batches = sum(
            1 for b in persisted_state.batches if b.success
        )
        if state_path is not None:
            _persist_batch_state(state_path, persisted_state)

        _emit_progress(
            phase="analyze",
            total_batches=total_batches,
            completed_batches=len(batch_results),
            current_batch=batch_idx + 1,
            event="batch_done",
        )

    _emit_progress(
        phase="analyze",
        total_batches=total_batches,
        completed_batches=total_batches,
        current_batch=total_batches,
        event="complete",
    )

    # Merge all batch results
    merged_tools: list[AnalysisToolCandidate] = []
    merged_warnings: list[str] = []
    for batch in batch_results:
        merged_tools.extend(batch.tools)
        merged_warnings.extend(batch.warnings)
    merged_warnings.append(
        f"{provider} analysis executed in {total_batches} batches with "
        f"max {max_input_tokens} input tokens per request."
    )

    merged_plan = _normalize_merged_batch_plan(
        surface, config, source, model, merged_tools, merged_warnings
    )

    persisted_state.completed_batches = total_batches
    persisted_state.status = "completed"
    persisted_state.failed_batch = None
    if state_path is not None:
        _persist_batch_state(state_path, persisted_state)

    return merged_plan


# ---------------------------------------------------------------------------
# Endpoint batching
# ---------------------------------------------------------------------------


def build_endpoint_batches(
    surface: UasfSurface,
    max_input_tokens: int,
) -> list[list[UasfEndpoint]]:
    """Split endpoints into token-budget-aware batches."""
    endpoint_budget = min(
        max(
            max_input_tokens - BATCH_PROMPT_OVERHEAD_TOKENS - BATCH_HISTORY_TOKEN_BUDGET,
            0,
        ),
        BATCH_ENDPOINT_TOKEN_BUDGET,
    )
    endpoint_budget = max(endpoint_budget, 2_000)

    batches: list[list[UasfEndpoint]] = []
    current_batch: list[UasfEndpoint] = []
    current_tokens = 0

    for endpoint in surface.endpoints:
        entry = _endpoint_catalog_entry(endpoint)
        serialized = json.dumps(entry)
        estimated_tokens = _estimate_text_tokens(serialized) + 24

        if current_batch and (current_tokens + estimated_tokens) > endpoint_budget:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(endpoint)
        current_tokens += estimated_tokens

    if current_batch:
        batches.append(current_batch)

    if not batches:
        batches.append([])

    return batches


def _estimate_text_tokens(text: str) -> int:
    """Estimate token count: roughly len(text) // 4."""
    return (len(text) + 3) // 4


# ---------------------------------------------------------------------------
# Batch context summarization
# ---------------------------------------------------------------------------


def _summarize_prior_batch_context(
    batch_results: list[_PersistedBatchAnalysis],
) -> str | None:
    if not batch_results:
        return None

    lines: list[str] = []
    for batch in batch_results:
        for tool in batch.tools:
            endpoints = ", ".join(tool.covered_endpoints[:10])
            lines.append(
                f"- {tool.name}: {_normalize_description(tool.description)} | endpoints: {endpoints}"
            )

    text = "\n".join(lines)
    estimated = _estimate_text_tokens(text)
    while estimated > BATCH_HISTORY_TOKEN_BUDGET and text:
        new_len = max(len(text) - 600, 0)
        text = text[:new_len]
        estimated = _estimate_text_tokens(text)

    if not text.strip():
        return None
    return text


# ---------------------------------------------------------------------------
# Merged batch plan normalization
# ---------------------------------------------------------------------------


def _normalize_merged_batch_plan(
    surface: UasfSurface,
    config: AppConfig,
    source: AnalysisSource,
    model: str | None,
    candidates: list[AnalysisToolCandidate],
    warnings: list[str],
) -> AnalysisPlan:
    known_ids = {ep.id for ep in surface.endpoints}

    # Group by normalized name: (description, endpoint_ids)
    grouped: dict[str, tuple[str, set[str]]] = {}
    for candidate in candidates:
        normalized_name = sanitize_tool_name(candidate.name)
        name_key = normalized_name if normalized_name else "tool"

        if name_key not in grouped:
            grouped[name_key] = (
                _normalize_description(candidate.description),
                set(),
            )

        entry = grouped[name_key]
        desc = entry[0]
        if len(candidate.description.strip()) > len(desc.strip()):
            desc = _normalize_description(candidate.description)

        ep_ids = entry[1]
        for eid in candidate.covered_endpoints:
            if eid in known_ids:
                ep_ids.add(eid)

        grouped[name_key] = (desc, ep_ids)

    tools: list[AnalysisToolCandidate] = []
    seen_names: set[str] = set()
    for base_name in sorted(grouped.keys()):
        description, endpoint_ids = grouped[base_name]
        if not endpoint_ids:
            warnings.append(
                f"Dropped merged tool '{base_name}' because it had no valid endpoint ids."
            )
            continue

        name = base_name
        dedupe_idx = 2
        while name in seen_names:
            name = f"{base_name}_{dedupe_idx}"
            dedupe_idx += 1
        seen_names.add(name)

        tools.append(AnalysisToolCandidate(
            name=name,
            description=description,
            covered_endpoints=sorted(endpoint_ids),
            # confidence is computed by curate.curate() final pass
        ))

    if len(tools) < config.target_tool_count.min:
        warnings.append(
            f"Merged LLM plan produced {len(tools)} tools, below min "
            f"{config.target_tool_count.min}. Curator will expand intent splits."
        )

    if len(tools) > config.target_tool_count.max:
        warnings.append(
            f"Merged LLM plan produced {len(tools)} tools, above max "
            f"{config.target_tool_count.max}. Curator will merge tools."
        )

    return AnalysisPlan(
        source=source,
        model=model,
        tools=tools,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Batch persistence helpers
# ---------------------------------------------------------------------------


def _batch_result_from_trace(
    batch_idx: int,
    endpoints: list[UasfEndpoint],
    trace: LlmCallTrace | None,
    plan: AnalysisPlan | None,
    forced_error: str | None,
) -> _PersistedBatchAnalysis:
    if trace is not None:
        request_payload = trace.request_payload
        response_payload = trace.response_payload
        response_text = trace.response_text
        success = trace.success
        error = forced_error or trace.error
    else:
        request_payload = {}
        response_payload = None
        response_text = None
        success = forced_error is None
        error = forced_error

    return _PersistedBatchAnalysis(
        batch_index=batch_idx,
        endpoint_ids=[ep.id for ep in endpoints],
        request_payload=request_payload,
        response_payload=response_payload,
        response_text=response_text,
        success=success and plan is not None,
        error=error,
        tools=list(plan.tools) if plan else [],
        warnings=list(plan.warnings) if plan else [],
    )


def _upsert_persisted_batch_result(
    state: _PersistedBatchState,
    result: _PersistedBatchAnalysis,
) -> None:
    for i, batch in enumerate(state.batches):
        if batch.batch_index == result.batch_index:
            state.batches[i] = result
            return
    state.batches.append(result)
    state.batches.sort(key=lambda b: b.batch_index)


def _load_persisted_batch_state_from_options(
    path: Path | None,
    provider: str,
    model: str,
    max_input_tokens: int,
    total_batches: int,
) -> _PersistedBatchState:
    if path is None:
        return _PersistedBatchState()
    existing = _load_persisted_batch_state(path)
    if existing is None:
        return _PersistedBatchState()
    if (
        existing.provider != provider
        or existing.model != model
        or existing.max_input_tokens != max_input_tokens
        or existing.total_batches != total_batches
    ):
        return _PersistedBatchState()
    return existing


def _load_persisted_batch_state(path: Path) -> _PersistedBatchState | None:
    if not path.exists():
        return None
    raw = path.read_text()
    data = json.loads(raw)
    return _PersistedBatchState.from_dict(data)


def _persist_batch_state(path: Path, state: _PersistedBatchState) -> None:
    parent = path.parent
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2)
    path.write_text(payload)


def load_batch_state_snapshot(path: Path) -> LlmBatchStateSnapshot | None:
    """Load a batch state snapshot from a persisted state file."""
    state = _load_persisted_batch_state(path)
    if state is None:
        return None

    completed = min(state.completed_batches, state.total_batches, len(state.batches))

    return LlmBatchStateSnapshot(
        total_batches=state.total_batches,
        completed_batches=completed,
        pending_batches=max(state.total_batches - completed, 0),
        status=state.status,
        failed_batch=state.failed_batch,
    )


# ---------------------------------------------------------------------------
# Provider source mapping
# ---------------------------------------------------------------------------


def _analysis_source_from_provider(provider: str) -> AnalysisSource:
    mapping: dict[str, AnalysisSource] = {
        "openai": AnalysisSource.OPEN_AI,
        "vllm": AnalysisSource.VLLM,
        "sarvam": AnalysisSource.SARVAM,
        "mistral": AnalysisSource.MISTRAL,
        "gemini": AnalysisSource.GEMINI,
        "aws_bedrock": AnalysisSource.AWS_BEDROCK,
        "vertex_ai": AnalysisSource.VERTEX_AI,
    }
    return mapping.get(provider, AnalysisSource.ANTHROPIC)


# ---------------------------------------------------------------------------
# Heuristic analysis (no LLM)
# ---------------------------------------------------------------------------


_HEURISTIC_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "for", "of", "in", "on",
    "at", "by", "from", "with", "as", "is", "are", "was", "were", "be",
    "been", "being", "it", "this", "that", "these", "those", "i", "we",
    "you", "they", "he", "she", "my", "our", "your", "their", "me", "us",
    "them", "him", "her", "what", "which", "who", "whom", "whose", "when",
    "where", "why", "how", "do", "does", "did", "have", "has", "had", "can",
    "could", "should", "would", "will", "may", "might", "must", "shall",
    "not", "no", "so", "if", "then", "than", "also", "about", "into", "out",
    "up", "down", "over", "under", "any", "all", "some", "such", "only",
    "just", "need", "needs", "want", "wants", "help", "helps", "use", "uses",
    "using", "api", "agent", "tool", "tools", "task", "tasks", "please",
})


def _naive_stem(word: str) -> str:
    """Reduce a word to an approximate root form without external libraries.

    Strips common English suffixes so that ``payments`` matches ``payment``,
    ``subscriptions`` matches ``subscription``, ``processing`` matches
    ``process``, etc. This is intentionally aggressive — false positives
    (``billing`` → ``bill``) are acceptable because they increase recall in
    keyword matching, and precision is ensured by requiring multiple hits.
    """
    w = word.lower()
    # Order matters: try longest suffixes first
    for suffix in (
        "ations", "ation", "ments", "ment", "ings", "ing",
        "tions", "tion", "sions", "sion", "ences", "ence",
        "ances", "ance", "ities", "ity", "ness", "ment",
        "ists", "ist", "ous", "ive", "ful", "less",
        "able", "ible", "ally", "ies", "ers", "er",
        "ors", "or", "ess", "ess", "eds", "ed",
        "es", "ly", "al", "s",
    ):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def _tokenize_and_stem(text: str) -> set[str]:
    """Extract stemmed tokens from text. Splits on non-alphanumeric chars."""
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text.lower())
    # Also split camelCase: PaymentIntents → payment, intents
    expanded: list[str] = []
    for tok in raw_tokens:
        parts = re.findall(r"[A-Z]?[a-z0-9]+", tok)
        if parts:
            expanded.extend(parts)
        else:
            expanded.append(tok)
    return {_naive_stem(t) for t in expanded if t not in _HEURISTIC_STOPWORDS and len(t) >= 3}


def _extract_agent_keywords(agent_prompt: str | None) -> set[str]:
    """Extract stemmed keywords from an agent intent prompt."""
    if not agent_prompt:
        return set()
    return _tokenize_and_stem(agent_prompt)


def _endpoint_haystack_tokens(endpoint: UasfEndpoint) -> set[str]:
    """Extract stemmed tokens from all searchable fields of an endpoint."""
    text = " ".join([
        endpoint.id or "",
        endpoint.path.replace("/", " ").replace("{", " ").replace("}", " "),
        endpoint.summary or "",
        endpoint.description or "",
        endpoint.domain or "",
        " ".join(endpoint.tags or []),
    ])
    return _tokenize_and_stem(text)


def _score_endpoint_against_keywords(
    endpoint: UasfEndpoint, keywords: set[str]
) -> int:
    """Score an endpoint against agent keywords using stemmed token overlap."""
    if not keywords:
        return 0
    ep_tokens = _endpoint_haystack_tokens(endpoint)
    return len(keywords & ep_tokens)


def _build_domain_relevance_scores(
    endpoints: list[UasfEndpoint],
    agent_keywords: set[str],
) -> dict[str, float]:
    """Score each domain's overall relevance to the agent intent.

    Aggregates keyword hits across all endpoints in a domain and normalizes.
    This way, a domain like ``PaymentIntents`` scores high against
    ``payments`` even if individual endpoint summaries use different vocabulary
    like ``charge`` or ``capture``, because the domain name itself matches.
    """
    domain_eps: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        domain_eps.setdefault(ep.domain, []).append(ep)

    raw_scores: dict[str, float] = {}
    for domain, eps in domain_eps.items():
        # Score the domain name itself
        domain_tokens = _tokenize_and_stem(domain)
        domain_name_hits = len(agent_keywords & domain_tokens)

        # Score the aggregate vocabulary of all endpoints in this domain
        all_tokens: set[str] = set()
        for ep in eps:
            all_tokens.update(_endpoint_haystack_tokens(ep))
        vocab_hits = len(agent_keywords & all_tokens)

        # Combined: domain name match is worth more (×3) than vocabulary match
        raw_scores[domain] = domain_name_hits * 3 + vocab_hits

    # Max-normalize: the highest-scoring domain gets 1.0, everything else
    # is relative. This eliminates prompt-length bias — a 5-keyword prompt
    # and a 50-keyword prompt produce the same ranking.
    max_raw = max(raw_scores.values()) if raw_scores else 1
    max_raw = max(max_raw, 1)  # avoid division by zero
    return {d: v / max_raw for d, v in raw_scores.items()}


def _intent_label(agent_prompt: str) -> str:
    """Produce a short snake_case label summarising the agent intent."""
    keywords = _extract_agent_keywords(agent_prompt)
    # Preserve prompt order for readability instead of using set order.
    ordered: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", agent_prompt.lower()):
        if tok in keywords and tok not in seen:
            ordered.append(tok)
            seen.add(tok)
        if len(ordered) >= 3:
            break
    if not ordered:
        return "agent"
    return "_".join(ordered)


def heuristic_analysis(
    surface: UasfSurface,
    warnings: list[str] | None = None,
    *,
    agent_prompt: str | None = None,
) -> AnalysisPlan:
    """Build an analysis plan using smart heuristics.

    Strategy:
    1. Detect cross-domain workflows via parameter/path sharing.
    2. Group by adaptive granularity per domain size:
       - 1-4 endpoints → single lifecycle tool (``manage_{domain}``)
       - 5-12 endpoints → split by intent (``{domain}_{intent}``)
       - 13+ endpoints → split by intent + sub-resource
    3. When an agent prompt is provided, use it as a semantic filter to tier
       endpoints as core / supporting / peripheral and merge peripheral
       domains aggressively.
    """
    if warnings is None:
        warnings = []
    else:
        warnings = list(warnings)

    logger.debug(
        "building heuristic analysis plan endpoints=%d prior_warnings=%d agent_prompt=%s",
        len(surface.endpoints),
        len(warnings),
        bool(agent_prompt and agent_prompt.strip()),
    )

    agent_keywords = _extract_agent_keywords(agent_prompt)

    # Phase 1: detect cross-domain workflows (parameter/path sharing)
    workflow_tools, remaining_eps = _detect_cross_domain_workflows(
        surface.endpoints, agent_keywords, warnings,
    )

    # Phase 2: group remaining endpoints with adaptive granularity
    if agent_keywords:
        domain_tools = _group_with_agent_filter(
            remaining_eps, agent_keywords, agent_prompt, warnings,
        )
    else:
        domain_tools = _group_adaptive(remaining_eps)

    tools: list[AnalysisToolCandidate] = workflow_tools + domain_tools

    if not tools:
        warnings.append("Heuristic analysis produced zero domain groups.")

    return AnalysisPlan(
        source=AnalysisSource.HEURISTIC,
        model=None,
        tools=tools,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Cross-domain workflow detection
# ---------------------------------------------------------------------------


def _parse_path_segments(path: str) -> list[str]:
    """Extract non-parameter segments from a path: /pets/{id}/toys → ['pets', 'toys']."""
    return [
        seg for seg in path.strip("/").split("/")
        if seg and not seg.startswith("{")
    ]


def _extract_path_param_names(path: str) -> set[str]:
    """Extract parameter names from a path: /pets/{petId}/toys/{toyId} → {'petId', 'toyId'}."""
    return {
        seg.strip("{}")
        for seg in path.strip("/").split("/")
        if seg.startswith("{") and seg.endswith("}")
    }


_MAX_WORKFLOW_FRACTION = 0.30  # A workflow can absorb at most 30% of all endpoints


# ---------------------------------------------------------------------------
# Statistical scope-prefix detection (no hardcoded lists)
# ---------------------------------------------------------------------------


def _is_scope_prefix(
    segment: str,
    segment_eps: list[UasfEndpoint],
    total_endpoint_count: int,
) -> bool:
    """Statistically determine whether a path segment is a scope prefix.

    A scope prefix (``/me``, ``/admin``, ``/v2``) fans out to many unrelated
    sub-resources and domains. A real domain resource (``/artists``,
    ``/albums``) clusters around one concept.

    Three signals (all must hold for scope detection):

    1. **Domain fan-out**: the segment's endpoints span ≥4 distinct domains,
       OR the segment covers >25% of total endpoints.
    2. **Sub-resource diversity**: ≥3 distinct child path segments appear
       beneath this segment (e.g., ``/me/albums``, ``/me/tracks``).
    3. **Low self-identity**: the segment is NOT the domain tag for the
       majority of its endpoints.
    """
    if not segment_eps:
        return False

    domains = {ep.domain for ep in segment_eps}
    child_segments: set[str] = set()
    domain_match_count = 0

    for ep in segment_eps:
        segs = _parse_path_segments(ep.path)
        try:
            idx = segs.index(segment)
            for s in segs[idx + 1:]:
                child_segments.add(s)
                break
        except (ValueError, IndexError):
            pass

        if ep.domain.lower().replace(" ", "_") == segment.lower():
            domain_match_count += 1

    self_domain_ratio = domain_match_count / len(segment_eps)
    if self_domain_ratio > 0.5:
        return False

    high_fan_out = len(domains) >= 4
    large_fraction = len(segment_eps) > total_endpoint_count * 0.25
    diverse_children = len(child_segments) >= 3

    return (high_fan_out or large_fraction) and diverse_children


# ---------------------------------------------------------------------------
# Parameter dependency graph
# ---------------------------------------------------------------------------


def _extract_schema_field_names(schema: Any, depth: int = 0) -> set[str]:
    """Recursively extract field names from a JSON Schema (max depth 3)."""
    if depth > 3 or not isinstance(schema, dict):
        return set()
    names: set[str] = set()
    for key, val in schema.get("properties", {}).items():
        names.add(key.lower())
        names.update(_extract_schema_field_names(val, depth + 1))
    # Handle items in array schemas
    items = schema.get("items")
    if isinstance(items, dict):
        names.update(_extract_schema_field_names(items, depth + 1))
    return names


def _build_dependency_edges(
    endpoints: list[UasfEndpoint],
) -> dict[str, set[str]]:
    """Build a parameter dependency graph between endpoints.

    If endpoint A's response schema contains a field name that matches
    endpoint B's path parameter, draw an edge A → B. This discovers
    implicit workflows: ``GET /artists/{id}`` → ``GET /artists/{id}/albums``
    is linked because ``id`` flows through.

    Also links endpoints sharing the same path parameters (e.g., two
    endpoints both using ``{orderId}``).

    Returns a mapping: endpoint_id → set of endpoint_ids it depends on.
    """
    # Index: parameter name → endpoints that consume it (in path or query)
    param_consumers: dict[str, list[str]] = {}
    # Index: parameter name → endpoints that produce it (in response schema)
    param_producers: dict[str, list[str]] = {}
    # Index: path parameter name → endpoints that use it
    path_param_users: dict[str, list[str]] = {}

    for ep in endpoints:
        # Collect consumed parameters
        for param in ep.parameters:
            param_name = param.name.lower()
            param_consumers.setdefault(param_name, []).append(ep.id)
            if param.location == "path":
                path_param_users.setdefault(param_name, []).append(ep.id)

        # Collect request body field names as consumed parameters
        if ep.request_body_schema:
            for field_name in _extract_schema_field_names(ep.request_body_schema):
                param_consumers.setdefault(field_name, []).append(ep.id)

        # Collect produced parameters from response schemas
        if ep.response_schema:
            for field_name in _extract_schema_field_names(ep.response_schema):
                param_producers.setdefault(field_name, []).append(ep.id)

    # Build edges: producer → consumer relationships
    edges: dict[str, set[str]] = {}
    for param_name, consumers in param_consumers.items():
        producers = param_producers.get(param_name, [])
        for producer_id in producers:
            for consumer_id in consumers:
                if producer_id != consumer_id:
                    edges.setdefault(producer_id, set()).add(consumer_id)
                    edges.setdefault(consumer_id, set()).add(producer_id)

    # Also link endpoints sharing path parameters (same resource)
    for param_name, users in path_param_users.items():
        if len(users) < 2:
            continue
        for i, a in enumerate(users):
            for b in users[i + 1:]:
                edges.setdefault(a, set()).add(b)
                edges.setdefault(b, set()).add(a)

    return edges


def _find_connected_components(
    endpoints: list[UasfEndpoint],
    edges: dict[str, set[str]],
) -> list[list[UasfEndpoint]]:
    """Find connected components in the dependency graph using BFS."""
    ep_by_id = {ep.id: ep for ep in endpoints}
    visited: set[str] = set()
    components: list[list[UasfEndpoint]] = []

    for ep in endpoints:
        if ep.id in visited:
            continue
        # BFS from this endpoint
        queue = [ep.id]
        component_ids: list[str] = []
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component_ids.append(current)
            for neighbor in edges.get(current, set()):
                if neighbor not in visited and neighbor in ep_by_id:
                    queue.append(neighbor)

        component = [ep_by_id[eid] for eid in component_ids if eid in ep_by_id]
        if component:
            components.append(component)

    return components


# ---------------------------------------------------------------------------
# Cross-domain workflow detection (using both path analysis + dependency graph)
# ---------------------------------------------------------------------------


def _detect_cross_domain_workflows(
    endpoints: list[UasfEndpoint],
    agent_keywords: set[str],
    warnings: list[str],
) -> tuple[list[AnalysisToolCandidate], list[UasfEndpoint]]:
    """Find endpoints across different domains that form natural workflows.

    Uses two complementary signals:

    1. **Path-structure analysis**: parent-child path nesting where
       ``/artists/{id}/albums`` links the ``artists`` and ``albums`` domains.
       Scope prefixes are filtered statistically (domain fan-out, child
       diversity, self-identity ratio) — no hardcoded lists.

    2. **Parameter dependency graph**: if endpoint A's response contains a
       field used as endpoint B's path parameter, they form a data-flow
       workflow. Connected components spanning 2+ domains become workflow tools.

    A single workflow tool cannot absorb more than 30% of total endpoints.

    Returns (workflow_tools, remaining_endpoints_not_in_workflows).
    """
    total_count = len(endpoints)
    max_workflow_size = max(int(total_count * _MAX_WORKFLOW_FRACTION), 6)

    # --- Signal 1: Path-structure analysis ---
    parent_children: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        segments = _parse_path_segments(ep.path)
        if len(segments) >= 2:
            parent = segments[0]
            parent_children.setdefault(parent, []).append(ep)

    path_workflow_groups: list[tuple[str, list[UasfEndpoint]]] = []
    seen_workflow_eps: set[str] = set()

    for parent, eps in sorted(parent_children.items(), key=lambda kv: -len(kv[1])):
        if _is_scope_prefix(parent, eps, total_count):
            logger.debug(
                "scope prefix detected: '%s' (%d eps, %d domains) — skipping",
                parent, len(eps), len({ep.domain for ep in eps}),
            )
            continue

        domains = {ep.domain for ep in eps}
        if len(domains) < 2 or len(eps) < 3:
            continue

        domain_counts: dict[str, int] = {}
        for ep in eps:
            domain_counts[ep.domain] = domain_counts.get(ep.domain, 0) + 1
        if sum(1 for c in domain_counts.values() if c >= 2) < 2:
            continue

        fresh = [ep for ep in eps if ep.id not in seen_workflow_eps]
        if len(fresh) < 3 or len(fresh) > max_workflow_size:
            continue

        path_workflow_groups.append((parent, fresh))
        for ep in fresh:
            seen_workflow_eps.add(ep.id)

    # --- Signal 2: Parameter dependency graph ---
    remaining_for_dep = [ep for ep in endpoints if ep.id not in seen_workflow_eps]
    dep_edges = _build_dependency_edges(remaining_for_dep)
    components = _find_connected_components(remaining_for_dep, dep_edges)

    dep_workflow_groups: list[tuple[str, list[UasfEndpoint]]] = []
    for component in components:
        domains = {ep.domain for ep in component}
        if len(domains) < 2 or len(component) < 3:
            continue
        if len(component) > max_workflow_size:
            continue
        # Name after the most common domain in the component
        domain_counts_c: dict[str, int] = {}
        for ep in component:
            domain_counts_c[ep.domain] = domain_counts_c.get(ep.domain, 0) + 1
        primary_domain = max(domain_counts_c, key=lambda d: domain_counts_c[d])
        dep_workflow_groups.append((primary_domain, component))
        for ep in component:
            seen_workflow_eps.add(ep.id)

    # --- Build workflow tools from both signals ---
    workflow_tools: list[AnalysisToolCandidate] = []

    for resource, eps in path_workflow_groups + dep_workflow_groups:
        ep_ids = [ep.id for ep in eps]
        clean = _to_title_case(resource)
        domains_involved = sorted({ep.domain for ep in eps})
        intent = _dominant_intent(eps)
        action = _intent_to_action(intent)

        tool_name = f"{sanitize_tool_name(resource)}_workflow"
        description = (
            f"Manage {clean} workflow spanning {', '.join(_to_title_case(d) for d in domains_involved[:3])} "
            f"to {action} resources."
        )

        confidence = 0.85 if agent_keywords else 0.7
        workflow_tools.append(AnalysisToolCandidate(
            name=tool_name,
            description=description,
            covered_endpoints=ep_ids,
            confidence=confidence,
        ))
        warnings.append(
            f"Cross-domain workflow detected: '{tool_name}' spans domains "
            f"{domains_involved} ({len(ep_ids)} endpoints)"
        )

    remaining = [ep for ep in endpoints if ep.id not in seen_workflow_eps]
    return workflow_tools, remaining


# ---------------------------------------------------------------------------
# Adaptive domain grouping (no agent prompt)
# ---------------------------------------------------------------------------


def _group_adaptive(
    endpoints: list[UasfEndpoint],
    base_confidence: float = 0.5,
) -> list[AnalysisToolCandidate]:
    """Group endpoints with adaptive granularity per domain size.

    - 1-4 endpoints: single lifecycle tool (manage_{domain})
    - 5-12 endpoints: split by intent ({domain}_{intent})
    - 13+ endpoints: split by intent + sub-resource

    After grouping, singleton domains (1 endpoint) are merged into the
    nearest related tool to avoid tool pollution.
    """
    by_domain: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        by_domain.setdefault(ep.domain, []).append(ep)

    # Separate singleton domains from real domains
    real_tools: list[AnalysisToolCandidate] = []
    orphan_eps: list[UasfEndpoint] = []

    for domain in sorted(by_domain):
        eps = by_domain[domain]
        count = len(eps)

        if count == 1:
            orphan_eps.extend(eps)
        elif count <= 4:
            real_tools.append(_make_lifecycle_tool(domain, eps, base_confidence))
        elif count <= 12:
            real_tools.extend(_split_by_intent(domain, eps, base_confidence))
        else:
            real_tools.extend(_split_by_intent_and_subresource(domain, eps, base_confidence))

    # Merge orphan endpoints into existing tools or create a combined utility tool
    # Pass all endpoints from this group so Jaccard can resolve tool endpoint IDs
    all_group_eps = [ep for eps in by_domain.values() for ep in eps]
    if orphan_eps and real_tools:
        _absorb_orphans_into_tools(orphan_eps, real_tools, all_group_eps, base_confidence)
    elif orphan_eps:
        # No real tools exist — just make a lifecycle tool from all orphans
        real_tools.append(AnalysisToolCandidate(
            name="manage_api",
            description="Manage miscellaneous API operations.",
            covered_endpoints=[ep.id for ep in orphan_eps],
            confidence=base_confidence * 0.6,
        ))

    return real_tools


def _absorb_orphans_into_tools(
    orphans: list[UasfEndpoint],
    tools: list[AnalysisToolCandidate],
    all_endpoints: list[UasfEndpoint],
    base_confidence: float,
) -> None:
    """Merge singleton-domain orphan endpoints into existing tools or a utility tool.

    Uses Jaccard similarity on actual path segments (not tool names) to find
    the best match. Falls back to intent-family affinity when paths don't
    overlap.
    """
    # Build endpoint lookup so we can resolve tool endpoint IDs to real paths
    ep_by_id = {ep.id: ep for ep in all_endpoints}

    # Pre-compute path segment sets for each tool (sample up to 20 endpoints)
    tool_path_cache: dict[int, set[str]] = {}
    for i, tool in enumerate(tools):
        segments: set[str] = set()
        for eid in tool.covered_endpoints[:20]:
            ep_obj = ep_by_id.get(eid)
            if ep_obj:
                segments.update(_parse_path_segments(ep_obj.path))
        tool_path_cache[i] = segments

    unmatched: list[UasfEndpoint] = []

    for ep in orphans:
        ep_segments = set(_parse_path_segments(ep.path))
        ep_family = _INTENT_AFFINITY.get(_intent_to_action_key(ep.intent), "read")

        best_idx = -1
        best_score = 0.0
        for i, tool in enumerate(tools):
            tool_segments = tool_path_cache[i]
            # Jaccard similarity on path segments
            intersection = len(ep_segments & tool_segments)
            union = len(ep_segments | tool_segments) or 1
            jaccard = intersection / union
            # Intent family bonus
            tool_family = _INTENT_AFFINITY.get(
                _intent_to_action_key(ep.intent), "read"
            )
            family_bonus = 0.15 if ep_family == tool_family else 0.0
            score = jaccard + family_bonus
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score > 0.05:
            tools[best_idx].covered_endpoints.append(ep.id)
            # Update the cache for future orphans
            tool_path_cache[best_idx].update(ep_segments)
        else:
            unmatched.append(ep)

    # Create a utility tool for remaining orphans
    if unmatched:
        if len(unmatched) <= 3:
            smallest = min(tools, key=lambda t: len(t.covered_endpoints))
            for ep in unmatched:
                smallest.covered_endpoints.append(ep.id)
        else:
            tools.append(AnalysisToolCandidate(
                name="utility_operations",
                description="Handle utility and miscellaneous API operations.",
                covered_endpoints=[ep.id for ep in unmatched],
                confidence=base_confidence * 0.5,
            ))


def _make_lifecycle_tool(
    domain: str,
    endpoints: list[UasfEndpoint],
    confidence: float,
) -> AnalysisToolCandidate:
    """Create a single tool covering the full lifecycle of a resource."""
    ep_ids = [ep.id for ep in endpoints]
    clean = _to_title_case(domain)
    intents = sorted({ep.intent.value for ep in endpoints})
    intent_summary = ", ".join(intents)

    return AnalysisToolCandidate(
        name=f"manage_{sanitize_tool_name(domain)}",
        description=f"Manage {clean} resources ({intent_summary}).",
        covered_endpoints=ep_ids,
        confidence=confidence,
    )


_INTENT_AFFINITY: dict[str, str] = {
    # When a tiny intent group needs a home, map it to the closest family.
    # Mutating intents go together; reading intents go together.
    "create": "write",
    "update": "write",
    "delete": "write",
    "read": "read",
    "search": "read",
    "workflow": "write",
    "admin": "write",
    "manage": "write",
}


def _split_by_intent(
    domain: str,
    endpoints: list[UasfEndpoint],
    confidence: float,
) -> list[AnalysisToolCandidate]:
    """Split a domain's endpoints by intent. Merge tiny intent groups by affinity."""
    by_intent: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        key = _intent_to_action_key(ep.intent)
        by_intent.setdefault(key, []).append(ep)

    # Merge tiny intent groups (1 endpoint) into the nearest large group by affinity
    large: dict[str, list[UasfEndpoint]] = {}
    tiny: list[tuple[str, UasfEndpoint]] = []
    for intent_key, eps in by_intent.items():
        if len(eps) >= 2:
            large[intent_key] = eps
        else:
            for ep in eps:
                tiny.append((intent_key, ep))

    # If merging everything into one tool is better (only 1 large group or none)
    if len(large) <= 1 and tiny:
        all_eps = [ep for eps in large.values() for ep in eps] + [ep for _, ep in tiny]
        return [_make_lifecycle_tool(domain, all_eps, confidence)]

    # Absorb tiny endpoints into their closest large group by affinity
    if tiny and large:
        for orphan_intent, ep in tiny:
            orphan_family = _INTENT_AFFINITY.get(orphan_intent, "write")
            # Find the best matching large group
            best_key = None
            for lk in large:
                if _INTENT_AFFINITY.get(lk, "write") == orphan_family:
                    if best_key is None or len(large[lk]) > len(large[best_key]):
                        best_key = lk
            if best_key is None:
                # No family match — use the largest group
                best_key = max(large, key=lambda k: len(large[k]))
            large[best_key].append(ep)
    elif tiny:
        # All groups are tiny — just make one lifecycle tool
        return [_make_lifecycle_tool(domain, endpoints, confidence)]

    tools: list[AnalysisToolCandidate] = []
    clean = _to_title_case(domain)
    for intent_key, eps in sorted(large.items()):
        ep_ids = [ep.id for ep in eps]
        # Check if this group has mixed intents (from absorbing orphans)
        actual_intents = {_intent_to_action_key(ep.intent) for ep in eps}
        if len(actual_intents) > 1:
            # Mixed group — name by family (read/write) not single intent
            family = _INTENT_AFFINITY.get(intent_key, "write")
            if family == "read":
                tool_name = f"{sanitize_tool_name(domain)}_read"
                action_desc = "list, search, and fetch"
            else:
                tool_name = f"{sanitize_tool_name(domain)}_write"
                action_desc = "create, update, and delete"
        else:
            tool_name = f"{sanitize_tool_name(domain)}_{intent_key}"
            action_desc = _intent_to_action(_dominant_intent(eps))

        tools.append(AnalysisToolCandidate(
            name=tool_name,
            description=f"Manage {clean} operations to {action_desc} resources.",
            covered_endpoints=ep_ids,
            confidence=confidence,
        ))

    return tools


def _split_by_intent_and_subresource(
    domain: str,
    endpoints: list[UasfEndpoint],
    confidence: float,
) -> list[AnalysisToolCandidate]:
    """Split a large domain by intent, with sub-resource awareness.

    For endpoints like /pets/{id}/vaccinations, the sub-resource 'vaccinations'
    gets its own tool if it has enough endpoints.
    """
    # Separate sub-resource endpoints from root-level endpoints
    root_eps: list[UasfEndpoint] = []
    sub_groups: dict[str, list[UasfEndpoint]] = {}

    for ep in endpoints:
        segments = _parse_path_segments(ep.path)
        if len(segments) >= 2:
            # Sub-resource: group by second resource segment
            sub_resource = segments[-1] if len(segments) > 1 else segments[0]
            sub_groups.setdefault(sub_resource, []).append(ep)
        else:
            root_eps.append(ep)

    tools: list[AnalysisToolCandidate] = []

    # Root-level endpoints: split by intent
    if root_eps:
        tools.extend(_split_by_intent(domain, root_eps, confidence))

    # Sub-resources: lifecycle tool if 2+ endpoints, otherwise merge into root
    clean = _to_title_case(domain)
    for sub, eps in sorted(sub_groups.items()):
        if len(eps) >= 2:
            sub_clean = _to_title_case(sub)
            sub_name = sanitize_tool_name(sub)
            # Avoid redundant names like player_player
            if sub_name == sanitize_tool_name(domain):
                tool_name = f"{sub_name}_controls"
            else:
                tool_name = f"{sanitize_tool_name(domain)}_{sub_name}"
            ep_ids = [ep.id for ep in eps]
            tools.append(AnalysisToolCandidate(
                name=tool_name,
                description=f"Manage {clean} {sub_clean} sub-resources.",
                covered_endpoints=ep_ids,
                confidence=confidence * 0.9,
            ))
        else:
            # Absorb singleton sub-resource endpoints into root tools
            root_eps.extend(eps)

    # If sub-resource absorption made root tools stale, rebuild
    if root_eps and not any(t for t in tools if not t.name.count("_") > 1):
        pass  # root tools already built above

    return tools


# ---------------------------------------------------------------------------
# Agent-filtered grouping
# ---------------------------------------------------------------------------


_MAX_TOOL_SIZE = 50  # No single tool should exceed this many endpoints


def _group_with_agent_filter(
    endpoints: list[UasfEndpoint],
    agent_keywords: set[str],
    agent_prompt: str | None,
    warnings: list[str],
) -> list[AnalysisToolCandidate]:
    """Use agent intent to tier endpoints and group adaptively.

    Uses two-level scoring:
    1. Domain-level relevance (domain name + collective vocabulary vs keywords)
    2. Endpoint-level scoring (individual text vs keywords)

    Tiering:
    - CORE: domains with high relevance → fine-grained adaptive grouping
    - SUPPORTING: domains with moderate relevance → lifecycle tools
    - PERIPHERAL: domains with zero relevance → adaptive grouping at low confidence
      (no more mega catch-all tools)
    """
    # --- Two-level scoring ---
    domain_scores = _build_domain_relevance_scores(endpoints, agent_keywords)

    # Tier domains by their relevance score
    by_domain: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        by_domain.setdefault(ep.domain, []).append(ep)

    # Determine thresholds relative to the max score (percentile-of-max).
    # No absolute floors — thresholds adapt to the actual score distribution
    # so that long agent prompts work just as well as short ones.
    max_domain_score = max(domain_scores.values()) if domain_scores else 0
    if max_domain_score > 0:
        core_threshold = max_domain_score * 0.6
        support_threshold = max_domain_score * 0.2
    else:
        core_threshold, support_threshold = 1.0, 1.0  # no matches → all peripheral

    core_domains: dict[str, list[UasfEndpoint]] = {}
    supporting_domains: dict[str, list[UasfEndpoint]] = {}
    peripheral_domains: dict[str, list[UasfEndpoint]] = {}

    for domain, eps in by_domain.items():
        score = domain_scores.get(domain, 0)
        if score >= core_threshold:
            core_domains[domain] = eps
        elif score >= support_threshold:
            supporting_domains[domain] = eps
        else:
            peripheral_domains[domain] = eps

    core_count = sum(len(v) for v in core_domains.values())
    support_count = sum(len(v) for v in supporting_domains.values())
    periph_count = sum(len(v) for v in peripheral_domains.values())

    logger.debug(
        "agent-filtered grouping: core=%d eps (%d domains) supporting=%d eps (%d domains) "
        "peripheral=%d eps (%d domains) thresholds=%.2f/%.2f",
        core_count, len(core_domains),
        support_count, len(supporting_domains),
        periph_count, len(peripheral_domains),
        core_threshold, support_threshold,
    )

    tools: list[AnalysisToolCandidate] = []

    # CORE: adaptive grouping with high confidence
    if core_domains:
        core_eps = [ep for eps in core_domains.values() for ep in eps]
        core_tools = _group_adaptive(core_eps, base_confidence=0.9)
        for t in core_tools:
            if not t.name.startswith("core_"):
                t.name = f"core_{t.name}"
            t.description = t.description.rstrip(".") + " (core to agent intent)."
        tools.extend(core_tools)

    # SUPPORTING: adaptive grouping at medium confidence
    if supporting_domains:
        support_eps = [ep for eps in supporting_domains.values() for ep in eps]
        support_tools = _group_adaptive(support_eps, base_confidence=0.5)
        tools.extend(support_tools)

    # PERIPHERAL: adaptive grouping at low confidence (NOT a mega catch-all)
    if peripheral_domains:
        periph_eps = [ep for eps in peripheral_domains.values() for ep in eps]
        periph_tools = _group_adaptive(periph_eps, base_confidence=0.2)
        tools.extend(periph_tools)

    # --- Enforce per-tool size cap ---
    # Any tool exceeding _MAX_TOOL_SIZE gets split by sub-resource/intent
    capped_tools: list[AnalysisToolCandidate] = []
    for tool in tools:
        if len(tool.covered_endpoints) <= _MAX_TOOL_SIZE:
            capped_tools.append(tool)
        else:
            # Resolve endpoints and re-split
            ep_by_id = {ep.id: ep for ep in endpoints}
            oversized_eps = [ep_by_id[eid] for eid in tool.covered_endpoints if eid in ep_by_id]
            split = _group_adaptive(oversized_eps, base_confidence=tool.confidence)
            # Preserve the core_ prefix if present
            if tool.name.startswith("core_"):
                for t in split:
                    if not t.name.startswith("core_"):
                        t.name = f"core_{t.name}"
            capped_tools.extend(split)
            warnings.append(
                f"Split oversized tool '{tool.name}' ({len(tool.covered_endpoints)} eps) "
                f"into {len(split)} sub-tools"
            )
    tools = capped_tools

    if not core_domains and not supporting_domains:
        warnings.append(
            "Agent intent did not strongly match any endpoints; "
            "all tools are domain-grouped. Consider using LLM analysis "
            "for better intent alignment."
        )

    return tools


# ---------------------------------------------------------------------------
# Legacy helpers kept for backward compatibility with tests
# ---------------------------------------------------------------------------


def _heuristic_group_by_domain_intent(
    endpoints: list[UasfEndpoint],
    agent_prompt: str | None,
    confidence: float = 0.5,
    prefix: str | None = None,
) -> list[AnalysisToolCandidate]:
    """Legacy grouping by (domain, intent). Delegates to adaptive grouping."""
    return _group_adaptive(endpoints, base_confidence=confidence)


def _heuristic_group_by_domain(
    endpoints: list[UasfEndpoint],
    confidence: float = 0.3,
) -> list[AnalysisToolCandidate]:
    """Legacy domain-only grouping. Delegates to adaptive grouping."""
    by_domain: dict[str, list[UasfEndpoint]] = {}
    for ep in endpoints:
        by_domain.setdefault(ep.domain, []).append(ep)

    tools: list[AnalysisToolCandidate] = []
    for domain in sorted(by_domain):
        tools.append(_make_lifecycle_tool(domain, by_domain[domain], confidence))
    return tools


def _intent_to_action_key(intent: EndpointIntent) -> str:
    """Short key for use in tool names."""
    return {
        EndpointIntent.READ: "read",
        EndpointIntent.SEARCH: "search",
        EndpointIntent.CREATE: "create",
        EndpointIntent.UPDATE: "update",
        EndpointIntent.DELETE: "delete",
        EndpointIntent.WORKFLOW: "workflow",
        EndpointIntent.ADMIN: "admin",
        EndpointIntent.UNKNOWN: "manage",
    }.get(intent, "manage")


# ---------------------------------------------------------------------------
# Normalize LLM tool plan
# ---------------------------------------------------------------------------


def normalize_anthropic_plan(
    surface: UasfSurface,
    raw: dict[str, Any],
    config: AppConfig,
    enforce_tool_bounds: bool,
) -> AnalysisPlan:
    """Normalize a parsed LLM tool-plan JSON into an AnalysisPlan."""
    known_ids = {ep.id for ep in surface.endpoints}

    tools: list[AnalysisToolCandidate] = []
    warnings: list[str] = list(raw.get("warnings") or [])
    seen_names: set[str] = set()

    for candidate in raw.get("tools", []):
        candidate_name = candidate.get("name", "")
        covered = sorted(
            {eid for eid in candidate.get("covered_endpoints", []) if eid in known_ids}
        )

        if not covered:
            warnings.append(
                f"Dropped Anthropic tool '{candidate_name}' because it did not "
                f"reference valid endpoint ids."
            )
            continue

        base_name = sanitize_tool_name(candidate_name)
        name = base_name if base_name else "tool"

        dedupe_idx = 2
        while name in seen_names:
            name = f"{sanitize_tool_name(candidate_name)}_{dedupe_idx}"
            dedupe_idx += 1
        seen_names.add(name)

        tools.append(AnalysisToolCandidate(
            name=name,
            description=_normalize_description(candidate.get("description", "")),
            covered_endpoints=covered,
            # confidence is computed by curate.curate() final pass; any
            # LLM-self-reported value is discarded in favor of a real score.
        ))

    if enforce_tool_bounds:
        if len(tools) < config.target_tool_count.min:
            warnings.append(
                f"Anthropic proposed {len(tools)} tools, below min "
                f"{config.target_tool_count.min}. Curator will expand intent splits."
            )
        if len(tools) > config.target_tool_count.max:
            warnings.append(
                f"Anthropic proposed {len(tools)} tools, above max "
                f"{config.target_tool_count.max}. Curator will merge tools."
            )

    return AnalysisPlan(
        source=AnalysisSource.ANTHROPIC,
        model=config.anthropic.model,
        tools=tools,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def analysis_prompt(
    config: AppConfig,
    endpoint_catalog: str,
    prompt_context: _BatchPromptContext | None = None,
    *,
    agent_prompt: str | None = None,
    endpoint_count: int = 0,
) -> str:
    """Build the analysis prompt for the LLM."""
    batch_context = ""
    if prompt_context is not None:
        history = prompt_context.prior_summary
        if not history or not history.strip():
            history = "No prior tooling context yet."

        batch_context = (
            f"Batch context:\n"
            f"- This is batch {prompt_context.batch_index}/{prompt_context.total_batches}.\n"
            f"- Keep names and descriptions consistent with prior batches.\n"
            f"- Prior grouped context from completed batches:\n{history}\n"
        )

    # Adaptive tool count guidance based on total endpoint count
    if endpoint_count > 200:
        tool_guidance_min = max(config.target_tool_count.min, endpoint_count // 50)
        tool_guidance_max = max(config.target_tool_count.max, min(endpoint_count // 25, 80))
    else:
        tool_guidance_min = config.target_tool_count.min
        tool_guidance_max = config.target_tool_count.max

    # When an agent intent is provided, frame the entire prompt around the
    # agent's purpose rather than the raw API structure.
    if agent_prompt and agent_prompt.strip():
        intent_section = (
            f"AGENT INTENT (this is the most important context):\n"
            f'"""{agent_prompt.strip()}"""\n\n'
            f"You MUST use this intent to drive every decision:\n"
            f"1. THINK about what workflows this agent needs to perform its job.\n"
            f"2. GROUP endpoints into workflow-oriented tools that match the agent's tasks.\n"
            f"   Example: instead of 'manage_repos' + 'manage_branches' + 'manage_pulls',\n"
            f"   create 'github_code_review' that covers the full review workflow.\n"
            f"3. NAME tools from the agent's perspective (what the agent DOES, not what the API provides).\n"
            f"4. EXCLUDE endpoints that are irrelevant to this agent's purpose.\n"
            f"   Be aggressive -- an agent that does payment processing does not need GitHub emoji endpoints.\n"
            f"5. Set CONFIDENCE to 0.9+ for tools directly serving the intent, 0.5-0.8 for supporting tools,\n"
            f"   and 0.1-0.4 for tangential/administrative tools.\n"
        )
        task_description = "You are curating an MCP tool plan for a specific AI agent."
    else:
        intent_section = ""
        task_description = "You are curating an MCP tool plan for an API."

    return (
        f"{task_description}\n"
        f"Return JSON only and no markdown.\n\n"
        f"{intent_section}\n"
        f"{batch_context}\n"
        f"Constraints:\n"
        f"- Group endpoints into task-oriented tools, NOT endpoint mirrors. Each tool should represent\n"
        f"  a coherent workflow or capability (e.g., 'process_payment', 'manage_playlist', 'review_code').\n"
        f"- Produce between {tool_guidance_min} and {tool_guidance_max} tools for this batch.\n"
        f"  It is OK to produce more tools if the endpoints span distinct workflows.\n"
        f"- Every endpoint id in this batch must be included at least once across covered_endpoints.\n"
        f"- Tool descriptions must be imperative and concise for AI agents.\n"
        f"- Set confidence scores: 0.9+ = core to agent intent, 0.5-0.8 = supporting, 0.1-0.4 = administrative.\n"
        f"Output JSON shape:\n"
        f'{{\n'
        f'  "tools": [{{"name": "tool_name", "description": "Imperative description", "covered_endpoints": ["endpoint_id"], "confidence": 0.85}}],\n'
        f'  "warnings": ["..."]\n'
        f'}}\n'
        f"Endpoint catalog JSON:\n{endpoint_catalog}"
    )


# ---------------------------------------------------------------------------
# Endpoint catalog serialization
# ---------------------------------------------------------------------------


def endpoint_catalog_json(surface: UasfSurface) -> str:
    """Serialize the endpoint catalog for inclusion in LLM prompts."""
    logger.debug(
        "serializing endpoint catalog for LLM prompt endpoints=%d",
        len(surface.endpoints),
    )
    payload = [_endpoint_catalog_entry(ep) for ep in surface.endpoints]
    return json.dumps(payload, indent=2)


def _endpoint_catalog_entry(endpoint: UasfEndpoint) -> dict[str, Any]:
    return {
        "id": endpoint.id,
        "method": endpoint.method.upper(),
        "path": endpoint.path,
        "summary": endpoint.summary,
        "domain": endpoint.domain,
        "intent": endpoint.intent.value,
        "security": endpoint.security,
        "tags": endpoint.tags,
    }


# ---------------------------------------------------------------------------
# Tool name / description normalization
# ---------------------------------------------------------------------------

# Pre-compiled regex for snake_case conversion
_SNAKE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _to_snake_case(text: str) -> str:
    """Convert a string to snake_case."""
    s = _SNAKE_RE_1.sub(r"\1_\2", text)
    s = _SNAKE_RE_2.sub(r"\1_\2", s)
    return s.lower()


def _to_title_case(text: str) -> str:
    """Convert a snake_case or plain string to Title Case."""
    return text.replace("_", " ").replace("-", " ").title()


def sanitize_tool_name(raw: str) -> str:
    """Sanitize a tool name to a valid snake_case identifier."""
    snake = _to_snake_case(raw)
    cleaned = "".join(ch if ch.isascii() and (ch.isalnum() or ch == "_") else "_" for ch in snake)
    return "_".join(segment for segment in cleaned.split("_") if segment)


def _normalize_description(raw: str) -> str:
    """Ensure a tool description starts with an imperative verb."""
    trimmed = raw.strip()
    if not trimmed:
        return "Manage grouped API operations."

    first_word = trimmed.split()[0].lower() if trimmed.split() else ""
    imperative_verbs = {
        "manage",
        "list",
        "search",
        "create",
        "update",
        "delete",
        "run",
        "send",
        "handle",
        "administer",
        "execute",
    }

    if first_word in imperative_verbs:
        return trimmed
    return f"Manage {trimmed}"


# ---------------------------------------------------------------------------
# Intent helpers (for heuristic analysis)
# ---------------------------------------------------------------------------


def _dominant_intent(endpoints: list[UasfEndpoint]) -> EndpointIntent:
    """Determine the most common intent among a set of endpoints."""
    counts: dict[str, int] = {}
    for ep in endpoints:
        label = ep.intent.value
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return EndpointIntent.UNKNOWN

    dominant_label = max(counts, key=lambda k: counts[k])
    try:
        return EndpointIntent(dominant_label)
    except ValueError:
        return EndpointIntent.UNKNOWN


def _intent_to_action(intent: EndpointIntent) -> str:
    """Map an intent to a human-readable action phrase."""
    mapping = {
        EndpointIntent.READ: "list and fetch",
        EndpointIntent.SEARCH: "search and filter",
        EndpointIntent.CREATE: "create and submit",
        EndpointIntent.UPDATE: "update and sync",
        EndpointIntent.DELETE: "remove and archive",
        EndpointIntent.WORKFLOW: "run workflows for",
        EndpointIntent.ADMIN: "administer",
        EndpointIntent.UNKNOWN: "manage",
    }
    return mapping.get(intent, "manage")


# ---------------------------------------------------------------------------
# JSON extraction from LLM response text
# ---------------------------------------------------------------------------


def extract_first_json_object(text: str) -> str | None:
    """Extract the first complete JSON object from free-form text.

    Handles nested braces and strings with escaped characters.
    """
    depth = 0
    start_idx: int | None = None
    in_string = False
    escaped = False

    for idx, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
            continue

        if ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_idx is not None:
                return text[start_idx : idx + 1]

    return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Attempt to parse text as JSON, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

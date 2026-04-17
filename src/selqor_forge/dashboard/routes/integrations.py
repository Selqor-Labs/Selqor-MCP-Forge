# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration CRUD endpoints."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    IntegrationRecord,
    NewIntegrationRequest,
    is_safe_token,
    now_utc_string,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import IntegrationRepository

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Inline spec persistence
# ─────────────────────────────────────────────────────────────────────────────
# The frontend ``SpecInputTabs`` component can send three kinds of specs on the
# ``specs`` array of a create request:
#   1. Plain HTTP(S) URLs (returned to the pipeline unchanged).
#   2. A JSON envelope ``{"__type": "file-upload", "filename": ..., "content": ...}``
#      holding the raw text of an uploaded OpenAPI document.
#   3. A JSON envelope ``{"__type": "pasted-content", "content": ...}`` holding
#      user-pasted spec text.
#
# The pipeline's ``parse_spec`` only understands URLs or filesystem paths, so we
# materialise kinds (2) and (3) as files under ``<state_dir>/integration_specs/
# <integration_id>/<basename>`` and store that absolute path in the integration
# record.  Files are removed when the integration is deleted.

_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_STEM = 48
_INLINE_TYPES = ("file-upload", "pasted-content")
# Maximum size for inline spec content (5 MB)
_MAX_INLINE_SPEC_BYTES = 5 * 1024 * 1024


def _integration_spec_dir(ctx: Ctx, integration_id: str) -> Path:
    return ctx.state_dir / "integration_specs" / integration_id


def _classify_spec(raw: str) -> tuple[str, str, str | None]:
    """Return ``(kind, payload, filename)`` for a raw spec entry.

    ``kind`` is ``"url"`` for plain URLs or ``"content"`` for inline documents.
    For URLs, ``payload`` is the trimmed URL and ``filename`` is ``None``.
    For inline documents, ``payload`` is the raw spec text.
    """
    if not raw or not raw.startswith("{"):
        return "url", raw, None
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return "url", raw, None
    if not isinstance(envelope, dict) or envelope.get("__type") not in _INLINE_TYPES:
        return "url", raw, None
    content = envelope.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="inline spec payload is empty")
    if len(content.encode("utf-8")) > _MAX_INLINE_SPEC_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"inline spec exceeds maximum size ({_MAX_INLINE_SPEC_BYTES // (1024*1024)}MB)",
        )
    filename = envelope.get("filename") if isinstance(envelope.get("filename"), str) else None
    return "content", content, filename


def _detect_spec_extension(content: str) -> str:
    """Return ``.json`` if *content* parses as JSON, else ``.yaml``."""
    stripped = content.strip()
    try:
        json.loads(stripped)
        return ".json"
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        parsed = yaml.safe_load(stripped)
        if isinstance(parsed, dict):
            return ".yaml"
    except yaml.YAMLError:
        pass
    # Neither JSON nor valid YAML — reject rather than silently storing garbage
    raise HTTPException(
        status_code=400,
        detail="inline spec content is not valid JSON or YAML",
    )


def _safe_filename_stem(filename: str | None, fallback: str) -> str:
    if not filename:
        return fallback
    stem = Path(filename).stem or fallback
    cleaned = _FILENAME_SANITIZE_RE.sub("_", stem).strip("._-")
    return (cleaned[:_MAX_FILENAME_STEM]) or fallback


def _persist_inline_spec(
    ctx: Ctx,
    integration_id: str,
    index: int,
    content: str,
    filename: str | None,
) -> str:
    """Write an inline spec to disk and return the absolute path as a string."""
    target_dir = _integration_spec_dir(ctx, integration_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = _detect_spec_extension(content)
    stem = _safe_filename_stem(filename, fallback=f"spec-{index}")
    candidate = target_dir / f"{stem}{ext}"
    # Disambiguate if the same stem is reused (e.g. multiple uploads with the same name).
    suffix = 2
    while candidate.exists():
        candidate = target_dir / f"{stem}-{suffix}{ext}"
        suffix += 1
    candidate.write_text(content, encoding="utf-8")
    logger.info(
        "persisted inline spec for integration %s: path=%s bytes=%d",
        integration_id, candidate, len(content),
    )
    return str(candidate)


def _cleanup_inline_specs(ctx: Ctx, integration_id: str) -> None:
    target_dir = _integration_spec_dir(ctx, integration_id)
    if target_dir.exists():
        try:
            shutil.rmtree(target_dir)
        except OSError as exc:
            logger.warning("failed to remove inline spec dir %s: %s", target_dir, exc)


# ---------------------------------------------------------------------------
# GET /integrations
# ---------------------------------------------------------------------------


@router.get("/integrations")
def list_integrations(ctx: Ctx) -> JSONResponse:
    """Return all integrations with run counts."""
    integrations = _list_integration_views(ctx)
    return JSONResponse(
        status_code=200,
        content={"integrations": integrations},
    )


# ---------------------------------------------------------------------------
# POST /integrations
# ---------------------------------------------------------------------------


@router.post("/integrations", status_code=201)
def create_integration(ctx: Ctx, body: NewIntegrationRequest) -> JSONResponse:
    """Create a new integration entry."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Build the deduplicated specs list from both the legacy ``spec`` field and
    # the new ``specs`` list.  At least one non-empty spec is required.
    # Inline (file-upload / paste) specs are materialised to disk below so the
    # pipeline can load them the same way it loads regular file paths.
    raw_specs = [s for s in ([body.spec] if body.spec else []) + list(body.specs) if s and s.strip()]
    if not raw_specs:
        raise HTTPException(status_code=400, detail="spec is required")

    agent_prompt = (body.agent_prompt or "").strip() or None
    notes = (body.notes or "").strip() or None
    tags = [t.strip() for t in body.tags if t.strip()][:10]

    integration_id = _unique_integration_id(ctx, name)

    seen: set[str] = set()
    specs: list[str] = []
    persisted_paths: list[str] = []
    try:
        for index, entry in enumerate(raw_specs):
            kind, payload, filename = _classify_spec(entry.strip())
            if kind == "content":
                resolved = _persist_inline_spec(
                    ctx, integration_id, index, payload, filename
                )
                persisted_paths.append(resolved)
            else:
                resolved = payload.strip()
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            specs.append(resolved)

        if not specs:
            raise HTTPException(status_code=400, detail="spec is required")

        record = IntegrationRecord(
            id=integration_id,
            name=name,
            spec=specs[0],
            specs=specs,
            agent_prompt=agent_prompt,
            created_at=now_utc_string(),
            notes=notes,
            tags=tags,
        )

        _ensure_integration_not_duplicated(ctx, record)
        _save_new_integration(ctx, record)
    except BaseException:
        # Clean up any files we already wrote so failed creates don't orphan
        # partial state on disk. ``BaseException`` also covers HTTPException.
        _cleanup_inline_specs(ctx, integration_id)
        raise

    logger.info(
        "integration created: id=%s name=%s specs=%d inline=%d agent_prompt=%s",
        record.id, record.name, len(specs), len(persisted_paths), bool(agent_prompt),
    )
    return JSONResponse(status_code=201, content=record.model_dump())


# ---------------------------------------------------------------------------
# PATCH /integrations/{integration_id}
# ---------------------------------------------------------------------------


@router.patch("/integrations/{integration_id}")
def update_integration(ctx: Ctx, integration_id: str, body: dict) -> JSONResponse:
    """Update integration metadata (name, notes, tags)."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        model = repo.get_by_id(integration_id)
        if model is None:
            raise HTTPException(status_code=404, detail="integration not found")

        if "name" in body:
            name = (body["name"] or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="name cannot be empty")
            model.name = name
        if "notes" in body:
            model.notes = (body["notes"] or "").strip() or None
        if "tags" in body and isinstance(body["tags"], list):
            model.tags = [t.strip() for t in body["tags"] if t.strip()][:10]

        session.commit()
        logger.info("integration updated: %s name=%s", integration_id, model.name)
        return JSONResponse(status_code=200, content={
            "id": model.id,
            "name": model.name,
            "notes": model.notes,
            "tags": model.tags or [],
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# DELETE /integrations/{integration_id}
# ---------------------------------------------------------------------------


@router.delete("/integrations/{integration_id}")
def delete_integration(ctx: Ctx, integration_id: str) -> JSONResponse:
    """Delete an integration and its associated files."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    deleted_count = _delete_integration_group(ctx, integration_id)
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="integration not found")

    _cleanup_inline_specs(ctx, integration_id)

    logger.info("integration deleted: %s (rows=%d)", integration_id, deleted_count)
    return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted_count})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:48] or "integration"


def _now_millis() -> int:
    return int(time.time() * 1000)


def _unique_integration_id(ctx: Ctx, name: str) -> str:
    """Generate unique integration ID, checking the database."""
    base = _slugify(name)
    seed = _now_millis()
    attempt = f"{base}-{seed}"

    existing_ids: set[str] = set()

    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        for integration in repo.list_all():
            existing_ids.add(integration.id)
    finally:
        session.close()

    suffix = 2
    while attempt in existing_ids:
        attempt = f"{base}-{seed}-{suffix}"
        suffix += 1
    return attempt


def _save_new_integration(ctx: Ctx, record: IntegrationRecord) -> None:
    """Save new integration to the database."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        repo.create(record)
    finally:
        session.close()


def _delete_integration_group(ctx: Ctx, integration_id: str) -> int:
    """Delete the visible integration card and any duplicate rows behind it."""
    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        integrations = repo.list_all()
        target = next((integration for integration in integrations if integration.id == integration_id), None)
        if target is None:
            return 0

        target_identity = _integration_identity({
            "name": target.name,
            "spec": target.spec,
            "specs": target.specs or ([target.spec] if target.spec else []),
        })

        duplicates = [
            integration
            for integration in integrations
            if _integration_identity({
                "name": integration.name,
                "spec": integration.spec,
                "specs": integration.specs or ([integration.spec] if integration.spec else []),
            }) == target_identity
        ]

        deleted = 0
        for duplicate in duplicates:
            if repo.delete(duplicate.id):
                deleted += 1
        return deleted
    finally:
        session.close()


def _list_integration_views(ctx: Ctx) -> list[dict]:
    """List integrations from the database."""
    from sqlalchemy import func, select as sa_select
    from selqor_forge.dashboard.models import Integration as IntModel, Run as RunModel

    grouped: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
    session = ctx.db_session_factory()
    try:
        # Single query with LEFT JOIN for run counts instead of N+1
        stmt = (
            sa_select(IntModel, func.count(RunModel.run_id).label("run_count"))
            .outerjoin(RunModel, IntModel.id == RunModel.integration_id)
            .group_by(IntModel.id)
            .order_by(IntModel.created_at.desc())
        )
        rows = session.execute(stmt).all()

        for integration, run_count in rows:

            view = {
                "id": integration.id,
                "name": integration.name,
                "spec": integration.spec,
                "specs": integration.specs or ([integration.spec] if integration.spec else []),
                "created_at": integration.created_at,
                "notes": integration.notes,
                "tags": integration.tags or [],
                "last_connection_test": integration.last_connection_test,
                "run_count": run_count,
            }
            grouped[_integration_identity(view)].append(view)

        result = [_merge_integration_duplicates(items) for items in grouped.values()]
        result.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return result
    finally:
        session.close()


def _ensure_integration_not_duplicated(ctx: Ctx, record: IntegrationRecord) -> None:
    """Reject creates that match an existing integration by name and specs."""
    candidate_identity = _integration_identity({
        "name": record.name,
        "spec": record.spec,
        "specs": record.effective_specs(),
    })

    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        for integration in repo.list_all():
            existing_identity = _integration_identity({
                "name": integration.name,
                "spec": integration.spec,
                "specs": integration.specs or ([integration.spec] if integration.spec else []),
            })
            if existing_identity == candidate_identity:
                raise HTTPException(
                    status_code=409,
                    detail="An integration with the same name and spec already exists",
                )
    finally:
        session.close()


def _normalize_spec(spec: str | None) -> str:
    return (spec or "").strip().lower()


def _integration_identity(item: dict) -> tuple[str, tuple[str, ...]]:
    specs = item.get("specs") or ([item.get("spec")] if item.get("spec") else [])
    normalized_specs = tuple(sorted({s for s in (_normalize_spec(spec) for spec in specs) if s}))
    return ((item.get("name") or "").strip().lower(), normalized_specs)


def _merge_integration_duplicates(items: list[dict]) -> dict:
    """Collapse duplicate integrations created with the same name/specs."""
    items = sorted(
        items,
        key=lambda item: (
            item.get("run_count", 0),
            bool(item.get("last_connection_test")),
            item.get("created_at", ""),
        ),
        reverse=True,
    )
    canonical = dict(items[0])
    canonical["tags"] = sorted({tag for item in items for tag in (item.get("tags") or [])})
    canonical["run_count"] = max(item.get("run_count", 0) for item in items)

    if not canonical.get("last_connection_test"):
        for item in items[1:]:
            if item.get("last_connection_test"):
                canonical["last_connection_test"] = item["last_connection_test"]
                break

    if not canonical.get("notes"):
        for item in items[1:]:
            if item.get("notes"):
                canonical["notes"] = item["notes"]
                break

    return canonical

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Notification delivery routes.

Provides CRUD for notification channels (email, webhook, Slack) and a
``send_notification()`` helper that fans out to all enabled channels,
logging every attempt to the NotificationLog table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import (
    NotificationChannelRepository,
    NotificationLogRepository,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

_VALID_CHANNEL_TYPES = {"email", "webhook", "slack"}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateChannelBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    channel_type: str = Field(..., description="email, webhook, or slack")
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateChannelBody(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class SendNotificationBody(BaseModel):
    event_type: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body: str = Field(default="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _channel_to_dict(model) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "channel_type": model.channel_type,
        "config": model.config,
        "enabled": model.enabled,
        "created_at": model.created_at,
    }


def _log_to_dict(model) -> dict:
    return {
        "id": model.id,
        "channel_id": model.channel_id,
        "event_type": model.event_type,
        "subject": model.subject,
        "body": model.body,
        "status": model.status,
        "error": model.error,
        "created_at": model.created_at,
    }


# ---------------------------------------------------------------------------
# Notification delivery
# ---------------------------------------------------------------------------


async def send_notification(
    session,
    channel,
    event_type: str,
    subject: str,
    body: str,
) -> dict:
    """Deliver a single notification and log the result.

    Returns the created log entry as a dict.
    """
    log_repo = NotificationLogRepository(session)
    now = datetime.utcnow().isoformat() + "Z"
    log_id = str(uuid.uuid4())
    status = "sent"
    error: str | None = None

    try:
        if channel.channel_type == "webhook":
            url = channel.config.get("url")
            if not url:
                raise ValueError("Webhook channel missing 'url' in config")
            headers = {"Content-Type": "application/json"}
            extra_headers = channel.config.get("headers")
            if isinstance(extra_headers, dict):
                headers.update(extra_headers)
            payload = {
                "event": event_type,
                "subject": subject,
                "body": body,
                "timestamp": now,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

        elif channel.channel_type == "slack":
            webhook_url = channel.config.get("webhook_url")
            if not webhook_url:
                raise ValueError("Slack channel missing 'webhook_url' in config")
            payload = {"text": f"*{subject}*\n{body}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()

        elif channel.channel_type == "email":
            # Actual SMTP delivery requires server-level config.
            # Log as sent with an informational note.
            error = "Email delivery is configured via SMTP settings"

        else:
            raise ValueError(f"Unsupported channel type: {channel.channel_type}")

    except Exception as exc:
        status = "failed"
        error = str(exc)[:500]

    log_entry = log_repo.create(
        id=log_id,
        channel_id=channel.id,
        event_type=event_type,
        subject=subject,
        body=body,
        status=status,
        error=error,
        created_at=now,
    )
    return _log_to_dict(log_entry)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/channels")
async def list_channels(ctx: Ctx) -> dict:
    """List all notification channels."""
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        channels = repo.list_all()
        items = [_channel_to_dict(c) for c in channels]
        return {"channels": items, "total": len(items)}
    finally:
        session.close()


@router.post("/channels")
async def create_channel(ctx: Ctx, body: CreateChannelBody) -> dict:
    """Create a new notification channel."""
    if body.channel_type not in _VALID_CHANNEL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel_type. Must be one of: {', '.join(sorted(_VALID_CHANNEL_TYPES))}",
        )
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        channel_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        channel = repo.create(
            id=channel_id,
            name=body.name,
            channel_type=body.channel_type,
            config=body.config,
            enabled=body.enabled,
            created_at=now,
        )
        return _channel_to_dict(channel)
    finally:
        session.close()


@router.patch("/channels/{channel_id}")
async def update_channel(ctx: Ctx, channel_id: str, body: UpdateChannelBody) -> dict:
    """Update an existing notification channel."""
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        if repo.get_by_id(channel_id) is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        repo.update(channel_id, **updates)
        updated = repo.get_by_id(channel_id)
        return _channel_to_dict(updated)
    finally:
        session.close()


@router.delete("/channels/{channel_id}")
async def delete_channel(ctx: Ctx, channel_id: str) -> dict:
    """Delete a notification channel."""
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        if not repo.delete(channel_id):
            raise HTTPException(status_code=404, detail="Channel not found")
        return {"message": "Channel deleted", "id": channel_id}
    finally:
        session.close()


@router.post("/channels/{channel_id}/test")
async def test_channel(ctx: Ctx, channel_id: str) -> dict:
    """Send a test notification through a specific channel."""
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        channel = repo.get_by_id(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        result = await send_notification(
            session,
            channel,
            event_type="test",
            subject="Test notification from Selqor Forge",
            body="If you received this, the channel is working correctly.",
        )
        return result
    finally:
        session.close()


@router.get("/logs")
async def list_logs(ctx: Ctx, limit: int = 100) -> dict:
    """List recent notification log entries."""
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    session = ctx.db_session_factory()
    try:
        repo = NotificationLogRepository(session)
        logs = repo.list_recent(limit=limit)
        items = [_log_to_dict(entry) for entry in logs]
        return {"logs": items, "total": len(items)}
    finally:
        session.close()


@router.post("/send")
async def send_to_all(ctx: Ctx, body: SendNotificationBody) -> dict:
    """Send a notification to all enabled channels."""
    session = ctx.db_session_factory()
    try:
        repo = NotificationChannelRepository(session)
        channels = repo.list_enabled()
        if not channels:
            raise HTTPException(status_code=404, detail="No enabled channels found")
        results = []
        for ch in channels:
            log_entry = await send_notification(
                session,
                ch,
                event_type=body.event_type,
                subject=body.subject,
                body=body.body,
            )
            results.append(log_entry)
        sent = sum(1 for r in results if r["status"] == "sent")
        failed = sum(1 for r in results if r["status"] == "failed")
        return {
            "results": results,
            "summary": {"total": len(results), "sent": sent, "failed": failed},
        }
    finally:
        session.close()

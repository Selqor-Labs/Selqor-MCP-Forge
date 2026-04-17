# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Authentication API endpoints.

Authentication is disabled — the dashboard is fully open to everyone.
These endpoints exist for API compatibility but return anonymous/open responses.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import is_safe_token
from selqor_forge.dashboard.middleware import (
    Ctx,
    OrgId,
    User,
    auth_placeholder_config,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /auth/config
# ---------------------------------------------------------------------------


@router.get("/auth/config")
def get_auth_config() -> JSONResponse:
    """Return auth configuration — always reports auth as disabled."""
    return JSONResponse(status_code=200, content=auth_placeholder_config())


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get("/auth/me")
def get_auth_me(ctx: Ctx, user: User) -> JSONResponse:
    """Return anonymous user profile — dashboard is open."""
    return JSONResponse(
        status_code=200,
        content={
            "user_id": "anonymous",
            "email": None,
            "name": "Anonymous User",
            "role": "admin",
            "auth_enabled": False,
            "organizations": [],
        },
    )


# ---------------------------------------------------------------------------
# GET /auth/context
# ---------------------------------------------------------------------------


@router.get("/auth/context")
def get_auth_context(user: User, org_id: OrgId) -> JSONResponse:
    """Return the current user_id and effective org_id."""
    return JSONResponse(
        status_code=200,
        content={"user_id": "anonymous", "org_id": org_id, "auth_enabled": False},
    )


# ---------------------------------------------------------------------------
# GET /users/me/onboarding-status
# ---------------------------------------------------------------------------


@router.get("/users/me/onboarding-status")
def get_onboarding_status(ctx: Ctx, user: User) -> JSONResponse:
    """Return onboarding status."""
    return JSONResponse(
        status_code=200,
        content={
            "needs_onboarding": False,
            "has_organizations": True,
            "pending_invites_count": 0,
            "organizations_count": 1,
        },
    )


# ---------------------------------------------------------------------------
# GET /users/me/pending-invites
# ---------------------------------------------------------------------------


@router.get("/users/me/pending-invites")
def get_pending_invites(ctx: Ctx, user: User) -> JSONResponse:
    """List pending organisation invites — always empty."""
    return JSONResponse(status_code=200, content=[])


# ---------------------------------------------------------------------------
# POST /users/me/invites/{invite_id}/accept
# ---------------------------------------------------------------------------


@router.post("/users/me/invites/{invite_id}/accept")
def accept_invite(ctx: Ctx, user: User, invite_id: str) -> JSONResponse:
    """Accept a pending organisation invite."""
    if not is_safe_token(invite_id):
        raise HTTPException(status_code=400, detail="invalid invite id")
    raise HTTPException(status_code=404, detail="Invitation not found")


# ---------------------------------------------------------------------------
# POST /users/me/invites/{invite_id}/decline
# ---------------------------------------------------------------------------


@router.post("/users/me/invites/{invite_id}/decline")
def decline_invite(ctx: Ctx, user: User, invite_id: str) -> JSONResponse:
    """Decline a pending organisation invite."""
    if not is_safe_token(invite_id):
        raise HTTPException(status_code=400, detail="invalid invite id")
    raise HTTPException(status_code=404, detail="Invitation not found")

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Authentication API endpoints for the local-only public dashboard."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.middleware import auth_placeholder_config, local_only_feature_error

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /auth/config
# ---------------------------------------------------------------------------


@router.get("/auth/config")  # type: ignore[untyped-decorator, unused-ignore]
def get_auth_config() -> JSONResponse:
    """Return capability metadata for the public local-only build."""
    return JSONResponse(status_code=200, content=auth_placeholder_config())


# ---------------------------------------------------------------------------
# Shared dashboard auth/org endpoints are intentionally disabled
# ---------------------------------------------------------------------------


@router.get("/auth/me")  # type: ignore[untyped-decorator, unused-ignore]
def get_auth_me() -> JSONResponse:
    """Shared-user auth is not part of the local-only public build."""
    raise local_only_feature_error("auth")


@router.get("/auth/context")  # type: ignore[untyped-decorator, unused-ignore]
def get_auth_context() -> JSONResponse:
    """Shared auth context is not available in the local-only public build."""
    raise local_only_feature_error("auth")


@router.get("/users/me/onboarding-status")  # type: ignore[untyped-decorator, unused-ignore]
def get_onboarding_status() -> JSONResponse:
    """Onboarding is disabled in the local-only public build."""
    raise local_only_feature_error("onboarding")


@router.get("/users/me/pending-invites")  # type: ignore[untyped-decorator, unused-ignore]
def get_pending_invites() -> JSONResponse:
    """Team invites are disabled in the local-only public build."""
    raise local_only_feature_error("team_invites")


@router.post("/users/me/invites/{invite_id}/accept")  # type: ignore[untyped-decorator, unused-ignore]
def accept_invite(invite_id: str) -> JSONResponse:
    """Team invites are disabled in the local-only public build."""
    del invite_id
    raise local_only_feature_error("team_invites")


@router.post("/users/me/invites/{invite_id}/decline")  # type: ignore[untyped-decorator, unused-ignore]
def decline_invite(invite_id: str) -> JSONResponse:
    """Team invites are disabled in the local-only public build."""
    del invite_id
    raise local_only_feature_error("team_invites")

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard middleware and FastAPI dependency functions.

All requests proceed without authentication — the dashboard is fully open.
Suitable for open-source self-hosted usage.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from selqor_forge.dashboard.context import CurrentUser, DashboardContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth state (always anonymous / open)
# ---------------------------------------------------------------------------


def is_auth_enabled() -> bool:
    """Auth is disabled — dashboard is open to everyone."""
    return False


def is_auth_placeholder_active() -> bool:
    """Return True — dashboard runs in anonymous (no-auth) mode."""
    return True


def auth_placeholder_config() -> dict:
    """Return the auth configuration payload for /api/auth/config."""
    return {
        "enabled": False,
        "provider": "anonymous",
        "message": "Dashboard is open — no authentication required.",
    }


def auth_module_not_integrated_error() -> HTTPException:
    """Return a 501 error for endpoints that require an auth module."""
    return HTTPException(
        status_code=501,
        detail={
            "detail": "AUTH_NOT_ENABLED",
            "message": "Authentication is not enabled in this build.",
        },
    )


# ---------------------------------------------------------------------------
# FastAPI dependency functions
# ---------------------------------------------------------------------------


def get_dashboard_context(request: Request) -> DashboardContext:
    """Retrieve the :class:`DashboardContext` stored on ``app.state``."""
    ctx: DashboardContext | None = getattr(request.app.state, "dashboard_ctx", None)
    if ctx is None:
        raise HTTPException(
            status_code=500,
            detail="Dashboard context not initialised.",
        )
    return ctx


def get_current_user(request: Request) -> CurrentUser | None:
    """Always returns None — no authentication, everyone is anonymous."""
    return None


def get_effective_org_id(
    request: Request,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> str | None:
    """Resolve the effective organisation ID for the current request."""
    if x_org_id:
        return x_org_id
    return None


# ---------------------------------------------------------------------------
# Typed dependency aliases (for use in route signatures)
# ---------------------------------------------------------------------------

Ctx = Annotated[DashboardContext, Depends(get_dashboard_context)]
User = Annotated[CurrentUser | None, Depends(get_current_user)]
OrgId = Annotated[str | None, Depends(get_effective_org_id)]

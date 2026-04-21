# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard middleware and FastAPI dependency functions.

The public v1 dashboard is intentionally local-only and single-user. It does
not include shared-user authentication, organization management, or team
management flows.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from selqor_forge.dashboard.context import CurrentUser, DashboardContext

_LOCAL_ONLY_MESSAGE = (
    "This public Selqor Forge build is a local-only single-user dashboard. "
    "Shared auth, organization, and team-management features are not included."
)


# ---------------------------------------------------------------------------
# Auth state (always anonymous / local-only)
# ---------------------------------------------------------------------------


def is_auth_enabled() -> bool:
    """Auth is disabled in the public local-only dashboard build."""
    return False


def is_auth_placeholder_active() -> bool:
    """Return True because the dashboard runs in local-only mode."""
    return True


def auth_placeholder_config() -> dict[str, object]:
    """Return the auth configuration payload for /api/auth/config."""
    return {
        "enabled": False,
        "provider": "local_only",
        "local_only": True,
        "auth_routes_enabled": False,
        "organizations_enabled": False,
        "team_management_enabled": False,
        "message": _LOCAL_ONLY_MESSAGE,
    }


def local_only_feature_error(feature: str) -> HTTPException:
    """Return a 501 error for shared-dashboard features disabled in public v1."""
    return HTTPException(
        status_code=501,
        detail={
            "detail": "LOCAL_ONLY_BUILD",
            "feature": feature,
            "message": _LOCAL_ONLY_MESSAGE,
        },
    )


def auth_module_not_integrated_error() -> HTTPException:
    """Backward-compatible alias for shared auth/org feature call sites."""
    return local_only_feature_error("auth")


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
    """Always returns None because everyone is anonymous in local-only mode."""
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

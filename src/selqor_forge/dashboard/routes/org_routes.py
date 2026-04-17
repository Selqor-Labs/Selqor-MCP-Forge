# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Organisation management endpoints."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import CreateOrgRequest
from selqor_forge.dashboard.middleware import Ctx, User, auth_module_not_integrated_error

logger = logging.getLogger(__name__)

router = APIRouter()

_SLUG_VALID_RE = re.compile(r"^[a-z0-9\-]+$")


# ---------------------------------------------------------------------------
# POST /organizations
# ---------------------------------------------------------------------------


@router.post("/organizations", status_code=201)
def create_organization(ctx: Ctx, user: User, body: CreateOrgRequest) -> JSONResponse:
    """Create a new organisation (requires auth module and DB)."""
    if user is None:
        raise auth_module_not_integrated_error()

    if ctx.db is None:
        raise HTTPException(
            status_code=400,
            detail="Organization management requires PostgreSQL. Set DATABASE_URL.",
        )

    name = body.name.strip()
    slug = body.slug.strip().lower()

    if len(name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Name must be at least 2 characters",
        )
    if len(slug) < 2 or not _SLUG_VALID_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be lowercase letters, numbers, and hyphens only",
        )

    # DB-based availability check and creation would go here.
    # For now, return a 400 since DB is required but stubbed.
    raise HTTPException(
        status_code=400,
        detail="Organization management requires PostgreSQL. Set DATABASE_URL.",
    )


# ---------------------------------------------------------------------------
# GET /organizations/check
# ---------------------------------------------------------------------------


@router.get("/organizations/check")
def check_org_availability(
    ctx: Ctx,
    name: str = Query(default=""),
    slug: str = Query(default=""),
) -> JSONResponse:
    """Check if an organisation name/slug is available."""
    if ctx.db is None:
        return JSONResponse(
            status_code=200,
            content={
                "name_available": True,
                "slug_available": True,
            },
        )

    # With DB, availability check would go here.
    return JSONResponse(
        status_code=200,
        content={
            "name_available": True,
            "slug_available": True,
        },
    )

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Organization management endpoints.

These shared-user features are intentionally disabled in the public local-only
dashboard build.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import CreateOrgRequest
from selqor_forge.dashboard.middleware import local_only_feature_error

router = APIRouter()


@router.post("/organizations", status_code=201)
def create_organization(body: CreateOrgRequest) -> JSONResponse:
    """Organizations are not included in the local-only public build."""
    del body
    raise local_only_feature_error("organizations")


@router.get("/organizations/check")
def check_org_availability() -> JSONResponse:
    """Organizations are not included in the local-only public build."""
    raise local_only_feature_error("organizations")

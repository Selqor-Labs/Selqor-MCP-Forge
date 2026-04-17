# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Run-job status polling endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import is_safe_token
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.run_worker import find_active_run_job, load_run_job_view

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/run-jobs/active
# ---------------------------------------------------------------------------
# Registered BEFORE the /{job_id}/status route so that "active" is not
# swallowed by the {job_id} path parameter.


@router.get("/integrations/{integration_id}/run-jobs/active")
def get_active_run_job(
    ctx: Ctx, integration_id: str
) -> JSONResponse:
    """Return the active (queued/running) run job for *integration_id*, if any.

    Used by the frontend to resume the progress stepper after a page
    reload while a pipeline run is still in progress.
    """
    if not is_safe_token(integration_id):
        raise HTTPException(
            status_code=400, detail="invalid integration id"
        )

    view = find_active_run_job(ctx, integration_id)
    if view is None:
        return JSONResponse(
            status_code=200, content={"job": None}
        )

    return JSONResponse(
        status_code=200, content={"job": view.model_dump()}
    )


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/run-jobs/{job_id}/status
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/run-jobs/{job_id}/status")
def get_run_job_status(
    ctx: Ctx, integration_id: str, job_id: str
) -> JSONResponse:
    """Return the current status and progress of a background run job."""
    if not is_safe_token(integration_id) or not is_safe_token(job_id):
        raise HTTPException(
            status_code=400, detail="invalid integration or job id"
        )

    view = load_run_job_view(ctx, integration_id, job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="run job not found")

    return JSONResponse(
        status_code=200, content={"job": view.model_dump()}
    )

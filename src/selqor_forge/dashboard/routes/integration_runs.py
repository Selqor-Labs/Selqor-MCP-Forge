# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration run endpoints: start run, list runs, artifacts."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from selqor_forge.dashboard.context import (
    RunIntegrationRequest,
    is_safe_filename,
    is_safe_token,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import ArtifactRepository, RunRepository
from selqor_forge.dashboard.run_worker import start_run_job

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /integrations/{integration_id}/run
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/run", status_code=202)
def run_integration(
    ctx: Ctx,
    integration_id: str,
    body: RunIntegrationRequest | None = None,
) -> JSONResponse:
    """Start an analysis run for the integration.  Returns 202 with job info."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    mode = "llm"
    agent_prompt: str | None = None
    llm_config_id: str | None = None
    if body is not None:
        if body.mode:
            mode = body.mode
        if body.agent_prompt:
            agent_prompt = body.agent_prompt.strip() or None
        if body.llm_config_id:
            llm_config_id = body.llm_config_id.strip() or None

    run_id = str(int(time.time() * 1000))

    try:
        job_view = start_run_job(
            ctx,
            integration_id,
            run_id,
            mode,
            agent_prompt=agent_prompt,
            llm_config_id=llm_config_id,
        )
    except Exception as exc:
        logger.error("failed to start run job: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(
        status_code=202,
        content={"job": job_view.model_dump()},
    )


# ---------------------------------------------------------------------------
# POST /integrations/{integration_id}/runs/{run_id}/resume
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/runs/{run_id}/resume", status_code=202)
def resume_run(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
) -> JSONResponse:
    """Resume a failed or stopped run from its last batch checkpoint.

    Reads ``batch_state.json`` from the run directory. The actual resumption
    logic lives in ``analyze._run_batched_runtime_analysis``: when a new
    ``start_run_job`` is invoked with the same ``run_id``, the pipeline
    passes ``AnalyzeOptions(batch_state_path=..., resume_batches=True)``
    which causes completed batches to be reused and only remaining batches
    re-processed.

    Returns 202 with checkpoint summary on success.
    Returns 404 if no batch checkpoint is found for this run.
    Returns 409 if an active job already exists for this integration.
    """
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(status_code=400, detail="invalid integration or run id")

    import json

    from selqor_forge.dashboard.run_worker import _run_dir, find_active_run_job

    # Refuse if an active job already exists for this integration
    active = find_active_run_job(ctx, integration_id)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f"an active run is already in progress for integration {integration_id}",
        )

    run_root = _run_dir(ctx, integration_id, run_id)
    batch_state_path = run_root / "batch_state.json"

    if not batch_state_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No batch checkpoint found for run {run_id}. "
                "The run either completed successfully, never reached the analyze stage, "
                "or was run on a build without checkpointing enabled."
            ),
        )

    # Load snapshot for response payload (informational only — resume itself is
    # driven by the pipeline when it reloads the state file).
    try:
        state_data = json.loads(batch_state_path.read_text())
    except Exception as exc:
        logger.warning("could not parse batch_state.json for %s/%s: %s", integration_id, run_id, exc)
        state_data = {}

    total_batches = int(state_data.get("total_batches") or 0)
    completed_batches = int(state_data.get("completed_batches") or 0)
    status = state_data.get("status") or "unknown"
    failed_batch = state_data.get("failed_batch")

    logger.info(
        "resuming run %s/%s status=%s completed=%d/%d failed_batch=%s",
        integration_id, run_id, status, completed_batches, total_batches, failed_batch,
    )

    try:
        job_view = start_run_job(
            ctx,
            integration_id,
            run_id,
            mode="llm",
            agent_prompt=None,
            llm_config_id=None,
        )
    except Exception as exc:
        logger.error("failed to resume run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(
        status_code=202,
        content={
            "job": job_view.model_dump(),
            "checkpoint": {
                "status": status,
                "total_batches": total_batches,
                "completed_batches": completed_batches,
                "pending_batches": max(0, total_batches - completed_batches),
                "failed_batch": failed_batch,
            },
        },
    )


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/runs/{run_id}/checkpoint
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/runs/{run_id}/checkpoint")
def get_run_checkpoint(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
) -> JSONResponse:
    """Return the batch checkpoint snapshot for a run, if one exists.

    Used by the frontend to decide whether to show a "Resume" button.
    Returns 200 with ``{"checkpoint": null}`` if no checkpoint file is present.
    """
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(status_code=400, detail="invalid integration or run id")

    import json

    from selqor_forge.dashboard.run_worker import _run_dir

    batch_state_path = _run_dir(ctx, integration_id, run_id) / "batch_state.json"
    if not batch_state_path.exists():
        return JSONResponse(status_code=200, content={"checkpoint": None})

    try:
        state_data = json.loads(batch_state_path.read_text())
    except Exception as exc:
        logger.warning("could not parse batch_state.json for %s/%s: %s", integration_id, run_id, exc)
        return JSONResponse(status_code=200, content={"checkpoint": None})

    total_batches = int(state_data.get("total_batches") or 0)
    completed_batches = int(state_data.get("completed_batches") or 0)

    return JSONResponse(
        status_code=200,
        content={
            "checkpoint": {
                "status": state_data.get("status") or "unknown",
                "total_batches": total_batches,
                "completed_batches": completed_batches,
                "pending_batches": max(0, total_batches - completed_batches),
                "failed_batch": state_data.get("failed_batch"),
                "provider": state_data.get("provider"),
                "model": state_data.get("model"),
                "resumable": (
                    completed_batches < total_batches
                    and (state_data.get("status") or "") != "completed"
                ),
            }
        },
    )


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/runs
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/runs")
def list_runs(ctx: Ctx, integration_id: str) -> JSONResponse:
    """List all runs for an integration."""
    if not is_safe_token(integration_id):
        raise HTTPException(status_code=400, detail="invalid integration id")

    runs = _load_runs(ctx, integration_id)
    return JSONResponse(status_code=200, content={"runs": runs})


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/runs/{run_id}/artifacts
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/runs/{run_id}/artifacts")
def list_artifacts(
    ctx: Ctx, integration_id: str, run_id: str
) -> JSONResponse:
    """List run artifacts (JSON files in the run directory)."""
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(
            status_code=400, detail="invalid integration or run id"
        )

    artifacts = _list_artifacts(ctx, integration_id, run_id)
    return JSONResponse(status_code=200, content={"artifacts": artifacts})


# ---------------------------------------------------------------------------
# DELETE /integrations/{integration_id}/runs/{run_id}
# ---------------------------------------------------------------------------


@router.delete("/integrations/{integration_id}/runs/{run_id}")
def delete_run(ctx: Ctx, integration_id: str, run_id: str) -> JSONResponse:
    """Delete a single run."""
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(status_code=400, detail="invalid integration or run id")

    session = ctx.db_session_factory()
    try:
        repo = RunRepository(session)
        deleted = repo.delete(integration_id, run_id)
    finally:
        session.close()

    if not deleted:
        raise HTTPException(status_code=404, detail="run not found")

    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/runs/{run_id}/artifact/{artifact_name}
# ---------------------------------------------------------------------------


@router.get(
    "/integrations/{integration_id}/runs/{run_id}/artifact/{artifact_name}"
)
def get_artifact(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
    artifact_name: str,
) -> JSONResponse:
    """Return the raw content of a single artifact."""
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(
            status_code=400, detail="invalid integration or run id"
        )
    if not is_safe_filename(artifact_name):
        raise HTTPException(status_code=400, detail="invalid path segments")

    content = _read_artifact_content(ctx, integration_id, run_id, artifact_name)
    if content is None:
        raise HTTPException(status_code=404, detail="artifact not found")

    # Return the raw JSON text (content-type set by the Rust source)
    from fastapi.responses import Response

    return Response(
        content=content,
        status_code=200,
        media_type="application/json; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_runs(ctx: Ctx, integration_id: str) -> list[dict]:
    """Load runs from the database."""
    session = ctx.db_session_factory()
    try:
        repo = RunRepository(session)
        db_runs = repo.list_by_integration(integration_id)
        runs = []
        for run in db_runs:
            runs.append({
                "run_id": run.run_id,
                "status": run.status,
                "created_at": run.created_at,
                "integration_id": run.integration_id,
                "integration_name": run.integration_name,
                "spec": run.spec,
                "analysis_source": run.analysis_source,
                "model": run.model,
                "score": run.score,
                "tool_count": run.tool_count,
                "endpoint_count": run.endpoint_count,
                "compression_ratio": run.compression_ratio,
                "coverage": run.coverage,
                "warnings": run.warnings or [],
                "error": run.error,
                "artifacts": run.artifacts or [],
            })
        return sorted(runs, key=lambda r: r.get("run_id", ""), reverse=True)
    finally:
        session.close()


def _list_artifacts(
    ctx: Ctx, integration_id: str, run_id: str
) -> list[str]:
    """List artifact names from the database (without loading content)."""
    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        return repo.list_names_by_run(integration_id, run_id)
    finally:
        session.close()


def _read_artifact_content(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
    artifact: str,
) -> str | None:
    """Read artifact content from the database."""
    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        art = repo.get(integration_id, run_id, artifact)
        if art and art.content:
            return art.content
        return None
    finally:
        session.close()

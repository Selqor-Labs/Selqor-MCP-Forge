# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard summary endpoint."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from sqlalchemy import select

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.routes.integrations import _integration_identity, _merge_integration_duplicates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard")
def get_dashboard(ctx: Ctx) -> JSONResponse:
    """Return dashboard summary with totals and recent_runs."""
    integrations = _list_integration_views(ctx)
    runs = _load_all_runs(ctx)
    if not integrations and not runs:
        integrations, runs = _load_filesystem_dashboard_state(ctx.state_dir)
    integrations = _collapse_duplicate_integrations(integrations)
    integration_summaries = _build_integration_summaries(integrations, runs)
    activity = _build_activity(runs)

    successful_runs = sum(1 for r in runs if r.get("status") == "ok")
    failed_runs = sum(1 for r in runs if r.get("status") == "failed")
    warning_runs = sum(1 for r in runs if r.get("warnings"))

    score_values = [
        float(r["score"]) for r in runs if r.get("score") is not None
    ]
    average_score: int | None = None
    if score_values:
        average_score = round(sum(score_values) / len(score_values))

    total_runs = successful_runs + failed_runs
    success_rate = (successful_runs / total_runs) if total_runs > 0 else 0.0
    latest_scores = [
        item["latest_score"] for item in integration_summaries
        if item.get("latest_score") is not None
    ]
    latest_coverages = [
        item["latest_coverage"] for item in integration_summaries
        if item.get("latest_coverage") is not None
    ]
    total_tools = sum(item.get("latest_tool_count") or 0 for item in integration_summaries)
    total_endpoints = sum(item.get("latest_endpoint_count") or 0 for item in integration_summaries)
    healthy_integrations = sum(
        1
        for item in integration_summaries
        if item.get("last_run_status") in {"ok", "completed"}
    )
    average_latest_score: int | None = None
    if latest_scores:
        average_latest_score = round(sum(latest_scores) / len(latest_scores))
    average_latest_coverage: float | None = None
    if latest_coverages:
        average_latest_coverage = sum(latest_coverages) / len(latest_coverages)

    # Most-recent 8 runs (sorted descending by run_id)
    sorted_runs = sorted(runs, key=lambda r: r.get("run_id", ""), reverse=True)
    recent_runs = sorted_runs[:8]

    return JSONResponse(
        status_code=200,
        content={
            "totals": {
                "integrations": len(integrations),
                "runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "average_score": average_score,
                "success_rate": success_rate,
                "warning_runs": warning_runs,
                "healthy_integrations": healthy_integrations,
                "average_latest_score": average_latest_score,
                "average_latest_coverage": average_latest_coverage,
                "tools": total_tools,
                "endpoints": total_endpoints,
            },
            "activity": activity,
            "integrations": integration_summaries,
            "recent_runs": recent_runs,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _list_integration_views(ctx: Ctx) -> list[dict]:
    """Load integrations from the database with run counts in a single query."""
    if ctx.db_session_factory is None:
        return []
    session = ctx.db_session_factory()
    try:
        from sqlalchemy import func
        from selqor_forge.dashboard.models import Integration as IntModel, Run as RunModel

        # Single query: LEFT JOIN integrations with aggregated run counts
        stmt = (
            select(IntModel, func.count(RunModel.run_id).label("run_count"))
            .outerjoin(RunModel, IntModel.id == RunModel.integration_id)
            .group_by(IntModel.id)
            .order_by(IntModel.created_at.desc())
        )
        rows = session.execute(stmt).all()
        result = []
        for model, run_count in rows:
            result.append({
                "id": model.id,
                "name": model.name,
                "spec": model.spec,
                "created_at": model.created_at,
                "notes": model.notes,
                "tags": model.tags or [],
                "run_count": run_count,
            })
        return result
    finally:
        session.close()


def _load_all_runs(ctx: Ctx) -> list[dict]:
    """Load all runs across all integrations in a single query."""
    if ctx.db_session_factory is None:
        return []
    session = ctx.db_session_factory()
    try:
        from selqor_forge.dashboard.models import Run as RunModel
        from sqlalchemy.sql import desc

        stmt = select(RunModel).order_by(desc(RunModel.created_at))
        runs = session.execute(stmt).scalars().all()
        all_runs = [
            {
                "integration_id": run.integration_id,
                "run_id": run.run_id,
                "status": run.status,
                "created_at": run.created_at,
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
            }
            for run in runs
        ]
        return all_runs
    finally:
        session.close()


def _build_integration_summaries(integrations: list[dict], runs: list[dict]) -> list[dict]:
    """Return per-integration dashboard summaries based on latest and historical runs."""
    runs_by_integration: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        integration_id = run.get("integration_id")
        if integration_id:
            runs_by_integration[integration_id].append(run)

    summaries: list[dict] = []
    for integration in integrations:
        integration_runs = sorted(
            runs_by_integration.get(integration["id"], []),
            key=lambda item: item.get("run_id", ""),
            reverse=True,
        )
        latest_run = integration_runs[0] if integration_runs else None
        score_values = [
            float(run["score"]) for run in integration_runs if run.get("score") is not None
        ]
        average_score: int | None = None
        if score_values:
            average_score = round(sum(score_values) / len(score_values))

        summaries.append({
            **integration,
            "run_count": len(integration_runs),
            "successful_runs": sum(1 for run in integration_runs if run.get("status") == "ok"),
            "failed_runs": sum(1 for run in integration_runs if run.get("status") == "failed"),
            "warning_runs": sum(1 for run in integration_runs if run.get("warnings")),
            "warning_count": sum(len(run.get("warnings") or []) for run in integration_runs),
            "average_score": average_score,
            "last_run_id": latest_run.get("run_id") if latest_run else None,
            "last_run_at": latest_run.get("created_at") if latest_run else None,
            "last_run_status": latest_run.get("status") if latest_run else None,
            "latest_score": latest_run.get("score") if latest_run else None,
            "latest_tool_count": latest_run.get("tool_count") if latest_run else None,
            "latest_endpoint_count": latest_run.get("endpoint_count") if latest_run else None,
            "latest_coverage": latest_run.get("coverage") if latest_run else None,
            "latest_compression_ratio": latest_run.get("compression_ratio") if latest_run else None,
            "latest_warnings": latest_run.get("warnings") if latest_run else [],
        })

    summaries.sort(
        key=lambda item: (
            item.get("latest_score") is not None,
            item.get("latest_score") or -1,
            item.get("run_count") or 0,
        ),
        reverse=True,
    )
    return summaries


def _build_activity(runs: list[dict], days: int = 14) -> list[dict]:
    """Return day-by-day activity buckets for the recent dashboard chart."""
    today = datetime.now(timezone.utc).date()
    buckets: dict[str, dict[str, int | str]] = {}

    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        buckets[key] = {
            "date": key,
            "label": day.strftime("%b %d"),
            "runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "warning_runs": 0,
        }

    for run in runs:
        day_key = (run.get("created_at") or "")[:10]
        bucket = buckets.get(day_key)
        if not bucket:
            continue
        bucket["runs"] += 1
        if run.get("status") == "ok":
            bucket["successful_runs"] += 1
        if run.get("status") == "failed":
            bucket["failed_runs"] += 1
        if run.get("warnings"):
            bucket["warning_runs"] += 1

    return [buckets[key] for key in buckets]


def _collapse_duplicate_integrations(integrations: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
    for integration in integrations:
        grouped[_integration_identity(integration)].append(integration)

    collapsed = [_merge_integration_duplicates(items) for items in grouped.values()]
    collapsed.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return collapsed


def _load_filesystem_dashboard_state(state_dir: Path) -> tuple[list[dict], list[dict]]:
    """Load legacy dashboard state from integrations.json and runs/*/*/run.json."""
    integrations: list[dict] = []
    integration_ids: set[str] = set()
    runs: list[dict] = []
    seen_runs: set[tuple[str, str]] = set()

    integrations_path = state_dir / "integrations.json"
    if integrations_path.is_file():
        try:
            payload = json.loads(integrations_path.read_text(encoding="utf-8"))
            raw_integrations = payload.get("integrations", payload) if isinstance(payload, dict) else payload
            if isinstance(raw_integrations, list):
                for item in raw_integrations:
                    if not isinstance(item, dict):
                        continue
                    integration_id = item.get("id")
                    if not integration_id:
                        continue
                    integrations.append({
                        "id": integration_id,
                        "name": item.get("name") or integration_id,
                        "spec": item.get("spec"),
                        "created_at": item.get("created_at"),
                        "notes": item.get("notes"),
                        "tags": item.get("tags") or [],
                        "run_count": 0,
                    })
                    integration_ids.add(integration_id)
        except Exception as exc:
            logger.warning("Failed to read legacy integrations from %s: %s", integrations_path, exc)

    runs_dir = state_dir / "runs"
    if runs_dir.is_dir():
        for run_path in sorted(runs_dir.rglob("run.json")):
            try:
                payload = json.loads(run_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read legacy run from %s: %s", run_path, exc)
                continue

            if not isinstance(payload, dict):
                continue

            integration_id = payload.get("integration_id")
            run_id = payload.get("run_id")
            if not integration_id or not run_id:
                continue

            seen_runs.add((integration_id, run_id))
            runs.append({
                "integration_id": integration_id,
                "run_id": run_id,
                "status": payload.get("status"),
                "created_at": payload.get("created_at"),
                "integration_name": payload.get("integration_name"),
                "spec": payload.get("spec"),
                "analysis_source": payload.get("analysis_source"),
                "model": payload.get("model"),
                "score": payload.get("score"),
                "tool_count": payload.get("tool_count"),
                "endpoint_count": payload.get("endpoint_count"),
                "compression_ratio": payload.get("compression_ratio"),
                "coverage": payload.get("coverage"),
                "warnings": payload.get("warnings") or [],
                "error": payload.get("error"),
                "artifacts": payload.get("artifacts") or [],
            })

            if integration_id not in integration_ids:
                integrations.append({
                    "id": integration_id,
                    "name": payload.get("integration_name") or integration_id,
                    "spec": payload.get("spec"),
                    "created_at": payload.get("created_at"),
                    "notes": None,
                    "tags": [],
                    "run_count": 0,
                })
                integration_ids.add(integration_id)

    if integrations_path.is_file():
        try:
            payload = json.loads(integrations_path.read_text(encoding="utf-8"))
            raw_integrations = payload.get("integrations", payload) if isinstance(payload, dict) else payload
            if isinstance(raw_integrations, list):
                for item in raw_integrations:
                    if not isinstance(item, dict):
                        continue
                    integration_id = item.get("id")
                    last_run = item.get("last_run")
                    if not integration_id or not isinstance(last_run, dict):
                        continue
                    run_id = last_run.get("run_id")
                    if not run_id or (integration_id, run_id) in seen_runs:
                        continue
                    runs.append({
                        "integration_id": integration_id,
                        "run_id": run_id,
                        "status": last_run.get("status"),
                        "created_at": last_run.get("created_at"),
                        "integration_name": item.get("name") or integration_id,
                        "spec": item.get("spec"),
                        "analysis_source": last_run.get("analysis_source"),
                        "model": None,
                        "score": last_run.get("score"),
                        "tool_count": last_run.get("tool_count"),
                        "endpoint_count": last_run.get("endpoint_count"),
                        "compression_ratio": last_run.get("compression_ratio"),
                        "coverage": last_run.get("coverage"),
                        "warnings": last_run.get("warnings") or [],
                        "error": last_run.get("error"),
                        "artifacts": [],
                    })
        except Exception as exc:
            logger.warning("Failed to synthesize legacy runs from %s: %s", integrations_path, exc)

    runs.sort(key=lambda item: item.get("run_id", ""), reverse=True)
    return integrations, runs

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Background run-job worker: spawns pipeline runs in daemon threads."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from selqor_forge.dashboard.context import (
    DashboardContext,
    IntegrationRunMode,
    RunJobProgressView,
    RunJobState,
    RunJobStatus,
    RunJobView,
    RunRecord,
    RunStepView,
    now_utc_string,
)

# Ordered list of stepper rows emitted for every run. Order matters — the
# frontend renders rows in this order and relies on the keys being stable.
_PIPELINE_STEPS: list[tuple[str, str]] = [
    ("parse", "Parsing OpenAPI specs"),
    ("normalize", "Normalizing endpoints"),
    ("analyze", "Analyzing endpoints with LLM"),
    ("curate", "Curating tool candidates"),
    ("score", "Scoring quality & compression"),
    ("generate", "Generating MCP server artifacts"),
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_run_job(
    ctx: DashboardContext,
    integration_id: str,
    run_id: str,
    mode: str,
    *,
    agent_prompt: str | None = None,
    llm_config_id: str | None = None,
) -> RunJobView:
    """Create a run job entry and spawn a background thread to execute it.

    Returns the initial :class:`RunJobView` (status will be ``queued``).
    Raises :class:`ValueError` if an active job already exists for the
    integration.
    """
    run_mode = _parse_run_mode(mode)

    # Atomically check for an active job AND create the new one under the
    # same lock acquisition to prevent two requests both passing the check.
    job_id = f"job-{integration_id}-{_now_unix_millis()}"

    with ctx.run_jobs_lock:
        active = [
            j
            for j in ctx.run_jobs.values()
            if j.integration_id == integration_id
            and j.status in (RunJobStatus.QUEUED, RunJobStatus.RUNNING)
        ]
        if active:
            best = max(active, key=lambda j: j.created_at)
            return _job_state_to_view(best)

        job_state = RunJobState(
            job_id=job_id,
            integration_id=integration_id,
            run_id=run_id,
            mode=run_mode,
            status=RunJobStatus.QUEUED,
            created_at=now_utc_string(),
            batch_state_path=None,
        )
        ctx.run_jobs[job_id] = job_state

    thread = threading.Thread(
        target=run_integration_job,
        args=(ctx, job_id, integration_id, run_id, mode),
        kwargs={"agent_prompt": agent_prompt, "llm_config_id": llm_config_id},
        daemon=True,
        name=f"run-job-{job_id}",
    )
    thread.start()

    view = load_run_job_view(ctx, integration_id, job_id)
    if view is None:
        raise RuntimeError("failed to read queued run job immediately after creation")
    return view


def run_integration_job(
    ctx: DashboardContext,
    job_id: str,
    integration_id: str,
    run_id: str,
    mode: str,
    *,
    agent_prompt: str | None = None,
    llm_config_id: str | None = None,
) -> None:
    """Thread target that executes the full pipeline for *integration_id*.

    Stages: parse spec -> normalize -> analyze (with optional LLM runtime)
    -> curate -> score -> generate -> save artifacts.

    Updates the in-memory :class:`RunJobState` on completion or failure.
    """
    import traceback

    # Mark as running
    with ctx.run_jobs_lock:
        job = ctx.run_jobs.get(job_id)
        if job is not None:
            job.status = RunJobStatus.RUNNING
            job.started_at = now_utc_string()
            job.error = None

    run_record: RunRecord | None = None
    error_message: str | None = None

    try:
        run_record = _execute_pipeline(
            ctx,
            integration_id,
            run_id,
            mode,
            agent_prompt=agent_prompt,
            llm_config_id=llm_config_id,
            job_id=job_id,
        )
    except Exception as exc:
        logger.exception(
            "run job %s for integration %s failed", job_id, integration_id
        )
        error_message = str(exc)
        # Also write crash info to a bounded log file under state_dir
        try:
            crash_log = ctx.state_dir / "run_job_crash.log"
            # Rotate if file exceeds 1MB
            if crash_log.exists() and crash_log.stat().st_size > 1_048_576:
                rotated = ctx.state_dir / "run_job_crash.log.1"
                crash_log.replace(rotated)
            with open(crash_log, "a") as f:
                f.write(f"\n=== CRASH at {now_utc_string()} ===\n")
                f.write(f"Job: {job_id}\n")
                f.write(f"Integration: {integration_id}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass

    # Record outcome
    with ctx.run_jobs_lock:
        job = ctx.run_jobs.get(job_id)
        if job is not None:
            job.completed_at = now_utc_string()
            if run_record is not None:
                job.status = RunJobStatus.COMPLETED
                job.error = None
                job.result = run_record
            else:
                job.status = RunJobStatus.FAILED
                job.error = error_message
                job.result = None

        # Keep the in-memory cache bounded.
        if len(ctx.run_jobs) > 120:
            entries = sorted(
                ctx.run_jobs.items(), key=lambda kv: kv[1].created_at
            )
            for stale_id, _ in entries[: len(ctx.run_jobs) - 120]:
                ctx.run_jobs.pop(stale_id, None)


def find_active_run_job(
    ctx: DashboardContext,
    integration_id: str,
) -> RunJobView | None:
    """Return the view for the most-recent active (queued/running) job, if any."""
    with ctx.run_jobs_lock:
        active = [
            j
            for j in ctx.run_jobs.values()
            if j.integration_id == integration_id
            and j.status in (RunJobStatus.QUEUED, RunJobStatus.RUNNING)
        ]
        if not active:
            return None

        best = max(active, key=lambda j: j.created_at)
        return _job_state_to_view(best)


def load_run_job_view(
    ctx: DashboardContext,
    integration_id: str,
    job_id: str,
) -> RunJobView | None:
    """Load a :class:`RunJobView` from the in-memory job map.

    The snapshot is built entirely inside the lock so the background
    thread's mutations of ``job.progress`` can never race with
    Pydantic's serialisation.
    """
    with ctx.run_jobs_lock:
        job = ctx.run_jobs.get(job_id)
        if job is None or job.integration_id != integration_id:
            return None
        return _job_state_to_view(job)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_run_mode(raw: str) -> IntegrationRunMode:
    cleaned = raw.strip().lower()
    if cleaned in ("manual", "manual_only"):
        return IntegrationRunMode.MANUAL
    return IntegrationRunMode.LLM


def _now_unix_millis() -> int:
    return int(time.time() * 1000)


def _run_dir(ctx: DashboardContext, integration_id: str, run_id: str) -> Path:
    return ctx.state_dir / "runs" / integration_id / run_id


def _job_state_to_view(job: RunJobState) -> RunJobView:
    """Convert internal :class:`RunJobState` to the frontend-facing view.

    **Must be called while holding ``ctx.run_jobs_lock``** so that the
    mutable ``job.progress`` (and its nested ``steps`` list) is not
    being mutated by the background worker mid-serialisation.  We take
    a deep copy via ``model_copy(deep=True)`` so the returned view is
    a frozen snapshot safe to serialise outside the lock.
    """
    progress: RunJobProgressView | None = None
    if job.progress is not None:
        progress = job.progress.model_copy(deep=True)

    return RunJobView(
        job_id=job.job_id,
        integration_id=job.integration_id,
        run_id=job.run_id,
        mode=str(job.mode),
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        progress=progress,
        run=job.result,
    )


class _StepTracker:
    """Mutates the job's ``progress.steps`` list under the context lock.

    The tracker owns the ordered stepper shown in the frontend. It provides
    coarse stage transitions (``start_step`` / ``finish_step``), a per-step
    ``detail`` line (used for "Batch 2/5…" during analysis), and a
    ``warn_step`` helper so live warnings appear under the matching row as
    they are discovered.
    """

    def __init__(self, ctx: DashboardContext, job_id: str) -> None:
        self._ctx = ctx
        self._job_id = job_id
        # Seed all six rows as pending so the UI can render the outline
        # immediately, before any stage actually starts.
        steps = [
            RunStepView(key=key, label=label, status="pending")
            for key, label in _PIPELINE_STEPS
        ]
        progress = RunJobProgressView(
            steps=steps,
            current_step=None,
            message="Queued",
            status="running",
        )
        self._apply(lambda _p: None, replacement=progress)

    # ---------- internal ---------------------------------------------------

    def _apply(
        self,
        mutator,
        *,
        replacement: RunJobProgressView | None = None,
    ) -> None:
        with self._ctx.run_jobs_lock:
            job = self._ctx.run_jobs.get(self._job_id)
            if job is None:
                return
            if replacement is not None:
                job.progress = replacement
                return
            if job.progress is None:
                job.progress = RunJobProgressView(
                    steps=[
                        RunStepView(key=key, label=label, status="pending")
                        for key, label in _PIPELINE_STEPS
                    ],
                    status="running",
                )
            mutator(job.progress)

    def _find(self, progress: RunJobProgressView, key: str) -> RunStepView | None:
        for step in progress.steps:
            if step.key == key:
                return step
        return None

    # ---------- public -----------------------------------------------------

    def start_step(self, key: str, detail: str | None = None) -> None:
        def _m(progress: RunJobProgressView) -> None:
            step = self._find(progress, key)
            if step is None:
                return
            step.status = "running"
            step.started_at = now_utc_string()
            if detail is not None:
                step.detail = detail
            progress.current_step = key
            label = next(
                (lbl for k, lbl in _PIPELINE_STEPS if k == key), key
            )
            progress.message = label

        self._apply(_m)

    def set_detail(self, key: str, detail: str) -> None:
        def _m(progress: RunJobProgressView) -> None:
            step = self._find(progress, key)
            if step is not None:
                step.detail = detail

        self._apply(_m)

    def warn_step(self, key: str, warnings: list[str]) -> None:
        if not warnings:
            return

        def _m(progress: RunJobProgressView) -> None:
            step = self._find(progress, key)
            if step is None:
                return
            for w in warnings:
                if w and w not in step.warnings:
                    step.warnings.append(w)
            if step.status == "running":
                step.status = "warning"

        self._apply(_m)

    def finish_step(
        self,
        key: str,
        *,
        detail: str | None = None,
        warned: bool = False,
    ) -> None:
        def _m(progress: RunJobProgressView) -> None:
            step = self._find(progress, key)
            if step is None:
                return
            step.completed_at = now_utc_string()
            if detail is not None:
                step.detail = detail
            # Preserve a warning status if warnings were already attached,
            # otherwise mark the row as done.
            if warned or step.warnings:
                step.status = "warning"
            else:
                step.status = "done"
            if progress.current_step == key:
                progress.current_step = None

        self._apply(_m)

    def fail_step(self, key: str, error: str) -> None:
        def _m(progress: RunJobProgressView) -> None:
            step = self._find(progress, key)
            if step is None:
                return
            step.status = "failed"
            step.completed_at = now_utc_string()
            if error:
                step.detail = error[:180]
            progress.status = "failed"
            progress.message = error[:180] if error else "Run failed"

        self._apply(_m)


def _execute_pipeline(
    ctx: DashboardContext,
    integration_id: str,
    run_id: str,
    mode: str,
    *,
    agent_prompt: str | None = None,
    llm_config_id: str | None = None,
    job_id: str | None = None,
) -> RunRecord:
    """Run the full 6-stage pipeline and return the resulting :class:`RunRecord`.

    Stages: parse -> normalize -> analyze -> curate -> score -> generate.

    Supports multiple specs: when an integration has more than one spec URL/path
    the parsed results are merged into a single unified UASF surface before
    analysis.  An optional *agent_prompt* steers the LLM to group tools around
    the agent's intent rather than the raw API structure.

    This is a blocking call and is intended to be invoked from a daemon
    thread only.
    """
    from selqor_forge.pipeline import analyze, curate, generate, normalize, parse, score  # noqa: E501 - lazy imports to avoid circular deps

    run_mode = _parse_run_mode(mode)
    run_root = _run_dir(ctx, integration_id, run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    created_at = now_utc_string()

    # --- Load the integration record ---
    integration = _load_integration_record(ctx, integration_id)
    if integration is None:
        raise ValueError(f"integration '{integration_id}' not found")

    # Resolve agent prompt: per-run override takes precedence, then integration default.
    effective_agent_prompt = agent_prompt or integration.agent_prompt or None

    # Attach a step tracker so the frontend can render a live "deep
    # research" style progress stepper. The tracker is a no-op when no
    # job entry exists (e.g. direct call paths in tests).
    tracker: _StepTracker | None = (
        _StepTracker(ctx, job_id) if job_id is not None else None
    )

    def _start(key: str, detail: str | None = None) -> None:
        if tracker is not None:
            tracker.start_step(key, detail)

    def _finish(key: str, *, detail: str | None = None) -> None:
        if tracker is not None:
            tracker.finish_step(key, detail=detail)

    def _warn(key: str, warnings: list[str]) -> None:
        if tracker is not None:
            tracker.warn_step(key, warnings)

    def _fail(key: str, error: str) -> None:
        if tracker is not None:
            tracker.fail_step(key, error)

    current_stage_key = "parse"

    try:
        # Stage 1: parse (supports multiple specs)
        current_stage_key = "parse"
        all_specs = integration.effective_specs()
        if not all_specs:
            raise ValueError(f"integration '{integration_id}' has no spec configured")

        _start(
            "parse",
            detail=(
                f"{len(all_specs)} spec{'s' if len(all_specs) != 1 else ''}"
            ),
        )

        if len(all_specs) == 1:
            parsed = parse.parse_spec(all_specs[0])
        else:
            logger.info(
                "merging %d specs for integration %s: %s",
                len(all_specs), integration_id, all_specs,
            )
            parsed_specs = [parse.parse_spec(s) for s in all_specs]
            parsed = parse.merge_parsed_specs(parsed_specs, combined_title=integration.name)

        _finish(
            "parse",
            detail=f"Parsed {len(all_specs)} spec{'s' if len(all_specs) != 1 else ''}",
        )

        # Stage 2: normalize
        current_stage_key = "normalize"
        _start("normalize")
        uasf = normalize.normalize(parsed)
        endpoint_count = len(uasf.endpoints) if hasattr(uasf, "endpoints") else 0
        _finish("normalize", detail=f"{endpoint_count} endpoints")

        if effective_agent_prompt:
            logger.info(
                "using agent prompt for integration %s: %r",
                integration_id, effective_agent_prompt[:80],
            )

        # Stage 3: analyze (heuristic when mode=manual, LLM otherwise)
        current_stage_key = "analyze"
        _start("analyze", detail=f"{endpoint_count} endpoints")

        def _analyze_progress_cb(payload: dict) -> None:
            """Translate batch progress events into the analyze row detail."""
            if tracker is None:
                return
            total = int(payload.get("total_batches") or 0)
            current = int(payload.get("current_batch") or 0)
            event = payload.get("event") or ""
            if total <= 1:
                if event == "batch_start":
                    tracker.set_detail("analyze", f"{endpoint_count} endpoints")
                return
            if event == "batch_start":
                tracker.set_detail(
                    "analyze", f"Batch {max(current, 1)}/{total}"
                )
            elif event == "batch_done":
                tracker.set_detail(
                    "analyze", f"Batch {current}/{total} complete"
                )
            elif event == "complete":
                tracker.set_detail(
                    "analyze", f"Processed {total} batches"
                )

        if run_mode == IntegrationRunMode.MANUAL:
            analysis = analyze.heuristic_analysis(
                uasf,
                agent_prompt=effective_agent_prompt,
            )
        else:
            llm_runtime = _resolve_llm_runtime(ctx, llm_config_id)
            if llm_runtime is None:
                logger.warning(
                    "no LLM config available for integration %s; falling back to heuristic",
                    integration_id,
                )
                analysis = analyze.heuristic_analysis(
                    uasf,
                    [
                        "No LLM configuration was available; using heuristic analysis instead. "
                        "Configure an LLM under Settings → LLM Config to enable AI analysis."
                    ],
                    agent_prompt=effective_agent_prompt,
                )
            else:
                # Configure per-batch checkpointing so large specs (500-1k endpoints)
                # are resumable. The batch_state.json lives under run_root, so a new
                # run triggered with the same run_id will automatically pick up any
                # previously completed batches and only process what's left.
                batch_state_path = run_root / "batch_state.json"
                resume_mode = batch_state_path.exists()
                options = analyze.AnalyzeOptions(
                    batch_state_path=batch_state_path,
                    resume_batches=True,
                    max_input_tokens=40_000,
                )
                logger.info(
                    "running LLM analysis for integration %s provider=%s model=%s resume=%s endpoints=%d",
                    integration_id,
                    llm_runtime.provider,
                    llm_runtime.model,
                    resume_mode,
                    endpoint_count,
                )
                analysis = analyze.analyze_with_override_and_options(
                    uasf,
                    ctx.config,
                    llm_override=llm_runtime,
                    options=options,
                    agent_prompt=effective_agent_prompt,
                    progress_cb=_analyze_progress_cb,
                )

        # Persist LLM call traces captured during analysis
        _persist_llm_traces(
            ctx,
            integration_id=integration_id,
            integration_name=integration.name,
            run_id=run_id,
            run_mode=str(run_mode),
        )

        _warn("analyze", list(getattr(analysis, "warnings", []) or []))
        tool_candidate_count = len(getattr(analysis, "tools", []) or [])
        _finish(
            "analyze",
            detail=f"{tool_candidate_count} tool candidates",
        )

        # Stage 4: curate
        current_stage_key = "curate"
        _start("curate", detail=f"{tool_candidate_count} candidates")
        plan = curate.curate(
            uasf, ctx.config, analysis, agent_prompt=effective_agent_prompt
        )
        curate_new_warnings = [
            w
            for w in (getattr(plan, "warnings", []) or [])
            if w not in (getattr(analysis, "warnings", []) or [])
        ]
        _warn("curate", curate_new_warnings)
        _finish("curate", detail=f"{len(plan.tools)} curated tools")

        # Stage 5: score
        current_stage_key = "score"
        _start("score")
        quality = score.score(uasf, plan)
        score_warnings = list(getattr(quality, "warnings", []) or [])
        _warn("score", score_warnings)
        quality_score = getattr(quality, "score", None)
        _finish(
            "score",
            detail=(
                f"Quality score {quality_score}/100"
                if quality_score is not None
                else "Scored"
            ),
        )

        # Stage 6: generate (writes to run_root as staging area)
        current_stage_key = "generate"
        _start("generate")
        generate.generate(run_root, uasf, analysis, plan, quality, ctx.config)
        _finish("generate", detail="Artifacts staged")

        # Collect artifact names from the staging directory
        artifacts = _list_artifacts_fs(run_root)

        run_record = RunRecord(
            run_id=run_id,
            status="ok",
            created_at=created_at,
            integration_id=integration.id,
            integration_name=integration.name,
            spec=integration.spec,
            analysis_source=getattr(analysis, "source", "unknown"),
            model=getattr(analysis, "model", None),
            score=getattr(quality, "score", None),
            tool_count=len(plan.tools) if hasattr(plan, "tools") else None,
            endpoint_count=len(uasf.endpoints) if hasattr(uasf, "endpoints") else None,
            compression_ratio=getattr(quality, "compression_ratio", None),
            coverage=getattr(quality, "coverage", None),
            warnings=getattr(quality, "warnings", []),
            error=None,
            artifacts=artifacts,
        )
    except Exception as exc:
        logger.error(
            "pipeline failed for %s/%s: %s", integration_id, run_id, exc
        )
        _fail(current_stage_key, str(exc))
        run_record = RunRecord(
            run_id=run_id,
            status="failed",
            created_at=created_at,
            integration_id=integration.id if integration else integration_id,
            integration_name=integration.name if integration else "",
            spec=integration.spec if integration else "",
            analysis_source="unknown",
            error=str(exc),
            artifacts=[],
        )

    # Also persist run.json as an artifact
    run_json_content = run_record.model_dump_json(indent=2)

    # Persist run record to database
    _update_last_run_summary(ctx, integration_id, run_record)

    # Persist all JSON artifacts from staging dir to database, then run.json
    _persist_artifacts_to_db(ctx, integration_id, run_id, run_root)
    _persist_single_artifact(ctx, integration_id, run_id, "run.json", run_json_content)

    # Update artifact list on run record to include run.json
    run_record.artifacts = _get_artifact_names_from_db(ctx, integration_id, run_id)

    # Clean up staging JSON files (keep server dirs for deployment)
    _cleanup_staging_json(run_root)

    return run_record


def _load_integration_record(ctx: DashboardContext, integration_id: str):
    """Load an IntegrationRecord from the database."""
    from selqor_forge.dashboard.context import IntegrationRecord
    from selqor_forge.dashboard.repositories import IntegrationRepository

    if ctx.db_session_factory is None:
        return None

    session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        model = repo.get_by_id(integration_id)
        if model is None:
            return None
        return IntegrationRecord(
            id=model.id,
            name=model.name,
            spec=model.spec,
            specs=model.specs or [model.spec],
            agent_prompt=model.agent_prompt,
            created_at=model.created_at,
            notes=model.notes,
            tags=model.tags or [],
        )
    finally:
        session.close()


def _list_artifacts_fs(run_root: Path) -> list[str]:
    """List JSON artifact filenames in a run directory."""
    if not run_root.exists():
        return []
    artifacts = sorted(
        f.name for f in run_root.iterdir() if f.is_file() and f.suffix == ".json"
    )
    return artifacts


def _persist_artifacts_to_db(
    ctx: DashboardContext,
    integration_id: str,
    run_id: str,
    run_root: Path,
) -> None:
    """Save all JSON artifacts from the staging directory to the database."""
    if ctx.db_session_factory is None:
        return

    from selqor_forge.dashboard.repositories import ArtifactRepository

    artifacts = _list_artifacts_fs(run_root)
    if not artifacts:
        return

    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        successful_count = 0

        # Batch artifacts in groups of 10 to reduce transaction overhead
        batch_size = 10
        for batch_start in range(0, len(artifacts), batch_size):
            batch_end = min(batch_start + batch_size, len(artifacts))
            batch_names = artifacts[batch_start:batch_end]

            try:
                for name in batch_names:
                    artifact_path = run_root / name
                    try:
                        content = artifact_path.read_text(encoding="utf-8")
                        repo.create(
                            integration_id=integration_id,
                            run_id=run_id,
                            name=name,
                            content=content,
                        )
                        successful_count += 1
                    except Exception:
                        logger.debug("failed saving artifact %s to database", name, exc_info=True)
                # Commit batch after 10 artifacts
                session.commit()
            except Exception:
                session.rollback()
                logger.debug("failed saving artifact batch %d-%d", batch_start, batch_end, exc_info=True)

        logger.debug("Saved %d/%d artifacts for %s/%s to database", successful_count, len(artifacts), integration_id, run_id)
    except Exception:
        session.rollback()
        logger.debug("failed saving artifacts to database", exc_info=True)
    finally:
        session.close()


def _persist_single_artifact(
    ctx: DashboardContext,
    integration_id: str,
    run_id: str,
    name: str,
    content: str,
) -> None:
    """Save a single artifact to the database."""
    if ctx.db_session_factory is None:
        return

    from selqor_forge.dashboard.repositories import ArtifactRepository

    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        repo.create(
            integration_id=integration_id,
            run_id=run_id,
            name=name,
            content=content,
        )
    except Exception:
        session.rollback()
        logger.debug("failed saving artifact %s to database", name, exc_info=True)
    finally:
        session.close()


def _get_artifact_names_from_db(
    ctx: DashboardContext,
    integration_id: str,
    run_id: str,
) -> list[str]:
    """Get artifact names from the database."""
    if ctx.db_session_factory is None:
        return []

    from selqor_forge.dashboard.repositories import ArtifactRepository

    session = ctx.db_session_factory()
    try:
        repo = ArtifactRepository(session)
        artifacts = repo.list_by_run(integration_id, run_id)
        return [a.name for a in artifacts]
    finally:
        session.close()


def _cleanup_staging_json(run_root: Path) -> None:
    """Remove JSON staging files from the run directory, keep server dirs."""
    if not run_root.exists():
        return
    for f in run_root.iterdir():
        if f.is_file() and f.suffix == ".json":
            try:
                f.unlink()
            except Exception:
                pass


def _resolve_llm_runtime(
    ctx: DashboardContext,
    llm_config_id: str | None,
):
    """Load an LLM config from the DB and convert it to an LlmRuntimeConfig.

    When ``llm_config_id`` is ``None`` the default-enabled config is used.
    Returns ``None`` when no usable config is found so callers can fall back
    to heuristic analysis.
    """
    from selqor_forge.dashboard.repositories import LLMConfigRepository
    from selqor_forge.pipeline.analyze import LlmRuntimeConfig

    if ctx.db_session_factory is None:
        return None

    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        models = repo.list_all()

        if not models:
            return None

        # Find the chosen config while session is still active
        chosen = None
        if llm_config_id:
            chosen = next((m for m in models if m.id == llm_config_id), None)
        if chosen is None:
            chosen = next((m for m in models if m.is_default and (m.model or "").strip()), None)
        if chosen is None:
            # Fall back to the first config that at least has a model set.
            chosen = next((m for m in models if (m.model or "").strip()), None)
        if chosen is None:
            return None

        # CRITICAL: Extract ALL ORM data BEFORE closing session
        secret_manager = ctx.secret_manager
        api_key = (
            secret_manager.decrypt_text(chosen.api_key)
            if secret_manager is not None and chosen.api_key
            else chosen.api_key
        )
        bearer_token = (
            secret_manager.decrypt_text(chosen.bearer_token)
            if secret_manager is not None and chosen.bearer_token
            else chosen.bearer_token
        )
        custom_headers = (
            secret_manager.decrypt_json_blob(chosen.custom_headers, {})
            if secret_manager is not None
            else (chosen.custom_headers or {})
        )

        # Extract provider and model while ORM object is still attached
        provider = (chosen.provider or "").strip()
        model = (chosen.model or None)
        base_url = (chosen.base_url or None)
        auth_type = (chosen.auth_type or "bearer")
        auth_header_name = getattr(chosen, "auth_header_name", None)
        auth_header_prefix = getattr(chosen, "auth_header_prefix", None)

        return LlmRuntimeConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            auth_type=auth_type,
            auth_header_name=auth_header_name,
            auth_header_prefix=auth_header_prefix,
            api_key=api_key or None,
            bearer_token=bearer_token or None,
            custom_headers=custom_headers or {},
        )
    finally:
        session.close()


def _persist_llm_traces(
    ctx: DashboardContext,
    *,
    integration_id: str,
    integration_name: str,
    run_id: str,
    run_mode: str,
) -> None:
    """Drain thread-local LLM call traces and persist them to the database.

    Called once after the analyze stage finishes.  Each captured
    :class:`LlmCallTrace` becomes a row in ``sf_llm_logs``.
    """
    from selqor_forge.pipeline.analyze import take_llm_call_traces

    traces = take_llm_call_traces()
    if not traces:
        return

    if ctx.db_session_factory is None:
        logger.debug("no db session; skipping %d llm trace(s)", len(traces))
        return

    from selqor_forge.dashboard.repositories import LLMLogRepository

    session = ctx.db_session_factory()
    try:
        repo = LLMLogRepository(session)
        successful_count = 0

        # Batch traces in groups of 5 to reduce transaction overhead
        batch_size = 5
        for batch_start in range(0, len(traces), batch_size):
            batch_end = min(batch_start + batch_size, len(traces))
            batch_traces = traces[batch_start:batch_end]

            try:
                for idx, trace in enumerate(batch_traces, start=batch_start):
                    log_id = f"log-{run_id}-{idx}"
                    try:
                        repo.create(
                            log_id=log_id,
                            integration_id=integration_id,
                            integration_name=integration_name,
                            run_id=run_id,
                            run_mode=run_mode,
                            provider=trace.provider or "",
                            model=trace.model,
                            endpoint=trace.endpoint or "",
                            success=trace.success,
                            latency_ms=trace.latency_ms,
                            request_payload=trace.request_payload or {},
                            response_payload=trace.response_payload,
                            response_text=trace.response_text,
                            error=trace.error,
                            created_at=now_utc_string(),
                        )
                        successful_count += 1
                    except Exception:
                        logger.debug(
                            "failed persisting llm trace %d for %s/%s",
                            idx, integration_id, run_id, exc_info=True,
                        )
                # Commit batch after 5 traces
                session.commit()
            except Exception:
                session.rollback()
                logger.debug("failed persisting llm trace batch %d-%d", batch_start, batch_end, exc_info=True)

        logger.info(
            "persisted %d/%d llm call trace(s) for %s/%s",
            successful_count, len(traces), integration_id, run_id,
        )
    except Exception:
        session.rollback()
        logger.debug("failed persisting llm traces", exc_info=True)
    finally:
        session.close()


def _update_last_run_summary(
    ctx: DashboardContext,
    integration_id: str,
    run: RunRecord,
) -> None:
    """Persist the run record to the database."""
    if ctx.db_session_factory is None:
        return

    from selqor_forge.dashboard.repositories import RunRepository

    session = ctx.db_session_factory()
    try:
        repo = RunRepository(session)
        repo.create(run)
        logger.debug("Saved run %s/%s to database", integration_id, run.run_id)
    except Exception:
        session.rollback()
        logger.debug("failed saving run to database", exc_info=True)
    finally:
        session.close()

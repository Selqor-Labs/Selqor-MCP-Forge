# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Benchmark suite: runs the forge pipeline against a manifest of APIs and
produces CSV, Markdown, and JSON summary reports comparing curated (LLM) tool
plans against a naive baseline that mirrors one tool per endpoint."""

from __future__ import annotations

import datetime
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from selqor_forge.config import AppConfig
from selqor_forge.models import (
    ToolDefinition,
    ToolPlan,
    UasfEndpoint,
    UasfSurface,
)
from selqor_forge.pipeline import analyze, curate, generate, normalize, parse, score
from selqor_forge.pipeline.analyze import LlmRuntimeConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class BenchmarkApi(BaseModel):
    """Single API entry inside a benchmark manifest."""

    name: str
    slug: str
    spec: str
    auth_type: str | None = None
    complexity: str | None = None
    expected_tools: str | None = None
    domain: str | None = None


class BenchmarkManifest(BaseModel):
    """Top-level manifest listing APIs to benchmark."""

    apis: list[BenchmarkApi] = Field(default_factory=list)


@dataclass
class BenchmarkRow:
    """Result row for a single benchmarked API."""

    name: str
    slug: str
    status: str
    spec: str
    endpoints: int | None = None
    curated_tools: int | None = None
    baseline_tools: int | None = None
    curated_score: int | None = None
    baseline_score: int | None = None
    score_delta: int | None = None
    curated_compression: float | None = None
    baseline_compression: float | None = None
    coverage: float | None = None
    duration_ms: int = 0
    error: str | None = None
    analysis_source: str | None = None
    model: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON output."""
        return {
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "spec": self.spec,
            "endpoints": self.endpoints,
            "curated_tools": self.curated_tools,
            "baseline_tools": self.baseline_tools,
            "curated_score": self.curated_score,
            "baseline_score": self.baseline_score,
            "score_delta": self.score_delta,
            "curated_compression": self.curated_compression,
            "baseline_compression": self.baseline_compression,
            "coverage": self.coverage,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "analysis_source": self.analysis_source,
            "model": self.model,
            "warnings": self.warnings,
        }


@dataclass
class BenchmarkSummary:
    """Aggregate summary written to the output directory."""

    generated_at_utc: str
    successful: int
    failed: int
    rows: list[BenchmarkRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "successful": self.successful,
            "failed": self.failed,
            "rows": [r.to_dict() for r in self.rows],
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    manifest: Path,
    out: Path,
    app_config: AppConfig,
    generate_servers: bool,
    fail_fast: bool,
    llm_config: LlmRuntimeConfig | None = None,
) -> None:
    """Execute the full benchmark suite.

    Parameters
    ----------
    manifest:
        Path to the benchmark manifest JSON file containing an ``apis`` list.
    out:
        Directory where per-API artefacts and the aggregate summary are written.
    app_config:
        Forge application configuration (LLM settings, targets, etc.).
    generate_servers:
        When *True*, additionally invoke the ``generate`` stage for each API.
    fail_fast:
        When *True*, abort the run on the first API failure.
    llm_config:
        Optional LLM runtime configuration loaded from the dashboard database.
        When provided, the benchmark uses real LLM analysis instead of heuristic.
    """
    logger.info(
        "starting benchmark suite: manifest=%s out=%s generate_servers=%s "
        "fail_fast=%s anthropic_enabled=%s llm_config=%s",
        manifest,
        out,
        generate_servers,
        fail_fast,
        app_config.anthropic.enabled,
        f"{llm_config.provider}/{llm_config.model}" if llm_config else "none",
    )

    loaded = _load_manifest(manifest)
    if not loaded.apis:
        raise ValueError("benchmark manifest did not contain any APIs")

    out.mkdir(parents=True, exist_ok=True)

    manifest_dir = manifest.parent if manifest.parent else Path(".")

    # Resume support: load previously completed rows from checkpoint
    completed_rows, completed_slugs = _load_checkpoint(out)
    rows: list[BenchmarkRow] = list(completed_rows)
    if completed_slugs:
        logger.info(
            "resuming benchmark: %d/%d APIs already completed",
            len(completed_slugs),
            len(loaded.apis),
        )

    logger.info(
        "running benchmark suite: apis=%d anthropic=%s llm=%s",
        len(loaded.apis),
        "enabled" if app_config.anthropic.enabled else "disabled",
        f"{llm_config.provider}/{llm_config.model}" if llm_config else "heuristic",
    )

    for api in loaded.apis:
        # Skip already completed APIs (resume support)
        if api.slug in completed_slugs:
            logger.info(
                "benchmark API skipped (already completed): api=%s slug=%s",
                api.name,
                api.slug,
            )
            continue

        started = time.monotonic()
        resolved_spec = _resolve_spec_input(api.spec, manifest_dir)
        logger.info(
            "benchmark API started: api=%s slug=%s spec=%s",
            api.name,
            api.slug,
            resolved_spec,
        )

        try:
            row = _run_single_api(
                out=out,
                app_config=app_config,
                api=api,
                spec_input=resolved_spec,
                generate_servers=generate_servers,
                llm_config=llm_config,
            )
        except Exception:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            error_message = _format_exception()
            logger.error(
                "benchmark API failed: api=%s slug=%s error=%s",
                api.name,
                api.slug,
                error_message,
            )

            row = BenchmarkRow(
                name=api.name,
                slug=api.slug,
                status="failed",
                spec=resolved_spec,
                duration_ms=elapsed_ms,
                error=error_message,
            )

            if fail_fast:
                rows.append(row)
                _save_checkpoint(out, rows)
                _write_reports(out, rows)
                raise RuntimeError(
                    f"benchmark aborted due to fail_fast after {api.name}"
                ) from None

        elapsed_ms = int((time.monotonic() - started) * 1000)

        if row.status == "ok":
            logger.info(
                "benchmark API completed: api=%s slug=%s endpoints=%s "
                "curated_tools=%s score=%s source=%s model=%s duration_ms=%d",
                row.name,
                row.slug,
                row.endpoints or 0,
                row.curated_tools or 0,
                row.curated_score or 0,
                row.analysis_source or "unknown",
                row.model or "none",
                elapsed_ms,
            )
        else:
            logger.warning(
                "benchmark API completed with failure status: api=%s slug=%s "
                "duration_ms=%d",
                row.name,
                row.slug,
                elapsed_ms,
            )

        row.duration_ms = elapsed_ms
        rows.append(row)

        # Save checkpoint after each API so interrupted runs can resume
        _save_checkpoint(out, rows)

    _write_reports(out, rows)
    # Clean up checkpoint file after successful completion
    checkpoint_path = out / ".benchmark-checkpoint.json"
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    logger.info("benchmark complete: out=%s", out)


# ---------------------------------------------------------------------------
# Single-API pipeline execution
# ---------------------------------------------------------------------------


def _run_single_api(
    out: Path,
    app_config: AppConfig,
    api: BenchmarkApi,
    spec_input: str,
    generate_servers: bool,
    llm_config: LlmRuntimeConfig | None = None,
) -> BenchmarkRow:
    """Run the full pipeline for a single API and return a result row."""

    logger.debug(
        "running benchmark pipeline: api=%s slug=%s spec=%s llm=%s",
        api.name,
        api.slug,
        spec_input,
        f"{llm_config.provider}/{llm_config.model}" if llm_config else "heuristic",
    )

    # Stage 1 - Parse (with retry for remote specs)
    parsed = _fetch_and_parse_spec(spec_input)
    logger.debug(
        "parsed benchmark spec: api=%s endpoints=%d",
        api.name,
        len(parsed.endpoints),
    )

    # Stage 2 - Normalize
    surface = normalize.normalize(parsed)
    logger.debug(
        "normalized benchmark surface: api=%s endpoints=%d",
        api.name,
        len(surface.endpoints),
    )

    # Stage 3 - Analyze (use LLM config if available)
    if llm_config is not None:
        analysis = analyze.analyze_with_override(
            surface, app_config, llm_override=llm_config,
        )
    else:
        analysis = analyze.analyze(surface, app_config)

    analysis_source = getattr(analysis, "source", "unknown")
    analysis_model = getattr(analysis, "model", None)
    analysis_warnings = list(getattr(analysis, "warnings", []) or [])

    logger.debug(
        "analysis plan generated: api=%s tools=%d warnings=%d source=%s model=%s",
        api.name,
        len(analysis.tools),
        len(analysis.warnings),
        analysis_source,
        analysis_model,
    )

    # Stage 4 - Curate (curated plan driven by analysis)
    curated_plan = curate.curate(surface, app_config, analysis)
    curated_quality = score.score(surface, curated_plan)

    # Baseline: naive 1-endpoint-per-tool mirror
    baseline_plan = _baseline_mirror_plan(surface)
    baseline_quality = score.score(surface, baseline_plan)

    # Persist per-API artefacts
    api_out = out / api.slug
    api_out.mkdir(parents=True, exist_ok=True)

    _write_json(api_out / "analysis-plan.json", analysis.model_dump(mode="json"))
    _write_json(api_out / "curated-tool-plan.json", curated_plan.model_dump(mode="json"))
    _write_json(api_out / "curated-quality.json", curated_quality.model_dump(mode="json"))
    _write_json(api_out / "baseline-tool-plan.json", baseline_plan.model_dump(mode="json"))
    _write_json(api_out / "baseline-quality.json", baseline_quality.model_dump(mode="json"))

    metadata = {
        "name": api.name,
        "slug": api.slug,
        "spec": spec_input,
        "auth_type": api.auth_type,
        "complexity": api.complexity,
        "expected_tools": api.expected_tools,
        "domain": api.domain,
        "endpoints": len(surface.endpoints),
        "analysis_source": analysis_source,
        "model": analysis_model,
    }
    _write_json(api_out / "benchmark-metadata.json", metadata)

    # Optional stage 6 - Generate server scaffolds
    if generate_servers:
        generated_out = api_out / "generated"
        logger.debug(
            "generating benchmark server outputs: api=%s out=%s",
            api.name,
            generated_out,
        )
        generate.generate(
            generated_out,
            surface,
            analysis,
            curated_plan,
            curated_quality,
            app_config,
        )

    return BenchmarkRow(
        name=api.name,
        slug=api.slug,
        status="ok",
        spec=spec_input,
        endpoints=len(surface.endpoints),
        curated_tools=len(curated_plan.tools),
        baseline_tools=len(baseline_plan.tools),
        curated_score=curated_quality.score,
        baseline_score=baseline_quality.score,
        score_delta=curated_quality.score - baseline_quality.score,
        curated_compression=curated_quality.compression_ratio,
        baseline_compression=baseline_quality.compression_ratio,
        coverage=curated_quality.coverage,
        duration_ms=0,
        error=None,
        analysis_source=analysis_source,
        model=analysis_model,
        warnings=analysis_warnings,
    )


# ---------------------------------------------------------------------------
# Checkpoint (resume support)
# ---------------------------------------------------------------------------

_CHECKPOINT_FILENAME = ".benchmark-checkpoint.json"


def _load_checkpoint(out_dir: Path) -> tuple[list[BenchmarkRow], set[str]]:
    """Load completed rows from a checkpoint file, if it exists."""
    checkpoint_path = out_dir / _CHECKPOINT_FILENAME
    if not checkpoint_path.exists():
        return [], set()
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        rows = [BenchmarkRow(**r) for r in data.get("rows", [])]
        slugs = {r.slug for r in rows}
        return rows, slugs
    except Exception as exc:
        logger.warning("failed to load benchmark checkpoint: %s; starting fresh", exc)
        return [], set()


def _save_checkpoint(out_dir: Path, rows: list[BenchmarkRow]) -> None:
    """Save current rows to a checkpoint file for resume support."""
    checkpoint_path = out_dir / _CHECKPOINT_FILENAME
    data = {"rows": [r.to_dict() for r in rows]}
    checkpoint_path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Spec fetching with retry
# ---------------------------------------------------------------------------

_SPEC_FETCH_MAX_RETRIES = 3
_SPEC_FETCH_RETRY_DELAY = 2.0  # seconds


def _fetch_and_parse_spec(spec_input: str) -> Any:
    """Parse a spec with retry logic for remote URLs."""
    parsed_url = urlparse(spec_input)
    is_remote = parsed_url.scheme in ("http", "https")

    if not is_remote:
        return parse.parse_spec(spec_input)

    last_error: Exception | None = None
    for attempt in range(_SPEC_FETCH_MAX_RETRIES):
        try:
            return parse.parse_spec(spec_input)
        except Exception as exc:
            last_error = exc
            if attempt < _SPEC_FETCH_MAX_RETRIES - 1:
                delay = _SPEC_FETCH_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "spec fetch failed (attempt %d/%d): %s; retrying in %.0fs",
                    attempt + 1,
                    _SPEC_FETCH_MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "spec fetch failed after %d attempts: %s",
                    _SPEC_FETCH_MAX_RETRIES,
                    exc,
                )
    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _load_manifest(path: Path) -> BenchmarkManifest:
    """Read and parse a benchmark manifest JSON file."""
    logger.debug("loading benchmark manifest: path=%s", path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"failed reading benchmark manifest: {path}") from exc

    try:
        return BenchmarkManifest.model_validate(json.loads(raw))
    except Exception as exc:
        raise RuntimeError(f"failed parsing benchmark manifest: {path}") from exc


# ---------------------------------------------------------------------------
# Spec resolution
# ---------------------------------------------------------------------------


def _resolve_spec_input(spec: str, manifest_dir: Path) -> str:
    """Resolve a spec reference to an absolute path or URL.

    - If *spec* is an HTTP(S) URL it is returned as-is.
    - If *spec* is an absolute filesystem path it is returned as-is.
    - Otherwise it is treated as relative to *manifest_dir*.
    """
    parsed_url = urlparse(spec)
    if parsed_url.scheme in ("http", "https"):
        return spec

    as_path = Path(spec)
    if as_path.is_absolute():
        return str(as_path)

    return str(manifest_dir / spec)


# ---------------------------------------------------------------------------
# Baseline mirror plan
# ---------------------------------------------------------------------------


def _baseline_mirror_plan(surface: UasfSurface) -> ToolPlan:
    """Create a naive 1:1 endpoint-to-tool baseline plan.

    Each endpoint becomes its own tool with a generic passthrough schema.
    This serves as the lower-quality comparison target.
    """
    tools: list[ToolDefinition] = []

    for endpoint in surface.endpoints:
        endpoint_id = endpoint.id
        path_schema = _parameter_schema(endpoint, "path")
        query_schema = _parameter_schema(endpoint, "query")

        tools.append(
            ToolDefinition(
                name=f"{endpoint_id}_tool",
                description=(
                    f"Execute {endpoint.method.upper()} {endpoint.path} "
                    f"directly as an endpoint mirror."
                ),
                covered_endpoints=[endpoint_id],
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [endpoint_id],
                            "description": "Operation id to execute",
                        },
                        "path_params": path_schema,
                        "query": query_schema,
                        "body": {
                            "type": [
                                "object",
                                "array",
                                "string",
                                "number",
                                "boolean",
                                "null",
                            ],
                        },
                        "headers": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["operation"],
                },
                confidence=0.45,
            )
        )

    endpoint_catalog = {ep.id: ep for ep in surface.endpoints}

    return ToolPlan(
        tools=tools,
        endpoint_catalog=endpoint_catalog,
        warnings=["Baseline mirrors one endpoint per tool."],
    )


def _parameter_schema(endpoint: UasfEndpoint, location: str) -> dict[str, Any]:
    """Build a JSON Schema object for parameters at a given *location* (path/query)."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in endpoint.parameters:
        if param.location != location:
            continue

        schema_value = param.schema_ if param.schema_ is not None else {}
        properties[param.name] = schema_value
        if param.required:
            required.append(param.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required

    return schema


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _write_reports(out_dir: Path, rows: list[BenchmarkRow]) -> None:
    """Write JSON, Markdown, and CSV summary reports to *out_dir*."""
    logger.debug("writing benchmark reports: out_dir=%s rows=%d", out_dir, len(rows))

    successful = sum(1 for r in rows if r.status == "ok")
    failed = len(rows) - successful

    # Surface a warning if all successful runs used heuristic analysis
    heuristic_count = sum(
        1 for r in rows if r.status == "ok" and r.analysis_source == "heuristic"
    )
    llm_count = successful - heuristic_count

    summary = BenchmarkSummary(
        generated_at_utc=_current_time_utc(),
        successful=successful,
        failed=failed,
        rows=list(rows),
    )

    summary_dict = summary.to_dict()
    summary_dict["llm_runs"] = llm_count
    summary_dict["heuristic_runs"] = heuristic_count
    if heuristic_count > 0 and llm_count == 0:
        summary_dict["notice"] = (
            "WARNING: All runs used heuristic analysis (no LLM). "
            "Configure an LLM via the dashboard or pass --llm-config-id "
            "to get LLM-assisted results."
        )
        logger.warning(
            "all %d successful benchmark runs used heuristic analysis — "
            "no LLM was configured",
            heuristic_count,
        )

    _write_json(out_dir / "benchmark-summary.json", summary_dict)

    (out_dir / "benchmark-summary.md").write_text(
        _markdown_table(rows), encoding="utf-8"
    )
    (out_dir / "benchmark-summary.csv").write_text(
        _csv_table(rows), encoding="utf-8"
    )

    logger.info(
        "benchmark summary generated: successful=%d failed=%d",
        successful,
        failed,
    )
    logger.debug("benchmark markdown summary:\n%s", _markdown_table(rows))


# ---------------------------------------------------------------------------
# Markdown table
# ---------------------------------------------------------------------------


def _markdown_table(rows: list[BenchmarkRow]) -> str:
    """Render benchmark rows as a Markdown table."""
    lines: list[str] = [
        "| API | Status | Source | Model | Endpoints | Curated Tools | Baseline Tools "
        "| Curated Score | Baseline Score | Delta | Curated Compression "
        "| Baseline Compression | Coverage |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in rows:
        source = row.analysis_source or "-"
        model = row.model or "-"
        endpoints = str(row.endpoints) if row.endpoints is not None else "-"
        curated_tools = str(row.curated_tools) if row.curated_tools is not None else "-"
        baseline_tools = (
            str(row.baseline_tools) if row.baseline_tools is not None else "-"
        )
        curated_score = (
            str(row.curated_score) if row.curated_score is not None else "-"
        )
        baseline_score = (
            str(row.baseline_score) if row.baseline_score is not None else "-"
        )
        delta = f"{row.score_delta:+d}" if row.score_delta is not None else "-"
        curated_compression = (
            f"{row.curated_compression:.3f}"
            if row.curated_compression is not None
            else "-"
        )
        baseline_compression = (
            f"{row.baseline_compression:.3f}"
            if row.baseline_compression is not None
            else "-"
        )
        coverage = f"{row.coverage:.3f}" if row.coverage is not None else "-"

        lines.append(
            f"| {row.name} | {row.status} | {source} | {model} | {endpoints} | {curated_tools} "
            f"| {baseline_tools} | {curated_score} | {baseline_score} "
            f"| {delta} | {curated_compression} | {baseline_compression} "
            f"| {coverage} |"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CSV table
# ---------------------------------------------------------------------------

_CSV_HEADER = (
    "name,slug,status,analysis_source,model,endpoints,curated_tools,baseline_tools,"
    "curated_score,baseline_score,score_delta,"
    "curated_compression,baseline_compression,coverage,"
    "duration_ms,error"
)


def _csv_table(rows: list[BenchmarkRow]) -> str:
    """Render benchmark rows as a CSV string."""
    lines: list[str] = [_CSV_HEADER]

    for row in rows:
        error_str = (
            row.error.replace(",", " ").replace("\n", " ") if row.error else ""
        )
        lines.append(
            ",".join(
                [
                    row.name.replace(",", " "),
                    row.slug.replace(",", " "),
                    row.status,
                    row.analysis_source or "",
                    row.model or "",
                    str(row.endpoints) if row.endpoints is not None else "",
                    str(row.curated_tools) if row.curated_tools is not None else "",
                    str(row.baseline_tools) if row.baseline_tools is not None else "",
                    str(row.curated_score) if row.curated_score is not None else "",
                    str(row.baseline_score) if row.baseline_score is not None else "",
                    str(row.score_delta) if row.score_delta is not None else "",
                    (
                        f"{row.curated_compression:.6f}"
                        if row.curated_compression is not None
                        else ""
                    ),
                    (
                        f"{row.baseline_compression:.6f}"
                        if row.baseline_compression is not None
                        else ""
                    ),
                    f"{row.coverage:.6f}" if row.coverage is not None else "",
                    str(row.duration_ms),
                    error_str,
                ]
            )
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, value: Any) -> None:
    """Serialise *value* as pretty-printed JSON and write to *path*."""
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def _current_time_utc() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def _format_exception() -> str:
    """Format the current exception as a single-line string."""
    import traceback

    return traceback.format_exc().strip().replace("\n", " | ")

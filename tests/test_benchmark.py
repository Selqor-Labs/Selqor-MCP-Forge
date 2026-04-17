# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the benchmark runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from selqor_forge.benchmark import (
    BenchmarkRow,
    _fetch_and_parse_spec,
    _load_checkpoint,
    _save_checkpoint,
    _write_reports,
    run,
)
from selqor_forge.config import AppConfig


@pytest.fixture()
def tiny_spec(tmp_path: Path) -> Path:
    """Write a minimal OpenAPI spec to a temporary file."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "List items",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/items/{id}": {
                "get": {
                    "operationId": "getItem",
                    "summary": "Get item",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }
    path = tmp_path / "test-spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


@pytest.fixture()
def manifest_file(tmp_path: Path, tiny_spec: Path) -> Path:
    """Write a benchmark manifest pointing at the tiny spec."""
    manifest = {
        "apis": [
            {
                "name": "Test API",
                "slug": "test-api",
                "spec": str(tiny_spec),
                "domain": "testing",
            },
            {
                "name": "Test API 2",
                "slug": "test-api-2",
                "spec": str(tiny_spec),
                "domain": "testing",
            },
        ]
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_benchmark_runs_heuristic_and_records_source(manifest_file: Path, tmp_path: Path):
    """Benchmark should run with heuristic analysis and record analysis_source."""
    out = tmp_path / "results"
    config = AppConfig.load(None).with_anthropic_enabled(False)

    run(
        manifest=manifest_file,
        out=out,
        app_config=config,
        generate_servers=False,
        fail_fast=False,
    )

    summary_path = out / "benchmark-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["successful"] == 2
    assert summary["failed"] == 0
    assert summary["heuristic_runs"] == 2
    assert summary["llm_runs"] == 0
    assert "WARNING" in summary.get("notice", "")

    # Each row should have analysis_source recorded
    for row in summary["rows"]:
        assert row["analysis_source"] == "heuristic"
        assert row["model"] is None


def test_benchmark_resume_skips_completed(manifest_file: Path, tmp_path: Path):
    """After interruption, resumed benchmark should skip completed APIs."""
    out = tmp_path / "results"
    out.mkdir(parents=True, exist_ok=True)
    config = AppConfig.load(None).with_anthropic_enabled(False)

    # Simulate a checkpoint with first API already completed
    checkpoint_rows = [
        BenchmarkRow(
            name="Test API",
            slug="test-api",
            status="ok",
            spec="fake",
            endpoints=2,
            curated_tools=1,
            baseline_tools=2,
            curated_score=80,
            baseline_score=50,
            score_delta=30,
            analysis_source="heuristic",
        )
    ]
    _save_checkpoint(out, checkpoint_rows)

    run(
        manifest=manifest_file,
        out=out,
        app_config=config,
        generate_servers=False,
        fail_fast=False,
    )

    summary = json.loads((out / "benchmark-summary.json").read_text(encoding="utf-8"))
    assert summary["successful"] == 2
    # Only the second API should have per-API artifacts
    assert (out / "test-api-2" / "analysis-plan.json").exists()
    # Checkpoint should be cleaned up after success
    assert not (out / ".benchmark-checkpoint.json").exists()


def test_checkpoint_roundtrip(tmp_path: Path):
    """Checkpoint save/load should preserve all row fields."""
    rows = [
        BenchmarkRow(
            name="API",
            slug="api",
            status="ok",
            spec="spec.json",
            analysis_source="heuristic",
            model=None,
            warnings=["test warning"],
        )
    ]
    _save_checkpoint(tmp_path, rows)
    loaded_rows, slugs = _load_checkpoint(tmp_path)
    assert slugs == {"api"}
    assert loaded_rows[0].analysis_source == "heuristic"
    assert loaded_rows[0].warnings == ["test warning"]


def test_fetch_and_parse_spec_local(tiny_spec: Path):
    """Local specs should parse without retry logic."""
    parsed = _fetch_and_parse_spec(str(tiny_spec))
    assert len(parsed.endpoints) == 2


def test_write_reports_includes_source_columns(tmp_path: Path):
    """Reports should include analysis_source and model columns."""
    rows = [
        BenchmarkRow(
            name="API",
            slug="api",
            status="ok",
            spec="spec.json",
            endpoints=5,
            curated_tools=3,
            baseline_tools=5,
            curated_score=85,
            baseline_score=50,
            score_delta=35,
            curated_compression=0.6,
            baseline_compression=1.0,
            coverage=1.0,
            analysis_source="anthropic",
            model="claude-sonnet-4-20250514",
        )
    ]
    _write_reports(tmp_path, rows)

    md = (tmp_path / "benchmark-summary.md").read_text(encoding="utf-8")
    assert "Source" in md
    assert "anthropic" in md
    assert "claude-sonnet-4-20250514" in md

    csv = (tmp_path / "benchmark-summary.csv").read_text(encoding="utf-8")
    assert "analysis_source" in csv
    assert "anthropic" in csv

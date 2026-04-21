# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Pipeline unit/integration tests using a local minimal OpenAPI spec."""

import json
from datetime import datetime, timezone

import pytest
import yaml

from selqor_forge.config import AppConfig, OutputTarget, TransportMode
from selqor_forge.pipeline import curate, generate, normalize, parse, score


# ---------------------------------------------------------------------------
# Minimal OpenAPI 3.0 spec (no network required)
# ---------------------------------------------------------------------------

MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Pets API", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "A list of pets"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "tag": {"type": "string"},
                                },
                                "required": ["name"],
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Created pet"}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a specific pet",
                "parameters": [
                    {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "A pet"}},
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet",
                "parameters": [
                    {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"204": {"description": "Deleted"}},
            },
        },
    },
}


@pytest.fixture()
def spec_file(tmp_state_dir):
    """Write minimal spec to a temp JSON file."""
    spec_path = tmp_state_dir / "pets.json"
    spec_path.write_text(json.dumps(MINIMAL_SPEC), encoding="utf-8")
    return str(spec_path)


@pytest.fixture()
def spec_yaml_file(tmp_state_dir):
    """Write minimal spec to a temp YAML file."""
    spec_path = tmp_state_dir / "pets.yaml"
    spec_path.write_text(yaml.dump(MINIMAL_SPEC), encoding="utf-8")
    return str(spec_path)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_parse_json_file(spec_file):
    parsed = parse.parse_spec(spec_file)
    assert parsed.title == "Pets API"
    assert parsed.version == "1.0.0"
    assert len(parsed.endpoints) == 4


def test_parse_yaml_file(spec_yaml_file):
    parsed = parse.parse_spec(spec_yaml_file)
    assert parsed.title == "Pets API"
    assert len(parsed.endpoints) == 4


def test_parse_endpoint_fields(spec_file):
    parsed = parse.parse_spec(spec_file)
    # IDs are lowercased operationIds
    ids = {ep.id for ep in parsed.endpoints}
    assert "listpets" in ids
    list_ep = next(ep for ep in parsed.endpoints if ep.id == "listpets")
    assert list_ep.method == "get"
    assert list_ep.path == "/pets"


def test_parse_path_parameters(spec_file):
    parsed = parse.parse_spec(spec_file)
    get_pet = next(ep for ep in parsed.endpoints if ep.id == "getpet")
    param_names = [p.name for p in get_pet.parameters]
    assert "petId" in param_names


def test_parse_invalid_file_raises():
    with pytest.raises(Exception):
        parse.parse_spec("/nonexistent/path/to/spec.json")


def test_parse_invalid_content_raises(tmp_state_dir):
    bad = tmp_state_dir / "bad.json"
    bad.write_text("this is not valid JSON or YAML at all!!!", encoding="utf-8")
    with pytest.raises(Exception):
        parse.parse_spec(str(bad))


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------


def test_normalize_produces_uasf(spec_file):
    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    assert uasf.title == "Pets API"
    assert len(uasf.endpoints) == 4


def test_normalize_endpoint_intents(spec_file):
    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    for ep in uasf.endpoints:
        assert ep.intent is not None
        assert ep.domain is not None


# ---------------------------------------------------------------------------
# Analyze (heuristic mode only â€” no LLM calls)
# ---------------------------------------------------------------------------


def test_analyze_heuristic(spec_file):
    from selqor_forge.pipeline import analyze

    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    config = AppConfig().with_anthropic_enabled(False)
    result = analyze.analyze(uasf, config)
    assert result.source == "heuristic"
    assert len(result.tools) > 0


def test_analyze_heuristic_tool_fields(spec_file):
    from selqor_forge.pipeline import analyze

    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    config = AppConfig().with_anthropic_enabled(False)
    result = analyze.analyze(uasf, config)
    for tool in result.tools:
        assert tool.name
        assert isinstance(tool.covered_endpoints, list)
        assert len(tool.covered_endpoints) > 0


# ---------------------------------------------------------------------------
# Curate
# ---------------------------------------------------------------------------


def test_curate_produces_tool_plan(spec_file):
    from selqor_forge.pipeline import analyze

    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    config = AppConfig().with_anthropic_enabled(False)
    analysis = analyze.analyze(uasf, config)
    plan = curate.curate(uasf, config, analysis)
    assert len(plan.tools) >= 1
    assert plan.tools[0].name
    assert plan.tools[0].description


def test_curate_tool_count_does_not_exceed_max(spec_file):
    from selqor_forge.pipeline import analyze

    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    config = AppConfig().with_anthropic_enabled(False)
    analysis = analyze.analyze(uasf, config)
    plan = curate.curate(uasf, config, analysis)
    # A small spec with few endpoints may produce fewer tools than min_tools;
    # but must never exceed max_tools.
    assert 1 <= len(plan.tools) <= config.target_tool_count.max


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


def test_score_output(spec_file):
    from selqor_forge.pipeline import analyze

    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    config = AppConfig().with_anthropic_enabled(False)
    analysis = analyze.analyze(uasf, config)
    plan = curate.curate(uasf, config, analysis)
    report = score.score(uasf, plan)

    assert 0 <= report.score <= 100
    assert 0.0 <= report.coverage <= 1.0
    assert 0.0 <= report.compression_ratio <= 1.0
    assert 0.0 <= report.description_clarity <= 1.0
    assert 0.0 <= report.schema_completeness <= 1.0


# ---------------------------------------------------------------------------
# Generate â€” filesystem artifact output
# ---------------------------------------------------------------------------


def _full_pipeline(spec_file, config):
    from selqor_forge.pipeline import analyze
    parsed = parse.parse_spec(spec_file)
    uasf = normalize.normalize(parsed)
    analysis = analyze.analyze(uasf, config)
    plan = curate.curate(uasf, config, analysis)
    report = score.score(uasf, plan)
    return uasf, analysis, plan, report


def test_generate_ts_artifacts(spec_file, tmp_state_dir):
    config = AppConfig().with_anthropic_enabled(False).with_targets([OutputTarget.TYPESCRIPT])
    uasf, analysis, plan, report = _full_pipeline(spec_file, config)
    out = tmp_state_dir / "ts_output"
    summary = generate.generate(out, uasf, analysis, plan, report, config)

    assert summary.root == out
    assert OutputTarget.TYPESCRIPT in summary.targets

    assert (out / "forge.report.json").exists()
    assert (out / "tool-plan.json").exists()
    assert (out / "uasf.json").exists()
    assert (out / "analysis-plan.json").exists()

    assert (out / "typescript-server" / "package.json").exists()
    assert (out / "typescript-server" / "src" / "index.ts").exists()
    index_source = (out / "typescript-server" / "src" / "index.ts").read_text(encoding="utf-8")
    assert 'join(__dirname, "..", "src", "plan.json")' in index_source


def test_generate_rust_artifacts(spec_file, tmp_state_dir):
    config = AppConfig().with_anthropic_enabled(False).with_targets([OutputTarget.RUST])
    uasf, analysis, plan, report = _full_pipeline(spec_file, config)
    out = tmp_state_dir / "rust_output"
    summary = generate.generate(out, uasf, analysis, plan, report, config)

    assert OutputTarget.RUST in summary.targets
    assert (out / "rust-server" / "Cargo.toml").exists()
    assert (out / "rust-server" / "src" / "main.rs").exists()


def test_generate_both_targets(spec_file, tmp_state_dir):
    config = AppConfig().with_anthropic_enabled(False)
    uasf, analysis, plan, report = _full_pipeline(spec_file, config)
    out = tmp_state_dir / "both_output"
    summary = generate.generate(out, uasf, analysis, plan, report, config)

    assert len(summary.targets) == 2
    assert (out / "typescript-server").exists()
    assert (out / "rust-server").exists()


def test_generate_forge_report_schema(spec_file, tmp_state_dir):
    config = AppConfig().with_anthropic_enabled(False)
    uasf, analysis, plan, report = _full_pipeline(spec_file, config)
    out = tmp_state_dir / "schema_check"
    generate.generate(out, uasf, analysis, plan, report, config)

    with open(out / "forge.report.json") as f:
        data = json.load(f)

    assert "score" in data
    assert "coverage" in data
    assert "compression_ratio" in data
    assert "description_clarity" in data
    assert "schema_completeness" in data


def test_generate_tool_plan_schema(spec_file, tmp_state_dir):
    config = AppConfig().with_anthropic_enabled(False)
    uasf, analysis, plan, report = _full_pipeline(spec_file, config)
    out = tmp_state_dir / "tp_check"
    generate.generate(out, uasf, analysis, plan, report, config)

    with open(out / "tool-plan.json") as f:
        data = json.load(f)

    assert "tools" in data
    assert len(data["tools"]) > 0
    tool = data["tools"][0]
    assert "name" in tool
    assert "description" in tool
    assert "covered_endpoints" in tool


def test_generate_write_json_serializes_datetime_values(tmp_state_dir):
    from pydantic import BaseModel

    class Payload(BaseModel):
        created_at: datetime

    out = tmp_state_dir / "datetime.json"
    payload = Payload(created_at=datetime(2026, 4, 20, 19, 0, tzinfo=timezone.utc))

    generate._write_json(out, payload)

    with open(out, encoding="utf-8") as f:
        data = json.load(f)

    assert data["created_at"] == "2026-04-20T19:00:00Z"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_defaults():
    cfg = AppConfig()
    assert cfg.target_tool_count.min == 5
    assert cfg.target_tool_count.max == 15
    assert OutputTarget.TYPESCRIPT in cfg.output_targets
    assert OutputTarget.RUST in cfg.output_targets


def test_config_load_json(tmp_state_dir):
    cfg_file = tmp_state_dir / "forge.json"
    cfg_file.write_text(json.dumps({"target_tool_count": {"min": 3, "max": 8}}), encoding="utf-8")
    cfg = AppConfig.load(cfg_file)
    assert cfg.target_tool_count.min == 3
    assert cfg.target_tool_count.max == 8


def test_config_with_targets():
    cfg = AppConfig().with_targets([OutputTarget.TYPESCRIPT])
    assert cfg.output_targets == [OutputTarget.TYPESCRIPT]


def test_config_with_transport():
    cfg = AppConfig().with_transport(TransportMode.HTTP)
    assert cfg.default_transport == TransportMode.HTTP


def test_config_with_anthropic_disabled():
    cfg = AppConfig().with_anthropic_enabled(False)
    assert cfg.anthropic.enabled is False

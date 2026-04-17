# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for CLI helper behavior."""

import json

from typer.testing import CliRunner

from selqor_forge.cli import app
from selqor_forge.cli import _resolve_dashboard_llm_config
from selqor_forge.dashboard.context import now_utc_string
from selqor_forge.dashboard.db import init_db
from selqor_forge.dashboard.repositories import LLMConfigRepository
from selqor_forge.dashboard.secrets import DashboardSecretManager


MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Pets API", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List pets",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


def test_resolve_dashboard_llm_config_decrypts_default(tmp_state_dir):
    """CLI generate/benchmark should load dashboard LLM configs with secrets."""
    session_factory = init_db(state_dir=tmp_state_dir)
    assert session_factory is not None

    secret_manager = DashboardSecretManager.from_environment(tmp_state_dir)
    session = session_factory()
    try:
        repo = LLMConfigRepository(session, secret_manager)
        now = now_utc_string()
        repo.upsert(
            "mistral-test",
            name="Mistral Test",
            provider="mistral",
            model="mistral-small-latest",
            base_url="https://api.mistral.ai",
            auth_type="api_key",
            api_key="test-mistral-key",
            custom_headers={},
            is_default=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
    finally:
        session.close()

    runtime = _resolve_dashboard_llm_config(tmp_state_dir)

    assert runtime is not None
    assert runtime.provider == "mistral"
    assert runtime.model == "mistral-small-latest"
    assert runtime.base_url == "https://api.mistral.ai"
    assert runtime.auth_type == "api_key"
    assert runtime.api_key == "test-mistral-key"


def test_generate_without_state_does_not_create_dashboard_dir(tmp_state_dir, monkeypatch):
    spec_path = tmp_state_dir / "pets.json"
    spec_path.write_text(json.dumps(MINIMAL_SPEC), encoding="utf-8")
    monkeypatch.chdir(tmp_state_dir)

    result = CliRunner().invoke(
        app,
        [
            "generate",
            str(spec_path),
            "--out",
            str(tmp_state_dir / "out"),
            "--target",
            "ts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (tmp_state_dir / "dashboard").exists()

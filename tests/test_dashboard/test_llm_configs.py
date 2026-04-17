# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LLM configuration endpoints."""

from selqor_forge.dashboard.repositories import LLMConfigRepository
from selqor_forge.dashboard.secrets import DashboardSecretManager


MASK = "\u2022\u2022\u2022\u2022"


ANTHROPIC_CONFIG = {
    "name": "Anthropic Test",
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "auth_type": "api_key",
    "api_key": "sk-ant-test-key",
    "is_default": False,
    "enabled": True,
}

OPENAI_CONFIG = {
    "name": "OpenAI Test",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "auth_type": "bearer",
    "bearer_token": "sk-test",
    "is_default": False,
    "enabled": True,
}

VLLM_CONFIG = {
    "name": "vLLM Local",
    "provider": "vllm",
    "model": "mistral-7b",
    "base_url": "http://localhost:8000",
    "auth_type": "none",
    "is_default": False,
    "enabled": True,
}


def test_list_providers(client):
    resp = client.get("/api/llm/providers")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    ids = [p["id"] for p in providers]
    assert "anthropic" in ids
    assert "openai" in ids
    assert "vllm" in ids
    assert "gemini" in ids
    assert "mistral" in ids
    assert "aws_bedrock" in ids
    assert "vertex_ai" in ids
    for provider in providers:
        assert "label" in provider
        assert "requires_api_key" in provider
        assert "models" in provider


def test_list_configs_empty(client):
    resp = client.get("/api/llm/configs")
    assert resp.status_code == 200
    assert resp.json()["configs"] == []


def test_create_config(client):
    resp = client.post("/api/llm/configs", json=ANTHROPIC_CONFIG)
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert body["name"] == "Anthropic Test"
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["api_key"] != ANTHROPIC_CONFIG["api_key"]
    assert MASK in body["api_key"]


def test_create_multiple_configs(client):
    client.post("/api/llm/configs", json=ANTHROPIC_CONFIG)
    client.post("/api/llm/configs", json=OPENAI_CONFIG)
    client.post("/api/llm/configs", json=VLLM_CONFIG)
    resp = client.get("/api/llm/configs")
    configs = resp.json()["configs"]
    assert len(configs) == 3
    openai = next(item for item in configs if item["provider"] == "openai")
    assert openai["bearer_token"] != OPENAI_CONFIG["bearer_token"]
    assert MASK in openai["bearer_token"]


def test_set_default(client):
    r1 = client.post("/api/llm/configs", json={**ANTHROPIC_CONFIG, "is_default": False}).json()
    r2 = client.post("/api/llm/configs", json={**OPENAI_CONFIG, "is_default": False}).json()

    resp = client.post(f"/api/llm/configs/{r2['id']}/default")
    assert resp.status_code == 200

    configs = {c["id"]: c for c in client.get("/api/llm/configs").json()["configs"]}
    assert configs[r2["id"]]["is_default"] is True
    assert configs[r1["id"]]["is_default"] is False


def test_set_default_embedding(client):
    cfg = client.post(
        "/api/llm/configs",
        json={
            **ANTHROPIC_CONFIG,
            "embedding_model": "text-embedding-3-small",
        },
    ).json()
    resp = client.post(f"/api/llm/configs/{cfg['id']}/default-embedding")
    assert resp.status_code == 200


def test_delete_config(client):
    cfg = client.post("/api/llm/configs", json=ANTHROPIC_CONFIG).json()
    resp = client.delete(f"/api/llm/configs/{cfg['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    configs = client.get("/api/llm/configs").json()["configs"]
    assert all(config["id"] != cfg["id"] for config in configs)


def test_delete_nonexistent_config(client):
    resp = client.delete("/api/llm/configs/no-such-config")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_llm_logs_empty(client):
    resp = client.get("/api/llm/logs")
    assert resp.status_code == 200
    assert "logs" in resp.json()


def test_llm_test_connection_no_default(client):
    resp = client.post("/api/llm/test-connection", json={})
    assert resp.status_code == 400


def test_llm_test_connection_with_config_id(client):
    cfg = client.post("/api/llm/configs", json=ANTHROPIC_CONFIG).json()
    resp = client.post("/api/llm/test-connection", json={"config_id": cfg["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body
    assert "provider" in body
    assert "tested_at" in body
    assert body["success"] is False
    assert body["error"] is not None


def test_llm_secrets_are_encrypted_at_rest(client):
    cfg = client.post(
        "/api/llm/configs",
        json={
            **ANTHROPIC_CONFIG,
            "custom_headers": {"Authorization": "Bearer test-secret", "X-Tenant": "acme"},
        },
    ).json()

    session = client.app.state.dashboard_ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, client.app.state.dashboard_ctx.secret_manager)
        model = repo.get_by_id(cfg["id"])
        assert model is not None
        assert model.api_key != ANTHROPIC_CONFIG["api_key"]
        assert DashboardSecretManager.is_encrypted(model.api_key)
        assert isinstance(model.custom_headers, str)
        assert DashboardSecretManager.is_encrypted(model.custom_headers)
    finally:
        session.close()

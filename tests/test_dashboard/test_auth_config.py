# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for integration auth configuration and connection testing."""

from selqor_forge.dashboard.repositories import AuthConfigRepository
from selqor_forge.dashboard.secrets import DashboardSecretManager


MASK = "\u2022\u2022\u2022\u2022"


def test_get_auth_defaults(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/auth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_mode"] == "none"
    assert "updated_at" in body


def test_update_auth_bearer(client, integration):
    intg_id = integration["id"]
    resp = client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "bearer",
            "bearer_token": "my-secret-token",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_mode"] == "bearer"
    assert body["bearer_token"] != "my-secret-token"
    assert MASK in body["bearer_token"]


def test_update_auth_api_key(client, integration):
    intg_id = integration["id"]
    resp = client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "api_key",
            "api_key": "key-123",
            "api_key_header": "X-Custom-Key",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_mode"] == "api_key"
    assert body["api_key_header"] == "X-Custom-Key"


def test_update_auth_basic(client, integration):
    intg_id = integration["id"]
    resp = client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "basic",
            "basic_username": "user",
            "basic_password": "pass",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["auth_mode"] == "basic"


def test_update_auth_custom_headers(client, integration):
    intg_id = integration["id"]
    resp = client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "custom_headers",
            "custom_headers": {"X-Tenant": "acme", "X-Version": "v2"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_mode"] == "custom_headers"
    assert body["custom_headers"]["X-Tenant"] == "acme"


def test_auth_persisted_across_requests(client, integration):
    intg_id = integration["id"]
    client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "bearer",
            "bearer_token": "persisted-token",
        },
    )
    resp = client.get(f"/api/integrations/{intg_id}/auth")
    assert resp.json()["bearer_token"] != "persisted-token"
    assert MASK in resp.json()["bearer_token"]


def test_auth_secrets_are_encrypted_at_rest(client, integration):
    intg_id = integration["id"]
    client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "bearer",
            "bearer_token": "persisted-token",
            "custom_headers": {"Authorization": "Bearer test-secret", "X-Tenant": "acme"},
        },
    )

    session = client.app.state.dashboard_ctx.db_session_factory()
    try:
        repo = AuthConfigRepository(session, client.app.state.dashboard_ctx.secret_manager)
        auth = repo.get_by_integration(intg_id)
        assert auth is not None
        assert auth.bearer_token != "persisted-token"
        assert DashboardSecretManager.is_encrypted(auth.bearer_token)
        assert isinstance(auth.custom_headers, str)
        assert DashboardSecretManager.is_encrypted(auth.custom_headers)
    finally:
        session.close()


def test_test_connection(client, integration):
    intg_id = integration["id"]
    client.put(
        f"/api/integrations/{intg_id}/auth",
        json={
            "auth_mode": "none",
            "base_url": "https://petstore3.swagger.io",
        },
    )
    resp = client.post(f"/api/integrations/{intg_id}/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body
    assert "latency_ms" in body
    assert "message" in body
    assert "tested_at" in body


def test_test_connection_no_base_url(client):
    resp = client.post(
        "/api/integrations",
        json={
            "name": "Local Spec",
            "spec": "/local/path/to/spec.json",
        },
    )
    intg_id = resp.json()["id"]
    resp = client.post(f"/api/integrations/{intg_id}/test-connection")
    assert resp.status_code == 400


def test_auth_for_missing_integration(client):
    resp = client.get("/api/integrations/ghost-id/auth")
    assert resp.status_code == 404

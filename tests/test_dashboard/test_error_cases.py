# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for error handling and edge cases across the API."""


# ---------------------------------------------------------------------------
# 404 â€” unknown resource IDs (routes that explicitly check existence)
# ---------------------------------------------------------------------------


def test_get_auth_for_missing_integration(client):
    resp = client.get("/api/integrations/does-not-exist/auth")
    assert resp.status_code == 404


def test_get_tooling_for_missing_integration(client):
    resp = client.get("/api/integrations/does-not-exist/tooling")
    assert resp.status_code == 404


def test_run_job_status_not_found(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/run-jobs/no-such-job/status")
    assert resp.status_code == 404


def test_artifact_not_found_for_unknown_run(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/no-run/artifact/run.json")
    assert resp.status_code == 404


def test_delete_nonexistent_integration(client):
    resp = client.delete("/api/integrations/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Routes that return empty results (not 404) for unknown integration IDs
# ---------------------------------------------------------------------------


def test_get_runs_for_missing_integration_returns_empty(client):
    """list_runs returns 200 with empty list for unknown integration IDs."""
    resp = client.get("/api/integrations/does-not-exist/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []


def test_get_deployments_for_missing_integration_returns_empty(client):
    """list_deployments returns 200 with empty list for unknown integration IDs."""
    resp = client.get("/api/integrations/does-not-exist/deployments")
    assert resp.status_code == 200
    assert resp.json()["deployments"] == []


# ---------------------------------------------------------------------------
# Delete idempotency â€” no error on missing resources
# ---------------------------------------------------------------------------


def test_delete_nonexistent_llm_config_is_idempotent(client):
    """Deleting a non-existent LLM config returns 200 (idempotent)."""
    resp = client.delete("/api/llm/configs/does-not-exist")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# 400 â€” manual validation in routes (not pydantic 422)
# ---------------------------------------------------------------------------


def test_create_integration_missing_name(client):
    """Empty name triggers 400 from manual validation."""
    resp = client.post("/api/integrations", json={"spec": "https://example.com/api.json"})
    assert resp.status_code == 400


def test_create_integration_missing_spec(client):
    """Empty spec triggers 400 from manual validation."""
    resp = client.post("/api/integrations", json={"name": "No spec"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 422 â€” pydantic validation errors
# ---------------------------------------------------------------------------


def test_put_tooling_invalid_type(client, integration):
    intg_id = integration["id"]
    resp = client.put(f"/api/integrations/{intg_id}/tooling", json={"tools": "not-a-list"})
    assert resp.status_code == 422


def test_malformed_json_body(client):
    resp = client.post(
        "/api/integrations",
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Path traversal â€” safe ID checks
# ---------------------------------------------------------------------------


def test_artifact_path_traversal_rejected(client, integration):
    intg_id = integration["id"]
    resp = client.get(
        f"/api/integrations/{intg_id}/runs/some-run/artifact/../../etc/passwd"
    )
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# 400 â€” bad report format (only when run exists)
# ---------------------------------------------------------------------------


def test_invalid_report_format_returns_404_when_no_run(client, integration):
    """Report endpoint returns 404 (no run) before checking format."""
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/no-run/report/xlsx")
    assert resp.status_code == 404

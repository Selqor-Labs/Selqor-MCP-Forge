# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for run management, artifacts, reports, and deployment."""


def test_trigger_run_returns_202(client, integration):
    intg_id = integration["id"]
    resp = client.post(f"/api/integrations/{intg_id}/run", json={"mode": "llm"})
    assert resp.status_code == 202
    body = resp.json()
    assert "job" in body
    job = body["job"]
    assert "job_id" in job
    assert "run_id" in job
    assert job["status"] in ("queued", "running", "completed")


def test_list_runs_empty_before_run(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []


def test_completed_run_record(client, completed_run):
    assert completed_run["status"] == "ok"
    assert completed_run["score"] is not None
    assert completed_run["tool_count"] is not None
    assert completed_run["endpoint_count"] is not None
    assert completed_run["analysis_source"] in (
        "anthropic", "openai", "vllm", "sarvam", "mistral", "gemini",
        "aws_bedrock", "vertex_ai", "heuristic",
    )


def test_run_artifacts_list(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifacts")
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert "forge.report.json" in artifacts
    assert "tool-plan.json" in artifacts
    assert "uasf.json" in artifacts
    assert "analysis-plan.json" in artifacts
    assert "run.json" in artifacts


def test_get_forge_report(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifact/forge.report.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "score" in body
    assert "coverage" in body
    assert "compression_ratio" in body
    assert "description_clarity" in body
    assert "schema_completeness" in body
    assert 0 <= body["score"] <= 100
    assert 0.0 <= body["coverage"] <= 1.0


def test_get_tool_plan(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifact/tool-plan.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "tools" in body
    assert len(body["tools"]) > 0
    tool = body["tools"][0]
    assert "name" in tool
    assert "description" in tool
    assert "covered_endpoints" in tool


def test_get_uasf(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifact/uasf.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "endpoints" in body
    assert len(body["endpoints"]) > 0


def test_get_run_json(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifact/run.json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["run_id"] == run_id


def test_artifact_not_found(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/artifact/does-not-exist.json")
    assert resp.status_code == 404


def test_csv_report(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/report/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.text
    assert "run_id" in text or run_id in text


def test_pdf_report(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/report/pdf")
    assert resp.status_code == 200
    assert "application/pdf" in resp.headers["content-type"]
    # PDF magic bytes
    assert resp.content[:4] == b"%PDF"


def test_invalid_report_format(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.get(f"/api/integrations/{intg_id}/runs/{run_id}/report/xlsx")
    assert resp.status_code == 400


def test_deploy_typescript(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.post(f"/api/integrations/{intg_id}/runs/{run_id}/deploy", json={
        "target": "typescript",
        "transport": "stdio",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "typescript"
    assert body["status"] == "prepared"
    assert "server_path" in body
    assert "command" in body
    assert "deployment_id" in body


def test_deploy_rust(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.post(f"/api/integrations/{intg_id}/runs/{run_id}/deploy", json={
        "target": "rust",
        "transport": "stdio",
    })
    assert resp.status_code == 200
    assert resp.json()["target"] == "rust"


def test_deploy_http_transport(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    resp = client.post(f"/api/integrations/{intg_id}/runs/{run_id}/deploy", json={
        "target": "typescript",
        "transport": "http",
        "http_port": 4000,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "typescript"


def test_list_deployments(client, integration, completed_run):
    intg_id = integration["id"]
    run_id = completed_run["run_id"]
    client.post(f"/api/integrations/{intg_id}/runs/{run_id}/deploy", json={"target": "typescript"})
    resp = client.get(f"/api/integrations/{intg_id}/deployments")
    assert resp.status_code == 200
    deployments = resp.json()["deployments"]
    assert len(deployments) >= 1
    assert deployments[0]["integration_id"] == intg_id


def test_job_status_polling(client, integration):
    intg_id = integration["id"]
    resp = client.post(f"/api/integrations/{intg_id}/run", json={})
    job_id = resp.json()["job"]["job_id"]
    status_resp = client.get(f"/api/integrations/{intg_id}/run-jobs/{job_id}/status")
    assert status_resp.status_code == 200
    assert "job" in status_resp.json()
    assert status_resp.json()["job"]["job_id"] == job_id


def test_job_status_not_found(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/run-jobs/no-such-job/status")
    assert resp.status_code == 404


def test_run_for_missing_integration(client):
    # Run endpoint doesn't pre-validate integration existence (accepts any valid token)
    resp = client.post("/api/integrations/ghost/run", json={})
    assert resp.status_code == 202

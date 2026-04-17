# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for CI/CD routes: config generation, webhooks, badge."""

import hashlib
import hmac
import json


def test_generate_github_actions(client):
    resp = client.post("/api/cicd/generate", json={
        "targets": ["github_actions"],
        "branches": ["main"],
        "scan_threshold": 80,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "github_actions" in body["files"]
    content = body["files"]["github_actions"]["content"]
    assert "Selqor Forge Security Scan" in content
    assert "selqor-forge" in content
    assert "threshold" in content.lower()


def test_generate_gitlab_ci(client):
    resp = client.post("/api/cicd/generate", json={
        "targets": ["gitlab_ci"],
    })
    assert resp.status_code == 200
    assert "gitlab_ci" in resp.json()["files"]


def test_generate_pre_commit(client):
    resp = client.post("/api/cicd/generate", json={
        "targets": ["pre_commit"],
    })
    assert resp.status_code == 200
    content = resp.json()["files"]["pre_commit"]["content"]
    assert "pre-commit-config.yaml" in resp.json()["files"]["pre_commit"]["filename"]
    assert "selqor-forge" in content


def test_generate_invalid_targets_falls_back_to_default(client):
    """Invalid target names get filtered; fallback to github_actions via resolved_targets."""
    resp = client.post("/api/cicd/generate", json={
        "targets": ["invalid_target_name"],
    })
    # resolved_targets() falls back to ["github_actions"] when targets is empty
    assert resp.status_code == 200
    assert "github_actions" in resp.json()["files"]


def test_list_templates(client):
    resp = client.get("/api/cicd/templates")
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    ids = [t["id"] for t in templates]
    assert "github_actions" in ids
    assert "gitlab_ci" in ids
    assert "pre_commit" in ids


def test_webhook_register_and_list(client):
    resp = client.post("/api/cicd/webhooks/register", json={
        "project_name": "test-project",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_name"] == "test-project"
    assert "webhook_secret" in body
    assert body["webhook_url"] == "/api/cicd/webhooks/ingest"

    # List
    listed = client.get("/api/cicd/webhooks").json()
    assert listed["total"] == 1
    assert listed["projects"][0]["project_name"] == "test-project"


def test_webhook_ingest_records_run(client):
    # Register first
    reg = client.post("/api/cicd/webhooks/register", json={
        "project_name": "my-app",
    }).json()
    secret = reg["webhook_secret"]

    # Build signed payload
    payload = json.dumps({
        "project_name": "my-app",
        "score": 85,
        "findings_count": 3,
        "branch": "main",
        "commit_sha": "abc123",
        "ci_provider": "github_actions",
        "duration_seconds": 42,
        "risk_level": "low",
        "threshold": 70,
        "severity_counts": {"high": 0, "medium": 2, "low": 1},
    }).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/cicd/webhooks/ingest",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Selqor-Signature": f"sha256={sig}",
        },
    )
    assert resp.status_code == 200
    run = resp.json()["run"]
    assert run["project_name"] == "my-app"
    assert run["score"] == 85
    assert run["status"] == "pass"
    assert run["findings_count"] == 3


def test_webhook_ingest_bad_signature(client):
    client.post("/api/cicd/webhooks/register", json={
        "project_name": "secure-app",
    })

    payload = json.dumps({"project_name": "secure-app", "score": 50}).encode()
    resp = client.post(
        "/api/cicd/webhooks/ingest",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Selqor-Signature": "sha256=invalid_signature",
        },
    )
    assert resp.status_code == 403


def test_ci_runs_list_and_stats(client):
    # Ingest a run without registration (auto-registers)
    payload = json.dumps({
        "project_name": "auto-project",
        "score": 90,
        "findings_count": 1,
    }).encode()
    client.post(
        "/api/cicd/webhooks/ingest",
        content=payload,
        headers={"Content-Type": "application/json"},
    )

    # List runs
    runs = client.get("/api/cicd/runs").json()
    assert runs["total"] >= 1

    # Stats
    stats = client.get("/api/cicd/runs/stats").json()
    assert stats["total_runs"] >= 1
    assert stats["pass_rate"] > 0


def test_badge_returns_svg(client):
    # Ingest a run
    payload = json.dumps({
        "project_name": "badge-test",
        "score": 95,
        "findings_count": 0,
    }).encode()
    client.post(
        "/api/cicd/webhooks/ingest",
        content=payload,
        headers={"Content-Type": "application/json"},
    )

    resp = client.get("/api/cicd/badge/badge-test")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert "<svg" in resp.text
    assert "95" in resp.text and "/100" in resp.text


def test_badge_no_data(client):
    resp = client.get("/api/cicd/badge/nonexistent")
    assert resp.status_code == 200
    assert "no data" in resp.text


def test_webhook_delete(client):
    client.post("/api/cicd/webhooks/register", json={
        "project_name": "to-delete",
    })

    resp = client.delete("/api/cicd/webhooks/to-delete")
    assert resp.status_code == 200

    resp = client.delete("/api/cicd/webhooks/to-delete")
    assert resp.status_code == 404

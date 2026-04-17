# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for integration CRUD endpoints."""

import json

from fastapi.testclient import TestClient

from selqor_forge.config import AppConfig
from selqor_forge.dashboard.app import create_app
from selqor_forge.dashboard.context import IntegrationRecord, now_utc_string
from selqor_forge.dashboard.repositories import IntegrationRepository


def test_list_integrations_empty(client):
    resp = client.get("/api/integrations")
    assert resp.status_code == 200
    assert resp.json() == {"integrations": []}


def test_create_integration(client):
    resp = client.post("/api/integrations", json={
        "name": "My API",
        "spec": "https://petstore3.swagger.io/api/v3/openapi.json",
        "tags": ["demo"],
        "notes": "Test integration",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["name"] == "My API"
    assert body["tags"] == ["demo"]
    assert body["notes"] == "Test integration"
    assert "created_at" in body


def test_list_integrations_after_create(client, integration):
    resp = client.get("/api/integrations")
    assert resp.status_code == 200
    items = resp.json()["integrations"]
    assert len(items) == 1
    assert items[0]["id"] == integration["id"]


def test_create_requires_name(client):
    # name defaults to "" â€” manual validation returns 400 (not pydantic 422)
    resp = client.post("/api/integrations", json={"spec": "https://example.com/api.json"})
    assert resp.status_code == 400


def test_create_requires_spec(client):
    resp = client.post("/api/integrations", json={"name": "No spec"})
    assert resp.status_code == 400


def test_create_rejects_duplicate_name_and_spec(client, integration):
    resp = client.post("/api/integrations", json={
        "name": integration["name"],
        "spec": integration["spec"],
    })
    assert resp.status_code == 409


def test_list_integrations_collapses_duplicate_records(client):
    session = client.app.state.dashboard_ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        repo.create(IntegrationRecord(
            id="petstore-old",
            name="Petstore",
            spec="https://petstore3.swagger.io/api/v3/openapi.json",
            created_at="2026-04-07T08:00:00Z",
            tags=["legacy"],
        ))
        repo.create(IntegrationRecord(
            id="petstore-new",
            name="Petstore",
            spec="https://petstore3.swagger.io/api/v3/openapi.json",
            created_at="2026-04-07T09:00:00Z",
            tags=["test"],
        ))
        repo.create(IntegrationRecord(
            id="twilio-one",
            name="Twilio",
            spec="https://example.com/twilio.json",
            created_at=now_utc_string(),
        ))
    finally:
        session.close()

    resp = client.get("/api/integrations")
    assert resp.status_code == 200
    items = resp.json()["integrations"]
    assert len(items) == 2
    petstore = next(item for item in items if item["name"] == "Petstore")
    assert petstore["id"] == "petstore-new"
    assert set(petstore["tags"]) == {"legacy", "test"}


def test_delete_integration(client, integration):
    intg_id = integration["id"]
    resp = client.delete(f"/api/integrations/{intg_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["deleted"] == 1

    # Confirm it's gone
    remaining = client.get("/api/integrations").json()["integrations"]
    assert all(i["id"] != intg_id for i in remaining)


def test_delete_integration_removes_duplicate_group(client):
    session = client.app.state.dashboard_ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        repo.create(IntegrationRecord(
            id="local-spec-old",
            name="Local Spec",
            spec="/local/path/to/spec.json",
            created_at="2026-04-07T08:00:00Z",
        ))
        repo.create(IntegrationRecord(
            id="local-spec-new",
            name="Local Spec",
            spec="/local/path/to/spec.json",
            created_at="2026-04-07T09:00:00Z",
        ))
        repo.create(IntegrationRecord(
            id="pet-store-test",
            name="Pet store test",
            spec="https://petstore.swagger.io/v2/swagger.json",
            created_at=now_utc_string(),
        ))
    finally:
        session.close()

    resp = client.delete("/api/integrations/local-spec-new")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["deleted"] == 2

    remaining = client.get("/api/integrations").json()["integrations"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == "pet-store-test"


def test_delete_nonexistent_integration(client):
    resp = client.delete("/api/integrations/does-not-exist")
    assert resp.status_code == 404


def test_dashboard_summary(client, integration):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert "totals" in body
    assert "activity" in body
    assert "integrations" in body
    assert "recent_runs" in body
    totals = body["totals"]
    assert totals["integrations"] >= 1
    assert "runs" in totals
    assert "success_rate" in totals
    assert "warning_runs" in totals
    assert isinstance(body["activity"], list)
    assert isinstance(body["integrations"], list)


def test_dashboard_collapses_duplicate_integrations(client):
    session = client.app.state.dashboard_ctx.db_session_factory()
    try:
        repo = IntegrationRepository(session)
        repo.create(IntegrationRecord(
            id="petstore-old",
            name="Petstore",
            spec="https://petstore3.swagger.io/api/v3/openapi.json",
            created_at="2026-04-07T08:00:00Z",
            tags=["legacy"],
        ))
        repo.create(IntegrationRecord(
            id="petstore-new",
            name="Petstore",
            spec="https://petstore3.swagger.io/api/v3/openapi.json",
            created_at="2026-04-07T09:00:00Z",
            tags=["test"],
        ))
    finally:
        session.close()

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["integrations"] == 1
    assert len(body["integrations"]) == 1
    assert body["integrations"][0]["id"] == "petstore-new"


def test_dashboard_summary_falls_back_to_legacy_files(tmp_state_dir):
    (tmp_state_dir / "selqor-forge.db").write_text("", encoding="utf-8")

    integrations_payload = {
        "integrations": [
            {
                "id": "legacy-petstore",
                "name": "Legacy Petstore",
                "spec": "https://example.com/openapi.json",
                "created_at": "2026-04-04T18:01:00Z",
                "notes": None,
                "tags": ["legacy"],
                "last_run": {
                    "run_id": "1775325689586",
                    "status": "ok",
                    "created_at": "2026-04-04T18:01:29Z",
                    "score": 100,
                    "tool_count": 6,
                    "endpoint_count": 20,
                    "compression_ratio": 0.25,
                    "coverage": 1.0,
                    "analysis_source": "heuristic",
                    "warnings": ["Legacy warning"],
                    "error": None,
                },
            }
        ]
    }
    (tmp_state_dir / "integrations.json").write_text(
        json.dumps(integrations_payload),
        encoding="utf-8",
    )

    run_dir = tmp_state_dir / "runs" / "legacy-petstore" / "1775325689586"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": "1775325689586",
                "status": "ok",
                "created_at": "2026-04-04T18:01:29Z",
                "integration_id": "legacy-petstore",
                "integration_name": "Legacy Petstore",
                "spec": "https://example.com/openapi.json",
                "analysis_source": "heuristic",
                "model": None,
                "score": 100,
                "tool_count": 6,
                "endpoint_count": 20,
                "compression_ratio": 0.25,
                "coverage": 1.0,
                "warnings": ["Legacy warning"],
                "error": None,
                "artifacts": ["forge.report.json"],
            }
        ),
        encoding="utf-8",
    )

    app = create_app(tmp_state_dir, AppConfig())
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get("/api/dashboard")

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["integrations"] == 1
    assert body["totals"]["runs"] == 1
    assert body["totals"]["tools"] == 6
    assert body["totals"]["endpoints"] == 20
    assert body["recent_runs"][0]["integration_id"] == "legacy-petstore"

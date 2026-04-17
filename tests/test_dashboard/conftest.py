# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard test fixtures: TestClient + seeded local-spec state."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from selqor_forge.config import AppConfig
from selqor_forge.dashboard.app import create_app

MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Pets API", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "responses": {"200": {"description": "A list of pets"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
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
            }
        },
    },
}


@pytest.fixture()
def client(tmp_state_dir):
    """Return a TestClient with a clean filesystem-only state."""
    app = create_app(tmp_state_dir, AppConfig())
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def integration(client, tmp_state_dir):
    """Create a local-spec integration and return its record."""
    spec_path = tmp_state_dir / "petstore-local.json"
    spec_path.write_text(json.dumps(MINIMAL_SPEC), encoding="utf-8")
    resp = client.post(
        "/api/integrations",
        json={
            "name": "Petstore",
            "spec": str(spec_path),
            "tags": ["test"],
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def completed_run(client, integration):
    """Trigger a run on the Petstore integration and wait for completion."""
    intg_id = integration["id"]
    resp = client.post(f"/api/integrations/{intg_id}/run", json={"mode": "llm"})
    assert resp.status_code == 202
    job_id = resp.json()["job"]["job_id"]

    for _ in range(30):
        status_resp = client.get(f"/api/integrations/{intg_id}/run-jobs/{job_id}/status")
        status = status_resp.json()["job"]["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(2)

    assert status == "completed", f"Run did not complete: {status}"
    runs = client.get(f"/api/integrations/{intg_id}/runs").json()["runs"]
    return runs[0]

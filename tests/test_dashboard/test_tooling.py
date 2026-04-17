# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for integration tooling CRUD endpoints."""


SAMPLE_TOOLS = [
    {
        "name": "list_pets",
        "description": "List all pets in the store",
        "covered_endpoints": ["get_pets"],
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        "confidence": 0.9,
    },
    {
        "name": "create_pet",
        "description": "Add a new pet to the store",
        "covered_endpoints": ["post_pets"],
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        "confidence": 0.95,
    },
]


def test_get_tooling_default(client, integration):
    intg_id = integration["id"]
    resp = client.get(f"/api/integrations/{intg_id}/tooling")
    assert resp.status_code == 200
    body = resp.json()
    assert "source" in body
    assert "tools" in body


def test_put_tooling(client, integration):
    intg_id = integration["id"]
    resp = client.put(f"/api/integrations/{intg_id}/tooling", json={"tools": SAMPLE_TOOLS})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "manual"
    assert len(body["tools"]) == 2
    assert body["tools"][0]["name"] == "list_pets"


def test_tooling_persisted(client, integration):
    intg_id = integration["id"]
    client.put(f"/api/integrations/{intg_id}/tooling", json={"tools": SAMPLE_TOOLS})
    resp = client.get(f"/api/integrations/{intg_id}/tooling")
    assert resp.status_code == 200
    assert resp.json()["source"] == "manual"
    assert len(resp.json()["tools"]) == 2


def test_delete_tooling(client, integration):
    intg_id = integration["id"]
    # First set manual tooling
    client.put(f"/api/integrations/{intg_id}/tooling", json={"tools": SAMPLE_TOOLS})
    # Then delete it
    resp = client.delete(f"/api/integrations/{intg_id}/tooling")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # Should revert to default/generated source
    resp = client.get(f"/api/integrations/{intg_id}/tooling")
    assert resp.json()["source"] != "manual"


def test_tooling_requires_tools_list(client, integration):
    intg_id = integration["id"]
    resp = client.put(f"/api/integrations/{intg_id}/tooling", json={"tools": "not-a-list"})
    assert resp.status_code == 422


def test_tooling_for_missing_integration(client):
    resp = client.get("/api/integrations/ghost-id/tooling")
    assert resp.status_code == 404

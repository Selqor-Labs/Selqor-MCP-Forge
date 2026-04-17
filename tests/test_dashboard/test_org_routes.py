# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for organisation management endpoints."""


def test_org_check_no_db(client):
    """Without DB, check endpoint reports both available."""
    resp = client.get("/api/organizations/check", params={"name": "Acme", "slug": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name_available"] is True
    assert body["slug_available"] is True


def test_org_check_empty_params(client):
    """Check endpoint handles missing query params gracefully."""
    resp = client.get("/api/organizations/check")
    assert resp.status_code == 200
    body = resp.json()
    assert "name_available" in body
    assert "slug_available" in body


def test_create_org_requires_auth(client):
    """POST /organizations returns 501 (auth not integrated) in test mode."""
    resp = client.post("/api/organizations", json={"name": "Acme Inc", "slug": "acme"})
    assert resp.status_code == 501


def test_create_org_requires_auth_with_valid_body(client):
    """Even with a valid payload, 501 is returned without auth."""
    resp = client.post("/api/organizations", json={
        "name": "Valid Corp",
        "slug": "valid-corp",
    })
    assert resp.status_code == 501

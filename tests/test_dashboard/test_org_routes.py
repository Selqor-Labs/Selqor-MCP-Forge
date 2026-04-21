# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for organization endpoints in the local-only public build."""


def test_org_check_is_disabled(client):
    """Organization endpoints are disabled in the public local-only build."""
    resp = client.get("/api/organizations/check", params={"name": "Acme", "slug": "acme"})
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "organizations"


def test_org_check_empty_params(client):
    """The disabled response is stable even without query params."""
    resp = client.get("/api/organizations/check")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "organizations"


def test_create_org_requires_local_only_error(client):
    """POST /organizations returns the shared-feature-disabled response."""
    resp = client.post("/api/organizations", json={"name": "Acme Inc", "slug": "acme"})
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "organizations"

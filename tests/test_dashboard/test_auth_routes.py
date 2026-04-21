# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for auth-related API endpoints in the local-only public build."""


def test_auth_config_always_200(client):
    resp = client.get("/api/auth/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["provider"] == "local_only"
    assert body["local_only"] is True
    assert body["organizations_enabled"] is False
    assert "message" in body


def test_auth_me_is_disabled_in_local_only_build(client):
    """Shared-user auth surfaces return an explicit local-only error."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 501
    body = resp.json()
    assert body["detail"]["detail"] == "LOCAL_ONLY_BUILD"
    assert body["detail"]["feature"] == "auth"


def test_auth_context_is_disabled_in_local_only_build(client):
    """Shared auth context is disabled in the public local-only build."""
    resp = client.get("/api/auth/context")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "auth"


def test_onboarding_status_is_disabled(client):
    """Onboarding is disabled in the public local-only build."""
    resp = client.get("/api/users/me/onboarding-status")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "onboarding"


def test_pending_invites_are_disabled(client):
    """Team invites are disabled in the public local-only build."""
    resp = client.get("/api/users/me/pending-invites")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "team_invites"


def test_accept_invite_is_disabled(client):
    """Accept invite returns a local-only disabled response."""
    resp = client.post("/api/users/me/invites/some-invite-id/accept")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "team_invites"


def test_decline_invite_is_disabled(client):
    """Decline invite returns a local-only disabled response."""
    resp = client.post("/api/users/me/invites/some-invite-id/decline")
    assert resp.status_code == 501
    assert resp.json()["detail"]["feature"] == "team_invites"

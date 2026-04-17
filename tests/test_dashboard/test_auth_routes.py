# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for auth-related API endpoints.

Authentication is disabled — the dashboard is fully open. These tests
verify the anonymous/open-access behaviour of all auth endpoints.
"""


def test_auth_config_always_200(client):
    resp = client.get("/api/auth/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["provider"] == "anonymous"
    assert "message" in body


def test_auth_me_returns_anonymous(client):
    """Without auth, /auth/me returns anonymous user profile."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "anonymous"
    assert body["auth_enabled"] is False
    assert body["role"] == "admin"


def test_auth_context_returns_anonymous(client):
    """Without auth, /auth/context returns anonymous context."""
    resp = client.get("/api/auth/context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "anonymous"
    assert body["auth_enabled"] is False


def test_onboarding_status_returns_ok(client):
    """Without auth, onboarding-status returns a valid response."""
    resp = client.get("/api/users/me/onboarding-status")
    assert resp.status_code == 200
    body = resp.json()
    assert "needs_onboarding" in body
    assert body["has_organizations"] is True


def test_pending_invites_returns_empty(client):
    """Without auth, pending-invites returns an empty list."""
    resp = client.get("/api/users/me/pending-invites")
    assert resp.status_code == 200
    assert resp.json() == []


def test_accept_invite_returns_404(client):
    """Accept invite always returns 404 (no invitations exist)."""
    resp = client.post("/api/users/me/invites/some-invite-id/accept")
    assert resp.status_code == 404


def test_decline_invite_returns_404(client):
    """Decline invite always returns 404 (no invitations exist)."""
    resp = client.post("/api/users/me/invites/some-invite-id/decline")
    assert resp.status_code == 404

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for settings routes in the public local-only build."""

from selqor_forge.dashboard.repositories import (
    TeamInviteRepository,
    TeamSettingsRepository,
    UserPreferencesRepository,
)


def test_preferences_defaults_match_frontend_choices(client):
    resp = client.get("/api/settings/preferences")

    assert resp.status_code == 200
    assert resp.json()["theme"] == "light"
    assert resp.json()["default_scan_mode"] == "basic"


def test_preferences_coerce_legacy_values(client):
    ctx = client.app.state.dashboard_ctx
    session = ctx.db_session_factory()
    try:
        UserPreferencesRepository(session).upsert(theme="system", default_scan_mode="standard")
    finally:
        session.close()

    resp = client.get("/api/settings/preferences")

    assert resp.status_code == 200
    assert resp.json()["theme"] == "light"
    assert resp.json()["default_scan_mode"] == "basic"


def test_export_hides_team_and_invites_in_local_only_build(client):
    ctx = client.app.state.dashboard_ctx
    session = ctx.db_session_factory()
    try:
        TeamSettingsRepository(session).upsert(
            name="Private Team",
            members=[{"email": "owner@example.com"}],
            settings={"visibility": "private"},
        )
        TeamInviteRepository(session).create(
            id="invite-1",
            email="member@example.com",
            role="admin",
            status="pending",
            created_at="2026-04-20T00:00:00Z",
        )
    finally:
        session.close()

    resp = client.get("/api/settings/export")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["team"]["status"] == "disabled"
    assert data["team"]["reason"] == "LOCAL_ONLY_BUILD"
    assert data["team"]["feature"] == "team_management"
    assert data["invites"] == []

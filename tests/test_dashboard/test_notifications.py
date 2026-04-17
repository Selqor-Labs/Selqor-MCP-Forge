# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for notification channel CRUD and delivery logging."""


def test_list_channels_empty(client):
    resp = client.get("/api/notifications/channels")
    assert resp.status_code == 200
    assert resp.json()["channels"] == []


def test_create_webhook_channel(client):
    resp = client.post("/api/notifications/channels", json={
        "name": "Ops Webhook",
        "channel_type": "webhook",
        "config": {"url": "https://hooks.example.com/notify"},
    })
    assert resp.status_code == 200
    ch = resp.json()
    assert ch["name"] == "Ops Webhook"
    assert ch["channel_type"] == "webhook"
    assert ch["enabled"] is True
    assert ch["config"]["url"] == "https://hooks.example.com/notify"


def test_create_slack_channel(client):
    resp = client.post("/api/notifications/channels", json={
        "name": "Slack Alerts",
        "channel_type": "slack",
        "config": {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
    })
    assert resp.status_code == 200
    assert resp.json()["channel_type"] == "slack"


def test_create_invalid_channel_type(client):
    resp = client.post("/api/notifications/channels", json={
        "name": "Bad",
        "channel_type": "telegram",
        "config": {},
    })
    assert resp.status_code == 400


def test_update_channel(client):
    ch = client.post("/api/notifications/channels", json={
        "name": "Original",
        "channel_type": "webhook",
        "config": {"url": "https://old.example.com"},
    }).json()

    resp = client.patch(f"/api/notifications/channels/{ch['id']}", json={
        "name": "Updated",
        "enabled": False,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"
    assert resp.json()["enabled"] is False


def test_delete_channel(client):
    ch = client.post("/api/notifications/channels", json={
        "name": "Temp",
        "channel_type": "email",
        "config": {},
    }).json()

    resp = client.delete(f"/api/notifications/channels/{ch['id']}")
    assert resp.status_code == 200

    resp = client.delete(f"/api/notifications/channels/{ch['id']}")
    assert resp.status_code == 404


def test_notification_logs_empty(client):
    resp = client.get("/api/notifications/logs")
    assert resp.status_code == 200
    assert resp.json()["logs"] == []

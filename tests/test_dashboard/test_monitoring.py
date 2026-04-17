# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for monitoring routes: scheduler, alerts, notifications."""

def test_list_servers_empty(client):
    resp = client.get("/api/monitoring/servers")
    assert resp.status_code == 200
    assert resp.json()["servers"] == []


def test_add_server(client):
    resp = client.post("/api/monitoring/servers", json={
        "name": "Test MCP",
        "url": "http://localhost:3333",
        "check_interval_seconds": 60,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Test MCP"
    assert body["url"] == "http://localhost:3333"
    assert body["status"] == "unknown"
    assert body["check_interval_seconds"] == 60


def test_add_server_invalid_url(client):
    resp = client.post("/api/monitoring/servers", json={
        "name": "Bad URL",
        "url": "not-a-url",
    })
    assert resp.status_code == 422


def test_update_server(client):
    create = client.post("/api/monitoring/servers", json={
        "name": "Original",
        "url": "http://localhost:3333",
    })
    server_id = create.json()["id"]

    resp = client.patch(f"/api/monitoring/servers/{server_id}", json={
        "name": "Updated",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


def test_delete_server(client):
    create = client.post("/api/monitoring/servers", json={
        "name": "Temp",
        "url": "http://localhost:3333",
    })
    server_id = create.json()["id"]

    resp = client.delete(f"/api/monitoring/servers/{server_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == server_id

    # Verify gone
    servers = client.get("/api/monitoring/servers").json()["servers"]
    assert all(s["id"] != server_id for s in servers)


def test_create_alert_rule(client):
    server = client.post("/api/monitoring/servers", json={
        "name": "Test",
        "url": "http://localhost:3333",
    }).json()

    resp = client.post(f"/api/monitoring/servers/{server['id']}/alerts", json={
        "name": "High Latency",
        "condition": "latency_above",
        "threshold": 500,
    })
    assert resp.status_code == 200
    rule = resp.json()
    assert rule["name"] == "High Latency"
    assert rule["condition"] == "latency_above"
    assert rule["threshold"] == 500
    assert rule["enabled"] is True


def test_create_alert_rule_invalid_condition(client):
    server = client.post("/api/monitoring/servers", json={
        "name": "Test",
        "url": "http://localhost:3333",
    }).json()

    resp = client.post(f"/api/monitoring/servers/{server['id']}/alerts", json={
        "name": "Bad",
        "condition": "invalid_condition",
        "threshold": 100,
    })
    assert resp.status_code == 422


def test_list_alert_rules(client):
    server = client.post("/api/monitoring/servers", json={
        "name": "Test",
        "url": "http://localhost:3333",
    }).json()

    client.post(f"/api/monitoring/servers/{server['id']}/alerts", json={
        "name": "Rule A",
        "condition": "latency_above",
        "threshold": 1000,
    })
    client.post(f"/api/monitoring/servers/{server['id']}/alerts", json={
        "name": "Rule B",
        "condition": "status_unhealthy",
        "threshold": 1,
    })

    resp = client.get(f"/api/monitoring/servers/{server['id']}/alerts")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_delete_alert_rule(client):
    server = client.post("/api/monitoring/servers", json={
        "name": "Test",
        "url": "http://localhost:3333",
    }).json()

    rule = client.post(f"/api/monitoring/servers/{server['id']}/alerts", json={
        "name": "Temp Rule",
        "condition": "consecutive_failures",
        "threshold": 3,
    }).json()

    resp = client.delete(f"/api/monitoring/servers/{server['id']}/alerts/{rule['id']}")
    assert resp.status_code == 200


def test_list_fired_alerts_empty(client):
    resp = client.get("/api/monitoring/alerts")
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []


def test_scheduler_status_initially_not_running(client):
    resp = client.get("/api/monitoring/scheduler/status")
    assert resp.status_code == 200
    # May be running from auto-start, just verify structure
    body = resp.json()
    assert "running" in body


def test_scheduler_start_and_stop(client):
    start = client.post("/api/monitoring/scheduler/start")
    assert start.status_code == 200
    assert start.json()["status"] in ("started", "already_running")

    status = client.get("/api/monitoring/scheduler/status").json()
    assert status["running"] is True

    stop = client.post("/api/monitoring/scheduler/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"


def test_server_stats_empty(client):
    server = client.post("/api/monitoring/servers", json={
        "name": "Test",
        "url": "http://localhost:3333",
    }).json()

    resp = client.get(f"/api/monitoring/servers/{server['id']}/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total_checks"] == 0
    assert stats["uptime_percent"] == 0
    assert stats["latency_sparkline"] == []

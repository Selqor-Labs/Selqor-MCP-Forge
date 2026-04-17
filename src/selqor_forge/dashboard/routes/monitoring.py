# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Post-deploy monitoring routes for MCP servers.

The original health check did a plain ``GET <url>`` and treated 404 as
"unhealthy", which broke for every real MCP server (which expose ``/sse`` for
SSE transport, not the root URL). It also tried to enumerate tools via a
fictional ``/mcp/v1/tools/list`` REST endpoint that does not exist in the MCP
spec. This module probes the server using the actual MCP HTTP+SSE protocol:

1. Open ``GET {base}/sse`` with ``Accept: text/event-stream``
2. Wait for the ``event: endpoint`` line that announces the message URL
3. POST a JSON-RPC ``initialize`` then ``tools/list`` to that URL
4. Read the JSON-RPC responses from the still-open SSE stream
5. Close the SSE stream cleanly

If the URL the user supplied doesn't have ``/sse`` it is appended
automatically; if the user pasted ``http://host:port/sse`` we use it as-is.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets as _secrets
import time
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import (
    AlertRuleRepository,
    FiredAlertRepository,
    MonitoredServerRepository,
    MonitoringCheckRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_MAX_HISTORY = 50
_MIN_INTERVAL = 30
_HTTP_URL_RE = re.compile(r"^https?://[^\s]+$")

# Background scheduler state
_scheduler_task: asyncio.Task | None = None
_scheduler_running: bool = False


# ---------------------------------------------------------------------------
# Request models with real validation
# ---------------------------------------------------------------------------


class AddServerBody(BaseModel):
    """Request to add a server to monitor."""

    name: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=1, max_length=2048)
    transport: str = "http_sse"
    check_interval_seconds: int = Field(300, ge=_MIN_INTERVAL, le=86400)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not _HTTP_URL_RE.match(v):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, v: str) -> str:
        v = (v or "http_sse").strip().lower()
        # The backend only knows how to probe HTTP+SSE servers right now,
        # so accept the legacy ``sse`` and ``http`` aliases too.
        if v in ("sse", "http", "http_sse", "https"):
            return "http_sse"
        raise ValueError(f"unsupported transport: {v}")


class UpdateServerBody(BaseModel):
    """Partial update for a monitored server."""

    name: str | None = Field(None, min_length=1, max_length=120)
    url: str | None = Field(None, min_length=1, max_length=2048)
    check_interval_seconds: int | None = Field(None, ge=_MIN_INTERVAL, le=86400)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        return v

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not _HTTP_URL_RE.match(v):
            raise ValueError("url must start with http:// or https://")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server_to_dict(model) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "url": model.url,
        "transport": model.transport,
        "check_interval_seconds": model.check_interval_seconds,
        "created_at": model.created_at,
        "last_check": model.last_check,
        "status": model.status,
    }


def _check_to_dict(model) -> dict:
    return {
        "timestamp": model.timestamp,
        "status": model.status,
        "latency_ms": model.latency_ms,
        "tool_count": model.tool_count,
        "error": model.error,
    }


def _rule_to_dict(model) -> dict:
    return {
        "id": model.id,
        "server_id": model.server_id,
        "name": model.name,
        "condition": model.condition,
        "threshold": model.threshold,
        "enabled": model.enabled,
        "created_at": model.created_at,
    }


def _alert_to_dict(model) -> dict:
    return {
        "id": model.id,
        "server_id": model.server_id,
        "rule_id": model.rule_id,
        "rule_name": model.rule_name,
        "condition": model.condition,
        "detail": model.detail,
        "timestamp": model.timestamp,
        "acknowledged": model.acknowledged,
    }


def _resolve_sse_url(url: str) -> tuple[str, str]:
    """Return ``(base_url, sse_url)`` from whatever the user supplied.

    If the URL already ends in ``/sse`` we use it as-is; otherwise we append
    it. ``base_url`` is everything up to (but not including) ``/sse``.
    """
    url = url.rstrip("/")
    if url.endswith("/sse"):
        return url[: -len("/sse")], url
    return url, f"{url}/sse"


# ---------------------------------------------------------------------------
# MCP HTTP+SSE health probe
# ---------------------------------------------------------------------------


async def _probe_mcp_http_sse(server_url: str, timeout: float = 8.0) -> dict:
    """Probe an MCP HTTP+SSE server and return a check-result dict.

    Returns ``{status, latency_ms, tool_count, error}``.

    Strategy
    --------
    The MCP SSE transport is bidirectional: the client opens an SSE stream and
    receives an ``event: endpoint`` line whose ``data:`` is the relative URL
    where it should POST JSON-RPC messages. Responses come back as
    ``event: message`` events on the same SSE stream. We:

    1. Open the SSE stream
    2. Wait (with a deadline) for the endpoint event
    3. POST ``initialize`` and ``tools/list`` to the messages URL
    4. Read responses off the SSE stream
    5. Cancel the SSE reader task and close the client
    """

    base_url, sse_url = _resolve_sse_url(server_url)
    queue: asyncio.Queue = asyncio.Queue()
    started = time.monotonic()

    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=timeout))

    async def _sse_reader() -> None:
        try:
            async with client.stream("GET", sse_url, headers={"Accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    await queue.put({"event": "error", "data": f"SSE returned HTTP {resp.status_code}"})
                    return
                event_type: str | None = None
                data_lines: list[str] = []
                async for raw in resp.aiter_lines():
                    line = raw.strip()
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        data_lines = []
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        if event_type:
                            await queue.put({"event": event_type, "data": "\n".join(data_lines)})
                        event_type = None
                        data_lines = []
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await queue.put({"event": "error", "data": str(exc)[:200]})

    sse_task = asyncio.create_task(_sse_reader())

    async def _wait_event(deadline: float, accept_message: bool) -> dict | None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            kind = evt.get("event")
            if kind == "error":
                return evt
            if kind == "endpoint":
                return evt
            if kind == "message" and accept_message:
                return evt
            # Skip unrelated events (heartbeats, ping, etc.)

    deadline = time.monotonic() + timeout
    result: dict = {
        "status": "unknown",
        "latency_ms": 0.0,
        "tool_count": 0,
        "error": None,
    }

    try:
        # 1. wait for endpoint
        endpoint_evt = await _wait_event(deadline, accept_message=False)
        if endpoint_evt is None:
            result["status"] = "timeout"
            result["error"] = f"No SSE endpoint event after {timeout}s"
            return result
        if endpoint_evt.get("event") == "error":
            err = endpoint_evt.get("data", "SSE error")
            if "ConnectError" in err or "Connection refused" in err or "timed out" in err.lower():
                result["status"] = "unreachable"
            else:
                result["status"] = "unhealthy"
            result["error"] = err
            return result

        endpoint_path = endpoint_evt.get("data", "")
        if endpoint_path.startswith("/"):
            messages_url = f"{base_url}{endpoint_path}"
        else:
            messages_url = endpoint_path

        # 2. initialize
        async with httpx.AsyncClient(timeout=timeout) as post_client:
            init_resp = await post_client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "selqor-forge-monitor", "version": "1.0"},
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            if init_resp.status_code not in (200, 202):
                result["status"] = "unhealthy"
                result["error"] = f"initialize POST returned HTTP {init_resp.status_code}"
                return result

        init_msg = await _wait_event(deadline, accept_message=True)
        if init_msg is None:
            result["status"] = "unhealthy"
            result["error"] = "No initialize response on SSE stream"
            return result
        try:
            init_data = json.loads(init_msg.get("data", "{}"))
            if "error" in init_data:
                result["status"] = "unhealthy"
                result["error"] = f"initialize error: {init_data['error']}"
                return result
        except json.JSONDecodeError:
            result["status"] = "unhealthy"
            result["error"] = "initialize returned invalid JSON"
            return result

        # 3. notifications/initialized + tools/list
        async with httpx.AsyncClient(timeout=timeout) as post_client:
            await post_client.post(
                messages_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers={"Content-Type": "application/json"},
            )
            await post_client.post(
                messages_url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={"Content-Type": "application/json"},
            )

        tools_msg = await _wait_event(deadline, accept_message=True)
        if tools_msg is None:
            # We did get an initialize response, so the server is responsive.
            # Just count zero tools.
            result["status"] = "healthy"
            result["tool_count"] = 0
        else:
            try:
                tools_data = json.loads(tools_msg.get("data", "{}"))
                tools = tools_data.get("result", {}).get("tools", [])
                result["status"] = "healthy"
                result["tool_count"] = len(tools)
            except json.JSONDecodeError:
                result["status"] = "healthy"
                result["tool_count"] = 0

        return result

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:200]
        return result
    finally:
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        sse_task.cancel()
        try:
            await sse_task
        except Exception:
            pass
        try:
            await client.aclose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Alert evaluation helper
# ---------------------------------------------------------------------------


def _evaluate_alerts(
    session,
    server_id: str,
    check_result: dict,
    stats: dict,
) -> list[dict]:
    """Evaluate alert rules against a check result and fire alerts.

    Called internally after each health check. Uses the provided DB session
    to read rules and persist fired alerts.
    """
    rule_repo = AlertRuleRepository(session)
    alert_repo = FiredAlertRepository(session)
    rules = rule_repo.list_by_server(server_id)
    fired: list[dict] = []

    for rule in rules:
        if not rule.enabled:
            continue

        triggered = False
        detail = ""

        if rule.condition == "latency_above":
            latency = check_result.get("latency_ms", 0)
            if latency > rule.threshold:
                triggered = True
                detail = f"Latency {latency:.0f}ms exceeds threshold {rule.threshold:.0f}ms"

        elif rule.condition == "consecutive_failures":
            consec = stats.get("consecutive_failures", 0)
            if consec >= rule.threshold:
                triggered = True
                detail = f"{consec} consecutive failures (threshold: {int(rule.threshold)})"

        elif rule.condition == "status_unhealthy":
            if check_result.get("status") != "healthy":
                triggered = True
                detail = f"Server status: {check_result.get('status', 'unknown')}"

        if triggered:
            alert_model = alert_repo.create(
                id=_secrets.token_hex(8),
                server_id=server_id,
                rule_id=rule.id,
                rule_name=rule.name,
                condition=rule.condition,
                detail=detail,
                timestamp=datetime.utcnow().isoformat() + "Z",
                acknowledged=False,
            )
            fired.append(_alert_to_dict(alert_model))

    # Prune old alerts to keep the table bounded
    if fired:
        alert_repo.prune(keep=500)

    return fired


def _compute_stats_for_server(session, server_id: str) -> dict:
    """Compute lightweight stats dict needed for alert evaluation."""
    check_repo = MonitoringCheckRepository(session)
    checks = check_repo.list_by_server(server_id, limit=_MAX_HISTORY)
    if not checks:
        return {"consecutive_failures": 0}
    consec_failures = 0
    for c in reversed(checks):
        if c.status != "healthy":
            consec_failures += 1
        else:
            break
    return {"consecutive_failures": consec_failures}


# ---------------------------------------------------------------------------
# Routes — Server CRUD (already DB-persisted)
# ---------------------------------------------------------------------------


@router.get("/servers")
async def list_servers(ctx: Ctx) -> dict:
    """List all monitored servers."""
    session = ctx.db_session_factory()
    try:
        repo = MonitoredServerRepository(session)
        servers = repo.list_all()
        server_dicts = [_server_to_dict(s) for s in servers]
        return {"servers": server_dicts, "total": len(server_dicts)}
    finally:
        session.close()


@router.post("/servers")
async def add_server(ctx: Ctx, body: AddServerBody) -> dict:
    """Add a server to monitoring."""
    session = ctx.db_session_factory()
    try:
        repo = MonitoredServerRepository(session)
        server_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        server = repo.create(
            id=server_id,
            name=body.name,
            url=body.url,
            transport=body.transport,
            check_interval_seconds=body.check_interval_seconds,
            created_at=now,
            last_check=None,
            status="unknown",
        )
        return _server_to_dict(server)
    finally:
        session.close()


@router.patch("/servers/{server_id}")
async def update_server(ctx: Ctx, server_id: str, body: UpdateServerBody) -> dict:
    """Update name / url / interval on a monitored server."""
    session = ctx.db_session_factory()
    try:
        repo = MonitoredServerRepository(session)
        if repo.get_by_id(server_id) is None:
            raise HTTPException(status_code=404, detail="Server not found")
        updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        repo.update(server_id, **updates)
        updated = repo.get_by_id(server_id)
        return _server_to_dict(updated)
    finally:
        session.close()


@router.delete("/servers/{server_id}")
async def remove_server(ctx: Ctx, server_id: str) -> dict:
    """Remove a monitored server."""
    session = ctx.db_session_factory()
    try:
        repo = MonitoredServerRepository(session)
        if not repo.delete(server_id):
            raise HTTPException(status_code=404, detail="Server not found")
        return {"message": "Server removed", "id": server_id}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Routes — Health checks
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/check")
async def check_server(ctx: Ctx, server_id: str) -> dict:
    """Run a real MCP health check on a monitored server."""
    session = ctx.db_session_factory()
    try:
        server_repo = MonitoredServerRepository(session)
        check_repo = MonitoringCheckRepository(session)

        server = server_repo.get_by_id(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        result = await _probe_mcp_http_sse(server.url)
        now = datetime.utcnow().isoformat() + "Z"
        result["timestamp"] = now

        # Persist
        server_repo.update(server_id, last_check=now, status=result["status"])
        check_repo.create(
            id=str(uuid.uuid4()),
            server_id=server_id,
            timestamp=now,
            status=result["status"],
            latency_ms=result["latency_ms"],
            tool_count=result["tool_count"],
            error=result["error"],
        )
        check_repo.prune(server_id, keep=_MAX_HISTORY)

        # Evaluate alert rules after health check
        stats = _compute_stats_for_server(session, server_id)
        fired = _evaluate_alerts(session, server_id, result, stats)
        if fired:
            result["fired_alerts"] = fired
            await _notify_fired_alerts(session, fired)

        return result
    finally:
        session.close()


def _host_key(url: str) -> str:
    """Normalise a URL down to ``scheme://host:port`` for per-host serialisation."""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        host = p.hostname or url
        port = p.port or (443 if p.scheme == "https" else 80)
        return f"{p.scheme}://{host}:{port}"
    except Exception:
        return url


@router.post("/servers/check-all")
async def check_all_servers(ctx: Ctx) -> dict:
    """Run a health check on every monitored server.

    Servers on **different hosts** run in parallel; servers on the **same
    host** run sequentially. The MCP SSE transport stores its session in a
    single module-level variable on the server side, so two simultaneous
    SSE clients clobber each other and both come back unhealthy. Per-host
    serialisation avoids that without sacrificing throughput across hosts.
    """
    session = ctx.db_session_factory()
    try:
        server_repo = MonitoredServerRepository(session)
        check_repo = MonitoringCheckRepository(session)
        servers = server_repo.list_all()

        # Group by host
        groups: dict[str, list] = {}
        order: list[str] = []
        for s in servers:
            key = _host_key(s.url)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(s)

        async def _persist(server, r: dict) -> dict:
            now = datetime.utcnow().isoformat() + "Z"
            r["timestamp"] = now
            r["server_id"] = server.id
            r["server_name"] = server.name
            try:
                server_repo.update(server.id, last_check=now, status=r["status"])
                check_repo.create(
                    id=str(uuid.uuid4()),
                    server_id=server.id,
                    timestamp=now,
                    status=r["status"],
                    latency_ms=r["latency_ms"],
                    tool_count=r["tool_count"],
                    error=r["error"],
                )
                check_repo.prune(server.id, keep=_MAX_HISTORY)

                # Evaluate alert rules after each server check
                stats = _compute_stats_for_server(session, server.id)
                fired = _evaluate_alerts(session, server.id, r, stats)
                if fired:
                    r["fired_alerts"] = fired
                    await _notify_fired_alerts(session, fired)
            except Exception:
                pass
            return r

        async def _check_group(group_servers: list) -> list[dict]:
            out: list[dict] = []
            for idx, server in enumerate(group_servers):
                # Give the previous probe time to fully release the
                # server-side SSE transport before opening a new one. The
                # generated MCP server keeps a single module-level transport
                # variable and a too-fast back-to-back connect can race with
                # its cleanup callback.
                if idx > 0:
                    await asyncio.sleep(0.5)
                try:
                    r = await _probe_mcp_http_sse(server.url)
                except Exception as exc:
                    r = {
                        "status": "error",
                        "latency_ms": 0.0,
                        "tool_count": 0,
                        "error": str(exc)[:200],
                    }
                out.append(await _persist(server, r))
            return out

        # Parallel across hosts, sequential within a host
        per_host = await asyncio.gather(*[_check_group(groups[k]) for k in order])
        flat: list[dict] = []
        for chunk in per_host:
            flat.extend(chunk)
        return {"results": flat, "total": len(flat)}
    finally:
        session.close()


@router.get("/servers/{server_id}/history")
async def check_history(ctx: Ctx, server_id: str) -> dict:
    """Get health check history for a server (last 50 checks)."""
    session = ctx.db_session_factory()
    try:
        server_repo = MonitoredServerRepository(session)
        check_repo = MonitoringCheckRepository(session)

        server = server_repo.get_by_id(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        checks = check_repo.list_by_server(server_id, limit=_MAX_HISTORY)
        check_dicts = [_check_to_dict(c) for c in reversed(checks)]
        return {
            "server_id": server_id,
            "server_name": server.name,
            "checks": check_dicts,
            "total": len(check_dicts),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Uptime Statistics — computed from check history
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/stats")
async def server_stats(ctx: Ctx, server_id: str) -> dict:
    """Compute uptime stats from check history.

    Returns uptime percentage, average/p95/max latency, consecutive failures,
    and a latency sparkline (last 20 latency values for charting).
    """
    session = ctx.db_session_factory()
    try:
        server_repo = MonitoredServerRepository(session)
        check_repo = MonitoringCheckRepository(session)

        server = server_repo.get_by_id(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        checks = check_repo.list_by_server(server_id, limit=_MAX_HISTORY)
        if not checks:
            return {
                "server_id": server_id,
                "server_name": server.name,
                "total_checks": 0,
                "uptime_percent": 0,
                "avg_latency_ms": 0,
                "p95_latency_ms": 0,
                "max_latency_ms": 0,
                "consecutive_failures": 0,
                "last_healthy": None,
                "latency_sparkline": [],
            }

        total = len(checks)
        healthy_count = sum(1 for c in checks if c.status == "healthy")
        uptime = round(healthy_count / total * 100, 1) if total else 0

        latencies = sorted([c.latency_ms for c in checks if c.latency_ms and c.latency_ms > 0])
        avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0
        p95_idx = int(len(latencies) * 0.95) if latencies else 0
        p95_lat = round(latencies[min(p95_idx, len(latencies) - 1)], 1) if latencies else 0
        max_lat = round(max(latencies), 1) if latencies else 0

        # Consecutive failures from most recent
        consec_failures = 0
        for c in reversed(checks):
            if c.status != "healthy":
                consec_failures += 1
            else:
                break

        # Last healthy timestamp
        last_healthy = None
        for c in reversed(checks):
            if c.status == "healthy":
                last_healthy = c.timestamp
                break

        # Sparkline data: last 20 latency readings (oldest to newest)
        sparkline = [
            round(c.latency_ms, 1)
            for c in checks[-20:]
            if c.latency_ms and c.latency_ms > 0
        ]

        return {
            "server_id": server_id,
            "server_name": server.name,
            "total_checks": total,
            "uptime_percent": uptime,
            "avg_latency_ms": avg_lat,
            "p95_latency_ms": p95_lat,
            "max_latency_ms": max_lat,
            "consecutive_failures": consec_failures,
            "last_healthy": last_healthy,
            "latency_sparkline": sparkline,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Alert Rules — threshold-based alerting (DB-persisted)
# ---------------------------------------------------------------------------


class AlertRuleBody(BaseModel):
    """Create an alert rule for a monitored server."""
    name: str = Field(..., min_length=1, max_length=120)
    condition: str = Field(
        ...,
        description="One of: latency_above, consecutive_failures, status_unhealthy",
    )
    threshold: float = Field(..., description="Threshold value (ms for latency, count for failures)")
    enabled: bool = True

    @field_validator("condition")
    @classmethod
    def _validate_condition(cls, v: str) -> str:
        valid = {"latency_above", "consecutive_failures", "status_unhealthy"}
        if v not in valid:
            raise ValueError(f"condition must be one of: {', '.join(sorted(valid))}")
        return v


@router.post("/servers/{server_id}/alerts")
async def create_alert_rule(ctx: Ctx, server_id: str, body: AlertRuleBody) -> dict:
    """Create an alert rule for a server."""
    session = ctx.db_session_factory()
    try:
        server_repo = MonitoredServerRepository(session)
        if server_repo.get_by_id(server_id) is None:
            raise HTTPException(status_code=404, detail="Server not found")

        rule_repo = AlertRuleRepository(session)
        rule = rule_repo.create(
            id=_secrets.token_hex(8),
            server_id=server_id,
            name=body.name.strip(),
            condition=body.condition,
            threshold=body.threshold,
            enabled=body.enabled,
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        return _rule_to_dict(rule)
    finally:
        session.close()


@router.get("/servers/{server_id}/alerts")
async def list_alert_rules(ctx: Ctx, server_id: str) -> dict:
    """List alert rules for a server."""
    session = ctx.db_session_factory()
    try:
        rule_repo = AlertRuleRepository(session)
        rules = rule_repo.list_by_server(server_id)
        rule_dicts = [_rule_to_dict(r) for r in rules]
        return {"rules": rule_dicts, "total": len(rule_dicts)}
    finally:
        session.close()


@router.delete("/servers/{server_id}/alerts/{rule_id}")
async def delete_alert_rule(ctx: Ctx, server_id: str, rule_id: str) -> dict:
    """Delete an alert rule."""
    session = ctx.db_session_factory()
    try:
        rule_repo = AlertRuleRepository(session)
        rule = rule_repo.get_by_id(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        rule_dict = _rule_to_dict(rule)
        rule_repo.delete(rule_id)
        return {"message": "Alert rule removed", "rule": rule_dict}
    finally:
        session.close()


@router.get("/alerts")
async def list_fired_alerts(ctx: Ctx, limit: int = 50) -> dict:
    """List all fired alerts across all servers."""
    session = ctx.db_session_factory()
    try:
        alert_repo = FiredAlertRepository(session)
        alerts = alert_repo.list_all(limit=limit)
        alert_dicts = [_alert_to_dict(a) for a in alerts]
        return {"alerts": alert_dicts, "total": len(alert_dicts)}
    finally:
        session.close()


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(ctx: Ctx, alert_id: str) -> dict:
    """Mark an alert as acknowledged."""
    session = ctx.db_session_factory()
    try:
        alert_repo = FiredAlertRepository(session)
        model = alert_repo.acknowledge(alert_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"message": "Alert acknowledged", "alert": _alert_to_dict(model)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Background Scheduler — periodic health checks
# ---------------------------------------------------------------------------


async def _notify_fired_alerts(session, fired: list[dict]) -> None:
    """Fan out fired alerts to all enabled notification channels."""
    from selqor_forge.dashboard.repositories import NotificationChannelRepository
    from selqor_forge.dashboard.routes.notifications import send_notification

    channel_repo = NotificationChannelRepository(session)
    channels = channel_repo.list_enabled()
    if not channels:
        return

    for alert in fired:
        subject = f"Alert: {alert.get('rule_name', 'unknown rule')}"
        body = (
            f"Server: {alert.get('server_id', 'unknown')}\n"
            f"Condition: {alert.get('condition', 'unknown')}\n"
            f"Detail: {alert.get('detail', '')}\n"
            f"Time: {alert.get('timestamp', '')}"
        )
        for ch in channels:
            try:
                await send_notification(
                    session, ch,
                    event_type="monitoring_alert",
                    subject=subject,
                    body=body,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to send alert notification via channel %s: %s",
                    ch.id, str(exc)[:200],
                )


# Track last-check time per server so we respect per-server intervals
_last_check_times: dict[str, float] = {}


async def _scheduler_loop(ctx: Ctx) -> None:
    """Background loop that checks servers respecting per-server intervals.

    Instead of a single global interval, the loop ticks every 30 seconds and
    checks which servers are due based on their ``check_interval_seconds``.
    """
    global _scheduler_running
    _scheduler_running = True
    logger.info("Monitoring scheduler started (per-server intervals)")

    try:
        while _scheduler_running:
            await asyncio.sleep(_MIN_INTERVAL)
            if not _scheduler_running:
                break

            session = ctx.db_session_factory()
            try:
                server_repo = MonitoredServerRepository(session)
                check_repo = MonitoringCheckRepository(session)
                servers = server_repo.list_all()
                now_mono = time.monotonic()

                for server in servers:
                    if not _scheduler_running:
                        break

                    interval = server.check_interval_seconds or 300
                    last = _last_check_times.get(server.id, 0)
                    if (now_mono - last) < interval:
                        continue

                    try:
                        result = await _probe_mcp_http_sse(server.url)
                        now = datetime.utcnow().isoformat() + "Z"
                        result["timestamp"] = now

                        server_repo.update(server.id, last_check=now, status=result["status"])
                        check_repo.create(
                            id=str(uuid.uuid4()),
                            server_id=server.id,
                            timestamp=now,
                            status=result["status"],
                            latency_ms=result["latency_ms"],
                            tool_count=result["tool_count"],
                            error=result["error"],
                        )
                        check_repo.prune(server.id, keep=_MAX_HISTORY)
                        _last_check_times[server.id] = time.monotonic()

                        # Evaluate alerts and send notifications
                        stats = _compute_stats_for_server(session, server.id)
                        fired = _evaluate_alerts(session, server.id, result, stats)
                        if fired:
                            await _notify_fired_alerts(session, fired)

                    except Exception as exc:
                        logger.warning(
                            "Scheduler: failed to check server %s: %s",
                            server.id,
                            str(exc)[:200],
                        )
            finally:
                session.close()

    except asyncio.CancelledError:
        pass
    finally:
        _scheduler_running = False
        logger.info("Monitoring scheduler stopped")


@router.post("/scheduler/start")
async def start_scheduler(ctx: Ctx) -> dict:
    """Start the background monitoring scheduler."""
    global _scheduler_task, _scheduler_running

    if _scheduler_running and _scheduler_task is not None and not _scheduler_task.done():
        return {"status": "already_running"}

    _scheduler_task = asyncio.create_task(_scheduler_loop(ctx))
    return {"status": "started"}


@router.post("/scheduler/stop")
async def stop_scheduler(ctx: Ctx) -> dict:
    """Stop the background monitoring scheduler."""
    global _scheduler_task, _scheduler_running

    if not _scheduler_running or _scheduler_task is None or _scheduler_task.done():
        return {"status": "not_running"}

    _scheduler_running = False
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None
    return {"status": "stopped"}


@router.get("/scheduler/status")
async def scheduler_status(ctx: Ctx) -> dict:
    """Return whether the background scheduler is running."""
    running = (
        _scheduler_running
        and _scheduler_task is not None
        and not _scheduler_task.done()
    )
    return {"running": running}

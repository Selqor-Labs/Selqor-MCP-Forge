# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Forge Playground routes â€” connect to MCP servers, list tools, execute tools."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from selqor_forge.dashboard.mcp_client import (
    HttpSseMCPClient,
    MCPClient,
    MCPDisconnectedError,
    MCPError,
    StdioMCPClient,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.playground_assertions import (
    evaluate_all,
    ensure_jsonable,
    validate_assertions,
)
from selqor_forge.dashboard.repositories import (
    PlaygroundAgentRunRepository,
    PlaygroundExecutionRepository,
    PlaygroundSessionRepository,
    PlaygroundTestCaseRepository,
    PlaygroundTestRunRepository,
)

router = APIRouter(prefix="/playground", tags=["playground"])

# ---------------------------------------------------------------------------
# In-memory session store â€” tracks connected MCP servers
# ---------------------------------------------------------------------------

# Session metadata (name, tools, server_info, executions history, etc.) lives
# in ``_sessions``. The live transport (subprocess / HTTP+SSE connection) lives
# in ``_clients`` keyed by the same session id. Both entries are created and
# torn down together by connect / disconnect handlers.
_sessions: dict[str, dict] = {}
_clients: dict[str, MCPClient] = {}


def _model_to_dict(model) -> dict:
    """Convert an ORM model to a plain dict, filtering SQLAlchemy internals."""
    return {k: v for k, v in model.__dict__.items() if not k.startswith("_")}


class ConnectRequest(BaseModel):
    """Request to connect to an MCP server."""
    name: str = ""
    transport: str = "stdio"  # "stdio" or "http"
    # For stdio: command to run (e.g. "node ./dist/index.js")
    command: str | None = None
    working_dir: str | None = None
    # For http: server URL
    server_url: str | None = None
    # Environment variables to pass
    env_vars: dict[str, str] | None = None
    # Optional integration id used to reuse an existing session instead of creating a duplicate
    integration_id: str | None = None


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool on a connected MCP server."""
    tool_name: str
    arguments: dict[str, Any] = {}


class TestSuiteRequest(BaseModel):
    """Request to generate test cases for tools."""
    tool_names: list[str] | None = None  # None = all tools


class SuggestArgsRequest(BaseModel):
    """Request to have an LLM generate valid arguments for a tool from natural-language intent."""
    tool_name: str
    intent: str = ""
    config_id: str | None = None


class TestCaseRequest(BaseModel):
    """Create or update a test case."""
    tool_name: str
    name: str
    description: str | None = None
    arguments: dict[str, Any] = {}
    assertions: list[dict[str, Any]] = []


class TestCaseUpdateRequest(BaseModel):
    """Partial update of a test case."""
    name: str | None = None
    description: str | None = None
    arguments: dict[str, Any] | None = None
    assertions: list[dict[str, Any]] | None = None


class RunSuiteRequest(BaseModel):
    """Run a subset (or all) of the saved test cases for a session."""
    testcase_ids: list[str] | None = None  # None = run all on this session


class AgentChatRequest(BaseModel):
    """Drive an agent-in-the-loop conversation against the live MCP session."""
    message: str
    config_id: str | None = None
    max_iterations: int = 6
    system_prompt: str | None = None


# ---------------------------------------------------------------------------
# Deployment server management â€” start/stop servers
# ---------------------------------------------------------------------------

_deployment_processes: dict[str, subprocess.Popen] = {}


@router.post("/deployments/{integration_id}/start-server")
async def start_deployment_server(ctx: Ctx, integration_id: str) -> dict:
    """Start the MCP server for a deployed integration."""
    from selqor_forge.dashboard.repositories import IntegrationRepository
    import os

    db_session = ctx.db_session_factory()
    try:
        repo = IntegrationRepository(db_session)
        integration = repo.get_by_id(integration_id)
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
    finally:
        db_session.close()

    # Find the latest deployment from the database
    dep_db = ctx.db_session_factory()
    try:
        from selqor_forge.dashboard.repositories import DeploymentRepository
        dep_repo = DeploymentRepository(dep_db)
        deployments = dep_repo.list_by_integration(integration_id)
        if not deployments:
            raise HTTPException(status_code=404, detail="No deployments found for this integration")
        latest_dep = deployments[0]
        command = latest_dep.command or ""
        raw_path = (latest_dep.server_path or "").replace("\\", "/")
    finally:
        dep_db.close()

    # Resolve server path (handle relative + Windows backslashes)
    if raw_path and not Path(raw_path).is_absolute():
        server_path_obj = (ctx.state_dir.parent / raw_path).resolve()
    else:
        server_path_obj = Path(raw_path) if raw_path else None
    server_path = str(server_path_obj) if server_path_obj else ""

    try:
        if not command:
            raise HTTPException(status_code=400, detail="No command to start server")

        # Check if server is already running
        if integration_id in _deployment_processes:
            proc = _deployment_processes[integration_id]
            if proc.poll() is None:
                return {"status": "already_running", "integration_id": integration_id}

        # Start the server using tsx directly to avoid shell quoting issues
        env = os.environ.copy()

        # Load env vars from .env.generated first
        env_gen = server_path_obj / ".env.generated" if server_path_obj else None
        env_file = server_path_obj / ".env" if server_path_obj else None
        for ef in [env_gen, env_file]:
            if ef and ef.exists():
                for line in ef.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
                break  # Use first file found

        # Mirror what the deploy command string does: ensure .env exists (so
        # the server picks up FORGE_* even if the caller didn't inherit them
        # through process env) and install node_modules on first run.
        if server_path_obj is not None:
            env_dotfile = server_path_obj / ".env"
            env_generated = server_path_obj / ".env.generated"
            if env_generated.exists() and not env_dotfile.exists():
                try:
                    env_dotfile.write_text(
                        env_generated.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to materialise .env for server: {exc}",
                    )

            # On Windows, ``npm`` is actually ``npm.cmd``. We rely on
            # ``shell=True`` here because npm's shim behavior differs per
            # platform â€” the server_path is system-controlled (not
            # user-supplied) so there's no injection risk.
            needs_install = not (server_path_obj / "node_modules").exists()
            if needs_install:
                try:
                    install_proc = await asyncio.create_subprocess_shell(
                        "npm install",
                        cwd=str(server_path_obj),
                        env=env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    # npm install on Windows with a fresh cache can legitimately
                    # take over a minute; give it headroom.
                    try:
                        stdout_b, stderr_b = await asyncio.wait_for(
                            install_proc.communicate(), timeout=180.0
                        )
                    except asyncio.TimeoutError:
                        install_proc.kill()
                        raise HTTPException(
                            status_code=504,
                            detail="npm install timed out after 180s for the generated server",
                        )
                    if install_proc.returncode != 0:
                        tail = (stderr_b or b"").decode("utf-8", errors="replace")[-800:]
                        raise HTTPException(
                            status_code=500,
                            detail=(
                                f"npm install failed (exit={install_proc.returncode}): "
                                f"{tail}"
                            ),
                        )
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"npm install crashed: {exc}",
                    )

        # Use npm run dev directly in the server directory
        cmd_parts = ["npm", "run", "dev"]

        try:
            # Windows: npm is npm.cmd and asyncio.create_subprocess_exec often
            # fails to resolve shims, so keep the sync Popen here. This is the
            # deployment-server lifecycle (separate from the MCP client I/O
            # layer) so the sync subprocess is not a correctness hazard â€”
            # we don't read stdin/stdout of this process, we just keep a
            # handle to stop it later.
            popen_kwargs: dict[str, Any] = dict(
                cwd=server_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            if os.name == "nt":
                popen_kwargs["shell"] = True
                proc = subprocess.Popen("npm run dev", **popen_kwargs)
            else:
                proc = subprocess.Popen(cmd_parts, **popen_kwargs)
            _deployment_processes[integration_id] = proc
            await asyncio.sleep(2)  # Give server time to start

            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:800] if proc.stderr else ""
                raise HTTPException(status_code=500, detail=f"Server failed to start: {stderr}")

            return {
                "status": "started",
                "integration_id": integration_id,
                "message": "MCP server started successfully",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start server: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading deployment: {str(e)}")


# ---------------------------------------------------------------------------
# Available integrations â€” auto-discovery for Playground
# ---------------------------------------------------------------------------

def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read a .env file and return key-value pairs."""
    result = {}
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    result[key.strip()] = val.strip()
    except Exception:
        pass
    return result


@router.get("/available-integrations")
async def list_available_integrations(ctx: Ctx) -> dict:
    """List all integrations available for testing in the Playground."""
    from selqor_forge.dashboard.repositories import (
        IntegrationRepository,
        DeploymentRepository,
        RunRepository,
    )

    db_session = ctx.db_session_factory()
    try:
        int_repo = IntegrationRepository(db_session)
        dep_repo = DeploymentRepository(db_session)
        run_repo = RunRepository(db_session)
        integrations = int_repo.list_all()

        available = []
        for integration in integrations:
            try:
                # Get latest deployment from database
                deployments = dep_repo.list_by_integration(integration.id)
                if not deployments:
                    continue

                latest = deployments[0]  # Already sorted desc by created_at

                # Fetch the latest run to surface tool/endpoint counts so
                # the Playground can render the baseline-vs-curated panel
                # without a second round-trip.
                latest_run = None
                try:
                    runs = run_repo.list_by_integration(integration.id, limit=1)
                    latest_run = runs[0] if runs else None
                except Exception:
                    latest_run = None

                # Normalize path: handle Windows backslashes and relative paths
                raw_path = (latest.server_path or "").replace("\\", "/")
                if raw_path and not Path(raw_path).is_absolute():
                    server_path = (ctx.state_dir.parent / raw_path).resolve()
                else:
                    server_path = Path(raw_path) if raw_path else None

                # Read transport and port from .env.generated (no DB migration needed)
                env_vars = {}
                if server_path:
                    env_vars = _read_env_file(server_path / ".env.generated")
                    if not env_vars:
                        env_vars = _read_env_file(server_path / ".env")

                transport = env_vars.get("FORGE_TRANSPORT", "stdio")
                http_port = int(env_vars.get("FORGE_HTTP_PORT", "3333"))

                connection_info: dict = {"transport": transport}
                if transport == "http":
                    connection_info["server_url"] = f"http://localhost:{http_port}"
                else:
                    command = latest.command or ""
                    connection_info["command"] = command
                    connection_info["working_dir"] = str(server_path) if server_path else ""

                available.append({
                    "integration_id": integration.id,
                    "integration_name": integration.name or integration.id,
                    "spec_url": integration.spec,
                    "deployment_id": latest.deployment_id,
                    "deployment_status": latest.status,
                    "deployment_created_at": latest.created_at,
                    "connection": connection_info,
                    "deployment_notes": latest.notes or "",
                    # Baseline-vs-curated stats for the Playground comparison.
                    "endpoint_count": latest_run.endpoint_count if latest_run else None,
                    "tool_count": latest_run.tool_count if latest_run else None,
                    "quality_score": latest_run.score if latest_run else None,
                })
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to load deployment for %s: %s", integration.id, e
                )
                continue

        return {"integrations": available, "count": len(available)}
    finally:
        db_session.close()


# ---------------------------------------------------------------------------
# Sessions â€” list, create, delete
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(ctx: Ctx) -> dict:
    """List all playground sessions."""
    db_session = ctx.db_session_factory()
    try:
        repo = PlaygroundSessionRepository(db_session)
        db_sessions = repo.list_all()
        sessions_list = []
        for s in db_sessions:
            # Merge live status from _clients: a row persisted as "connected"
            # is only still connected if the in-memory client is alive.
            live_status = s.status
            client = _clients.get(s.id)
            if client is not None and client.is_alive():
                live_status = "connected"
            elif s.status == "connected":
                live_status = "disconnected"
            tools = s.tools or []
            sessions_list.append({
                "id": s.id,
                "name": s.name or "",
                "transport": s.transport or "stdio",
                "status": live_status,
                "connected_at": s.connected_at,
                "server_info": s.server_info,
                "tools_count": len(tools),
                "command": s.command,
                "server_url": s.server_url,
            })
        return {"sessions": sessions_list}
    finally:
        db_session.close()


@router.post("/auto-connect/{integration_id}")
async def auto_connect_integration(ctx: Ctx, integration_id: str) -> dict:
    """Automatically connect to a deployed MCP server for an integration."""
    # Get available integrations
    available_response = await list_available_integrations(ctx)
    available = available_response.get("integrations", [])

    # Find the matching integration
    integration = next((i for i in available if i["integration_id"] == integration_id), None)
    if not integration:
        raise HTTPException(status_code=404, detail=f"Integration '{integration_id}' not found or not deployed")

    # If HTTP transport, try to start the server first
    connection = integration["connection"]
    if connection["transport"] == "http":
        try:
            await start_deployment_server(ctx, integration_id)
        except Exception as e:
            # If server is already running, that's fine
            if "already_running" not in str(e):
                # Otherwise, log but continue - server might be already running
                pass
        # Give server time to fully initialize
        await asyncio.sleep(1)

    # Use the connection info to connect
    connect_body = ConnectRequest(
        name=integration["integration_name"],
        transport=connection["transport"],
        server_url=connection.get("server_url"),
        command=connection.get("command"),
        working_dir=connection.get("working_dir"),
        integration_id=integration_id,
    )

    return await connect_server(ctx, connect_body)


@router.post("/connect")
async def connect_server(ctx: Ctx, body: ConnectRequest) -> dict:
    """Connect to an MCP server via stdio or HTTP and enumerate tools.

    If ``integration_id`` is provided and a session already exists for it, reuse
    that session when its transport is live; otherwise drop the stale row and
    create a fresh session. This prevents duplicate "petstore"-style rows from
    piling up every time the user clicks Connect.
    """
    # Reuse a live session for this integration if one exists
    if body.integration_id:
        db_session = ctx.db_session_factory()
        try:
            repo = PlaygroundSessionRepository(db_session)
            existing = repo.get_active_by_integration_id(body.integration_id)
        finally:
            db_session.close()
        if existing:
            in_memory = _sessions.get(existing.id)
            client = _clients.get(existing.id)
            if in_memory and client is not None and client.is_alive():
                return {
                    "id": existing.id,
                    "status": "connected",
                    "transport": existing.transport,
                    "name": in_memory.get("name") or existing.name,
                    "server_info": in_memory.get("server_info", existing.server_info or {}),
                    "tools": in_memory.get("tools", existing.tools or []),
                    "tools_count": len(in_memory.get("tools", existing.tools or [])),
                    "connected_at": in_memory.get("connected_at", existing.connected_at),
                    "reused": True,
                }
            # Stale session â€” close the dead client, drop in-memory state and
            # DB row, then fall through to create a new one.
            _sessions.pop(existing.id, None)
            stale_client = _clients.pop(existing.id, None)
            if stale_client is not None:
                try:
                    await stale_client.close()
                except Exception:  # noqa: BLE001
                    pass
            db_session = ctx.db_session_factory()
            try:
                PlaygroundSessionRepository(db_session).delete(existing.id)
            finally:
                db_session.close()

    session_id = str(uuid.uuid4())

    if body.transport == "stdio":
        if not body.command:
            raise HTTPException(status_code=400, detail="Command is required for stdio transport")
        result = await _connect_stdio(session_id, body, ctx)
    elif body.transport == "http":
        if not body.server_url:
            raise HTTPException(status_code=400, detail="Server URL is required for HTTP transport")
        result = await _connect_http(session_id, body, ctx)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported transport: {body.transport}")

    # Persist session metadata to DB
    db_session = ctx.db_session_factory()
    try:
        repo = PlaygroundSessionRepository(db_session)
        sess_data = _sessions.get(session_id, {})
        repo.create(
            id=session_id,
            integration_id=body.integration_id,
            name=sess_data.get("name", body.name or ""),
            transport=body.transport,
            status="connected",
            connected_at=sess_data.get("connected_at", datetime.utcnow().isoformat() + "Z"),
            server_info=sess_data.get("server_info", {}),
            tools=sess_data.get("tools", []),
            command=body.command,
            working_dir=body.working_dir,
            server_url=body.server_url,
        )
    finally:
        db_session.close()

    return result


@router.delete("/sessions/{session_id}")
async def disconnect_session(ctx: Ctx, session_id: str) -> dict:
    """Disconnect and clean up a playground session."""
    db_session = ctx.db_session_factory()
    try:
        repo = PlaygroundSessionRepository(db_session)
        db_sess = repo.get_by_id(session_id)
        in_memory = _sessions.pop(session_id, None)
        if not db_sess and not in_memory:
            raise HTTPException(status_code=404, detail="Session not found")
        if db_sess:
            repo.delete(session_id)
    finally:
        db_session.close()

    # Tear down the live transport (subprocess or HTTP+SSE). The client's
    # own close() is responsible for cancelling reader tasks, waiting on the
    # subprocess with a SIGKILL fallback, closing the HTTP client, and
    # failing every pending future so concurrent callers don't hang.
    client = _clients.pop(session_id, None)
    if client is not None:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass

    return {"message": "Session disconnected", "id": session_id}


# ---------------------------------------------------------------------------
# Tools â€” list and execute
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/tools")
async def list_tools(ctx: Ctx, session_id: str) -> dict:
    """List all tools available on the connected MCP server."""
    # Prefer in-memory session (has live data), fall back to DB
    session = _sessions.get(session_id)
    if session:
        tools = session.get("tools", [])
        return {"tools": tools, "count": len(tools)}
    db_session = ctx.db_session_factory()
    try:
        repo = PlaygroundSessionRepository(db_session)
        db_sess = repo.get_by_id(session_id)
        if not db_sess:
            raise HTTPException(status_code=404, detail="Session not found")
        tools = db_sess.tools or []
        return {"tools": tools, "count": len(tools)}
    finally:
        db_session.close()


async def _run_tool(
    ctx,
    session_id: str,
    tool_name: str,
    arguments: dict,
    *,
    origin: str = "manual",
) -> dict:
    """Execute a tool, persist the result, and return ``{status, result?, error?, latency_ms, executed_at, raw_rpc}``.

    Shared by the manual execute endpoint, the suite runner, and the agent loop
    so every code path records the same shape of execution.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client = _clients.get(session_id)
    if client is None or not client.is_alive():
        # Keep the in-memory status in sync so the UI reflects reality.
        session["status"] = "disconnected"
        raise HTTPException(
            status_code=400,
            detail="Session is not connected. Reconnect to continue testing.",
        )

    tools = session.get("tools", [])
    tool = next((t for t in tools if t.get("name") == tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found on this server")

    start_time = time.time()
    raw_rpc = {
        "request": {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        "response": None,
    }

    try:
        result = await client.call(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=30.0,
        )

        elapsed = round((time.time() - start_time) * 1000, 1)
        executed_at = datetime.utcnow().isoformat() + "Z"
        exec_id = str(uuid.uuid4())
        raw_rpc["response"] = {"jsonrpc": "2.0", "result": result}

        # In-memory history (kept for the UI's live-refresh path)
        execution_record = {
            "id": exec_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "status": "success",
            "latency_ms": elapsed,
            "executed_at": executed_at,
            "origin": origin,
        }
        session.setdefault("executions", []).insert(0, execution_record)
        session["executions"] = session["executions"][:50]

        db_session = ctx.db_session_factory()
        try:
            exec_repo = PlaygroundExecutionRepository(db_session)
            exec_repo.create(
                id=exec_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status="success",
                latency_ms=elapsed,
                executed_at=executed_at,
                raw_rpc=raw_rpc,
                origin=origin,
            )
        finally:
            db_session.close()

        return {
            "id": exec_id,
            "status": "success",
            "tool_name": tool_name,
            "result": result,
            "latency_ms": elapsed,
            "executed_at": executed_at,
            "raw_rpc": raw_rpc,
        }

    except HTTPException:
        raise
    except Exception as e:
        elapsed = round((time.time() - start_time) * 1000, 1)
        executed_at = datetime.utcnow().isoformat() + "Z"
        exec_id = str(uuid.uuid4())
        raw_rpc["response"] = {"jsonrpc": "2.0", "error": {"message": str(e)}}

        # If the transport died under us, reflect that in the session status
        # so subsequent calls short-circuit cleanly and the UI can prompt a
        # reconnect instead of issuing more doomed requests.
        if isinstance(e, MCPDisconnectedError) or not client.is_alive():
            session["status"] = "disconnected"
            db_sess_update = ctx.db_session_factory()
            try:
                PlaygroundSessionRepository(db_sess_update).update(
                    session_id, status="disconnected"
                )
            except Exception:  # noqa: BLE001
                pass
            finally:
                db_sess_update.close()

        execution_record = {
            "id": exec_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": None,
            "error": str(e),
            "status": "error",
            "latency_ms": elapsed,
            "executed_at": executed_at,
            "origin": origin,
        }
        session.setdefault("executions", []).insert(0, execution_record)
        session["executions"] = session["executions"][:50]

        db_session = ctx.db_session_factory()
        try:
            exec_repo = PlaygroundExecutionRepository(db_session)
            exec_repo.create(
                id=exec_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=None,
                error=str(e),
                status="error",
                latency_ms=elapsed,
                executed_at=executed_at,
                raw_rpc=raw_rpc,
                origin=origin,
            )
        finally:
            db_session.close()

        return {
            "id": exec_id,
            "status": "error",
            "tool_name": tool_name,
            "error": str(e),
            "latency_ms": elapsed,
            "executed_at": executed_at,
            "raw_rpc": raw_rpc,
        }


@router.post("/sessions/{session_id}/execute")
async def execute_tool(ctx: Ctx, session_id: str, body: ExecuteToolRequest) -> dict:
    """Execute a tool on the connected MCP server."""
    out = await _run_tool(ctx, session_id, body.tool_name, body.arguments, origin="manual")
    # Keep the legacy response shape for backwards compatibility
    return {
        "status": out["status"],
        "tool_name": out["tool_name"],
        "result": out.get("result"),
        "error": out.get("error"),
        "latency_ms": out["latency_ms"],
        "executed_at": out["executed_at"],
        "raw_rpc": out.get("raw_rpc"),
    }


@router.post("/sessions/{session_id}/suggest-args")
async def suggest_args(ctx: Ctx, session_id: str, body: SuggestArgsRequest) -> dict:
    """Ask the default LLM to produce valid tool arguments from a natural-language intent.

    This mirrors how Claude itself constructs tool_call arguments: it reads the tool's
    ``description`` + ``inputSchema`` and emits a JSON object matching the schema.
    """
    from selqor_forge.dashboard.routes.llm_test import (
        _resolve_config,
    )

    session = _sessions.get(session_id)
    if not session:
        db_session = ctx.db_session_factory()
        try:
            repo = PlaygroundSessionRepository(db_session)
            db_sess = repo.get_by_id(session_id)
            if not db_sess:
                raise HTTPException(status_code=404, detail="Session not found")
            tools = db_sess.tools or []
        finally:
            db_session.close()
    else:
        tools = session.get("tools", [])

    tool = next((t for t in tools if t.get("name") == body.tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{body.tool_name}' not found on this session")

    config = _resolve_config(ctx, body.config_id)
    if config is None:
        raise HTTPException(
            status_code=400,
            detail="No default LLM config set. Configure one in LLM Config before using AI fill.",
        )

    description = tool.get("description") or ""
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    intent = (body.intent or "").strip() or "Produce a reasonable example invocation."

    system_prompt = (
        "You are an MCP tool-argument generator. Given a tool's description, JSON Schema, "
        "and a natural-language intent, emit ONLY a JSON object containing the arguments "
        "that satisfy the schema. Do not include any markdown, comments, or explanation. "
        "If the schema has required fields, they MUST be present. Prefer realistic example "
        "values over nulls/zeros. The response MUST be a single JSON object."
    )
    user_prompt = (
        f"Tool name: {body.tool_name}\n"
        f"Description: {description}\n\n"
        f"Input JSON Schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Intent: {intent}\n\n"
        "Return ONLY the arguments JSON object."
    )

    try:
        text = await _call_llm_for_json(config, system_prompt, user_prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    arguments = _extract_json_object(text)
    if arguments is None:
        raise HTTPException(
            status_code=502,
            detail=f"LLM did not return valid JSON. Got: {text[:200]}",
        )

    return {
        "tool_name": body.tool_name,
        "arguments": arguments,
        "model": config.get("model"),
        "provider": config.get("provider"),
    }


async def _call_llm_for_json(config: dict, system_prompt: str, user_prompt: str) -> str:
    """Call the configured LLM and return the raw text response."""
    import httpx

    provider = (config.get("provider") or "").strip().lower()
    model = (config.get("model") or "").strip()
    if not model:
        raise ValueError("llm config has no model")

    if provider == "anthropic":
        base = (config.get("base_url") or "").strip() or "https://api.anthropic.com"
        url = f"{base.rstrip('/')}/v1/messages"
        api_key = (config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("anthropic API key is required")
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "x-api-key": api_key,
        }
        for k, v in (config.get("custom_headers") or {}).items():
            if k.strip() and v.strip():
                headers[k.strip()] = v.strip()
        payload = {
            "model": model,
            "max_tokens": 1024,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if not resp.is_success:
            raise ValueError(f"Anthropic error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        # Collect text blocks
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)

    # OpenAI-compatible (openai, mistral, sarvam, etc.)
    default_bases = {
        "openai": "https://api.openai.com",
        "mistral": "https://api.mistral.ai",
        "sarvam": "https://api.sarvam.ai",
    }
    base = (config.get("base_url") or "").strip() or default_bases.get(provider, "")
    if not base:
        raise ValueError(f"{provider or 'provider'} requires a base URL")
    url = f"{base.rstrip('/')}/v1/chat/completions"
    headers: dict[str, str] = {"content-type": "application/json"}
    auth_type = (config.get("auth_type") or "api_key").strip().lower()
    api_key = (config.get("api_key") or "").strip()
    bearer = (config.get("bearer_token") or "").strip()
    if auth_type == "api_key" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "bearer" and (bearer or api_key):
        headers["Authorization"] = f"Bearer {bearer or api_key}"
    for k, v in (config.get("custom_headers") or {}).items():
        if k.strip() and v.strip():
            headers[k.strip()] = v.strip()
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if not resp.is_success:
        raise ValueError(f"{provider} error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


def _extract_json_object(text: str) -> dict | None:
    """Extract the first JSON object from an arbitrary LLM response string."""
    if not text:
        return None
    # Strip common code fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json ... ```
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    # Try direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    # Fallback: find first { ... } balanced block
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return None
    return None


@router.get("/sessions/{session_id}/history")
async def execution_history(ctx: Ctx, session_id: str) -> dict:
    """Get execution history for a session."""
    # Prefer in-memory if available (freshest), otherwise query DB
    session = _sessions.get(session_id)
    if session:
        return {"executions": session.get("executions", [])}
    db_session = ctx.db_session_factory()
    try:
        sess_repo = PlaygroundSessionRepository(db_session)
        db_sess = sess_repo.get_by_id(session_id)
        if not db_sess:
            raise HTTPException(status_code=404, detail="Session not found")
        exec_repo = PlaygroundExecutionRepository(db_session)
        executions = exec_repo.list_by_session(session_id, limit=50)
        return {
            "executions": [_model_to_dict(e) for e in executions],
        }
    finally:
        db_session.close()


# ---------------------------------------------------------------------------
# Health check for connected session
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/health")
async def health_check(ctx: Ctx, session_id: str) -> dict:
    """Check if the connected server is still responsive."""
    session = _sessions.get(session_id)
    if not session:
        db_session = ctx.db_session_factory()
        try:
            repo = PlaygroundSessionRepository(db_session)
            db_sess = repo.get_by_id(session_id)
            if not db_sess:
                raise HTTPException(status_code=404, detail="Session not found")
            # Build a minimal session dict from DB for the checks below
            session = _model_to_dict(db_sess)
        finally:
            db_session.close()

    client = _clients.get(session_id)
    if client is None or not client.is_alive():
        if isinstance(session, dict) and session_id in _sessions:
            session["status"] = "disconnected"
        db_session = ctx.db_session_factory()
        try:
            PlaygroundSessionRepository(db_session).update(session_id, status="disconnected")
        finally:
            db_session.close()
        reason = "Transport is down."
        if client is not None:
            # Surface the close_reason when the client knows why it died.
            close_reason = getattr(client, "_close_reason", None)
            if close_reason:
                reason = close_reason
        return {"healthy": False, "status": "disconnected", "reason": reason}

    # Transport looks alive locally. For stdio that's enough; for HTTP+SSE we
    # additionally ping the server via the MCP ``ping`` RPC if the server
    # advertises it, otherwise we trust the SSE stream's liveness.
    return {"healthy": True, "status": "connected", "transport": session.get("transport")}


# ---------------------------------------------------------------------------
# Test cases â€” saveable args + assertions, run against live session
# ---------------------------------------------------------------------------


def _require_session(ctx, session_id: str) -> tuple[dict, Any]:
    """Return (live_session_dict, db_session_row). Either may be None if missing."""
    live = _sessions.get(session_id)
    if live:
        return live, None
    db_session = ctx.db_session_factory()
    try:
        repo = PlaygroundSessionRepository(db_session)
        db_sess = repo.get_by_id(session_id)
    finally:
        db_session.close()
    if not db_sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return _model_to_dict(db_sess), db_sess


def _tool_exists(live: dict, tool_name: str) -> bool:
    tools = live.get("tools") or []
    return any((t.get("name") if isinstance(t, dict) else t) == tool_name for t in tools)


@router.get("/sessions/{session_id}/testcases")
async def list_testcases(ctx: Ctx, session_id: str, tool_name: str | None = None) -> dict:
    """List test cases for a session (optionally filtered by tool name)."""
    _require_session(ctx, session_id)
    db = ctx.db_session_factory()
    try:
        repo = PlaygroundTestCaseRepository(db)
        items = repo.list_by_session(session_id, tool_name)
        return {"testcases": [_model_to_dict(i) for i in items]}
    finally:
        db.close()


@router.post("/sessions/{session_id}/testcases")
async def create_testcase(ctx: Ctx, session_id: str, body: TestCaseRequest) -> dict:
    """Create a new test case bound to this session and tool."""
    live, _ = _require_session(ctx, session_id)
    if not _tool_exists(live, body.tool_name):
        raise HTTPException(
            status_code=400,
            detail=f"Tool '{body.tool_name}' is not available on this session.",
        )
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Test case name is required.")

    assertions = validate_assertions(body.assertions)
    db = ctx.db_session_factory()
    try:
        repo = PlaygroundTestCaseRepository(db)
        now = datetime.utcnow().isoformat() + "Z"
        tc = repo.create(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=body.tool_name,
            name=body.name.strip(),
            description=(body.description or "").strip() or None,
            arguments=body.arguments or {},
            assertions=assertions,
            created_at=now,
            updated_at=now,
        )
        return {"testcase": _model_to_dict(tc)}
    finally:
        db.close()


@router.patch("/testcases/{testcase_id}")
async def update_testcase(ctx: Ctx, testcase_id: str, body: TestCaseUpdateRequest) -> dict:
    """Partial update of a test case."""
    db = ctx.db_session_factory()
    try:
        repo = PlaygroundTestCaseRepository(db)
        tc = repo.get_by_id(testcase_id)
        if not tc:
            raise HTTPException(status_code=404, detail="Test case not found")
        patch: dict = {"updated_at": datetime.utcnow().isoformat() + "Z"}
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Name cannot be empty")
            patch["name"] = name
        if body.description is not None:
            patch["description"] = body.description.strip() or None
        if body.arguments is not None:
            patch["arguments"] = body.arguments
        if body.assertions is not None:
            patch["assertions"] = validate_assertions(body.assertions)
        updated = repo.update(testcase_id, **patch)
        return {"testcase": _model_to_dict(updated)}
    finally:
        db.close()


@router.delete("/testcases/{testcase_id}")
async def delete_testcase(ctx: Ctx, testcase_id: str) -> dict:
    db = ctx.db_session_factory()
    try:
        repo = PlaygroundTestCaseRepository(db)
        if not repo.get_by_id(testcase_id):
            raise HTTPException(status_code=404, detail="Test case not found")
        repo.delete(testcase_id)
        return {"deleted": testcase_id}
    finally:
        db.close()


async def _run_one_testcase(ctx, session_id: str, tc) -> dict:
    """Execute a single test case against the live session and persist a PlaygroundTestRun."""
    exec_out = await _run_tool(
        ctx, session_id, tc.tool_name, tc.arguments or {}, origin="suite",
    )
    status = exec_out["status"]
    latency = exec_out.get("latency_ms")
    result = exec_out.get("result") if status == "success" else None
    error = exec_out.get("error")
    overall, outcomes = evaluate_all(
        tc.assertions or [],
        result=result,
        status=status,
        latency_ms=latency,
    )
    # If the tool call itself crashed, that's a run error, not a plain fail.
    if status == "error" and not (tc.assertions or []):
        overall = "error"

    # Ensure assertion outcomes are JSON-safe (actual values may contain complex stuff)
    safe_outcomes = [
        {**o, "actual": ensure_jsonable(o.get("actual"))} for o in outcomes
    ]

    now = datetime.utcnow().isoformat() + "Z"
    db = ctx.db_session_factory()
    try:
        run_repo = PlaygroundTestRunRepository(db)
        run = run_repo.create(
            id=str(uuid.uuid4()),
            testcase_id=tc.id,
            session_id=session_id,
            tool_name=tc.tool_name,
            status=overall,
            assertion_results=safe_outcomes,
            result=result,
            error=error,
            latency_ms=latency,
            executed_at=now,
        )
        # Update cached last-run on the case
        tc_repo = PlaygroundTestCaseRepository(db)
        tc_repo.update(tc.id, last_status=overall, last_run_at=now)
    finally:
        db.close()
    return {
        "testcase_id": tc.id,
        "name": tc.name,
        "tool_name": tc.tool_name,
        "status": overall,
        "latency_ms": latency,
        "error": error,
        "assertion_results": safe_outcomes,
        "executed_at": now,
        "run_id": run.id,
    }


@router.post("/sessions/{session_id}/run-suite")
async def run_suite(ctx: Ctx, session_id: str, body: RunSuiteRequest) -> dict:
    """Run saved test cases against the live MCP session, evaluate assertions, return summary."""
    _require_session(ctx, session_id)
    db = ctx.db_session_factory()
    try:
        repo = PlaygroundTestCaseRepository(db)
        if body.testcase_ids:
            cases = [c for c in (repo.get_by_id(i) for i in body.testcase_ids) if c is not None]
        else:
            cases = repo.list_by_session(session_id)
    finally:
        db.close()

    if not cases:
        return {
            "summary": {"total": 0, "passed": 0, "failed": 0, "errored": 0},
            "results": [],
        }

    results: list[dict] = []
    for tc in cases:
        try:
            results.append(await _run_one_testcase(ctx, session_id, tc))
        except HTTPException as exc:
            results.append({
                "testcase_id": tc.id,
                "name": tc.name,
                "tool_name": tc.tool_name,
                "status": "error",
                "error": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "assertion_results": [],
            })

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
        "errored": sum(1 for r in results if r["status"] == "error"),
    }
    return {"summary": summary, "results": results}


@router.get("/testcases/{testcase_id}/runs")
async def testcase_runs(ctx: Ctx, testcase_id: str) -> dict:
    """List recent runs for a test case."""
    db = ctx.db_session_factory()
    try:
        tc = PlaygroundTestCaseRepository(db).get_by_id(testcase_id)
        if not tc:
            raise HTTPException(status_code=404, detail="Test case not found")
        runs = PlaygroundTestRunRepository(db).list_by_testcase(testcase_id)
        return {"runs": [_model_to_dict(r) for r in runs]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per-tool stats + raw JSON-RPC trace
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Nearest-rank; good enough for small N that a playground produces.
    rank = max(0, min(len(sorted_values) - 1, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[rank]


@router.get("/sessions/{session_id}/stats")
async def session_stats(ctx: Ctx, session_id: str) -> dict:
    """Per-tool aggregates for the session: invocations, success/error rate, p50/p95 latency."""
    _require_session(ctx, session_id)
    db = ctx.db_session_factory()
    try:
        exec_repo = PlaygroundExecutionRepository(db)
        rows = exec_repo.list_for_stats(session_id)
    finally:
        db.close()

    by_tool: dict[str, dict] = {}
    for row in rows:
        bucket = by_tool.setdefault(row.tool_name, {
            "tool_name": row.tool_name,
            "invocations": 0,
            "successes": 0,
            "errors": 0,
            "latencies": [],
            "last_error": None,
            "last_status": None,
            "last_executed_at": None,
        })
        bucket["invocations"] += 1
        if row.status == "success":
            bucket["successes"] += 1
        else:
            bucket["errors"] += 1
            if bucket["last_error"] is None:
                bucket["last_error"] = row.error
        if row.latency_ms is not None:
            bucket["latencies"].append(row.latency_ms)
        if bucket["last_status"] is None:
            bucket["last_status"] = row.status
            bucket["last_executed_at"] = row.executed_at

    stats: list[dict] = []
    for bucket in by_tool.values():
        latencies = sorted(bucket.pop("latencies"))
        total = bucket["invocations"]
        bucket["success_rate"] = round(bucket["successes"] / total, 3) if total else 0.0
        bucket["error_rate"] = round(bucket["errors"] / total, 3) if total else 0.0
        bucket["p50_ms"] = _percentile(latencies, 50)
        bucket["p95_ms"] = _percentile(latencies, 95)
        stats.append(bucket)

    stats.sort(key=lambda s: s["invocations"], reverse=True)
    overall_total = sum(s["invocations"] for s in stats)
    overall_errors = sum(s["errors"] for s in stats)
    return {
        "stats": stats,
        "total_invocations": overall_total,
        "overall_error_rate": round(overall_errors / overall_total, 3) if overall_total else 0.0,
    }


@router.get("/sessions/{session_id}/trace")
async def session_trace(ctx: Ctx, session_id: str, limit: int = 25) -> dict:
    """Return the raw JSON-RPC frames from recent executions, newest-first."""
    _require_session(ctx, session_id)
    limit = max(1, min(100, int(limit)))
    db = ctx.db_session_factory()
    try:
        exec_repo = PlaygroundExecutionRepository(db)
        rows = exec_repo.list_by_session(session_id, limit=limit)
    finally:
        db.close()
    frames = []
    for row in rows:
        frames.append({
            "id": row.id,
            "tool_name": row.tool_name,
            "status": row.status,
            "origin": getattr(row, "origin", None) or "manual",
            "latency_ms": row.latency_ms,
            "executed_at": row.executed_at,
            "raw_rpc": getattr(row, "raw_rpc", None),
        })
    return {"frames": frames}


# ---------------------------------------------------------------------------
# Agent-in-the-loop chat
# ---------------------------------------------------------------------------


def _tools_to_anthropic_schema(tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to Anthropic ``tool_use`` schema."""
    out: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        schema = t.get("inputSchema") or t.get("input_schema") or {"type": "object", "properties": {}}
        out.append({
            "name": t["name"],
            "description": t.get("description") or "",
            "input_schema": schema,
        })
    return out


def _tools_to_openai_schema(tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to OpenAI ``function`` tools."""
    out: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        schema = t.get("inputSchema") or t.get("input_schema") or {"type": "object", "properties": {}}
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": schema,
            },
        })
    return out


async def _anthropic_turn(config: dict, system_prompt: str, messages: list[dict], tools_schema: list[dict]) -> dict:
    """Single call to Anthropic /v1/messages with tool_use."""
    import httpx
    base = (config.get("base_url") or "https://api.anthropic.com").rstrip("/")
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("Anthropic API key missing")
    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "x-api-key": api_key,
    }
    payload = {
        "model": config["model"],
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": messages,
        "tools": tools_schema,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{base}/v1/messages", json=payload, headers=headers)
    if not resp.is_success:
        raise ValueError(f"Anthropic error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


async def _openai_turn(config: dict, system_prompt: str, messages: list[dict], tools_schema: list[dict]) -> dict:
    """Single call to an OpenAI-compatible chat/completions endpoint with tool calls."""
    import httpx
    default_bases = {
        "openai": "https://api.openai.com",
        "mistral": "https://api.mistral.ai",
        "sarvam": "https://api.sarvam.ai",
    }
    provider = (config.get("provider") or "").strip().lower()
    base = (config.get("base_url") or default_bases.get(provider, "")).rstrip("/")
    if not base:
        raise ValueError(f"{provider or 'provider'} requires a base URL")
    headers: dict[str, str] = {"content-type": "application/json"}
    auth_type = (config.get("auth_type") or "api_key").strip().lower()
    api_key = (config.get("api_key") or "").strip()
    bearer = (config.get("bearer_token") or "").strip()
    if auth_type == "api_key" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "bearer" and (bearer or api_key):
        headers["Authorization"] = f"Bearer {bearer or api_key}"
    # Preserve the system prompt as a message, prepend only if caller didn't.
    chat_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = {
        "model": config["model"],
        "messages": chat_messages,
        "tools": tools_schema,
        "tool_choice": "auto",
        "max_tokens": 1024,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{base}/v1/chat/completions", json=payload, headers=headers)
    if not resp.is_success:
        raise ValueError(f"{provider} error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


@router.post("/sessions/{session_id}/agent-chat")
async def agent_chat(ctx: Ctx, session_id: str, body: AgentChatRequest) -> dict:
    """Run a short agent-in-the-loop conversation against the live MCP session.

    The agent iterates: LLM proposes tool call(s) â†’ playground executes â†’ result fed
    back â†’ LLM produces next turn, until the LLM stops calling tools or
    ``max_iterations`` is reached. Returns the full trace plus the final message.

    Currently supports Anthropic (``messages`` + ``tool_use``) and OpenAI-compatible
    (``chat/completions`` + ``tools``) providers. Other providers surface an error.
    """
    from selqor_forge.dashboard.routes.llm_test import _resolve_config

    live, _ = _require_session(ctx, session_id)
    if live.get("status") != "connected":
        raise HTTPException(status_code=400, detail="Session is not connected")

    tools = live.get("tools") or []
    if not tools:
        raise HTTPException(status_code=400, detail="Session has no tools to invoke")

    config = _resolve_config(ctx, body.config_id)
    if config is None:
        raise HTTPException(
            status_code=400,
            detail="No default LLM config set. Configure one in LLM Config before using agent chat.",
        )
    provider = (config.get("provider") or "").strip().lower()
    if provider not in ("anthropic", "openai", "mistral", "sarvam"):
        raise HTTPException(
            status_code=400,
            detail=f"Agent chat currently supports anthropic and openai-compatible providers; got '{provider}'.",
        )

    system_prompt = body.system_prompt or (
        "You are a helpful assistant connected to a live MCP server. "
        "Use the provided tools to fulfill the user's request. Prefer a tool over "
        "guessing. When you have the answer, reply in plain text and stop calling tools."
    )

    max_iter = max(1, min(12, body.max_iterations or 6))
    trace: list[dict] = []
    tools_used: list[str] = []
    started = time.time()
    status = "completed"
    error: str | None = None
    final_message: str | None = None

    try:
        if provider == "anthropic":
            tools_schema = _tools_to_anthropic_schema(tools)
            messages: list[dict] = [{"role": "user", "content": body.message}]
            trace.append({"role": "user", "content": body.message})

            for i in range(max_iter):
                data = await _anthropic_turn(config, system_prompt, messages, tools_schema)
                blocks = data.get("content") or []
                # Append the assistant message in Anthropic shape for the next turn.
                messages.append({"role": "assistant", "content": blocks})

                text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
                trace.append({
                    "role": "assistant",
                    "iteration": i + 1,
                    "text": "".join(text_parts),
                    "tool_calls": [{"name": b.get("name"), "arguments": b.get("input") or {}} for b in tool_uses],
                    "stop_reason": data.get("stop_reason"),
                })

                if not tool_uses:
                    final_message = "".join(text_parts).strip() or None
                    break

                # Execute each requested tool and feed results back.
                tool_results_block: list[dict] = []
                for tu in tool_uses:
                    tname = tu.get("name") or ""
                    targs = tu.get("input") or {}
                    if not _tool_exists(live, tname):
                        tool_results_block.append({
                            "type": "tool_result",
                            "tool_use_id": tu.get("id"),
                            "content": f"Error: tool '{tname}' does not exist on this server.",
                            "is_error": True,
                        })
                        trace.append({"role": "tool", "tool_name": tname, "status": "error",
                                      "error": "unknown tool"})
                        continue
                    tools_used.append(tname)
                    exec_out = await _run_tool(ctx, session_id, tname, targs, origin="agent")
                    # Anthropic tool_result content must be a string or list of blocks; we
                    # serialize MCP result to JSON text for the model to consume.
                    content_text = json.dumps(exec_out.get("result") if exec_out["status"] == "success" else {"error": exec_out.get("error")})
                    tool_results_block.append({
                        "type": "tool_result",
                        "tool_use_id": tu.get("id"),
                        "content": content_text,
                        "is_error": exec_out["status"] != "success",
                    })
                    trace.append({
                        "role": "tool",
                        "tool_name": tname,
                        "arguments": targs,
                        "status": exec_out["status"],
                        "latency_ms": exec_out.get("latency_ms"),
                        "error": exec_out.get("error"),
                        "result_preview": (content_text[:500] + "â€¦") if len(content_text) > 500 else content_text,
                    })

                messages.append({"role": "user", "content": tool_results_block})
            else:
                status = "max_iterations"

        else:  # OpenAI-compatible (openai/mistral/sarvam) with function calls
            tools_schema = _tools_to_openai_schema(tools)
            oa_messages: list[dict] = [{"role": "user", "content": body.message}]
            trace.append({"role": "user", "content": body.message})

            for i in range(max_iter):
                data = await _openai_turn(config, system_prompt, oa_messages, tools_schema)
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                oa_messages.append(msg)
                tool_calls = msg.get("tool_calls") or []
                text = msg.get("content") or ""
                trace.append({
                    "role": "assistant",
                    "iteration": i + 1,
                    "text": text,
                    "tool_calls": [
                        {
                            "name": (tc.get("function") or {}).get("name"),
                            "arguments": _safe_json(tc.get("function", {}).get("arguments")),
                        }
                        for tc in tool_calls
                    ],
                    "stop_reason": choice.get("finish_reason"),
                })
                if not tool_calls:
                    final_message = text.strip() or None
                    break

                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    tname = fn.get("name") or ""
                    targs = _safe_json(fn.get("arguments")) or {}
                    if not _tool_exists(live, tname):
                        oa_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": json.dumps({"error": f"unknown tool '{tname}'"}),
                        })
                        trace.append({"role": "tool", "tool_name": tname, "status": "error",
                                      "error": "unknown tool"})
                        continue
                    tools_used.append(tname)
                    exec_out = await _run_tool(ctx, session_id, tname, targs, origin="agent")
                    content = json.dumps(exec_out.get("result") if exec_out["status"] == "success"
                                         else {"error": exec_out.get("error")})
                    oa_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": content,
                    })
                    trace.append({
                        "role": "tool",
                        "tool_name": tname,
                        "arguments": targs,
                        "status": exec_out["status"],
                        "latency_ms": exec_out.get("latency_ms"),
                        "error": exec_out.get("error"),
                        "result_preview": (content[:500] + "â€¦") if len(content) > 500 else content,
                    })
            else:
                status = "max_iterations"

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        status = "error"
        error = str(exc)

    total_ms = round((time.time() - started) * 1000, 1)

    # Persist the run for future introspection
    db = ctx.db_session_factory()
    try:
        PlaygroundAgentRunRepository(db).create(
            id=str(uuid.uuid4()),
            session_id=session_id,
            user_message=body.message,
            final_message=final_message,
            trace=trace,
            tools_used=tools_used,
            iterations=sum(1 for t in trace if t.get("role") == "assistant"),
            status=status,
            error=error,
            total_latency_ms=total_ms,
            llm_model=config.get("model"),
            llm_provider=provider,
            created_at=datetime.utcnow().isoformat() + "Z",
        )
    finally:
        db.close()

    return {
        "status": status,
        "final_message": final_message,
        "trace": trace,
        "tools_used": tools_used,
        "iterations": sum(1 for t in trace if t.get("role") == "assistant"),
        "total_latency_ms": total_ms,
        "error": error,
        "llm_model": config.get("model"),
        "llm_provider": provider,
    }


@router.get("/sessions/{session_id}/agent-runs")
async def list_agent_runs(ctx: Ctx, session_id: str) -> dict:
    """Recent agent-chat runs for this session."""
    _require_session(ctx, session_id)
    db = ctx.db_session_factory()
    try:
        rows = PlaygroundAgentRunRepository(db).list_by_session(session_id)
        return {"runs": [_model_to_dict(r) for r in rows]}
    finally:
        db.close()


def _safe_json(text: Any) -> Any:
    """Tolerant JSON parse for OpenAI tool_call.arguments (which is a JSON string)."""
    if text is None:
        return {}
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Transport connect helpers â€” thin wrappers around MCPClient implementations
# ---------------------------------------------------------------------------


async def _connect_stdio(session_id: str, body: ConnectRequest, ctx) -> dict:
    """Launch a stdio MCP server as a child process and complete the MCP handshake."""
    import os
    import shlex

    cmd_parts = shlex.split(body.command or "")
    if not cmd_parts:
        raise HTTPException(status_code=400, detail="Command is empty after shell splitting.")

    working_dir = body.working_dir or None
    env: dict[str, str] | None = None
    if body.env_vars:
        env = {**os.environ, **body.env_vars}

    client = StdioMCPClient(
        command=body.command,
        working_dir=working_dir,
        env=env,
    )

    try:
        server_info = await client.connect(init_timeout=10.0)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MCPError as exc:
        await client.close()
        raise HTTPException(status_code=400, detail=f"MCP initialization failed: {exc}")
    except (ConnectionError, MCPDisconnectedError) as exc:
        await client.close()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        await client.close()
        raise HTTPException(status_code=500, detail=f"Failed to start MCP server: {exc}")

    try:
        tools = await client.list_tools(timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        # Non-fatal: some servers expose no tools or delay the tools/list
        # response. Keep the session connected so the user can still use it.
        tools = []
        logger_msg = f"tools/list failed for session {session_id}: {exc}"
        import logging
        logging.getLogger(__name__).warning(logger_msg)

    _clients[session_id] = client

    session = {
        "name": body.name or f"stdio-{cmd_parts[0]}",
        "transport": "stdio",
        "status": "connected",
        "connected_at": datetime.utcnow().isoformat() + "Z",
        "server_info": server_info,
        "tools": tools,
        "command": body.command,
        "working_dir": body.working_dir,
        "executions": [],
    }
    _sessions[session_id] = session

    return {
        "id": session_id,
        "status": "connected",
        "transport": "stdio",
        "name": session["name"],
        "server_info": server_info,
        "tools": tools,
        "tools_count": len(tools),
        "connected_at": session["connected_at"],
    }


async def _connect_http(session_id: str, body: ConnectRequest, ctx) -> dict:
    """Connect to an MCP server using HTTP+SSE transport and complete the handshake."""
    base_url = (body.server_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="server_url is required for HTTP transport")

    client = HttpSseMCPClient(server_url=base_url)
    try:
        server_info = await client.connect(init_timeout=10.0)
    except MCPError as exc:
        await client.close()
        raise HTTPException(status_code=400, detail=f"MCP initialization failed: {exc}")
    except (ConnectionError, MCPDisconnectedError) as exc:
        await client.close()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        await client.close()
        raise HTTPException(status_code=400, detail=f"MCP handshake failed: {exc}")

    try:
        tools = await client.list_tools(timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        tools = []
        import logging
        logging.getLogger(__name__).warning(
            "tools/list failed for session %s: %s", session_id, exc
        )

    _clients[session_id] = client

    session = {
        "name": body.name or base_url,
        "transport": "http",
        "status": "connected",
        "connected_at": datetime.utcnow().isoformat() + "Z",
        "server_info": server_info,
        "tools": tools,
        "server_url": base_url,
        "mcp_messages_url": client.messages_url,
        "executions": [],
    }
    _sessions[session_id] = session

    return {
        "id": session_id,
        "status": "connected",
        "transport": "http",
        "name": session["name"],
        "server_info": server_info,
        "tools": tools,
        "tools_count": len(tools),
        "connected_at": session["connected_at"],
    }

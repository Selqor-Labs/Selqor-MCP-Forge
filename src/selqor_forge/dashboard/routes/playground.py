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

_sessions: dict[str, dict] = {}
_processes: dict[str, subprocess.Popen] = {}

# SSE transport state (for HTTP MCP servers using SSE protocol)
_sse_tasks: dict[str, "asyncio.Task"] = {}
_sse_clients: dict[str, Any] = {}  # httpx.AsyncClient
_sse_queues: dict[str, "asyncio.Queue"] = {}


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

        # Use npm run dev directly in the server directory
        cmd_parts = ["npm", "run", "dev"]

        try:
            proc = subprocess.Popen(
                cmd_parts,
                cwd=server_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            _deployment_processes[integration_id] = proc
            await asyncio.sleep(2)  # Give server time to start

            if proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:500] if proc.stderr else ""
                raise HTTPException(status_code=500, detail=f"Server failed to start: {stderr}")

            return {
                "status": "started",
                "integration_id": integration_id,
                "message": "MCP server started successfully",
            }
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
            # Merge live status from _processes
            live_status = s.status
            proc = _processes.get(s.id)
            if s.transport == "stdio":
                if proc and proc.poll() is None:
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
    )

    return await connect_server(ctx, connect_body)


@router.post("/connect")
async def connect_server(ctx: Ctx, body: ConnectRequest) -> dict:
    """Connect to an MCP server via stdio or HTTP and enumerate tools."""
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

    # Kill subprocess if stdio
    proc = _processes.pop(session_id, None)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # Cancel SSE background task and close client if HTTP
    sse_task = _sse_tasks.pop(session_id, None)
    if sse_task:
        sse_task.cancel()
    sse_client = _sse_clients.pop(session_id, None)
    if sse_client:
        try:
            await sse_client.aclose()
        except Exception:
            pass
    _sse_queues.pop(session_id, None)

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

    if session.get("status") != "connected":
        raise HTTPException(status_code=400, detail="Session is not connected")

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
        if session["transport"] == "stdio":
            result = await _execute_stdio_tool(session_id, tool_name, arguments)
        else:
            result = await _execute_http_tool(session_id, session, tool_name, arguments)

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

    if session.get("transport") == "stdio":
        proc = _processes.get(session_id)
        if not proc or proc.poll() is not None:
            # Update status in memory and DB
            if isinstance(session, dict) and session_id in _sessions:
                session["status"] = "disconnected"
            db_session = ctx.db_session_factory()
            try:
                PlaygroundSessionRepository(db_session).update(session_id, status="disconnected")
            finally:
                db_session.close()
            return {"healthy": False, "status": "disconnected", "reason": "Process exited"}
        return {"healthy": True, "status": "connected"}
    else:
        # HTTP: ping the server
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(session.get("server_url", "").rstrip("/"))
                return {"healthy": resp.status_code < 500, "status": "connected", "http_status": resp.status_code}
        except Exception as e:
            if isinstance(session, dict) and session_id in _sessions:
                session["status"] = "disconnected"
            db_session = ctx.db_session_factory()
            try:
                PlaygroundSessionRepository(db_session).update(session_id, status="disconnected")
            finally:
                db_session.close()
            return {"healthy": False, "status": "disconnected", "reason": str(e)}


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
# Internal helpers â€” stdio transport
# ---------------------------------------------------------------------------

async def _connect_stdio(session_id: str, body: ConnectRequest, ctx) -> dict:
    """Connect to an MCP server via stdio subprocess using JSON-RPC."""
    import shlex

    cmd_parts = shlex.split(body.command)
    working_dir = body.working_dir or "."

    env = None
    if body.env_vars:
        import os
        env = {**os.environ, **body.env_vars}

    try:
        proc = subprocess.Popen(
            cmd_parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_dir,
            env=env,
            bufsize=0,
        )
        _processes[session_id] = proc
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"Command not found: {cmd_parts[0]}. Ensure the server is built and the command is correct.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {e}")

    # Give the process a moment to start
    await asyncio.sleep(0.5)

    if proc.poll() is not None:
        stderr_output = ""
        try:
            stderr_output = proc.stderr.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        _processes.pop(session_id, None)
        raise HTTPException(
            status_code=400,
            detail=f"Server process exited immediately. Stderr: {stderr_output}" if stderr_output else "Server process exited immediately. Check that the command and working directory are correct.",
        )

    # Send MCP initialize request
    try:
        init_result = await _send_jsonrpc(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "selqor-forge-playground", "version": "0.1.0"},
        }, timeout=10)

        # Send initialized notification
        _send_notification(proc, "notifications/initialized", {})

        server_info = init_result.get("result", {}).get("serverInfo", {})

    except Exception as e:
        proc.terminate()
        _processes.pop(session_id, None)
        raise HTTPException(status_code=400, detail=f"MCP initialization failed: {e}. Is this a valid MCP server?")

    # List tools
    try:
        tools_result = await _send_jsonrpc(proc, "tools/list", {}, timeout=10)
        tools = tools_result.get("result", {}).get("tools", [])
    except Exception:
        tools = []

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
        "_msg_id": 3,  # next JSON-RPC message ID (1=init, 2=tools/list)
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
    """Connect to an MCP server using SSE transport (MCP HTTP+SSE protocol).

    Flow:
    1. GET {base_url}/sse  â†’ server sends ``event: endpoint\\ndata: /messages?sessionId=XXX``
    2. POST {base_url}/messages?sessionId=XXX  â†’ send JSON-RPC requests
    3. SSE stream receives JSON-RPC responses as ``event: message\\ndata: {...}``
    """
    import httpx

    base_url = body.server_url.rstrip("/")
    sse_url = f"{base_url}/sse"

    # Queue used to pass SSE events from the background reader to the caller
    response_queue: asyncio.Queue = asyncio.Queue()

    # Persistent async client â€” kept alive for the lifetime of the session
    sse_client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))

    async def _sse_reader():
        """Background task: read the SSE stream and enqueue events."""
        try:
            async with sse_client.stream(
                "GET", sse_url, headers={"Accept": "text/event-stream"}
            ) as resp:
                if resp.status_code != 200:
                    await response_queue.put({"event": "error", "data": f"SSE returned {resp.status_code}"})
                    return
                event_type: str | None = None
                data_lines: list[str] = []
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        data_lines = []
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line == "":
                        # Blank line = end of event block
                        if event_type:
                            await response_queue.put(
                                {"event": event_type, "data": "\n".join(data_lines)}
                            )
                        event_type = None
                        data_lines = []
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await response_queue.put({"event": "error", "data": str(exc)})

    # Launch SSE reader as a background task
    sse_task = asyncio.create_task(_sse_reader())

    async def _wait_event(timeout: float = 10.0) -> dict:
        """Wait for the next non-notification SSE event."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            evt = await asyncio.wait_for(response_queue.get(), timeout=remaining)
            if evt.get("event") == "error":
                raise RuntimeError(evt.get("data", "SSE error"))
            # Skip notifications (no id field) that arrive between our requests
            if evt.get("event") == "message":
                try:
                    payload = json.loads(evt.get("data", "{}"))
                    if "id" in payload:
                        return evt
                    # Notification â€” put back? No, just skip.
                except Exception:
                    pass
                continue
            return evt  # e.g. "endpoint"

    # ------------------------------------------------------------------ #
    # Step 1 â€” wait for the endpoint event
    # ------------------------------------------------------------------ #
    try:
        endpoint_evt = await asyncio.wait_for(response_queue.get(), timeout=10.0)
    except asyncio.TimeoutError:
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(
            status_code=400,
            detail=f"Timeout waiting for SSE endpoint from {sse_url}. Is the server running?",
        )

    if endpoint_evt.get("event") == "error":
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot connect to MCP server at {base_url}: {endpoint_evt.get('data')}",
        )

    if endpoint_evt.get("event") != "endpoint":
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(
            status_code=400,
            detail=f"Expected 'endpoint' SSE event, got '{endpoint_evt.get('event')}'",
        )

    endpoint_path = endpoint_evt.get("data", "")
    if endpoint_path.startswith("/"):
        messages_url = f"{base_url}{endpoint_path}"
    else:
        messages_url = endpoint_path

    # ------------------------------------------------------------------ #
    # Step 2 â€” initialize
    # ------------------------------------------------------------------ #
    tools: list[dict] = []
    server_info: dict = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as post_client:
            await post_client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "selqor-forge-playground", "version": "0.1.0"},
                    },
                },
                headers={"Content-Type": "application/json"},
            )

        # Wait for initialize response on SSE stream
        init_evt = await _wait_event(timeout=10.0)
        init_data = json.loads(init_evt.get("data", "{}"))
        server_info = init_data.get("result", {}).get("serverInfo", {})

        # Step 3 â€” send initialized notification (no response expected)
        async with httpx.AsyncClient(timeout=5.0) as post_client:
            await post_client.post(
                messages_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                headers={"Content-Type": "application/json"},
            )

        # Step 4 â€” list tools
        async with httpx.AsyncClient(timeout=10.0) as post_client:
            await post_client.post(
                messages_url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={"Content-Type": "application/json"},
            )

        tools_evt = await _wait_event(timeout=10.0)
        tools_data = json.loads(tools_evt.get("data", "{}"))
        tools = tools_data.get("result", {}).get("tools", [])

    except httpx.ConnectError:
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(status_code=400, detail=f"Cannot connect to {base_url}. Is the server running?")
    except asyncio.TimeoutError:
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(status_code=400, detail=f"MCP handshake timed out with {base_url}.")
    except Exception as exc:
        sse_task.cancel()
        await sse_client.aclose()
        raise HTTPException(status_code=400, detail=f"MCP handshake failed: {exc}")

    # Store SSE state for this session
    _sse_tasks[session_id] = sse_task
    _sse_clients[session_id] = sse_client
    _sse_queues[session_id] = response_queue

    session = {
        "name": body.name or base_url,
        "transport": "http",
        "status": "connected",
        "connected_at": datetime.utcnow().isoformat() + "Z",
        "server_info": server_info,
        "tools": tools,
        "server_url": base_url,
        "mcp_messages_url": messages_url,
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


# ---------------------------------------------------------------------------
# JSON-RPC helpers for stdio
# ---------------------------------------------------------------------------

_MSG_ID_COUNTER = 0


async def _send_jsonrpc(proc: subprocess.Popen, method: str, params: dict, timeout: float = 30) -> dict:
    """Send a JSON-RPC request to the stdio process and await response."""
    global _MSG_ID_COUNTER
    _MSG_ID_COUNTER += 1
    msg_id = _MSG_ID_COUNTER

    message = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
    content = f"Content-Length: {len(message)}\r\n\r\n{message}"

    try:
        proc.stdin.write(content.encode("utf-8"))
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        raise RuntimeError(f"Failed to write to server stdin: {e}")

    # Read response with timeout
    response = await asyncio.wait_for(
        asyncio.get_event_loop().run_in_executor(None, lambda: _read_jsonrpc_response(proc)),
        timeout=timeout,
    )

    if "error" in response:
        err = response["error"]
        raise RuntimeError(f"Server error: {err.get('message', 'Unknown error')} (code: {err.get('code', '?')})")

    return response


def _send_notification(proc: subprocess.Popen, method: str, params: dict) -> None:
    """Send a JSON-RPC notification (no id, no response expected)."""
    message = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
    content = f"Content-Length: {len(message)}\r\n\r\n{message}"
    try:
        proc.stdin.write(content.encode("utf-8"))
        proc.stdin.flush()
    except Exception:
        pass


def _read_jsonrpc_response(proc: subprocess.Popen) -> dict:
    """Read a JSON-RPC response from stdout using Content-Length headers."""
    headers = {}
    while True:
        line = b""
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                raise RuntimeError("Server closed stdout unexpectedly")
            line += ch
            if line.endswith(b"\r\n"):
                break

        line_str = line.decode("utf-8").strip()
        if not line_str:
            break
        if ":" in line_str:
            key, val = line_str.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        raise RuntimeError("No Content-Length header in response")

    body = b""
    while len(body) < content_length:
        chunk = proc.stdout.read(content_length - len(body))
        if not chunk:
            raise RuntimeError("Server closed stdout while reading body")
        body += chunk

    return json.loads(body.decode("utf-8"))


async def _execute_stdio_tool(session_id: str, tool_name: str, arguments: dict) -> Any:
    """Execute a tool via stdio JSON-RPC."""
    proc = _processes.get(session_id)
    if not proc or proc.poll() is not None:
        session = _sessions.get(session_id)
        if session:
            session["status"] = "disconnected"
        raise HTTPException(status_code=400, detail="Server process has exited. Reconnect to continue testing.")

    result = await _send_jsonrpc(proc, "tools/call", {
        "name": tool_name,
        "arguments": arguments,
    }, timeout=30)

    return result.get("result", {})


async def _execute_http_tool(session_id: str, session: dict, tool_name: str, arguments: dict) -> Any:
    """Execute a tool via MCP SSE transport.

    Sends a JSON-RPC ``tools/call`` request to ``/messages?sessionId=...`` and
    reads the response from the persistent SSE stream.
    """
    import httpx

    queue = _sse_queues.get(session_id)
    messages_url = session.get("mcp_messages_url")

    if not queue or not messages_url:
        raise HTTPException(
            status_code=400,
            detail="SSE session state lost. Please disconnect and reconnect.",
        )

    msg_id = int(time.time() * 1000)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 202):
                raise RuntimeError(f"POST to MCP messages returned HTTP {resp.status_code}: {resp.text[:300]}")
    except httpx.ConnectError:
        session["status"] = "disconnected"
        raise HTTPException(status_code=400, detail="Server is no longer reachable. It may have stopped.")

    # Read the tool result from the SSE stream (responses come back over the event stream)
    deadline = asyncio.get_event_loop().time() + 30.0
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise HTTPException(status_code=400, detail="Tool execution timed out after 30 seconds.")
        try:
            evt = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=400, detail="Tool execution timed out after 30 seconds.")

        if evt.get("event") == "error":
            raise RuntimeError(evt.get("data", "SSE error during tool execution"))

        if evt.get("event") == "message":
            try:
                data = json.loads(evt.get("data", "{}"))
                # Match by id â€” skip notifications (which have no id)
                if data.get("id") == msg_id:
                    if "error" in data:
                        err = data["error"]
                        raise RuntimeError(
                            f"Server error: {err.get('message', 'Unknown')} (code: {err.get('code', '?')})"
                        )
                    return data.get("result", {})
            except (json.JSONDecodeError, KeyError):
                continue

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the new Playground surfaces.

These go through the FastAPI TestClient so they exercise:
  - request/response pydantic models
  - the assertion engine path
  - the DB layer (repositories writing/reading test cases and runs)
  - the test-suite runner (which internally calls _run_tool)

The upstream MCP server is mocked at the ``_execute_stdio_tool``/``_execute_http_tool``
seam so we don't need a real subprocess.
"""

from __future__ import annotations

import json

import pytest

from selqor_forge.dashboard.routes import playground as playground_module


# ----------------------------- fixtures --------------------------------------

@pytest.fixture
def fake_session(client, monkeypatch):
    """Register a fake live session in the playground in-memory store.

    Bypasses the real transport layer so tests don't require stdio/SSE infra.
    Returns the session_id.
    """
    session_id = "test-session-1"
    tools = [
        {
            "name": "echo_tool",
            "description": "Echoes the message argument",
            "inputSchema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
        {
            "name": "counter_tool",
            "description": "Returns a numeric count",
            "inputSchema": {"type": "object", "properties": {"n": {"type": "integer"}}},
        },
    ]
    # Seed in-memory registry
    playground_module._sessions[session_id] = {
        "name": "fake",
        "transport": "stdio",
        "status": "connected",
        "tools": tools,
        "executions": [],
    }

    # Persist to DB so routes that look up the DB also find it
    from selqor_forge.dashboard.app import create_app  # noqa: F401 — ensure app created the DB
    # The TestClient fixture already triggered startup; get the factory off the app.
    factory = client.app.state.dashboard_ctx.db_session_factory
    db = factory()
    try:
        from selqor_forge.dashboard.repositories import PlaygroundSessionRepository
        repo = PlaygroundSessionRepository(db)
        repo.create(
            id=session_id,
            name="fake",
            transport="stdio",
            status="connected",
            connected_at="2026-04-17T00:00:00Z",
            server_info={},
            tools=tools,
            command=None,
            server_url=None,
        )
    finally:
        db.close()

    # Fake tool executor — pretends to talk to an MCP server.
    async def fake_stdio_exec(session_id, tool_name, arguments):
        if tool_name == "echo_tool":
            return {
                "content": [
                    {"type": "text", "text": f"echo:{arguments.get('message', '')}"}
                ],
                "isError": False,
            }
        if tool_name == "counter_tool":
            return {
                "content": [{"type": "text", "text": json.dumps({"count": arguments.get("n", 0)})}],
                "structuredContent": {"count": arguments.get("n", 0)},
            }
        raise RuntimeError(f"unknown tool {tool_name}")

    monkeypatch.setattr(playground_module, "_execute_stdio_tool", fake_stdio_exec)

    yield session_id

    # Cleanup
    playground_module._sessions.pop(session_id, None)


# ----------------------------- tests -----------------------------------------


def test_execute_returns_raw_rpc(client, fake_session):
    resp = client.post(
        f"/api/playground/sessions/{fake_session}/execute",
        json={"tool_name": "echo_tool", "arguments": {"message": "hi"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["tool_name"] == "echo_tool"
    # The manual-exec response now surfaces the captured JSON-RPC frames.
    assert "raw_rpc" in body and body["raw_rpc"] is not None
    assert body["raw_rpc"]["request"]["method"] == "tools/call"
    assert body["raw_rpc"]["response"]["result"]["content"][0]["text"] == "echo:hi"


def test_testcase_crud_flow(client, fake_session):
    # Create
    payload = {
        "tool_name": "echo_tool",
        "name": "hello case",
        "description": "asserts echo returns the message",
        "arguments": {"message": "ping"},
        "assertions": [
            {"op": "status_is", "value": "success"},
            {"op": "text_includes", "value": "echo:ping"},
        ],
    }
    r = client.post(f"/api/playground/sessions/{fake_session}/testcases", json=payload)
    assert r.status_code == 200, r.text
    tc = r.json()["testcase"]
    tid = tc["id"]
    assert tc["tool_name"] == "echo_tool"
    assert len(tc["assertions"]) == 2

    # List
    r = client.get(f"/api/playground/sessions/{fake_session}/testcases")
    assert r.status_code == 200
    cases = r.json()["testcases"]
    assert any(c["id"] == tid for c in cases)

    # Update
    r = client.patch(f"/api/playground/testcases/{tid}", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["testcase"]["name"] == "renamed"

    # Delete
    r = client.delete(f"/api/playground/testcases/{tid}")
    assert r.status_code == 200
    r = client.get(f"/api/playground/sessions/{fake_session}/testcases")
    assert all(c["id"] != tid for c in r.json()["testcases"])


def test_create_testcase_rejects_unknown_tool(client, fake_session):
    r = client.post(
        f"/api/playground/sessions/{fake_session}/testcases",
        json={"tool_name": "nonexistent", "name": "x", "arguments": {}, "assertions": []},
    )
    assert r.status_code == 400
    assert "not available" in r.json()["detail"]


def test_run_suite_pass_fail_mix(client, fake_session):
    # Passing case
    r = client.post(f"/api/playground/sessions/{fake_session}/testcases", json={
        "tool_name": "echo_tool",
        "name": "echo-ok",
        "arguments": {"message": "ping"},
        "assertions": [
            {"op": "text_includes", "value": "echo:ping"},
        ],
    })
    assert r.status_code == 200

    # Failing case (wrong expected text)
    r = client.post(f"/api/playground/sessions/{fake_session}/testcases", json={
        "tool_name": "echo_tool",
        "name": "echo-wrong",
        "arguments": {"message": "hi"},
        "assertions": [
            {"op": "text_includes", "value": "this-wont-be-there"},
        ],
    })
    assert r.status_code == 200

    r = client.post(f"/api/playground/sessions/{fake_session}/run-suite", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == 2
    assert body["summary"]["passed"] == 1
    assert body["summary"]["failed"] == 1
    # Each result has assertion outcomes and an executed_at
    for result in body["results"]:
        assert "status" in result
        assert "assertion_results" in result


def test_session_stats_aggregates_per_tool(client, fake_session):
    for msg in ["a", "b", "c"]:
        client.post(
            f"/api/playground/sessions/{fake_session}/execute",
            json={"tool_name": "echo_tool", "arguments": {"message": msg}},
        )
    client.post(
        f"/api/playground/sessions/{fake_session}/execute",
        json={"tool_name": "counter_tool", "arguments": {"n": 5}},
    )

    r = client.get(f"/api/playground/sessions/{fake_session}/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    stats = {s["tool_name"]: s for s in body["stats"]}
    assert stats["echo_tool"]["invocations"] == 3
    assert stats["echo_tool"]["success_rate"] == 1.0
    assert stats["counter_tool"]["invocations"] == 1
    # p50/p95 should be populated when latencies were recorded
    assert stats["echo_tool"]["p50_ms"] is not None


def test_session_trace_returns_raw_rpc_frames(client, fake_session):
    client.post(
        f"/api/playground/sessions/{fake_session}/execute",
        json={"tool_name": "echo_tool", "arguments": {"message": "trace"}},
    )
    r = client.get(f"/api/playground/sessions/{fake_session}/trace")
    assert r.status_code == 200, r.text
    frames = r.json()["frames"]
    assert len(frames) >= 1
    f = frames[0]
    assert f["tool_name"] == "echo_tool"
    assert f["raw_rpc"]["request"]["method"] == "tools/call"
    assert f["raw_rpc"]["response"]["result"]["content"][0]["text"] == "echo:trace"


def test_agent_chat_tool_loop_with_fake_anthropic(client, fake_session, monkeypatch):
    """Drive the agent loop end-to-end with a stubbed Anthropic response.

    Turn 1: the model asks to call ``echo_tool`` with ``message=world``.
    Turn 2: the model returns a final text message with no more tool calls.
    """
    # Seed a dummy default LLM config so _resolve_config finds one.
    factory = client.app.state.dashboard_ctx.db_session_factory
    db = factory()
    try:
        from selqor_forge.dashboard.models import LLMConfig
        db.add(LLMConfig(
            id="fake-llm",
            name="fake",
            provider="anthropic",
            model="claude-test",
            api_key="dummy",
            is_default=True,
            enabled=True,
            created_at="2026-04-17T00:00:00Z",
            updated_at="2026-04-17T00:00:00Z",
        ))
        db.commit()
    finally:
        db.close()

    turns = [
        # Turn 1: tool_use
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Let me call the tool."},
                {"type": "tool_use", "id": "tu_1", "name": "echo_tool", "input": {"message": "world"}},
            ],
        },
        # Turn 2: plain text, no tools
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "The tool echoed 'echo:world'."}],
        },
    ]
    call_count = {"n": 0}

    async def fake_anthropic_turn(config, system_prompt, messages, tools_schema):
        idx = call_count["n"]
        call_count["n"] += 1
        assert tools_schema, "tool schemas should be forwarded to the LLM"
        return turns[idx]

    monkeypatch.setattr(playground_module, "_anthropic_turn", fake_anthropic_turn)

    r = client.post(
        f"/api/playground/sessions/{fake_session}/agent-chat",
        json={"message": "say hello", "config_id": "fake-llm", "max_iterations": 4},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["final_message"] == "The tool echoed 'echo:world'."
    assert body["tools_used"] == ["echo_tool"]
    # Trace: user, assistant(turn1), tool(result), assistant(turn2) â€” at least 4 entries
    assert len(body["trace"]) >= 4
    assistant_entries = [t for t in body["trace"] if t.get("role") == "assistant"]
    assert len(assistant_entries) == 2
    tool_entries = [t for t in body["trace"] if t.get("role") == "tool"]
    assert tool_entries[0]["status"] == "success"

    # The agent run was persisted
    r = client.get(f"/api/playground/sessions/{fake_session}/agent-runs")
    runs = r.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["tools_used"] == ["echo_tool"]

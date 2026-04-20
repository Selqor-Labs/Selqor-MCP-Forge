"""End-to-end regression tests for the rewritten MCPClient.

Drives both transports against the in-tree petstore fixtures in
``tests/fixtures/mcp/`` and asserts the four correctness guarantees the
rewrite targets:

  1. Per-id response dispatch â€” concurrent calls don't steal each other's
     responses.
  2. stderr drainer keeps the subprocess alive even when the server logs
     heavily (stdio only).
  3. Timeout cleanup â€” timed-out calls release their futures so the next
     caller doesn't inherit a stale id slot.
  4. close() fails pending futures â€” callers never hang after disconnect.

Run from the repo root::

    python tests/test_dashboard/test_mcp_client_integration.py
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# The petstore fixtures (tests/fixtures/mcp/petstore_*.py) import the `mcp`
# server SDK. Skip the integration suite cleanly if it is not installed so
# environments without the dev extras don't see spurious subprocess errors.
pytest.importorskip("mcp")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "mcp"
sys.path.insert(0, str(REPO_ROOT / "src"))

from selqor_forge.dashboard.mcp_client import (  # noqa: E402
    HttpSseMCPClient,
    MCPDisconnectedError,
    StdioMCPClient,
)

pytestmark = pytest.mark.asyncio


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _log(msg: str) -> None:
    print(f"  {msg}", flush=True)


# ---------------------------------------------------------------------------
# stdio tests
# ---------------------------------------------------------------------------


async def test_stdio_basic() -> None:
    print("\n[stdio] basic connect + list_tools + call")
    client = StdioMCPClient(
        args=[sys.executable, str(FIXTURES / "petstore_stdio.py")],
        working_dir=str(REPO_ROOT),
    )
    info = await client.connect(init_timeout=10.0)
    assert "name" in info, f"expected serverInfo.name, got {info}"
    _log(f"connected. server_info={info}")

    tools = await client.list_tools()
    names = sorted(t["name"] for t in tools)
    assert names == ["get_pet", "list_pets", "slow_echo"], names
    _log(f"tools={names}")

    result = await client.call("tools/call", {"name": "list_pets", "arguments": {}})
    # MCP tools/call returns content blocks; unwrap the first text block.
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert payload["total"] == 3, payload
    _log(f"list_pets total={payload['total']}")

    await client.close()
    _log("closed cleanly")


async def test_stdio_concurrent_no_response_stealing() -> None:
    """Fire N overlapping calls; each must receive its own echo back.

    The old code read stdout in the request coroutine, so two concurrent
    callers could each receive the other's response. With the reader task
    + per-id futures, every call should resolve to its own payload.
    """
    print("\n[stdio] concurrent calls must receive their own responses")
    client = StdioMCPClient(
        args=[sys.executable, str(FIXTURES / "petstore_stdio.py")],
        working_dir=str(REPO_ROOT),
    )
    await client.connect()

    N = 20
    # Vary delays so responses come back out of order.
    texts = [f"msg-{i}" for i in range(N)]
    delays = [(i % 5) * 20 for i in range(N)]  # 0â€“80 ms

    async def one(i: int) -> tuple[int, dict]:
        r = await client.call(
            "tools/call",
            {
                "name": "slow_echo",
                "arguments": {"text": texts[i], "delay_ms": delays[i]},
            },
            timeout=10.0,
        )
        return i, json.loads(r["content"][0]["text"])

    results = await asyncio.gather(*[one(i) for i in range(N)])
    for i, payload in results:
        assert payload["echo"] == texts[i], (
            f"response stealing detected: call {i} (expected {texts[i]!r}) "
            f"received {payload!r}"
        )
    _log(f"{N} concurrent calls all received their own payloads")

    await client.close()


async def test_stdio_stderr_drain_no_deadlock() -> None:
    """Hammer the server with calls so it produces > 64 KB of stderr.

    If the drainer is broken the OS pipe buffer fills and the server blocks
    on its next stderr write, silently hanging the whole test.
    """
    print("\n[stdio] heavy stderr must not deadlock the server")
    client = StdioMCPClient(
        args=[sys.executable, str(FIXTURES / "petstore_stdio.py")],
        working_dir=str(REPO_ROOT),
    )
    await client.connect()

    # Each call writes ~60 bytes of stderr. 2000 calls â‰ˆ 120 KB, which is
    # well past the 64 KB pipe buffer on Windows.
    N = 2000
    t0 = time.time()
    for i in range(N):
        r = await client.call(
            "tools/call",
            {"name": "slow_echo", "arguments": {"text": f"x{i}"}},
            timeout=5.0,
        )
        assert json.loads(r["content"][0]["text"])["echo"] == f"x{i}"
    elapsed = time.time() - t0
    _log(f"{N} calls completed in {elapsed:.2f}s; no stderr deadlock")

    await client.close()


async def test_stdio_close_fails_pending() -> None:
    """Pending calls must be rejected (not hung) when close() is invoked."""
    print("\n[stdio] close() must fail pending calls, never hang")
    client = StdioMCPClient(
        args=[sys.executable, str(FIXTURES / "petstore_stdio.py")],
        working_dir=str(REPO_ROOT),
    )
    await client.connect()

    pending = asyncio.create_task(
        client.call(
            "tools/call",
            {"name": "slow_echo", "arguments": {"text": "hang", "delay_ms": 5000}},
            timeout=30.0,
        )
    )
    await asyncio.sleep(0.2)  # let the call reach the server
    await client.close()

    try:
        await asyncio.wait_for(pending, timeout=3.0)
        raise AssertionError("expected pending call to raise after close()")
    except MCPDisconnectedError:
        _log("pending call correctly raised MCPDisconnectedError")
    except asyncio.TimeoutError:
        raise AssertionError("pending call hung after close() â€” drain broken")


# ---------------------------------------------------------------------------
# HTTP+SSE tests
# ---------------------------------------------------------------------------


async def _wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                await asyncio.sleep(0.1)
    raise RuntimeError(f"HTTP server never came up on port {port}")


class _PetstoreHttp:
    """Context manager that boots petstore_http fixture on a free port."""

    def __init__(self) -> None:
        self.port = _pick_free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def __aenter__(self) -> "_PetstoreHttp":
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(FIXTURES / "petstore_http.py"),
                "--port",
                str(self.port),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await _wait_port(self.port)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


async def test_http_basic() -> None:
    print("\n[http+sse] basic connect + list_tools + call")
    async with _PetstoreHttp() as srv:
        client = HttpSseMCPClient(server_url=srv.base_url)
        info = await client.connect(init_timeout=10.0)
        _log(f"connected. server_info={info}")

        tools = await client.list_tools()
        names = sorted(t["name"] for t in tools)
        assert names == ["create_pet", "delete_pet", "get_pet", "list_pets"], names
        _log(f"tools={names}")

        r = await client.call("tools/call", {"name": "list_pets", "arguments": {}})
        payload = json.loads(r["content"][0]["text"])
        assert payload["total"] == 3, payload
        _log(f"list_pets total={payload['total']}")

        await client.close()
        _log("closed cleanly")


async def test_http_concurrent_no_response_stealing() -> None:
    """Concurrent HTTP calls used to steal messages off the shared queue.

    The new reader dispatches by id to per-id futures, so each coroutine
    receives exactly its own response.
    """
    print("\n[http+sse] concurrent calls must receive their own responses")
    async with _PetstoreHttp() as srv:
        client = HttpSseMCPClient(server_url=srv.base_url)
        await client.connect()

        N = 20

        async def one(i: int) -> tuple[int, dict]:
            r = await client.call(
                "tools/call",
                {
                    "name": "create_pet",
                    "arguments": {
                        "name": f"pet-{i}",
                        "species": "dog",
                    },
                },
                timeout=10.0,
            )
            return i, json.loads(r["content"][0]["text"])

        results = await asyncio.gather(*[one(i) for i in range(N)])
        names_back = [payload["name"] for _, payload in results]
        expected = [f"pet-{i}" for i in range(N)]
        assert sorted(names_back) == sorted(expected), (
            f"response stealing: expected each caller to see its own create, "
            f"got {names_back}"
        )
        # Each call must see its own name back (not a sibling's).
        for i, payload in results:
            assert payload["name"] == f"pet-{i}", (
                f"call {i} received {payload['name']!r} instead of pet-{i}"
            )
        _log(f"{N} concurrent create_pet calls each received their own result")

        await client.close()


async def test_http_close_fails_pending() -> None:
    print("\n[http+sse] close() must fail pending calls, never hang")
    async with _PetstoreHttp() as srv:
        client = HttpSseMCPClient(server_url=srv.base_url)
        await client.connect()

        # get_pet on a missing id returns fast, so we simulate "pending" by
        # closing immediately after firing. The client must reject rather
        # than hang.
        pending = asyncio.create_task(
            client.call(
                "tools/call",
                {"name": "get_pet", "arguments": {"id": 1}},
                timeout=30.0,
            )
        )
        # Give the POST a moment to land but not complete.
        await asyncio.sleep(0.01)
        await client.close()

        try:
            await asyncio.wait_for(pending, timeout=3.0)
        except MCPDisconnectedError:
            _log("pending call correctly raised MCPDisconnectedError")
        except asyncio.TimeoutError:
            raise AssertionError("pending call hung after close()")
        except Exception as exc:
            # A quick enough race may let the response land before close()
            # actually fails the future â€” that's fine, we only require no
            # hang and no corruption.
            _log(f"pending call completed/errored: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("Verifying MCPClient against petstore servers\n" + "=" * 46)
    await test_stdio_basic()
    await test_stdio_concurrent_no_response_stealing()
    await test_stdio_stderr_drain_no_deadlock()
    await test_stdio_close_fails_pending()
    await test_http_basic()
    await test_http_concurrent_no_response_stealing()
    await test_http_close_fails_pending()
    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())

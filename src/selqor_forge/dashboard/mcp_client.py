# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Async MCP client used by the Playground backend.

Single long-lived reader per client demultiplexes JSON-RPC responses to per-id
futures. Concurrent ``call()`` invocations cannot steal each other's responses,
stderr is drained continuously so MCPs that log heavily cannot deadlock, and
close() always fails pending futures so callers never hang after disconnect.

Two transports are supported:

* ``StdioMCPClient`` — launches the MCP as a child process via
  ``asyncio.create_subprocess_exec`` and frames messages as either
  ``Content-Length``-prefixed blocks (LSP style) or newline-delimited JSON.
  Framing is auto-detected on the first byte of stdout.

* ``HttpSseMCPClient`` — connects to an MCP using the HTTP+SSE transport.
  Requests are POSTed to the ``messages`` endpoint advertised by the server
  through an ``event: endpoint`` SSE frame; responses arrive on the persistent
  SSE stream and are routed to the matching future.

Both clients expose the same ``call() / notify() / close()`` interface so the
route layer can treat them identically.
"""

from __future__ import annotations

import abc
import asyncio
import collections
import contextlib
import itertools
import json
import logging
import shlex
import sys
from typing import Any

import httpx


logger = logging.getLogger(__name__)

_STDERR_RING_BYTES = 32 * 1024  # keep the last 32 KB of stderr for diagnostics
_DEFAULT_CALL_TIMEOUT = 30.0


class MCPError(RuntimeError):
    """Protocol-level error raised when the server returns a JSON-RPC error."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MCPDisconnectedError(RuntimeError):
    """Raised when the transport goes away while a call is pending."""


class MCPClient(abc.ABC):
    """Abstract MCP client. Both transports share ID allocation + dispatch."""

    def __init__(self) -> None:
        # ``itertools.count`` is atomic in CPython for the ``next()`` call, but
        # we guard behind a lock anyway so the implementation doesn't rely on
        # interpreter-specific behavior.
        self._id_counter = itertools.count(1)
        self._id_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._closed = False
        self._close_reason: str | None = None
        self._server_info: dict = {}
        self._tools: list[dict] = []

    # ---- public API --------------------------------------------------------

    @property
    def server_info(self) -> dict:
        return self._server_info

    @property
    def tools(self) -> list[dict]:
        return self._tools

    @abc.abstractmethod
    def is_alive(self) -> bool:
        """Return True if the underlying transport looks usable."""

    @abc.abstractmethod
    async def connect(self, *, init_timeout: float = 10.0) -> dict:
        """Perform the MCP initialize handshake and return server_info."""

    async def list_tools(self, *, timeout: float = 10.0) -> list[dict]:
        result = await self.call("tools/list", {}, timeout=timeout)
        tools = result.get("tools") or []
        self._tools = tools
        return tools

    async def call(
        self, method: str, params: dict, *, timeout: float = _DEFAULT_CALL_TIMEOUT
    ) -> dict:
        """Send a JSON-RPC request and await the matching response.

        Registers the future **before** writing to the wire so a response that
        arrives instantly is still dispatched correctly. On timeout, removes
        the id from ``_pending`` so a late response is discarded rather than
        handed to a different caller that happens to reuse the id.
        """
        if self._closed:
            raise MCPDisconnectedError(
                self._close_reason or "MCP client is closed"
            )

        async with self._id_lock:
            msg_id = next(self._id_counter)

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[msg_id] = fut

        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        try:
            await self._send(payload)
        except Exception:
            self._pending.pop(msg_id, None)
            raise

        try:
            response = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            # Drop the pending future so a late response doesn't get matched
            # to the next caller that happens to allocate the same id (ids are
            # monotonic per-client so this is defensive belt-and-suspenders).
            self._pending.pop(msg_id, None)
            raise TimeoutError(
                f"MCP call {method!r} timed out after {timeout}s"
            ) from None
        finally:
            # Normal completion path: future is already removed by the reader,
            # but pop again to be safe if the reader failed to clean up.
            self._pending.pop(msg_id, None)

        if "error" in response:
            err = response["error"] or {}
            raise MCPError(
                err.get("message") or "Unknown server error",
                code=err.get("code"),
                data=err.get("data"),
            )
        return response.get("result") or {}

    @abc.abstractmethod
    async def notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Tear down transport and fail every pending future."""

    # ---- internals ---------------------------------------------------------

    @abc.abstractmethod
    async def _send(self, payload: dict) -> None:
        """Serialize and push ``payload`` to the wire. Subclass-specific."""

    def _dispatch(self, msg: dict) -> None:
        """Route a received JSON-RPC message to the right waiter."""
        msg_id = msg.get("id")
        if msg_id is None:
            # Notification or server-initiated request. Log it; we don't yet
            # route these anywhere in v1.
            method = msg.get("method")
            if method:
                logger.debug("MCP notification received: %s", method)
            return

        fut = self._pending.pop(msg_id, None)
        if fut is None or fut.done():
            # Response to a call that already timed out, or to an id we never
            # issued. Drop silently; nothing to do.
            return
        fut.set_result(msg)

    def _fail_all_pending(self, exc: BaseException) -> None:
        """Wake every waiting caller with ``exc``. Idempotent."""
        pending = self._pending
        self._pending = {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------


class StdioMCPClient(MCPClient):
    """MCP client that talks to a child process over stdin/stdout."""

    def __init__(
        self,
        command: str | None = None,
        *,
        args: list[str] | None = None,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ):
        """Either pass ``command`` as a single shell-quoted string (the
        Playground path, where the user types a command into a text field),
        or pass ``args`` as a pre-split list (programmatic / test path).
        Exactly one must be supplied.
        """
        super().__init__()
        if args is not None:
            if command is not None:
                raise ValueError("pass either command or args, not both")
            if not args:
                raise ValueError("args list must be non-empty")
            self._args: list[str] | None = list(args)
            self._command: str | None = None
        else:
            if not command or not command.strip():
                raise ValueError("command is required for stdio MCP client")
            self._command = command
            self._args = None
        self._working_dir = working_dir or None
        self._env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        # Ring buffer of recent stderr bytes for diagnostics.
        self._stderr_buf: collections.deque[bytes] = collections.deque()
        self._stderr_size = 0
        # Stdin write serialized so two concurrent callers don't interleave
        # header + body bytes of different messages.
        self._write_lock = asyncio.Lock()
        # Framing detected from first byte of stdout. ``None`` = not yet seen.
        self._framing: str | None = None  # "lsp" or "ndjson"

    def is_alive(self) -> bool:
        return (
            not self._closed
            and self._proc is not None
            and self._proc.returncode is None
        )

    async def connect(self, *, init_timeout: float = 10.0) -> dict:
        if self._args is not None:
            cmd_parts = list(self._args)
        else:
            # Windows paths use backslashes, which POSIX shlex treats as
            # escapes and silently drops ("C:\\foo\\python.exe" ->
            # "C:foopython.exe"). Use Windows-style splitting on win32 to
            # preserve them.
            assert self._command is not None  # guaranteed by __init__
            cmd_parts = shlex.split(
                self._command, posix=(sys.platform != "win32")
            )
        if not cmd_parts:
            raise ValueError("command is empty after shell splitting")
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=self._env,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Command not found: {cmd_parts[0]!r}. "
                "Ensure the server is built and the command is correct."
            ) from exc

        # Start the reader and stderr drainer before sending anything so we
        # can't miss the first response or deadlock on a chatty stderr.
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="mcp-stdio-reader"
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_loop(), name="mcp-stdio-stderr"
        )

        # Give the process a moment to print a startup error before we try
        # to talk to it.
        await asyncio.sleep(0.05)
        if self._proc.returncode is not None:
            tail = self._stderr_tail().decode("utf-8", errors="replace")[:500]
            await self.close()
            raise ConnectionError(
                f"Server process exited immediately (code {self._proc.returncode}). "
                f"Stderr: {tail}" if tail else "Server process exited immediately."
            )

        try:
            init_result = await self.call(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "selqor-mcp-forge-playground",
                        "version": "0.1.0",
                    },
                },
                timeout=init_timeout,
            )
        except Exception:
            await self.close()
            raise

        self._server_info = init_result.get("serverInfo") or {}
        # Fire-and-forget "initialized" per MCP spec.
        try:
            await self.notify("notifications/initialized", {})
        except Exception:  # noqa: BLE001
            # Not fatal — the spec says servers should tolerate a missing
            # initialized notification from misbehaving clients, but we still
            # close on hard transport failures below.
            if not self.is_alive():
                await self.close()
                raise
        return self._server_info

    async def notify(self, method: str, params: dict) -> None:
        if self._closed:
            raise MCPDisconnectedError(
                self._close_reason or "MCP client is closed"
            )
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, payload: dict) -> None:
        if not self.is_alive() or self._proc is None or self._proc.stdin is None:
            raise MCPDisconnectedError("stdio MCP server is not running")
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        async with self._write_lock:
            try:
                if self._framing == "lsp":
                    header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
                    self._proc.stdin.write(header + data)
                else:
                    # Default to newline-delimited JSON which is what modern
                    # MCP stdio servers use. If the peer turns out to speak
                    # LSP framing we'll flip ``_framing`` after seeing its
                    # first response byte and subsequent writes use LSP
                    # framing too.
                    self._proc.stdin.write(data + b"\n")
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise MCPDisconnectedError(
                    f"Failed to write to server stdin: {exc}"
                ) from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_reason = self._close_reason or "stdio MCP client closed"

        # Wake everyone waiting before we tear down so they don't hang.
        self._fail_all_pending(
            MCPDisconnectedError(self._close_reason)
        )

        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()

        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)

        # Drain task cancellations (they will raise CancelledError, suppress).
        for task in (self._reader_task, self._stderr_task):
            if task is None:
                continue
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # ---- framing + reader --------------------------------------------------

    async def _reader_loop(self) -> None:
        assert self._proc is not None
        stdout = self._proc.stdout
        assert stdout is not None
        try:
            while True:
                if self._framing is None:
                    first = await stdout.read(1)
                    if not first:
                        break
                    # If the peer starts with ``C`` (``Content-Length:``) it's
                    # LSP framing. Otherwise assume newline-delimited JSON and
                    # put the byte back into the parse.
                    if first == b"C":
                        self._framing = "lsp"
                        rest = await stdout.readuntil(b"\r\n\r\n")
                        header_block = first + rest
                        msg = await self._read_lsp_body(
                            stdout, header_block.decode("utf-8", errors="replace")
                        )
                    else:
                        self._framing = "ndjson"
                        remainder = await stdout.readuntil(b"\n")
                        line = (first + remainder).strip()
                        if not line:
                            continue
                        msg = self._parse_json_line(line)
                elif self._framing == "lsp":
                    # Read the header block then body.
                    header_block_bytes = await stdout.readuntil(b"\r\n\r\n")
                    msg = await self._read_lsp_body(
                        stdout,
                        header_block_bytes.decode("utf-8", errors="replace"),
                    )
                else:  # ndjson
                    line = await stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    msg = self._parse_json_line(line)

                if msg is None:
                    continue
                self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except asyncio.IncompleteReadError:
            # Peer closed stdout mid-frame. Treat as disconnect.
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("stdio MCP reader crashed: %s", exc)
        finally:
            await self._handle_stream_closed()

    async def _read_lsp_body(
        self, stdout: asyncio.StreamReader, header_block: str
    ) -> dict | None:
        content_length = 0
        for line in header_block.split("\r\n"):
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            if key.strip().lower() == "content-length":
                try:
                    content_length = int(val.strip())
                except ValueError:
                    content_length = 0
                    break
        if content_length <= 0:
            return None
        body = await stdout.readexactly(content_length)
        return self._parse_json_line(body)

    @staticmethod
    def _parse_json_line(raw: bytes) -> dict | None:
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("stdio MCP emitted invalid JSON frame: %s", exc)
            return None
        if isinstance(decoded, dict):
            return decoded
        # Batched response arrays are legal in JSON-RPC 2.0 but rare in MCP.
        # Dispatch each element individually.
        if isinstance(decoded, list):
            # We return None and let the caller re-enter, but actually we need
            # a way to dispatch multiple. Simpler: log and drop — MCP does not
            # use batched responses in practice.
            logger.warning("stdio MCP emitted a JSON array frame; ignoring")
            return None
        return None

    async def _stderr_loop(self) -> None:
        assert self._proc is not None
        stderr = self._proc.stderr
        assert stderr is not None
        try:
            while True:
                chunk = await stderr.read(4096)
                if not chunk:
                    break
                self._stderr_buf.append(chunk)
                self._stderr_size += len(chunk)
                while self._stderr_size > _STDERR_RING_BYTES and self._stderr_buf:
                    dropped = self._stderr_buf.popleft()
                    self._stderr_size -= len(dropped)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("stdio MCP stderr drainer stopped: %s", exc)

    async def _handle_stream_closed(self) -> None:
        if self._closed:
            return
        tail = self._stderr_tail().decode("utf-8", errors="replace")[:500]
        rc = self._proc.returncode if self._proc else None
        reason = (
            f"MCP stdio stream closed (exit={rc}). Stderr tail: {tail}"
            if tail
            else f"MCP stdio stream closed (exit={rc})."
        )
        self._close_reason = reason
        self._fail_all_pending(MCPDisconnectedError(reason))

    def _stderr_tail(self) -> bytes:
        return b"".join(self._stderr_buf)


# ---------------------------------------------------------------------------
# HTTP + SSE transport
# ---------------------------------------------------------------------------


class HttpSseMCPClient(MCPClient):
    """MCP client that talks to a remote server using the HTTP+SSE transport.

    Responses arrive on a persistent SSE stream; requests are POSTed to a
    ``messages`` endpoint the server advertises via an ``event: endpoint``
    SSE frame during the handshake.
    """

    def __init__(self, server_url: str):
        super().__init__()
        if not server_url:
            raise ValueError("server_url is required")
        self._base_url = server_url.rstrip("/")
        self._sse_url = f"{self._base_url}/sse"
        self._messages_url: str | None = None
        self._endpoint_ready: asyncio.Event = asyncio.Event()
        self._http: httpx.AsyncClient | None = None
        self._reader_task: asyncio.Task | None = None
        self._connected = False

    @property
    def messages_url(self) -> str | None:
        return self._messages_url

    def is_alive(self) -> bool:
        return (
            not self._closed
            and self._connected
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    async def connect(self, *, init_timeout: float = 10.0) -> dict:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=10.0)
        )
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="mcp-sse-reader"
        )
        # Wait for the server to tell us where to POST.
        try:
            await asyncio.wait_for(
                self._endpoint_ready.wait(), timeout=init_timeout
            )
        except asyncio.TimeoutError:
            await self.close()
            raise ConnectionError(
                f"Timed out waiting for SSE endpoint from {self._sse_url}"
            ) from None

        if self._messages_url is None:
            await self.close()
            raise ConnectionError(
                f"Server at {self._sse_url} never sent an endpoint event"
            )

        self._connected = True

        try:
            init_result = await self.call(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "selqor-mcp-forge-playground",
                        "version": "0.1.0",
                    },
                },
                timeout=init_timeout,
            )
        except Exception:
            await self.close()
            raise

        self._server_info = init_result.get("serverInfo") or {}
        try:
            await self.notify("notifications/initialized", {})
        except Exception:
            if not self.is_alive():
                await self.close()
                raise
        return self._server_info

    async def notify(self, method: str, params: dict) -> None:
        if self._closed:
            raise MCPDisconnectedError(
                self._close_reason or "MCP client is closed"
            )
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, payload: dict) -> None:
        if (
            self._closed
            or self._http is None
            or self._messages_url is None
        ):
            raise MCPDisconnectedError(
                "HTTP+SSE MCP server is not connected"
            )
        try:
            resp = await self._http.post(
                self._messages_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise MCPDisconnectedError(
                f"Failed to POST to MCP server: {exc}"
            ) from exc
        if resp.status_code not in (200, 202):
            raise MCPError(
                f"POST {self._messages_url} returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_reason = self._close_reason or "HTTP+SSE MCP client closed"
        self._connected = False

        self._fail_all_pending(
            MCPDisconnectedError(self._close_reason)
        )

        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task

        if self._http is not None:
            with contextlib.suppress(Exception):
                await self._http.aclose()
            self._http = None

    async def _reader_loop(self) -> None:
        assert self._http is not None
        try:
            async with self._http.stream(
                "GET", self._sse_url, headers={"Accept": "text/event-stream"}
            ) as resp:
                if resp.status_code != 200:
                    self._close_reason = (
                        f"SSE GET {self._sse_url} returned HTTP {resp.status_code}"
                    )
                    # If we have never seen the endpoint, unblock connect().
                    self._endpoint_ready.set()
                    return

                event_type: str | None = None
                data_lines: list[str] = []
                async for raw_line in resp.aiter_lines():
                    line = raw_line.rstrip("\r")
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif line == "":
                        if event_type is not None:
                            self._handle_sse_event(
                                event_type, "\n".join(data_lines)
                            )
                        event_type = None
                        data_lines = []
                    # Silently ignore SSE comment lines (``:`` prefix) and
                    # unknown fields per the SSE spec.
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as exc:
            self._close_reason = f"SSE stream error: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("SSE MCP reader crashed: %s", exc)
            self._close_reason = f"SSE reader crashed: {exc}"
        finally:
            # Unblock any caller still waiting for the endpoint event, and
            # fail all in-flight calls.
            self._endpoint_ready.set()
            self._connected = False
            self._fail_all_pending(
                MCPDisconnectedError(
                    self._close_reason or "SSE stream closed"
                )
            )

    def _handle_sse_event(self, event_type: str, data: str) -> None:
        if event_type == "endpoint":
            path = data.strip()
            if path.startswith("http://") or path.startswith("https://"):
                self._messages_url = path
            elif path.startswith("/"):
                self._messages_url = f"{self._base_url}{path}"
            else:
                # Some servers send just a query string; join with base.
                self._messages_url = f"{self._base_url}/{path}"
            self._endpoint_ready.set()
            return

        if event_type == "message":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                logger.warning("SSE message was not valid JSON: %s", exc)
                return
            if isinstance(payload, dict):
                self._dispatch(payload)
            return

        # ``ping``, ``error``, or other event types — log and move on.
        if event_type == "error":
            logger.warning("SSE server error frame: %s", data)

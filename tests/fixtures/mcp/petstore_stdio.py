"""Petstore MCP server (stdio transport) for integration-testing StdioMCPClient.

Run this via::

    python tools/petstore_mcp_stdio.py

Or more typically, launched indirectly by the Playground / the integration test
harness in ``tools/verify_mcp_client.py``.

The tool surface mirrors ``petstore_mcp_server.py`` so tests can target the
same operations across transports. The handler intentionally emits a couple of
stderr lines per call so the StdioMCPClient's stderr drainer has real traffic
to swallow â€” this is what catches the "stderr buffer fills and deadlocks"
regression the old backend had.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


_PETS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "Rex", "species": "dog", "status": "available"},
    2: {"id": 2, "name": "Whiskers", "species": "cat", "status": "pending"},
    3: {"id": 3, "name": "Goldie", "species": "fish", "status": "sold"},
}
_next_id = itertools.count(4)


server = Server("petstore-stdio")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_pets",
            description="List all pets, optionally filtered by status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["available", "pending", "sold"],
                    }
                },
            },
        ),
        Tool(
            name="get_pet",
            description="Fetch a single pet by its numeric id.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        ),
        Tool(
            name="slow_echo",
            description=(
                "Echo back the provided text after a configurable delay, "
                "while also emitting extra stderr chatter. Useful for testing "
                "concurrent-call dispatch and the stderr drainer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "delay_ms": {"type": "integer", "default": 0},
                },
                "required": ["text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    # Deliberately chatty on stderr so the StdioMCPClient drainer gets a real
    # workout under load. The OS pipe buffer is finite â€” if the drainer is
    # broken the server will deadlock after enough calls.
    sys.stderr.write(f"[petstore-stdio] call {name} args={arguments}\n")
    sys.stderr.flush()

    if name == "list_pets":
        status = arguments.get("status")
        pets = list(_PETS.values())
        if status:
            pets = [p for p in pets if p["status"] == status]
        payload = {"pets": pets, "total": len(pets)}

    elif name == "get_pet":
        pet_id = int(arguments["id"])
        pet = _PETS.get(pet_id)
        payload = pet if pet is not None else {"error": f"pet {pet_id} not found"}

    elif name == "slow_echo":
        delay_ms = int(arguments.get("delay_ms") or 0)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
        payload = {"echo": arguments["text"], "delay_ms": delay_ms}

    else:
        payload = {"error": f"unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(payload))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())

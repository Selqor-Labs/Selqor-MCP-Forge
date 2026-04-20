"""Petstore MCP server over HTTP+SSE â€” internal test fixture.

Purpose-built target for regression-testing the HttpSseMCPClient. Boot on any
free port; the test harness in ``test_mcp_client_integration.py`` manages
lifecycle.

Run directly (usually for ad-hoc debugging)::

    python tests/fixtures/mcp/petstore_http.py --port 3336
"""

from __future__ import annotations

import argparse
import itertools
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Mount, Route


_PETS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "Rex", "species": "dog", "status": "available"},
    2: {"id": 2, "name": "Whiskers", "species": "cat", "status": "pending"},
    3: {"id": 3, "name": "Goldie", "species": "fish", "status": "sold"},
}
_next_id = itertools.count(4)


server = Server("petstore-http")


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
            description="Fetch a single pet by id.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        ),
        Tool(
            name="create_pet",
            description="Create a new pet. Returns the created pet with its id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "species": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["available", "pending", "sold"],
                        "default": "available",
                    },
                },
                "required": ["name", "species"],
            },
        ),
        Tool(
            name="delete_pet",
            description="Delete a pet by id. Returns ok=true if it existed.",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    import json

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
    elif name == "create_pet":
        pet_id = next(_next_id)
        pet = {
            "id": pet_id,
            "name": arguments["name"],
            "species": arguments["species"],
            "status": arguments.get("status", "available"),
        }
        _PETS[pet_id] = pet
        payload = pet
    elif name == "delete_pet":
        pet_id = int(arguments["id"])
        existed = _PETS.pop(pet_id, None) is not None
        payload = {"ok": existed, "id": pet_id}
    else:
        payload = {"error": f"unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(payload))]


def build_app() -> Starlette:
    transport = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    return Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=transport.handle_post_message),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3336)
    args = parser.parse_args()

    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

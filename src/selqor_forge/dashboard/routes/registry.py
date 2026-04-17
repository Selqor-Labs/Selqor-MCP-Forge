# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""MCP Registry publishing routes."""

from __future__ import annotations

import json
import textwrap

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from selqor_forge.dashboard.middleware import Ctx

router = APIRouter(prefix="/registry", tags=["registry"])


class PreparePublishBody(BaseModel):
    """Request to prepare a registry publish package."""
    integration_id: str
    run_id: str
    registry_type: str  # "npm" or "smithery"
    package_name: str
    version: str = "1.0.0"
    description: str = ""


# ---------------------------------------------------------------------------
# Prepare publish
# ---------------------------------------------------------------------------

def _generate_npm_package_json(body: PreparePublishBody) -> tuple[str, str]:
    """Generate package.json content and publish command for npm."""
    package_json = {
        "name": body.package_name,
        "version": body.version,
        "description": body.description or f"MCP server for {body.package_name}",
        "main": "index.js",
        "type": "module",
        "keywords": ["mcp", "model-context-protocol", "ai", "llm"],
        "license": "MIT",
        "engines": {
            "node": ">=18.0.0"
        },
        "bin": {
            body.package_name.split("/")[-1]: "./index.js"
        },
        "files": [
            "index.js",
            "README.md",
            "LICENSE"
        ],
        "mcp": {
            "integration_id": body.integration_id,
            "run_id": body.run_id,
        },
    }

    config_content = json.dumps(package_json, indent=2)
    publish_command = "npm publish --access public"

    return config_content, publish_command


def _generate_smithery_yaml(body: PreparePublishBody) -> tuple[str, str]:
    """Generate smithery.yaml content and publish command for Smithery."""
    config_content = textwrap.dedent("""\
name: {name}
version: {version}
description: {description}
type: mcp-server
runtime: python
entry: server.py

metadata:
  integration_id: {integration_id}
  run_id: {run_id}

tools: []

config:
  env: {{}}
""").format(
        name=body.package_name,
        version=body.version,
        description=body.description or f"MCP server for {body.package_name}",
        integration_id=body.integration_id,
        run_id=body.run_id,
    )

    publish_command = f"smithery publish {body.package_name}"

    return config_content, publish_command


@router.post("/prepare")
async def prepare_publish(ctx: Ctx, body: PreparePublishBody) -> dict:
    """Generate publish package metadata for a registry."""
    if body.registry_type not in ("npm", "smithery"):
        raise HTTPException(status_code=400, detail="Unsupported registry_type. Use 'npm' or 'smithery'.")

    try:
        if body.registry_type == "npm":
            config_content, publish_command = _generate_npm_package_json(body)
            config_filename = "package.json"
        else:
            config_content, publish_command = _generate_smithery_yaml(body)
            config_filename = "smithery.yaml"

        return {
            "registry_type": body.registry_type,
            "package_name": body.package_name,
            "version": body.version,
            "config_filename": config_filename,
            "config_content": config_content,
            "publish_command": publish_command,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to prepare publish: {e}")


# ---------------------------------------------------------------------------
# List registries
# ---------------------------------------------------------------------------

@router.get("/registries")
async def list_registries(ctx: Ctx) -> dict:
    """Return list of supported registries."""
    return {
        "registries": [
            {
                "id": "npm",
                "name": "npm",
                "description": "Node Package Manager registry. Publishes MCP servers as npm packages installable via npx.",
                "config_file": "package.json",
                "publish_command": "npm publish",
                "url": "https://www.npmjs.com",
            },
            {
                "id": "smithery",
                "name": "Smithery",
                "description": "Smithery MCP server registry. A dedicated registry for discovering and sharing MCP servers.",
                "config_file": "smithery.yaml",
                "publish_command": "smithery publish",
                "url": "https://smithery.ai",
            },
        ]
    }

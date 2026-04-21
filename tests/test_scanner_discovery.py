# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Scanner discovery tests."""

import pytest

from selqor_forge.scanner.discover import MCPDiscovery
from selqor_forge.scanner.models import TransportType


@pytest.mark.asyncio
async def test_discover_rust_server_uses_stdlib_tomllib(tmp_state_dir):
    cargo = tmp_state_dir / "Cargo.toml"
    cargo.write_text(
        """
[package]
name = "sample-mcp-rust"
version = "0.1.0"

[dependencies]
rmcp = "0.2"
serde = "1"
""".strip(),
        encoding="utf-8",
    )

    manifest = await MCPDiscovery.from_local_directory(str(tmp_state_dir))

    assert manifest.name == "sample-mcp-rust"
    assert manifest.version == "0.1.0"
    assert manifest.language == "rust"
    assert manifest.transport == TransportType.STDIO
    assert manifest.dependencies["rmcp"] == "0.2"


@pytest.mark.asyncio
async def test_discover_python_server_uses_stdlib_tomllib(tmp_state_dir):
    pyproject = tmp_state_dir / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-mcp-python"
version = "0.2.0"
dependencies = [
  "mcp==1.2.3",
  "httpx>=0.27",
  "uvicorn[standard]>=0.34 ; python_version >= '3.11'",
]
""".strip(),
        encoding="utf-8",
    )

    manifest = await MCPDiscovery.from_local_directory(str(tmp_state_dir))

    assert manifest.name == "sample-mcp-python"
    assert manifest.version == "0.2.0"
    assert manifest.language == "python"
    assert manifest.transport == TransportType.STDIO
    assert manifest.dependencies["mcp"] == "==1.2.3"
    assert manifest.dependencies["httpx"] == ">=0.27"
    assert manifest.dependencies["uvicorn"] == ">=0.34"


@pytest.mark.asyncio
async def test_discover_typescript_server_prefers_package_lock_versions(tmp_state_dir):
    package_json = tmp_state_dir / "package.json"
    package_json.write_text(
        """
{
  "name": "sample-mcp-ts",
  "version": "0.3.0",
  "dependencies": {
    "express": "^4.21.2",
    "@modelcontextprotocol/sdk": "^1.8.0"
  }
}
""".strip(),
        encoding="utf-8",
    )
    package_lock = tmp_state_dir / "package-lock.json"
    package_lock.write_text(
        """
{
  "name": "sample-mcp-ts",
  "lockfileVersion": 3,
  "packages": {
    "": {
      "dependencies": {
        "express": "^4.21.2",
        "@modelcontextprotocol/sdk": "^1.8.0"
      }
    },
    "node_modules/express": {
      "version": "4.22.1"
    },
    "node_modules/@modelcontextprotocol/sdk": {
      "version": "1.29.0"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )

    manifest = await MCPDiscovery.from_local_directory(str(tmp_state_dir))

    assert manifest.name == "sample-mcp-ts"
    assert manifest.language == "typescript"
    assert manifest.dependencies["express"] == "4.22.1"
    assert manifest.dependencies["@modelcontextprotocol/sdk"] == "1.29.0"

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
]
""".strip(),
        encoding="utf-8",
    )

    manifest = await MCPDiscovery.from_local_directory(str(tmp_state_dir))

    assert manifest.name == "sample-mcp-python"
    assert manifest.version == "0.2.0"
    assert manifest.language == "python"
    assert manifest.transport == TransportType.STDIO
    assert manifest.dependencies["mcp"] == "1.2.3"
    assert manifest.dependencies["httpx>=0.27"] == "*"

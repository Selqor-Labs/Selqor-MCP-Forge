# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""DISCOVER module: Auto-detect MCP server structure and extract metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import DiscoveryMethod, MCPManifest, TransportType


class MCPDiscovery:
    """Discover and parse MCP server manifests from various sources."""

    @staticmethod
    async def from_local_directory(path: str) -> MCPManifest:
        """Discover MCP server from local directory.

        Looks for: mcp.json, package.json, Cargo.toml, pyproject.toml
        """
        base_path = Path(path)
        if not base_path.is_dir():
            raise ValueError(f"Path does not exist: {path}")

        # Try mcp.json first (MCP standard manifest)
        mcp_json = base_path / "mcp.json"
        if mcp_json.exists():
            manifest_data = json.loads(mcp_json.read_text())
            return MCPDiscovery._parse_mcp_manifest(
                manifest_data,
                discovery_method=DiscoveryMethod.LOCAL_DIRECTORY,
                source=str(base_path),
            )

        # Try TypeScript/Node.js
        package_json = base_path / "package.json"
        if package_json.exists():
            return await MCPDiscovery._discover_typescript_server(
                base_path, package_json
            )

        # Try Rust
        cargo_toml = base_path / "Cargo.toml"
        if cargo_toml.exists():
            return await MCPDiscovery._discover_rust_server(base_path, cargo_toml)

        # Try Python
        pyproject_toml = base_path / "pyproject.toml"
        if pyproject_toml.exists():
            return await MCPDiscovery._discover_python_server(base_path, pyproject_toml)

        # Fallback: empty manifest
        return MCPManifest(
            discovery_method=DiscoveryMethod.LOCAL_DIRECTORY,
            source=str(base_path),
            transport=TransportType.UNKNOWN,
            language="unknown",
        )

    @staticmethod
    async def from_github_url(github_url: str) -> MCPManifest:
        """Discover MCP server from GitHub repository.

        Uses GitHub API to fetch manifest files without cloning.
        """
        # Parse owner/repo from URL
        parsed = urlparse(github_url)
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {github_url}")

        owner, repo = path_parts[0], path_parts[1]
        repo = repo.replace(".git", "")

        async with httpx.AsyncClient() as client:
            # Try mcp.json
            mcp_json_url = (
                f"https://api.github.com/repos/{owner}/{repo}/contents/mcp.json"
            )
            try:
                resp = await client.get(mcp_json_url)
                if resp.status_code == 200:
                    content_b64 = resp.json().get("content", "")
                    import base64
                    manifest_data = json.loads(base64.b64decode(content_b64))
                    return MCPDiscovery._parse_mcp_manifest(
                        manifest_data,
                        discovery_method=DiscoveryMethod.GITHUB_URL,
                        source=github_url,
                    )
            except Exception:
                pass

            # Try package.json
            package_json_url = (
                f"https://api.github.com/repos/{owner}/{repo}/contents/package.json"
            )
            try:
                resp = await client.get(package_json_url)
                if resp.status_code == 200:
                    content_b64 = resp.json().get("content", "")
                    import base64
                    manifest_data = json.loads(base64.b64decode(content_b64))
                    return await MCPDiscovery._parse_package_json(
                        manifest_data,
                        owner,
                        repo,
                        github_url,
                    )
            except Exception:
                pass

        # Fallback
        return MCPManifest(
            discovery_method=DiscoveryMethod.GITHUB_URL,
            source=github_url,
            transport=TransportType.UNKNOWN,
            language="unknown",
        )

    @staticmethod
    async def from_running_server(
        server_url: str,
        timeout: float = 5.0,
    ) -> MCPManifest:
        """Discover MCP server from running instance.

        Probes server endpoint to detect transport, tools, and metadata.
        Supports both stdio and HTTP transports.
        """
        # Determine if stdio or HTTP
        if server_url.startswith("http://") or server_url.startswith("https://"):
            return await MCPDiscovery._probe_http_server(server_url, timeout)
        else:
            return await MCPDiscovery._probe_stdio_server(server_url, timeout)

    @staticmethod
    async def _discover_typescript_server(
        base_path: Path,
        package_json: Path,
    ) -> MCPManifest:
        """Parse TypeScript/Node.js MCP server."""
        pkg = json.loads(package_json.read_text())

        # Extract dependencies
        dependencies = {}
        dependencies.update(pkg.get("dependencies", {}))
        dependencies.update(pkg.get("devDependencies", {}))

        # Try to detect transport from package.json scripts or mcp.json
        transport = TransportType.STDIO
        mcp_config = pkg.get("mcp", {})
        if isinstance(mcp_config, dict):
            if mcp_config.get("transport") == "http":
                transport = TransportType.HTTP

        return MCPManifest(
            discovery_method=DiscoveryMethod.LOCAL_DIRECTORY,
            source=str(base_path),
            name=pkg.get("name"),
            version=pkg.get("version"),
            transport=transport,
            language="typescript",
            dependencies=dependencies,
            raw_manifest=pkg,
        )

    @staticmethod
    async def _discover_rust_server(
        base_path: Path,
        cargo_toml: Path,
    ) -> MCPManifest:
        """Parse Rust MCP server."""
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        try:
            with open(cargo_toml, "rb") as f:
                cargo = tomllib.load(f)
        except Exception:
            cargo = {}

        package = cargo.get("package", {})
        dependencies = {}
        dependencies.update(cargo.get("dependencies", {}))
        dependencies.update(cargo.get("dev-dependencies", {}))

        return MCPManifest(
            discovery_method=DiscoveryMethod.LOCAL_DIRECTORY,
            source=str(base_path),
            name=package.get("name"),
            version=package.get("version"),
            transport=TransportType.STDIO,
            language="rust",
            dependencies=dependencies,
            raw_manifest=cargo,
        )

    @staticmethod
    async def _discover_python_server(
        base_path: Path,
        pyproject_toml: Path,
    ) -> MCPManifest:
        """Parse Python MCP server."""
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        try:
            with open(pyproject_toml, "rb") as f:
                pyproject = tomllib.load(f)
        except Exception:
            pyproject = {}

        project = pyproject.get("project", {})
        dependencies = {}

        # Extract dependencies from dependencies or requires fields
        for dep_str in project.get("dependencies", []):
            # Parse "package==1.0.0" format
            if "==" in dep_str:
                name, version = dep_str.split("==", 1)
                dependencies[name.strip()] = version.strip()
            else:
                dependencies[dep_str.split("[")[0].strip()] = "*"

        return MCPManifest(
            discovery_method=DiscoveryMethod.LOCAL_DIRECTORY,
            source=str(base_path),
            name=project.get("name"),
            version=project.get("version"),
            transport=TransportType.STDIO,
            language="python",
            dependencies=dependencies,
            raw_manifest=pyproject,
        )

    @staticmethod
    def _parse_mcp_manifest(
        manifest: dict[str, Any],
        discovery_method: DiscoveryMethod,
        source: str,
    ) -> MCPManifest:
        """Parse standard MCP manifest format."""
        transport_str = manifest.get("transport", "stdio").lower()
        transport = TransportType.STDIO
        if transport_str == "http":
            transport = TransportType.HTTP
        elif transport_str == "http_sse":
            transport = TransportType.HTTP_SSE

        return MCPManifest(
            discovery_method=discovery_method,
            source=source,
            name=manifest.get("name"),
            version=manifest.get("version"),
            transport=transport,
            language=manifest.get("language", "unknown"),
            tools=manifest.get("tools", []),
            dependencies=manifest.get("dependencies", {}),
            auth_config=manifest.get("auth", {}),
            raw_manifest=manifest,
        )

    @staticmethod
    async def _parse_package_json(
        pkg: dict[str, Any],
        owner: str,
        repo: str,
        source: str,
    ) -> MCPManifest:
        """Parse package.json from GitHub."""
        dependencies = {}
        dependencies.update(pkg.get("dependencies", {}))
        dependencies.update(pkg.get("devDependencies", {}))

        return MCPManifest(
            discovery_method=DiscoveryMethod.GITHUB_URL,
            source=source,
            name=pkg.get("name"),
            version=pkg.get("version"),
            transport=TransportType.STDIO,
            language="typescript",
            dependencies=dependencies,
            raw_manifest=pkg,
        )

    @staticmethod
    async def _probe_http_server(
        server_url: str,
        timeout: float,
    ) -> MCPManifest:
        """Probe HTTP MCP server for metadata with full MCP protocol probing."""
        tools = []
        transport = TransportType.HTTP
        name = None
        version = None
        language = "unknown"
        raw_manifest = {}
        auth_config = {}

        try:
            async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
                # 1. Try /info endpoint
                try:
                    resp = await client.get(f"{server_url}/info")
                    if resp.status_code == 200:
                        info = resp.json()
                        name = info.get("name")
                        version = info.get("version")
                        language = info.get("language", "unknown")
                        tools = info.get("tools", [])
                        auth_config = info.get("auth", {})
                        raw_manifest = info
                except Exception:
                    pass

                # 2. MCP JSON-RPC initialize
                try:
                    init_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "selqor-scanner", "version": "1.0"},
                        },
                    }
                    resp = await client.post(server_url, json=init_payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        result = data.get("result", {})
                        result.get("capabilities", {})
                        server_info = result.get("serverInfo", {})
                        name = name or server_info.get("name")
                        version = version or server_info.get("version")
                        raw_manifest["mcp_init"] = result
                except Exception:
                    pass

                # 3. MCP tools/list
                try:
                    tools_payload = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    }
                    resp = await client.post(server_url, json=tools_payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        mcp_tools = data.get("result", {}).get("tools", [])
                        if mcp_tools:
                            tools = [t.get("name", "") for t in mcp_tools]
                            raw_manifest["mcp_tools"] = mcp_tools
                except Exception:
                    pass

                # 4. Check for SSE transport
                try:
                    resp = await client.get(f"{server_url}/sse", timeout=2.0)
                    if resp.status_code == 200 and "text/event-stream" in resp.headers.get("content-type", ""):
                        transport = TransportType.HTTP_SSE
                except Exception:
                    pass

                # 5. TLS check
                tls_info = {}
                if server_url.startswith("https://"):
                    tls_info["tls"] = True
                    tls_info["verified"] = True  # httpx verify=True passed
                else:
                    tls_info["tls"] = False
                raw_manifest["tls_info"] = tls_info

        except httpx.ConnectError as e:
            raise ValueError(f"Failed to connect to server: {e}")
        except Exception as e:
            raise ValueError(f"Failed to probe HTTP server: {e}")

        return MCPManifest(
            discovery_method=DiscoveryMethod.RUNNING_SERVER,
            source=server_url,
            name=name,
            version=version,
            transport=transport,
            language=language,
            tools=tools,
            auth_config=auth_config,
            raw_manifest=raw_manifest,
        )

    @staticmethod
    async def _probe_stdio_server(
        server_cmd: str,
        timeout: float,
    ) -> MCPManifest:
        """Probe a stdio-based MCP server for metadata.

        Sends a JSON-RPC ``initialize`` request followed by ``tools/list``
        over stdin, parses stdout, and returns a populated
        :class:`MCPManifest`.  Falls back gracefully on any error.
        """
        import logging
        import shlex

        logger = logging.getLogger(__name__)

        name: str | None = None
        version: str | None = None
        language = "unknown"
        tools: list[str] = []
        raw_manifest: dict = {}

        try:
            cmd_parts = shlex.split(server_cmd)

            # Build a two-message NDJSON payload (initialize + tools/list)
            # so we can extract both server info and tool names in a single
            # process invocation.
            init_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "selqor-scanner", "version": "1.0"},
                },
            })
            tools_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            })
            payload = (init_msg + "\n" + tools_msg + "\n").encode()

            result = subprocess.run(
                cmd_parts,
                input=payload,
                capture_output=True,
                timeout=min(timeout, 30),
                shell=False,
            )

            stderr_text = (result.stderr or b"").decode(errors="replace").strip()
            if stderr_text:
                logger.debug("stdio server stderr: %s", stderr_text[:500])

            stdout_text = (result.stdout or b"").decode(errors="replace").strip()
            if not stdout_text:
                logger.warning(
                    "stdio probe returned empty stdout cmd=%s rc=%d",
                    server_cmd, result.returncode,
                )
            else:
                # Parse NDJSON - one JSON object per line
                responses: list[dict] = []
                for line in stdout_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        responses.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug("skipping non-JSON stdio line: %s", line[:120])

                # Process initialize response (id=1)
                for resp in responses:
                    resp_id = resp.get("id")
                    resp_result = resp.get("result", {})

                    if resp_id == 1:
                        raw_manifest["mcp_init"] = resp_result
                        server_info = resp_result.get("serverInfo", {})
                        name = server_info.get("name")
                        version = server_info.get("version")
                        proto_version = resp_result.get("protocolVersion")
                        if proto_version:
                            raw_manifest["protocolVersion"] = proto_version

                    elif resp_id == 2:
                        # tools/list response
                        raw_manifest["mcp_tools"] = resp_result
                        tool_list = resp_result.get("tools", [])
                        for t in tool_list:
                            if isinstance(t, dict) and t.get("name"):
                                tools.append(t["name"])
                            elif isinstance(t, str):
                                tools.append(t)

                # Attempt language detection from the command itself
                language = _detect_language_from_command(server_cmd)

        except subprocess.TimeoutExpired:
            logger.warning("stdio probe timed out after %.0fs cmd=%s", timeout, server_cmd)
        except FileNotFoundError:
            logger.warning("stdio probe command not found: %s", server_cmd)
        except Exception as exc:
            logger.warning("stdio probe failed cmd=%s error=%s", server_cmd, exc)

        return MCPManifest(
            discovery_method=DiscoveryMethod.RUNNING_SERVER,
            source=server_cmd,
            name=name,
            version=version,
            transport=TransportType.STDIO,
            language=language,
            tools=tools,
            raw_manifest=raw_manifest,
        )


def _detect_language_from_command(cmd: str) -> str:
    """Infer the server language from the command string.

    Heuristic-based - looks for well-known interpreter prefixes and
    file extensions in the command.
    """
    lowered = cmd.lower().strip()
    # Direct interpreter prefix
    if lowered.startswith(("node ", "npx ", "tsx ", "ts-node ")):
        return "typescript"
    if lowered.startswith(("python ", "python3 ", "uv run ", "uvx ")):
        return "python"
    if lowered.startswith("cargo "):
        return "rust"
    if lowered.startswith(("go run ", "go ")):
        return "go"
    if lowered.startswith(("java ", "mvn ", "gradle ")):
        return "java"
    if lowered.startswith(("dotnet ", "csharp ")):
        return "csharp"
    # Extension sniffing
    if ".py " in lowered or lowered.endswith(".py"):
        return "python"
    if ".ts " in lowered or lowered.endswith(".ts"):
        return "typescript"
    if ".js " in lowered or lowered.endswith(".js"):
        return "typescript"
    if ".rs " in lowered or lowered.endswith(".rs"):
        return "rust"
    return "unknown"

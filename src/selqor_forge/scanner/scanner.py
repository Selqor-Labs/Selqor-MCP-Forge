# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Main SCAN coordinator: security scanning pipeline."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

from .cve_checker import CVEChecker
from .discover import MCPDiscovery
from .llm_judge import LLMJudge
from .openapi_scanner import (
    is_likely_openapi_url,
    looks_like_openapi,
    scan_openapi_document,
)
from .models import (
    AIBillOfMaterials,
    Component,
    DiscoveryMethod,
    MCPManifest,
    RiskLevel,
    RiskSummary,
    ScanResult,
    ScanStatistics,
    VulnerabilitySource,
    VulnerabilityItem,
)
from .rules_engine import HeuristicRuleEngine, SemgrepRuleEngine

# Well-known SPDX license identifiers for common packages.  The map is
# intentionally small - it covers the vast majority of packages found in
# typical MCP servers.  For anything outside this set the code falls back
# to the raw license string from the manifest.
_KNOWN_SPDX: dict[str, str] = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "isc": "ISC",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "gpl-2.0": "GPL-2.0-only",
    "gpl-3.0": "GPL-3.0-only",
    "lgpl-2.1": "LGPL-2.1-only",
    "mpl-2.0": "MPL-2.0",
    "unlicense": "Unlicense",
    "0bsd": "0BSD",
    "cc0-1.0": "CC0-1.0",
}


def _normalize_spdx(raw: str) -> str | None:
    """Try to map a raw license string to a canonical SPDX identifier."""
    if not raw:
        return None
    lowered = raw.strip().lower()
    return _KNOWN_SPDX.get(lowered)


def _extract_licenses_from_manifest(
    manifest: MCPManifest,
    components: list[Component],
) -> list:
    """Extract license information from the manifest's raw metadata.

    Supports:
    - Node.js ``package.json`` → ``license`` (string) or ``licenses`` (array)
    - Python ``pyproject.toml`` → ``project.license`` (string or table)
    - Rust ``Cargo.toml`` → ``package.license``
    - Any ``raw_manifest`` with a top-level ``license`` key
    """
    from .models import License

    raw = manifest.raw_manifest or {}
    license_map: dict[str, list[str]] = {}  # spdx_or_name -> [component names]

    # 1. Manifest-level license (applies to the project itself)
    project_license = _extract_project_license(raw, manifest.language)
    if project_license:
        license_map.setdefault(project_license, [])
        if manifest.name:
            license_map[project_license].append(manifest.name)

    # 2. Per-component: tag each component with the project license
    #    when no per-dependency metadata is available (common in practice)
    for comp in components:
        if comp.licenses:
            for lic in comp.licenses:
                license_map.setdefault(lic, []).append(comp.name)
        elif project_license:
            license_map.setdefault(project_license, []).append(comp.name)
            comp.licenses = [project_license]

    # Build License objects
    licenses = []
    for name, comps in license_map.items():
        spdx_id = _normalize_spdx(name)
        licenses.append(
            License(
                name=name,
                spdx_id=spdx_id,
                components=sorted(set(comps)),
            )
        )

    return licenses


def _extract_project_license(raw: dict, language: str) -> str | None:
    """Pull the top-level license string from raw manifest data."""
    # Node.js / package.json
    if language in ("typescript", "javascript"):
        lic = raw.get("license")
        if isinstance(lic, str) and lic.strip():
            return lic.strip()
        # older "licenses" array format
        lic_arr = raw.get("licenses")
        if isinstance(lic_arr, list) and lic_arr:
            first = lic_arr[0]
            if isinstance(first, dict):
                return first.get("type", first.get("name", ""))
            return str(first)
        return None

    # Python / pyproject.toml
    if language == "python":
        project = raw.get("project", {})
        lic = project.get("license")
        if isinstance(lic, str) and lic.strip():
            return lic.strip()
        if isinstance(lic, dict):
            return lic.get("text", lic.get("file", "")).strip() or None
        # classifiers fallback
        for clf in project.get("classifiers", []):
            if "License ::" in str(clf):
                parts = str(clf).split(" :: ")
                return parts[-1].strip() if len(parts) > 1 else None
        return None

    # Rust / Cargo.toml
    if language == "rust":
        pkg = raw.get("package", {})
        lic = pkg.get("license")
        if isinstance(lic, str) and lic.strip():
            return lic.strip()
        return None

    # Generic fallback
    lic = raw.get("license")
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    return None


class SecurityScanner:
    """Complete security scanning pipeline for MCP servers."""

    def __init__(
        self,
        api_key: str | None = None,
        use_semgrep: bool = False,
        enable_trivy: bool = False,
        llm_provider: str = "anthropic",
        llm_model: str | None = None,
        llm_base_url: str | None = None,
    ):
        """Initialize scanner.

        Args:
            api_key: API key for the LLM provider.
            use_semgrep: Use Semgrep rules engine (requires CLI).
            enable_trivy: Use Trivy for additional checks (requires CLI).
            llm_provider: LLM provider — "anthropic", "mistral", "openai", etc.
            llm_model: Model name override. Defaults per provider.
            llm_base_url: Base URL for OpenAI-compatible endpoints.
        """
        self.api_key = api_key
        self.use_semgrep = use_semgrep
        self.enable_trivy = enable_trivy

        # Initialize engines
        self.heuristic_engine = HeuristicRuleEngine()
        self.semgrep_engine = SemgrepRuleEngine() if use_semgrep else None
        _default_model = llm_model or ("claude-sonnet-4-20250514" if llm_provider == "anthropic" else llm_model or "gpt-4o-mini")
        self.llm_judge = LLMJudge(
            api_key=api_key,
            model=_default_model,
            provider=llm_provider,
            base_url=llm_base_url,
        )
        self.cve_checker = CVEChecker()

    async def scan_local_server(
        self,
        directory: str,
        full_mode: bool = True,
        progress_callback=None,
    ) -> ScanResult:
        """Scan local MCP server directory.

        Args:
            directory: Path to MCP server directory
            full_mode: If False, skip expensive checks (Trivy, LLM)
            progress_callback: Optional async callback for progress updates

        Returns:
            Complete scan result with findings and recommendations.
        """
        start_time = time.time()
        scan_id = str(uuid.uuid4())

        async def update_progress(step: str, number: int, total: int = 9, message: str = ""):
            if progress_callback:
                await progress_callback(step, number, total, message)

        # Step 1: DISCOVER
        await update_progress("discovery", 1, message="Detecting MCP server structure...")
        manifest = await MCPDiscovery.from_local_directory(directory)

        findings = []
        stats = ScanStatistics()

        # Step 2: PARSE
        await update_progress("heuristic_scan", 2, message="Scanning source code for vulnerabilities...")
        code_findings = await self.heuristic_engine.scan_directory(directory)
        findings.extend(code_findings)
        stats.files_scanned += len(set(f.file for f in code_findings if f.file))

        # Step 3: Semgrep
        if self.semgrep_engine:
            await update_progress("semgrep_scan", 3, message="Running Semgrep analysis...")
            semgrep_findings = await self.semgrep_engine.scan_directory(directory)
            findings.extend(semgrep_findings)
        else:
            await update_progress("semgrep_scan", 3, message="Semgrep skipped (not enabled)")

        # Step 4: CVE check
        await update_progress("cve_check", 4, message="Checking dependencies for known CVEs...")
        cve_findings = await self.cve_checker.check_dependencies(
            manifest.dependencies,
            language=manifest.language,
        )
        findings.extend(cve_findings)
        stats.dependencies_checked = len(manifest.dependencies)

        # Step 5: Trivy
        if self.enable_trivy and full_mode:
            await update_progress("trivy_scan", 5, message="Running Trivy comprehensive scan...")
            trivy_findings = await self.cve_checker.scan_with_trivy(directory)
            findings.extend(trivy_findings)
        else:
            await update_progress("trivy_scan", 5, message="Trivy skipped")

        # Step 6: LLM analysis
        if full_mode and not self.llm_judge.heuristic_mode:
            await update_progress("llm_analysis", 6, message="Running LLM security analysis...")
            code_snippets = self._collect_local_code_snippets(directory, manifest.language)
            tool_defs = self._normalize_tool_definitions(
                manifest.raw_manifest.get("mcp_tools", []) or manifest.tools or []
            )
            tool_descs = [
                tool.get("description", tool.get("name", ""))
                for tool in tool_defs
                if isinstance(tool, dict)
            ]
            llm_findings = await self.llm_judge.analyze_prompt_injection_risk(
                tool_defs if tool_defs else [{"spec": "local"}],
                tool_descs,
            )
            owasp_findings = await self.llm_judge.analyze_owasp_agentic_top10(
                tool_defs,
                code_snippets,
            )
            findings.extend(llm_findings)
            findings.extend(owasp_findings)
        elif full_mode:
            await update_progress("llm_analysis", 6, message="LLM analysis skipped (no LLM configured)")
        else:
            await update_progress("llm_analysis", 6, message="LLM analysis skipped (full mode disabled)")

        # Step 7: AI-BOM
        await update_progress("ai_bom", 7, message="Generating AI Bill of Materials...")
        ai_bom = await self._generate_ai_bom(manifest, findings)

        # Step 8: Risk scoring
        await update_progress("risk_scoring", 8, message="Calculating risk scores...")
        risk_summary = self._calculate_risk_summary(findings)
        suggested_fixes = await self._generate_suggested_fixes(findings)

        # Step 9: Finalize
        await update_progress("complete", 9, message="Scan complete")

        stats.total_findings = len(findings)
        stats.by_risk_level = {
            RiskLevel.CRITICAL: len([f for f in findings if f.risk_level == RiskLevel.CRITICAL]),
            RiskLevel.HIGH: len([f for f in findings if f.risk_level == RiskLevel.HIGH]),
            RiskLevel.MEDIUM: len([f for f in findings if f.risk_level == RiskLevel.MEDIUM]),
            RiskLevel.LOW: len([f for f in findings if f.risk_level == RiskLevel.LOW]),
            RiskLevel.INFO: len([f for f in findings if f.risk_level == RiskLevel.INFO]),
        }
        stats.by_source = {}
        for finding in findings:
            stats.by_source[finding.source] = stats.by_source.get(finding.source, 0) + 1
        stats.scan_duration_seconds = time.time() - start_time

        return ScanResult(
            id=scan_id,
            mcp_manifest=manifest,
            scan_timestamp=datetime.utcnow(),
            findings=findings,
            statistics=stats,
            risk_summary=risk_summary,
            ai_bom=ai_bom,
            suggested_fixes=suggested_fixes,
        )

    async def scan_github_server(
        self,
        github_url: str,
        full_mode: bool = True,
        progress_callback=None,
    ) -> ScanResult:
        """Scan MCP server from GitHub repository.

        Args:
            github_url: GitHub repository URL
            full_mode: If False, skip expensive checks
            progress_callback: Optional async callback for progress updates

        Returns:
            Scan result with findings from GitHub API analysis.
        """
        start_time = time.time()

        async def update_progress(step: str, number: int, total: int = 7, message: str = ""):
            if progress_callback:
                await progress_callback(step, number, total, message)

        # Step 1: Discover
        await update_progress("discovery", 1, message="Discovering MCP server from GitHub...")
        manifest = await MCPDiscovery.from_github_url(github_url)

        findings = []
        stats = ScanStatistics()

        # Step 2: Check dependencies for CVEs
        await update_progress("cve_check", 2, message="Checking dependencies for known CVEs...")
        cve_findings = await self.cve_checker.check_dependencies(
            manifest.dependencies,
            language=manifest.language,
        )
        findings.extend(cve_findings)
        stats.dependencies_checked = len(manifest.dependencies)

        # Step 3: Fetch and scan source files from GitHub
        await update_progress("source_scan", 3, message="Fetching and scanning source files...")
        source_findings = await self._scan_github_source(github_url, manifest.language)
        findings.extend(source_findings)
        stats.files_scanned = len(set(f.file for f in source_findings if f.file))

        # Step 4: Tool permission analysis if tools discovered
        await update_progress("tool_analysis", 4, message="Analyzing tool permissions...")
        if manifest.tools or manifest.raw_manifest.get("mcp_tools"):
            findings.extend(self._check_tool_permissions(manifest))

        # Step 5: LLM analysis if enabled
        if full_mode and not self.llm_judge.heuristic_mode:
            await update_progress("llm_analysis", 5, message="Running LLM security analysis...")
            tools = manifest.raw_manifest.get("mcp_tools", []) or manifest.tools or []
            tool_descs = [t.get("description", t.get("name", "")) for t in tools if isinstance(t, dict)]
            llm_findings = await self.llm_judge.analyze_prompt_injection_risk(
                tools if tools else [{"spec": "github"}],
                tool_descs,
            )
            owasp_findings = await self.llm_judge.analyze_owasp_agentic_top10(
                tools,
                [],
            )
            findings.extend(llm_findings)
            findings.extend(owasp_findings)
        else:
            await update_progress("llm_analysis", 5, message="LLM analysis skipped (no LLM configured)")

        # Step 6: Risk scoring and fixes
        await update_progress("risk_scoring", 6, message="Calculating risk scores...")
        risk_summary = self._calculate_risk_summary(findings)
        ai_bom = await self._generate_ai_bom(manifest, findings)
        suggested_fixes = await self._generate_suggested_fixes(findings)

        # Step 7: Finalize
        await update_progress("complete", 7, message="Scan complete")

        stats.total_findings = len(findings)
        stats.by_risk_level = {
            RiskLevel.CRITICAL: len([f for f in findings if f.risk_level == RiskLevel.CRITICAL]),
            RiskLevel.HIGH: len([f for f in findings if f.risk_level == RiskLevel.HIGH]),
            RiskLevel.MEDIUM: len([f for f in findings if f.risk_level == RiskLevel.MEDIUM]),
            RiskLevel.LOW: len([f for f in findings if f.risk_level == RiskLevel.LOW]),
            RiskLevel.INFO: len([f for f in findings if f.risk_level == RiskLevel.INFO]),
        }
        stats.scan_duration_seconds = time.time() - start_time

        return ScanResult(
            id=str(uuid.uuid4()),
            mcp_manifest=manifest,
            scan_timestamp=datetime.utcnow(),
            findings=findings,
            statistics=stats,
            risk_summary=risk_summary,
            ai_bom=ai_bom,
            suggested_fixes=suggested_fixes,
        )

    async def _scan_github_source(self, github_url: str, language: str) -> list:
        """Fetch and scan source files from GitHub."""
        from urllib.parse import urlparse

        parsed = urlparse(github_url)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            return []

        owner, repo = path_parts[0], path_parts[1].replace(".git", "")

        # Map language to file extensions
        ext_map = {
            "typescript": [".ts", ".tsx", ".js", ".jsx"],
            "javascript": [".js", ".jsx"],
            "python": [".py"],
            "rust": [".rs"],
            "go": [".go"],
        }
        target_exts = ext_map.get(language, [".ts", ".js", ".py"])

        findings = []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Get repository tree (recursive)
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code != 200:
                    # Try 'master' branch
                    resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1",
                        headers={"Accept": "application/vnd.github.v3+json"},
                    )

                if resp.status_code != 200:
                    return findings

                tree = resp.json().get("tree", [])

                # Filter source files (skip node_modules, dist, etc.)
                skip_dirs = {"node_modules", "dist", "build", ".git", "target", "__pycache__", "venv"}
                source_files = []
                for item in tree:
                    if item.get("type") != "blob":
                        continue
                    path = item.get("path", "")
                    if any(skip in path.split("/") for skip in skip_dirs):
                        continue
                    if any(path.endswith(ext) for ext in target_exts):
                        source_files.append(path)

                # Limit to 30 files to avoid GitHub rate limits
                source_files = source_files[:30]

                # Fetch and scan each file
                for file_path in source_files:
                    try:
                        import base64
                        resp = await client.get(
                            f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}",
                            headers={"Accept": "application/vnd.github.v3+json"},
                        )
                        if resp.status_code == 200:
                            content_b64 = resp.json().get("content", "")
                            content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
                            file_findings = await self.heuristic_engine.scan_file(file_path, content)
                            findings.extend(file_findings)
                    except Exception:
                        continue
        except Exception:
            pass

        return findings

    def _collect_local_code_snippets(
        self,
        directory: str,
        language: str,
        *,
        limit: int = 30,
    ) -> list[tuple[str, str]]:
        """Load a small representative set of local source files for LLM checks."""
        ext_map = {
            "typescript": [".ts", ".tsx", ".js", ".jsx"],
            "javascript": [".js", ".jsx"],
            "python": [".py"],
            "rust": [".rs"],
            "go": [".go"],
        }
        target_exts = ext_map.get(language, [".ts", ".js", ".py"])
        skip_dirs = {"node_modules", "dist", "build", ".git", "target", "__pycache__", "venv"}

        snippets: list[tuple[str, str]] = []
        base_path = Path(directory)
        for file_path in base_path.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in skip_dirs for part in file_path.parts):
                continue
            if not any(file_path.name.endswith(ext) for ext in target_exts):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            snippets.append((str(file_path.relative_to(base_path)).replace("\\", "/"), content))
            if len(snippets) >= limit:
                break

        return snippets

    @staticmethod
    def _normalize_tool_definitions(tools: list) -> list[dict]:
        """Convert mixed manifest tool shapes into dict payloads for LLM analysis."""
        normalized: list[dict] = []
        for tool in tools:
            if isinstance(tool, dict):
                normalized.append(tool)
            elif isinstance(tool, str):
                normalized.append({"name": tool})
        return normalized

    async def scan_running_server(
        self,
        server_url: str,
        progress_callback=None,
    ) -> ScanResult:
        """Scan a running MCP server **or** a hosted OpenAPI / Swagger document.

        The endpoint may be either a live MCP server (HTTP / SSE) or a URL
        that resolves to an OpenAPI specification. We pick the right pipeline
        based on a cheap URL heuristic plus a content sniff.

        Args:
            server_url: URL of the running MCP server or OpenAPI spec
            progress_callback: Optional async callback for progress updates
        """
        start_time = time.time()

        async def update_progress(step: str, number: int, total: int = 7, message: str = ""):
            if progress_callback:
                await progress_callback(step, number, total, message)

        # Step 1: Discover. If the URL looks like an OpenAPI spec, fetch and
        # parse it. Otherwise probe the URL as a live MCP server first; if
        # that yields nothing useful, fall back to a content sniff in case
        # the URL is an unannotated spec endpoint.
        await update_progress("discovery", 1, message="Probing target...")
        spec_doc, manifest = await self._discover_target(server_url)

        findings = []
        stats = ScanStatistics()

        # If we discovered an OpenAPI document, run the OpenAPI heuristics
        # and return early â€" the MCP-specific checks below would all be no-ops.
        if spec_doc is not None:
            await update_progress("openapi_check", 2, total=5, message="Analysing OpenAPI specification...")
            findings.extend(scan_openapi_document(spec_doc, source=server_url))

            # LLM security analysis on the discovered tools/endpoints
            if not self.llm_judge.heuristic_mode:
                await update_progress("llm_analysis", 3, total=5, message="Running LLM security analysis...")
                tool_defs = manifest.tools or spec_doc.get("paths", {})
                tool_descs = [
                    f"{method.upper()} {path}: {(ops.get('summary') or ops.get('operationId') or path)}"
                    for path, methods in (spec_doc.get("paths") or {}).items()
                    for method, ops in methods.items()
                    if method in ("get", "post", "put", "patch", "delete")
                ]
                llm_findings = await self.llm_judge.analyze_prompt_injection_risk(
                    tool_defs if isinstance(tool_defs, list) else [{"spec": "openapi"}],
                    tool_descs[:50],  # Limit to 50 endpoint descriptions
                )
                findings.extend(llm_findings)
            else:
                await update_progress("llm_analysis", 3, total=5, message="LLM analysis skipped (no API key)")

            await update_progress("risk_scoring", 4, total=5, message="Calculating risk scores...")
            risk_summary = self._calculate_risk_summary(findings)
            ai_bom = await self._generate_ai_bom(manifest, findings)
            suggested_fixes = await self._generate_suggested_fixes(findings)

            await update_progress("complete", 5, total=5, message="Scan complete")

            stats.total_findings = len(findings)
            stats.by_risk_level = {
                RiskLevel.CRITICAL: len([f for f in findings if f.risk_level == RiskLevel.CRITICAL]),
                RiskLevel.HIGH: len([f for f in findings if f.risk_level == RiskLevel.HIGH]),
                RiskLevel.MEDIUM: len([f for f in findings if f.risk_level == RiskLevel.MEDIUM]),
                RiskLevel.LOW: len([f for f in findings if f.risk_level == RiskLevel.LOW]),
                RiskLevel.INFO: len([f for f in findings if f.risk_level == RiskLevel.INFO]),
            }
            stats.scan_duration_seconds = time.time() - start_time

            return ScanResult(
                id=str(uuid.uuid4()),
                mcp_manifest=manifest,
                scan_timestamp=datetime.utcnow(),
                findings=findings,
                statistics=stats,
                risk_summary=risk_summary,
                ai_bom=ai_bom,
                suggested_fixes=suggested_fixes,
            )

        # Step 2: Transport security checks
        await update_progress("transport_check", 2, message="Checking transport security...")
        findings.extend(self._check_transport_security(server_url, manifest))

        # Step 3: MCP protocol-level checks
        await update_progress("mcp_check", 3, message="Analyzing MCP protocol security...")
        findings.extend(await self._check_mcp_security(server_url, manifest))

        # Step 4: Tool permission analysis
        await update_progress("tool_analysis", 4, message="Analyzing tool permissions...")
        findings.extend(self._check_tool_permissions(manifest))

        # Step 5: Check dependencies if available
        await update_progress("cve_check", 5, message="Checking dependencies for known CVEs...")
        if manifest.dependencies:
            cve_findings = await self.cve_checker.check_dependencies(
                manifest.dependencies, language=manifest.language,
            )
            findings.extend(cve_findings)
            stats.dependencies_checked = len(manifest.dependencies)

        # Step 5b: LLM security analysis
        if not self.llm_judge.heuristic_mode and manifest.tools:
            await update_progress("llm_analysis", 5, message="Running LLM security analysis...")
            tool_descs = [t.get("description", t.get("name", "")) for t in manifest.tools if isinstance(t, dict)]
            llm_findings = await self.llm_judge.analyze_prompt_injection_risk(
                manifest.tools,
                tool_descs,
            )
            findings.extend(llm_findings)

        # Step 6: Calculate risk
        await update_progress("risk_scoring", 6, message="Calculating risk scores...")
        risk_summary = self._calculate_risk_summary(findings)
        ai_bom = await self._generate_ai_bom(manifest, findings)
        suggested_fixes = await self._generate_suggested_fixes(findings)

        # Step 7: Finalize
        await update_progress("complete", 7, message="Scan complete")

        stats.total_findings = len(findings)
        stats.by_risk_level = {
            RiskLevel.CRITICAL: len([f for f in findings if f.risk_level == RiskLevel.CRITICAL]),
            RiskLevel.HIGH: len([f for f in findings if f.risk_level == RiskLevel.HIGH]),
            RiskLevel.MEDIUM: len([f for f in findings if f.risk_level == RiskLevel.MEDIUM]),
            RiskLevel.LOW: len([f for f in findings if f.risk_level == RiskLevel.LOW]),
            RiskLevel.INFO: len([f for f in findings if f.risk_level == RiskLevel.INFO]),
        }
        stats.scan_duration_seconds = time.time() - start_time

        return ScanResult(
            id=str(uuid.uuid4()),
            mcp_manifest=manifest,
            scan_timestamp=datetime.utcnow(),
            findings=findings,
            statistics=stats,
            risk_summary=risk_summary,
            ai_bom=ai_bom,
            suggested_fixes=suggested_fixes,
        )

    async def _discover_target(self, server_url: str) -> tuple[dict | None, MCPManifest]:
        """Resolve a URL to either a parsed OpenAPI document + dummy manifest,
        or to a real MCP server manifest via the existing discovery probe.

        Returns ``(spec_doc, manifest)`` where ``spec_doc`` is non-None when
        the target is an OpenAPI / Swagger document.
        """
        import httpx
        from .models import TransportType

        async def _try_fetch_spec() -> dict | None:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(server_url, follow_redirects=True)
                if resp.status_code != 200:
                    return None
                ctype = (resp.headers.get("content-type") or "").lower()
                # JSON spec
                if "json" in ctype or server_url.lower().endswith(".json"):
                    try:
                        payload = resp.json()
                    except Exception:
                        return None
                    return payload if looks_like_openapi(payload) else None
                # YAML spec
                if "yaml" in ctype or server_url.lower().endswith((".yaml", ".yml")):
                    try:
                        import yaml  # type: ignore
                        payload = yaml.safe_load(resp.text)
                    except Exception:
                        return None
                    return payload if looks_like_openapi(payload) else None
                # Last resort: try to parse JSON anyway in case content-type is wrong.
                try:
                    payload = resp.json()
                    return payload if looks_like_openapi(payload) else None
                except Exception:
                    return None
            except Exception:
                return None

        spec_doc: dict | None = None

        # Cheap pre-check: URL extension or path hint
        if is_likely_openapi_url(server_url):
            spec_doc = await _try_fetch_spec()

        # If still nothing, fall back to MCP server probe
        if spec_doc is None:
            try:
                manifest = await MCPDiscovery.from_running_server(server_url)
            except Exception:
                manifest = MCPManifest(
                    discovery_method=DiscoveryMethod.RUNNING_SERVER,
                    source=server_url,
                    transport=TransportType.UNKNOWN,
                    language="unknown",
                )

            # Sniff: if the manifest is empty (no tools, no deps) and the URL
            # might still be a spec, try fetching it once more.
            if not manifest.tools and not manifest.dependencies and not is_likely_openapi_url(server_url):
                spec_doc = await _try_fetch_spec()
            return spec_doc, manifest

        # We have a spec; build a synthetic manifest so the rest of the
        # pipeline still has something to attach metadata to.
        info = (spec_doc.get("info") or {}) if isinstance(spec_doc, dict) else {}
        manifest = MCPManifest(
            discovery_method=DiscoveryMethod.RUNNING_SERVER,
            source=server_url,
            name=info.get("title"),
            version=info.get("version"),
            transport=TransportType.HTTP,
            language="openapi",
            raw_manifest={"openapi_spec_url": server_url, "info": info},
        )
        return spec_doc, manifest

    def _check_transport_security(self, server_url: str, manifest: MCPManifest) -> list:
        """Check transport-level security."""
        from .models import SecurityFinding
        findings = []

        # No TLS
        if server_url.startswith("http://") and not any(h in server_url for h in ["localhost", "127.0.0.1", "0.0.0.0"]):
            findings.append(SecurityFinding(
                id="transport_001_no_tls",
                title="No TLS Encryption",
                description="Server is accessible over unencrypted HTTP. All data including tool calls, credentials, and responses are transmitted in plaintext.",
                risk_level=RiskLevel.CRITICAL,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Enable HTTPS with a valid TLS certificate. Use Let's Encrypt for free certificates.",
                tags=["transport", "tls", "encryption"],
            ))

        # Check if CORS is overly permissive (from raw manifest if available)
        tls_info = manifest.raw_manifest.get("tls_info", {})
        if tls_info.get("tls") is False and not any(h in server_url for h in ["localhost", "127.0.0.1"]):
            findings.append(SecurityFinding(
                id="transport_002_no_cert",
                title="Missing TLS Certificate Verification",
                description="Connection does not use TLS certificate verification.",
                risk_level=RiskLevel.HIGH,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Deploy a valid TLS certificate and enforce HTTPS.",
                tags=["transport", "tls", "certificate"],
            ))

        return findings

    async def _check_mcp_security(self, server_url: str, manifest: MCPManifest) -> list:
        """MCP protocol-level security checks."""
        from .models import SecurityFinding
        findings = []
        mcp_tools = manifest.raw_manifest.get("mcp_tools", [])

        # Check for dangerous tool descriptions (prompt injection vectors)
        dangerous_keywords = ["eval", "exec", "system", "shell", "sudo", "rm -rf", "drop table", "delete from"]
        for tool in mcp_tools:
            desc = (tool.get("description") or "").lower()
            name = (tool.get("name") or "").lower()
            for keyword in dangerous_keywords:
                if keyword in desc or keyword in name:
                    findings.append(SecurityFinding(
                        id=f"mcp_001_{name}_{keyword}",
                        title=f"Dangerous Tool Definition: {tool.get('name', 'unknown')}",
                        description=f"Tool description or name contains dangerous keyword '{keyword}' which could enable prompt injection or code execution.",
                        risk_level=RiskLevel.HIGH,
                        source=VulnerabilitySource.HEURISTIC,
                        remediation="Review tool description. Remove dangerous operations or add strict input validation.",
                        tags=["mcp", "tool-poisoning", "prompt-injection"],
                    ))
                    break

        # Check for overly broad tool schemas (no input validation)
        for tool in mcp_tools:
            schema = tool.get("inputSchema", {})
            properties = schema.get("properties", {})

            # Tools with string inputs but no maxLength, pattern, or enum constraints
            unconstrained_inputs = []
            for prop_name, prop_def in properties.items():
                if isinstance(prop_def, dict) and prop_def.get("type") == "string":
                    has_constraint = any(k in prop_def for k in ["maxLength", "pattern", "enum", "const", "format"])
                    if not has_constraint:
                        unconstrained_inputs.append(prop_name)

            if unconstrained_inputs and len(unconstrained_inputs) >= 2:
                findings.append(SecurityFinding(
                    id=f"mcp_002_{tool.get('name', 'unknown')}",
                    title=f"Unconstrained Tool Inputs: {tool.get('name', 'unknown')}",
                    description=f"Tool has {len(unconstrained_inputs)} string inputs without validation constraints ({', '.join(unconstrained_inputs[:3])}). This increases injection attack surface.",
                    risk_level=RiskLevel.MEDIUM,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Add maxLength, pattern, or enum constraints to string input schemas.",
                    tags=["mcp", "schema-validation", "input-validation"],
                ))

        # Check for excessive tool count (large attack surface)
        if len(mcp_tools) > 20:
            findings.append(SecurityFinding(
                id="mcp_003_excessive_tools",
                title="Excessive Tool Count",
                description=f"Server exposes {len(mcp_tools)} tools. Large tool surfaces increase risk of unauthorized access and make security auditing difficult.",
                risk_level=RiskLevel.MEDIUM,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Review tool list and remove unnecessary tools. Group related operations. Apply principle of least privilege.",
                tags=["mcp", "attack-surface", "least-privilege"],
            ))

        # Check for missing auth on capabilities
        if not manifest.auth_config and mcp_tools:
            findings.append(SecurityFinding(
                id="mcp_004_no_auth",
                title="No Authentication on MCP Server",
                description="MCP server does not appear to require authentication. Any client can connect and invoke tools.",
                risk_level=RiskLevel.HIGH,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Implement authentication (API key, OAuth, or mTLS) for MCP server access.",
                tags=["mcp", "authentication", "access-control"],
            ))

        return findings

    def _check_tool_permissions(self, manifest: MCPManifest) -> list:
        """Analyze tool permissions for principle of least privilege."""
        from .models import SecurityFinding
        findings = []
        mcp_tools = manifest.raw_manifest.get("mcp_tools", [])

        # Categories of sensitive operations
        sensitive_categories = {
            "file_system": ["read", "write", "delete", "create", "move", "copy", "file", "directory", "path"],
            "network": ["http", "fetch", "request", "download", "upload", "url", "connect", "socket"],
            "database": ["query", "sql", "insert", "update", "delete", "drop", "create", "table", "database"],
            "system": ["exec", "shell", "command", "process", "system", "spawn", "run", "sudo"],
            "auth": ["token", "password", "credential", "secret", "key", "auth", "login", "session"],
        }

        tool_categories = {}
        for tool in mcp_tools:
            name = (tool.get("name") or "").lower()
            desc = (tool.get("description") or "").lower()
            text = f"{name} {desc}"

            cats = set()
            for category, keywords in sensitive_categories.items():
                if any(kw in text for kw in keywords):
                    cats.add(category)
            if cats:
                tool_categories[tool.get("name", "unknown")] = cats

        # Flag servers that mix too many permission scopes
        all_categories = set()
        for cats in tool_categories.values():
            all_categories.update(cats)

        if len(all_categories) >= 4:
            findings.append(SecurityFinding(
                id="perm_001_broad_scope",
                title="Overly Broad Permission Scope",
                description=f"Server tools span {len(all_categories)} sensitive categories ({', '.join(sorted(all_categories))}). This violates the principle of least privilege.",
                risk_level=RiskLevel.HIGH,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Split server into multiple focused servers with narrower scopes. Each server should handle one domain.",
                tags=["permissions", "least-privilege", "scope"],
            ))

        # Flag tools that combine read+write+delete (god tools)
        for tool_name, cats in tool_categories.items():
            if "system" in cats and len(cats) >= 2:
                findings.append(SecurityFinding(
                    id=f"perm_002_{tool_name}",
                    title=f"High-Privilege Tool: {tool_name}",
                    description=f"Tool has system-level access combined with {', '.join(cats - {'system'})} capabilities.",
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation=f"Restrict tool '{tool_name}' to minimum required permissions. Separate system operations from other capabilities.",
                    tags=["permissions", "privilege-escalation", "system-access"],
                ))

        return findings

    def _calculate_risk_summary(self, findings: list) -> RiskSummary:
        """Calculate overall risk score and summary.

        Score is a SAFETY score: 100 = perfectly safe, 0 = extremely dangerous.
        """
        if not findings:
            return RiskSummary(
                overall_score=100,  # No findings = perfect score
                risk_level=RiskLevel.INFO,
                top_risks=[],
                recommendation="No security issues detected. Server appears safe.",
            )

        # Deduction-based scoring: start at 100, subtract per finding
        score_deductions = {
            RiskLevel.CRITICAL: 25,
            RiskLevel.HIGH: 15,
            RiskLevel.MEDIUM: 8,
            RiskLevel.LOW: 3,
            RiskLevel.INFO: 1,
        }

        total_deduction = sum(score_deductions.get(f.risk_level, 1) for f in findings)
        # Diminishing returns: use log scale for many findings
        if len(findings) > 10:
            # Scale down deductions for high finding counts to keep score meaningful
            scale_factor = 10 / len(findings)
            total_deduction = total_deduction * (scale_factor + (1 - scale_factor) * 0.5)

        overall_score = max(0, round(100 - total_deduction))

        # Determine risk level
        critical_count = len([f for f in findings if f.risk_level == RiskLevel.CRITICAL])
        high_count = len([f for f in findings if f.risk_level == RiskLevel.HIGH])
        medium_count = len([f for f in findings if f.risk_level == RiskLevel.MEDIUM])

        if critical_count > 0:
            risk_level = RiskLevel.CRITICAL
            recommendation = f"CRITICAL: {critical_count} critical issue(s) require immediate remediation before deployment."
        elif high_count > 2:
            risk_level = RiskLevel.HIGH
            recommendation = f"HIGH RISK: {high_count} high-severity issues should be resolved before production use."
        elif high_count > 0:
            risk_level = RiskLevel.HIGH
            recommendation = f"HIGH: {high_count} high-severity issue(s) detected. Review and fix before deployment."
        elif medium_count > 3:
            risk_level = RiskLevel.MEDIUM
            recommendation = f"MODERATE: {medium_count} medium-severity issues found. Address before production."
        elif medium_count > 0:
            risk_level = RiskLevel.MEDIUM
            recommendation = "MODERATE: Some issues detected. Review recommended before production use."
        else:
            risk_level = RiskLevel.LOW
            recommendation = "LOW RISK: Only minor issues detected. Deployment is acceptable with monitoring."

        # Top 5 risks
        top_risks = [
            f.title
            for f in sorted(findings, key=lambda x: score_deductions.get(x.risk_level, 0), reverse=True)[:5]
        ]

        return RiskSummary(
            overall_score=overall_score,
            risk_level=risk_level,
            top_risks=top_risks,
            recommendation=recommendation,
        )

    async def _generate_ai_bom(
        self,
        manifest: MCPManifest,
        findings: list,
    ) -> AIBillOfMaterials:
        """Generate AI Bill of Materials."""
        components = []

        # Add components from dependencies
        for name, version in manifest.dependencies.items():
            # Determine component type
            comp_type = "library"
            if name in ["node", "python", "rust", "go"]:
                comp_type = "runtime"

            component = Component(
                name=name,
                version=version,
                component_type=comp_type,
                purl=f"pkg:{manifest.language.lower()}/{name}@{version}",
            )
            components.append(component)

        # Extract vulnerable packages from findings
        vulnerabilities = []
        for finding in findings:
            if finding.cve_id and finding.metadata.get("package"):
                vuln = VulnerabilityItem(
                    cve_id=finding.cve_id,
                    component=finding.metadata["package"],
                    version=finding.metadata.get("version", "unknown"),
                    severity=finding.risk_level,
                    cvss_score=finding.cvss_score,
                )
                vulnerabilities.append(vuln)

        # ── License detection from package metadata ────────────
        licenses = _extract_licenses_from_manifest(manifest, components)

        return AIBillOfMaterials(
            components=components,
            vulnerabilities=vulnerabilities,
            licenses=licenses,
            compliance_notes=[
                "Scanned with selqor-mcp-forge-scanner",
                f"Language: {manifest.language}",
                f"Transport: {manifest.transport}",
            ],
        )

    async def _generate_suggested_fixes(self, findings: list) -> list:
        """Generate one suggested fix per finding.

        Each ``SecurityFinding`` carries its own ``remediation`` text â€" the
        most accurate guidance available. Producing one ``SuggestedFix`` per
        finding gives the user a 1:1 mapping in the UI instead of three hard
        coded category buckets that hide most issues.
        """
        from .models import SuggestedFix

        if not findings:
            return []

        fixes: list = []
        # Sort by severity so the highest-impact remediations show first.
        severity_order = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 3,
            RiskLevel.INFO: 4,
        }
        sorted_findings = sorted(
            findings,
            key=lambda f: severity_order.get(getattr(f, "risk_level", None), 5),
        )

        for idx, finding in enumerate(sorted_findings, start=1):
            instructions = (finding.remediation or "").strip()
            if not instructions:
                instructions = (
                    "Review the finding details above and apply your team's "
                    "standard hardening for this class of issue."
                )

            # Map our broad risk levels to the SuggestedFix.severity literals.
            risk = getattr(finding, "risk_level", None)
            if risk in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                fix_severity = "patch"
                effort = "medium"
            elif risk == RiskLevel.MEDIUM:
                fix_severity = "config"
                effort = "low"
            else:
                fix_severity = "review"
                effort = "low"

            fixes.append(
                SuggestedFix(
                    finding_id=finding.id,
                    title=finding.title,
                    description=finding.description[:280] if finding.description else "",
                    severity=fix_severity,
                    instructions=instructions,
                    effort=effort,
                    precedence=idx,
                )
            )

        return fixes

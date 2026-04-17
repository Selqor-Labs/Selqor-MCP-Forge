# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Data models for security scanning and vulnerability analysis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    """Risk severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class DiscoveryMethod(StrEnum):
    """How the MCP server was discovered."""
    LOCAL_DIRECTORY = "local_directory"
    GITHUB_URL = "github_url"
    RUNNING_SERVER = "running_server"


class TransportType(StrEnum):
    """MCP transport mechanism."""
    STDIO = "stdio"
    HTTP = "http"
    HTTP_SSE = "http_sse"
    UNKNOWN = "unknown"


class VulnerabilitySource(StrEnum):
    """Source of vulnerability finding."""
    SEMGREP = "semgrep"
    CUSTOM_RULES = "custom_rules"
    CVE_DATABASE = "cve_database"
    LLM_JUDGE = "llm_judge"
    HEURISTIC = "heuristic"


class SecurityFinding(BaseModel):
    """A single security finding."""
    id: str
    title: str
    description: str
    risk_level: RiskLevel
    source: VulnerabilitySource
    file: str | None = None
    line: int | None = None
    code_snippet: str | None = None
    remediation: str | None = None
    cve_id: str | None = None
    cvss_score: float | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPManifest(BaseModel):
    """Discovered MCP server manifest."""
    discovery_method: DiscoveryMethod
    source: str  # file path, URL, or server URL
    name: str | None = None
    version: str | None = None
    transport: TransportType
    language: str  # typescript, rust, python, etc.
    tools: list[str] = Field(default_factory=list)
    dependencies: dict[str, str] = Field(default_factory=dict)  # name -> version
    auth_config: dict[str, Any] = Field(default_factory=dict)
    raw_manifest: dict[str, Any] = Field(default_factory=dict)  # full manifest data


class ScanProgress(BaseModel):
    """Progress tracking for running scans."""
    current_step: str = "initializing"
    step_number: int = 0
    total_steps: int = 8
    percent_complete: int = 0
    message: str = ""


class ScanResult(BaseModel):
    """Complete security scan result."""
    id: str
    mcp_manifest: MCPManifest
    scan_timestamp: datetime
    findings: list[SecurityFinding] = Field(default_factory=list)
    statistics: ScanStatistics = Field(default_factory=dict)
    risk_summary: RiskSummary = Field(default_factory=dict)
    ai_bom: AIBillOfMaterials | None = None
    suggested_fixes: list[SuggestedFix] = Field(default_factory=list)
    progress: ScanProgress = Field(default_factory=ScanProgress)


class ScanStatistics(BaseModel):
    """Statistics about the scan."""
    total_findings: int = 0
    by_risk_level: dict[RiskLevel, int] = Field(default_factory=lambda: {
        RiskLevel.CRITICAL: 0,
        RiskLevel.HIGH: 0,
        RiskLevel.MEDIUM: 0,
        RiskLevel.LOW: 0,
        RiskLevel.INFO: 0,
    })
    by_source: dict[VulnerabilitySource, int] = Field(default_factory=dict)
    files_scanned: int = 0
    lines_analyzed: int = 0
    dependencies_checked: int = 0
    scan_duration_seconds: float = 0.0


class RiskSummary(BaseModel):
    """Overall risk assessment."""
    overall_score: float  # 0-100
    risk_level: RiskLevel
    top_risks: list[str] = Field(default_factory=list)  # top 3 risk titles
    recommendation: str


class AIBillOfMaterials(BaseModel):
    """AI-generated Bill of Materials."""
    components: list[Component] = Field(default_factory=list)
    vulnerabilities: list[VulnerabilityItem] = Field(default_factory=list)
    licenses: list[License] = Field(default_factory=list)
    compliance_notes: list[str] = Field(default_factory=list)


class Component(BaseModel):
    """A software component in the BOM."""
    name: str
    version: str
    component_type: Literal["library", "tool", "runtime", "service"]
    purl: str  # Package URL
    licenses: list[str] = Field(default_factory=list)


class VulnerabilityItem(BaseModel):
    """Vulnerability entry in BOM."""
    cve_id: str
    component: str
    version: str
    severity: RiskLevel
    cvss_score: float | None = None
    status: Literal["vulnerable", "patched", "unaffected"] = "vulnerable"


class License(BaseModel):
    """License information."""
    name: str
    spdx_id: str | None = None
    components: list[str] = Field(default_factory=list)


class SuggestedFix(BaseModel):
    """Suggested fix for a finding."""
    finding_id: str
    title: str
    description: str
    severity: Literal["patch", "config", "refactor", "review"]
    patch: str | None = None  # unified diff format
    instructions: str
    effort: Literal["low", "medium", "high"]
    precedence: int  # 1 = highest priority

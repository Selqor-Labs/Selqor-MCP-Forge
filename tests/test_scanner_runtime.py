# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Runtime scanner regression tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from selqor_forge.scanner.cve_checker import CVEChecker
from selqor_forge.scanner.models import RiskLevel
from selqor_forge.scanner.scanner import SecurityScanner


@pytest.mark.asyncio
async def test_local_scan_uses_llm_analysis_when_configured(tmp_state_dir):
    pyproject = tmp_state_dir / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-mcp-python"
version = "0.2.0"
dependencies = ["httpx>=0.27"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_state_dir / "server.py").write_text("print('hello world')\n", encoding="utf-8")

    scanner = SecurityScanner(api_key="test-key", llm_provider="mistral", llm_model="mistral-medium-latest")
    scanner.heuristic_engine.scan_directory = AsyncMock(return_value=[])
    scanner.cve_checker.check_dependencies = AsyncMock(return_value=[])
    scanner.llm_judge.analyze_prompt_injection_risk = AsyncMock(return_value=[])
    scanner.llm_judge.analyze_owasp_agentic_top10 = AsyncMock(return_value=[])
    scanner._generate_ai_bom = AsyncMock(return_value=None)
    scanner._generate_suggested_fixes = AsyncMock(return_value=[])
    scanner._collect_local_code_snippets = lambda *args, **kwargs: [("server.py", "print('hello world')")]

    result = await scanner.scan_local_server(str(tmp_state_dir), full_mode=True)

    assert result.statistics.total_findings == 0
    scanner.llm_judge.analyze_prompt_injection_risk.assert_awaited_once()
    scanner.llm_judge.analyze_owasp_agentic_top10.assert_awaited_once()


@pytest.mark.asyncio
async def test_cve_checker_accepts_structured_osv_severity(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "vulns": [
                    {
                        "id": "OSV-2026-1",
                        "summary": "Structured severity vulnerability",
                        "severity": [{"type": "CVSS_V3", "score": "9.8"}],
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            requests.append(json)
            return FakeResponse()

    monkeypatch.setattr("selqor_forge.scanner.cve_checker.httpx.AsyncClient", lambda timeout: FakeClient())

    findings = await CVEChecker.check_dependencies({"httpx": ">=0.27"}, language="python")

    assert len(findings) == 1
    assert findings[0].risk_level == RiskLevel.CRITICAL
    assert "version" not in requests[0]


def test_cve_checker_severity_parsing_handles_strings_and_nested_payloads():
    assert CVEChecker._severity_to_risk("HIGH") == RiskLevel.HIGH
    assert CVEChecker._severity_to_risk({"score": "9.8"}) == RiskLevel.CRITICAL
    assert CVEChecker._severity_to_risk([{"score": "5.0"}, {"severity": "LOW"}]) == RiskLevel.MEDIUM

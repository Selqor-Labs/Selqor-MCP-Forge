# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""LLM-based judgment for complex vulnerability analysis."""

from __future__ import annotations

import json
from typing import Any

from .models import RiskLevel, SecurityFinding, VulnerabilitySource


class LLMCallRecord:
    """Simple record of an LLM API call for logging."""

    __slots__ = ("model", "endpoint", "success", "latency_ms", "request_summary", "response_text", "error")

    def __init__(self, *, model: str, endpoint: str, success: bool, latency_ms: int,
                 request_summary: str = "", response_text: str = "", error: str | None = None):
        self.model = model
        self.endpoint = endpoint
        self.success = success
        self.latency_ms = latency_ms
        self.request_summary = request_summary
        self.response_text = response_text
        self.error = error


class LLMJudge:
    """LLM-based security judge — supports Anthropic, OpenAI-compatible, and Mistral providers."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        provider: str = "anthropic",
        base_url: str | None = None,
    ):
        """Initialize LLM judge.

        Args:
            api_key: API key for the LLM provider. If None, uses heuristic mode.
            model: Model name to use.
            provider: Provider type — "anthropic", "mistral", "openai", "openrouter", etc.
            base_url: Base URL for OpenAI-compatible endpoints.
        """
        # NOTE: API key must be explicitly provided. We no longer fall back to
        # ANTHROPIC_API_KEY environment variable. LLM configuration is now
        # database-driven via the dashboard LLM Config screen.
        self.api_key = api_key
        self.model = model
        self.provider = provider.lower() if provider else "anthropic"
        self.base_url = base_url
        self.heuristic_mode = not self.api_key
        self.call_records: list[LLMCallRecord] = []

    async def analyze_prompt_injection_risk(
        self,
        tool_definitions: list[dict[str, Any]],
        tool_descriptions: list[str],
    ) -> list[SecurityFinding]:
        """Analyze tool definitions for prompt injection risks.

        This is a critical security check for MCP servers.
        """
        findings = []

        if self.heuristic_mode:
            # Heuristic analysis
            findings.extend(
                await self._heuristic_prompt_injection_check(
                    tool_definitions, tool_descriptions
                )
            )
        else:
            # LLM-based analysis
            findings.extend(
                await self._llm_prompt_injection_check(
                    tool_definitions, tool_descriptions
                )
            )

        return findings

    async def analyze_owasp_agentic_top10(
        self,
        tool_definitions: list[dict[str, Any]],
        code_snippets: list[tuple[str, str]],  # (file, code)
    ) -> list[SecurityFinding]:
        """Analyze for OWASP Agentic Top 10 vulnerabilities."""
        findings = []

        # These checks are mostly heuristic-based
        # 1. Prompt Injection
        for file, code in code_snippets:
            if self._check_prompt_injection_code(code):
                finding = SecurityFinding(
                    id=f"agentic_001_{file}",
                    title="Potential Prompt Injection Vulnerability",
                    description="User input passed to LLM prompts without sanitization",
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    file=file,
                    remediation="Sanitize user inputs, use prompt templates, separate data from instructions",
                    tags=["agent", "prompt-injection", "owasp-agentic-001"],
                )
                findings.append(finding)

        # 2. Insecure Output Handling
        for file, code in code_snippets:
            if self._check_insecure_output_handling(code):
                finding = SecurityFinding(
                    id=f"agentic_002_{file}",
                    title="Insecure Output Handling",
                    description="LLM output used without validation or sanitization",
                    risk_level=RiskLevel.MEDIUM,
                    source=VulnerabilitySource.HEURISTIC,
                    file=file,
                    remediation="Validate and sanitize LLM outputs before use",
                    tags=["agent", "output-handling", "owasp-agentic-002"],
                )
                findings.append(finding)

        # 3. Resource Limits
        for tool_def in tool_definitions:
            if self._check_missing_resource_limits(tool_def):
                finding = SecurityFinding(
                    id=f"agentic_004_{tool_def.get('name', 'unknown')}",
                    title="Missing Resource Limits",
                    description="Tool callable without resource constraints or timeout limits",
                    risk_level=RiskLevel.MEDIUM,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Implement timeout limits, memory quotas, and rate limiting",
                    tags=["agent", "resource-limits", "owasp-agentic-004"],
                )
                findings.append(finding)

        # 4. Unauthorized Tool Access
        for tool_def in tool_definitions:
            if self._check_auth_required(tool_def):
                finding = SecurityFinding(
                    id=f"agentic_005_{tool_def.get('name', 'unknown')}",
                    title="Unauthorized Tool Access",
                    description="Privileged tool accessible without proper authorization checks",
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Add authentication and authorization checks to privileged tools",
                    tags=["agent", "auth", "owasp-agentic-005"],
                )
                findings.append(finding)

        return findings

    async def _heuristic_prompt_injection_check(
        self,
        tool_definitions: list[dict[str, Any]],
        tool_descriptions: list[str],
    ) -> list[SecurityFinding]:
        """Heuristic check for prompt injection risks."""
        findings = []
        risky_keywords = {
            "eval", "exec", "system", "shell", "popen", "execute",
            "compile", "parse", "interpret", "run", "command",
        }

        for idx, desc in enumerate(tool_descriptions):
            if any(keyword in desc.lower() for keyword in risky_keywords):
                finding = SecurityFinding(
                    id=f"prompt_inj_heuristic_{idx}",
                    title="High-Risk Tool Description",
                    description=f"Tool accepts dynamic code/commands: {desc}",
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Limit tool capabilities to safe operations",
                    tags=["prompt-injection", "agent"],
                )
                findings.append(finding)

        return findings

    def _make_llm_call(self, prompt: str, max_tokens: int = 1024) -> str:
        """Make an LLM API call using the configured provider. Returns response text."""
        import time as _time

        _t0 = _time.monotonic()
        endpoint = ""
        try:
            if self.provider == "anthropic":
                from anthropic import Anthropic
                client = Anthropic(api_key=self.api_key)
                endpoint = "messages.create"
                message = client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = message.content[0].text
            else:
                # OpenAI-compatible (Mistral, OpenRouter, OpenAI, vLLM, etc.)
                import httpx
                base_url = self.base_url
                if not base_url:
                    _PROVIDER_URLS = {
                        "mistral": "https://api.mistral.ai/v1",
                        "openai": "https://api.openai.com/v1",
                        "openrouter": "https://openrouter.ai/api/v1",
                    }
                    base_url = _PROVIDER_URLS.get(self.provider, "https://api.openai.com/v1")
                endpoint = f"{base_url}/chat/completions"
                resp = httpx.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                response_text = data["choices"][0]["message"]["content"]

            _elapsed = int((_time.monotonic() - _t0) * 1000)
            self.call_records.append(LLMCallRecord(
                model=self.model,
                endpoint=endpoint,
                success=True,
                latency_ms=_elapsed,
                request_summary=f"Security analysis via {self.provider}",
                response_text=response_text[:2000],
            ))
            return response_text

        except Exception as exc:
            _elapsed = int((_time.monotonic() - _t0) * 1000)
            self.call_records.append(LLMCallRecord(
                model=self.model,
                endpoint=endpoint or f"{self.provider}/chat",
                success=False,
                latency_ms=_elapsed,
                request_summary=f"Security analysis via {self.provider}",
                error=str(exc)[:500],
            ))
            raise

    async def _llm_prompt_injection_check(
        self,
        tool_definitions: list[dict[str, Any]],
        tool_descriptions: list[str],
    ) -> list[SecurityFinding]:
        """LLM-based prompt injection analysis (supports any configured provider)."""
        findings = []

        prompt = f"""Analyze these MCP server tool definitions for prompt injection risks.

Tool Definitions:
{json.dumps(tool_definitions, indent=2)}

Tool Descriptions:
{json.dumps(tool_descriptions, indent=2)}

For each high-risk tool, respond with JSON in this format:
{{
  "findings": [
    {{
      "tool_name": "...",
      "risk": "critical|high|medium",
      "reason": "...",
      "remediation": "..."
    }}
  ]
}}

Focus on:
1. Tools that accept dynamic code/commands
2. Tools that execute user input
3. Tools without proper input validation
4. Tools that could be chained to break out of sandbox
5. Tools with unclear/dangerous descriptions

Be strict and security-focused."""

        try:
            response_text = self._make_llm_call(prompt)

            # Extract JSON from response
            if "{" in response_text:
                json_str = response_text[response_text.find("{") : response_text.rfind("}") + 1]
                data = json.loads(json_str)

                for finding_data in data.get("findings", []):
                    risk_map = {
                        "critical": RiskLevel.CRITICAL,
                        "high": RiskLevel.HIGH,
                        "medium": RiskLevel.MEDIUM,
                    }

                    finding = SecurityFinding(
                        id=f"llm_prompt_inj_{finding_data.get('tool_name')}",
                        title=f"Prompt Injection Risk: {finding_data.get('tool_name')}",
                        description=finding_data.get("reason", ""),
                        risk_level=risk_map.get(finding_data.get("risk", "medium"), RiskLevel.MEDIUM),
                        source=VulnerabilitySource.LLM_JUDGE,
                        remediation=finding_data.get("remediation", ""),
                        tags=["prompt-injection", "agent", "llm-analyzed"],
                    )
                    findings.append(finding)
        except Exception:
            # On error, fall back to heuristic
            findings.extend(
                await self._heuristic_prompt_injection_check(
                    tool_definitions, tool_descriptions
                )
            )

        return findings

    @staticmethod
    def _check_prompt_injection_code(code: str) -> bool:
        """Check code for potential prompt injection patterns."""
        patterns = [
            "prompt =", "system_prompt =", "message =",
            "prompt", "format_prompt", "inject_prompt",
            "${", "f\"", "f'", "`",  # Template literals
        ]
        return any(pattern in code for pattern in patterns)

    @staticmethod
    def _check_insecure_output_handling(code: str) -> bool:
        """Check for unsafe use of LLM output."""
        unsafe_patterns = [
            "eval(", "exec(", "system(", "popen(",
            "json.loads(llm_output)", "json.loads(response)",
        ]
        return any(pattern in code for pattern in unsafe_patterns)

    @staticmethod
    def _check_missing_resource_limits(tool_def: dict[str, Any]) -> bool:
        """Check if tool has resource limit configurations."""
        input_schema = tool_def.get("inputSchema", {})
        properties = input_schema.get("properties", {})

        # Check for max_length, max_items, timeout constraints
        has_limits = False
        for prop_name, prop_schema in properties.items():
            if isinstance(prop_schema, dict):
                if "maxLength" in prop_schema or "maxItems" in prop_schema:
                    has_limits = True
                    break

        # If no explicit limits and tool accepts dynamic input, it's risky
        return not has_limits and len(properties) > 0

    @staticmethod
    def _check_auth_required(tool_def: dict[str, Any]) -> bool:
        """Check if tool description indicates admin/privileged access."""
        name = tool_def.get("name", "").lower()
        desc = tool_def.get("description", "").lower()

        sensitive_keywords = {
            "admin", "delete", "drop", "remove", "modify",
            "config", "auth", "permission", "user", "org",
            "system", "deploy", "production",
        }

        has_sensitive = any(
            keyword in name or keyword in desc
            for keyword in sensitive_keywords
        )

        return has_sensitive

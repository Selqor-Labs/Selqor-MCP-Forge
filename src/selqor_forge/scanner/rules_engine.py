# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Static rules engine for vulnerability detection."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .models import RiskLevel, SecurityFinding, VulnerabilitySource


@dataclass
class Rule:
    """A security rule."""
    id: str
    title: str
    description: str
    risk_level: RiskLevel
    pattern: str  # regex or semgrep pattern
    tags: list[str]
    remediation: str


class RuleEngine(ABC):
    """Abstract base for rule engines."""

    @abstractmethod
    async def scan_file(self, file_path: str, content: str) -> list[SecurityFinding]:
        """Scan file content and return findings."""
        pass

    @abstractmethod
    async def scan_directory(self, directory: str) -> list[SecurityFinding]:
        """Scan directory recursively."""
        pass


class HeuristicRuleEngine(RuleEngine):
    """Heuristic-based rule engine using regex patterns."""

    def __init__(self):
        self.rules = self._init_security_rules()
        self.generated_artifact_names = {
            "analysis-plan.json",
            "forge.report.json",
            "plan.json",
            "tool-plan.json",
            "uasf.json",
        }
        self.lockfile_names = {
            "cargo.lock",
            "npm-shrinkwrap.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "pnpm-lock.yml",
            "yarn.lock",
        }

    def _init_security_rules(self) -> dict[str, Rule]:
        """Initialize built-in security rules."""
        return {
            # Hardcoded secrets
            "SEC001": Rule(
                id="SEC001",
                title="Hardcoded API Key",
                description="Potential hardcoded API key found in source code",
                risk_level=RiskLevel.CRITICAL,
                pattern=r"(?:api[_-]?key|apikey|api_secret|secret_key)\s*[:=]\s*['\"][\w\-]{20,}['\"]",
                tags=["secrets", "hardcoded"],
                remediation="Move API keys to environment variables or secrets manager",
            ),
            "SEC002": Rule(
                id="SEC002",
                title="Hardcoded Password",
                description="Potential hardcoded password in code",
                risk_level=RiskLevel.CRITICAL,
                pattern=r"(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
                tags=["secrets", "hardcoded"],
                remediation="Use environment variables or secure secrets management",
            ),
            "SEC003": Rule(
                id="SEC003",
                title="Hardcoded Database Credentials",
                description="Database connection string with embedded credentials",
                risk_level=RiskLevel.CRITICAL,
                pattern=r"(?:mongodb|postgres|mysql|mssql).*://[^:]+:[^@]+@",
                tags=["secrets", "database"],
                remediation="Use connection strings from environment or secrets",
            ),
            # Injection vulnerabilities
            "SEC010": Rule(
                id="SEC010",
                title="SQL Injection Pattern",
                description="Potential SQL injection vulnerability (string concatenation in query)",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:query|sql|execute)\s*\(\s*['\"].*\+|query\s*\(\s*\$\{|query\s*\(\s*f['\"]",
                tags=["injection", "sql"],
                remediation="Use parameterized queries or prepared statements",
            ),
            "SEC011": Rule(
                id="SEC011",
                title="Command Injection Pattern",
                description="Potential command injection (unquoted/unsanitized command execution)",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:exec|spawn|system)\s*\(\s*['\"][^'\"]*\$\{|(?:exec|spawn|system)\s*\(\s*\`[^\`]*\$\{",
                tags=["injection", "command"],
                remediation="Use execFile with array arguments or sanitize inputs",
            ),
            "SEC012": Rule(
                id="SEC012",
                title="Path Traversal Pattern",
                description="Potential path traversal vulnerability (user input in file paths)",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:readFile|writeFile|unlink|rmdir)\s*\(\s*['\"].*\$\{|path\.(?:join|resolve)\s*\(\s*\$\{",
                tags=["traversal", "path"],
                remediation="Validate and sanitize file paths, use path.join with whitelisted dirs",
            ),
            "SEC013": Rule(
                id="SEC013",
                title="Dynamic Code Execution",
                description="Use of eval() or similar dynamic code execution",
                risk_level=RiskLevel.CRITICAL,
                pattern=r"\b(?:eval|new\s+Function|vm\.runInNewContext)\s*\(|(?<!re\.)(?<!template\.)exec\s*\(",
                tags=["eval", "code-execution"],
                remediation="Avoid eval(). Use safer alternatives like JSON.parse() for data",
            ),
            # OWASP API Top 10
            "SEC020": Rule(
                id="SEC020",
                title="Missing Authentication Check",
                description="Route handler without authentication middleware",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:router\.|app\.)\s*(?:get|post|put|delete|patch)\s*\(['\"]\/(?:api|admin|private|internal)[^'\"]*['\"](?:\s*,\s*(?:async\s*)?\([^)]*\)\s*(?:=>|{)))",
                tags=["auth", "owasp-api"],
                remediation="Add authentication middleware or auth checks to API endpoints",
            ),
            "SEC021": Rule(
                id="SEC021",
                title="Broken Access Control Pattern",
                description="Potential missing authorization check (admin without verification)",
                risk_level=RiskLevel.HIGH,
                pattern=r"\/admin|\/api\/admin|\/private|is_admin\s*\|\|\s*true",
                tags=["auth", "authorization", "owasp-api"],
                remediation="Implement proper role-based access control (RBAC)",
            ),
            # Cryptography
            "SEC030": Rule(
                id="SEC030",
                title="Weak Cryptography (MD5/SHA1)",
                description="Use of weak hashing algorithm (MD5 or SHA1)",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:crypto\.createHash|hashlib\.md5|hashlib\.sha1)\s*\(",
                tags=["crypto", "weak-hash"],
                remediation="Use SHA-256 or stronger (SHA-512, PBKDF2, bcrypt, Argon2)",
            ),
            "SEC031": Rule(
                id="SEC031",
                title="Insecure Random for Security",
                description="Use of weak random number generation in security-sensitive context",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:Math\.random|random\.random|rand\(\)).*(?:token|secret|key|password|salt|nonce|iv|csrf|session)",
                tags=["crypto", "random"],
                remediation="Use crypto.randomBytes(), secrets module, or /dev/urandom for security-sensitive values",
            ),
            # OWASP Agentic Top 10
            "SEC040": Rule(
                id="SEC040",
                title="Unrestricted Tool Calling",
                description="Tool execution without proper input validation or resource limits",
                risk_level=RiskLevel.HIGH,
                pattern=r"execute_tool\s*\(\s*[^,)]*\s*\)|call_tool.*(?!validate|sanitize|check)",
                tags=["agent", "owasp-agentic"],
                remediation="Validate tool inputs, limit execution scope, add resource quotas",
            ),
            "SEC041": Rule(
                id="SEC041",
                title="Prompt Injection Risk",
                description="Potential prompt injection (user input in LLM prompts)",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:prompt|message|system_prompt)\s*[:=]\s*['\"`].*\$\{|f['\"`].*\$\{|query\s*[:=]\s*\$\{",
                tags=["agent", "prompt-injection", "owasp-agentic"],
                remediation="Sanitize user inputs, use prompt templates, separate data from instructions",
            ),
            # Logging and monitoring
            "SEC050": Rule(
                id="SEC050",
                title="Sensitive Data in Logs",
                description="Logging sensitive information (passwords, tokens, keys)",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:console\.log|logger\.info|print|logging\.)\s*\([^)]*(?:password|token|secret|key|api_key)[^)]*\)",
                tags=["logging", "secrets"],
                remediation="Never log passwords/tokens. Use redaction filters for sensitive data",
            ),
            "SEC051": Rule(
                id="SEC051",
                title="Missing Error Handling",
                description="Missing try-catch or error handling block",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:\.exec|\.run|database\.query)\s*\([^)]*\)\s*(?!\.catch|try|finally|except)",
                tags=["error-handling", "reliability"],
                remediation="Add proper error handling and logging for all async operations",
            ),
            # Dependency vulnerabilities (basic)
            "SEC060": Rule(
                id="SEC060",
                title="Vulnerable Dependency Pattern",
                description="Known vulnerable package detected (check CVE database)",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:express|lodash|moment|request)<[^>]*(?:[0-3]\.|4\.[0-9](?:\.[0-9])?(?:\D|$))",
                tags=["dependencies", "vulnerable"],
                remediation="Update to patched version. Check security advisories",
            ),
            # SSRF Detection
            "SEC070": Rule(
                id="SEC070",
                title="Potential SSRF Vulnerability",
                description="User-controlled URL used in server-side HTTP request without validation",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:fetch|axios|httpx?\.(?:get|post|put|delete|request)|requests\.(?:get|post|put|delete)|urllib\.request)\s*\(\s*(?:\$\{|[a-z_]+\s*[\+,]|f['\"])",
                tags=["ssrf", "network", "owasp-api"],
                remediation="Validate and whitelist allowed URLs/domains. Block internal IP ranges (127.0.0.1, 10.x, 172.16-31.x, 192.168.x). Use URL parsing to prevent bypass.",
            ),
            # Rate Limiting
            "SEC071": Rule(
                id="SEC071",
                title="Missing Rate Limiting",
                description="API endpoint or tool handler without rate limiting middleware",
                risk_level=RiskLevel.MEDIUM,
                pattern=r"(?:app\.(?:get|post|put|delete|all)|router\.(?:get|post|put|delete))\s*\(['\"][^'\"]+['\"](?!.*(?:rateLimit|rateLimiter|throttle|slowDown))",
                tags=["rate-limiting", "dos", "availability"],
                remediation="Add rate limiting middleware (express-rate-limit, slowapi, governor). Implement per-user and per-IP limits.",
            ),
            # Deserialization
            "SEC072": Rule(
                id="SEC072",
                title="Unsafe Deserialization",
                description="Deserializing untrusted data without validation",
                risk_level=RiskLevel.HIGH,
                pattern=r"(?:pickle\.loads?|yaml\.(?:load|unsafe_load)|unserialize|ObjectInputStream|JSON\.parse\s*\(\s*(?:req\.|request\.|body|params|query))",
                tags=["deserialization", "injection"],
                remediation="Use safe deserialization (yaml.safe_load, JSON with schema validation). Never deserialize untrusted data with pickle.",
            ),
            # Missing Content Security
            "SEC073": Rule(
                id="SEC073",
                title="Missing Security Headers",
                description="HTTP response missing security headers (CSP, HSTS, X-Frame-Options)",
                risk_level=RiskLevel.LOW,
                pattern=r"(?:res\.send|response\.send|return Response|return JSONResponse)\s*\(",
                tags=["headers", "security-headers", "web"],
                remediation="Add security headers: Content-Security-Policy, Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options.",
            ),
            # Excessive permissions in tool schemas
            "SEC074": Rule(
                id="SEC074",
                title="Tool Without Input Size Limits",
                description="MCP tool schema missing maxLength/maxItems constraints on inputs",
                risk_level=RiskLevel.MEDIUM,
                pattern=r'"type"\s*:\s*"(?:string|array)"(?:(?!maxLength|maxItems|maximum)[^}]){20,}',
                tags=["mcp", "schema", "resource-limits"],
                remediation="Add maxLength to string properties and maxItems to array properties in tool schemas.",
            ),
        }

    async def scan_file(self, file_path: str, content: str) -> list[SecurityFinding]:
        """Scan file for security findings."""
        findings = []
        lines = content.split("\n")

        for rule_id, rule in self.rules.items():
            try:
                pattern = re.compile(rule.pattern, re.IGNORECASE | re.MULTILINE)
                for line_num, line in enumerate(lines, start=1):
                    if pattern.search(line):
                        # Extract context around the match
                        start_line = max(0, line_num - 2)
                        end_line = min(len(lines), line_num + 2)
                        context = "\n".join(lines[start_line:end_line])

                        finding = SecurityFinding(
                            id=f"{rule_id}_{file_path}_{line_num}",
                            title=rule.title,
                            description=rule.description,
                            risk_level=rule.risk_level,
                            source=VulnerabilitySource.CUSTOM_RULES,
                            file=file_path,
                            line=line_num,
                            code_snippet=context,
                            remediation=rule.remediation,
                            tags=rule.tags,
                        )
                        findings.append(finding)
            except re.error:
                # Skip invalid regex patterns
                continue

        return findings

    async def scan_directory(self, directory: str) -> list[SecurityFinding]:
        """Scan directory recursively for security findings."""
        findings = []
        dir_path = Path(directory)

        if not dir_path.is_dir():
            return findings

        # File extensions to scan
        extensions_to_scan = {
            ".ts", ".tsx", ".js", ".jsx",  # TypeScript/JavaScript
            ".py",  # Python
            ".rs",  # Rust
            ".go",  # Go
            ".json",  # JSON configs
            ".yaml", ".yml",  # YAML configs
            ".env", ".env.example",  # Environment files
        }

        # Directories to skip
        skip_dirs = {
            "node_modules", ".git", "dist", "build", "target",
            "__pycache__", ".venv", "venv", ".pytest_cache",
            ".tox", "egg-info"
        }

        for file_path in dir_path.rglob("*"):
            # Skip directories
            if any(skip in file_path.parts for skip in skip_dirs):
                continue

            # Skip non-source files
            if file_path.suffix not in extensions_to_scan:
                continue

            if not self._should_scan_file(file_path):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                relative_path = str(file_path.relative_to(dir_path))
                file_findings = await self.scan_file(relative_path, content)
                findings.extend(file_findings)
            except Exception:
                # Skip files that can't be read
                continue

        return findings

    def _should_scan_file(self, file_path: Path) -> bool:
        """Return True when a file should be included in heuristic code scans."""
        name = file_path.name.lower()
        if name in self.generated_artifact_names:
            return False
        if name in self.lockfile_names:
            return False
        return True


class SemgrepRuleEngine(RuleEngine):
    """Semgrep-based rule engine (requires semgrep CLI)."""

    def __init__(self, semgrep_config: str = "p/owasp-top-ten"):
        self.config = semgrep_config

    async def scan_file(self, file_path: str, content: str) -> list[SecurityFinding]:
        """Not directly supported by Semgrep for single files."""
        # Would require directory-based scanning
        return []

    async def scan_directory(self, directory: str) -> list[SecurityFinding]:
        """Scan directory using semgrep CLI."""
        try:
            import subprocess
            result = subprocess.run(
                [
                    "semgrep",
                    "--config", self.config,
                    "--json",
                    directory,
                ],
                capture_output=True,
                timeout=60,
            )

            if result.returncode == 0 or result.returncode == 1:  # 1 = findings found
                data = json.loads(result.stdout.decode())
                findings = []

                for result_item in data.get("results", []):
                    finding = SecurityFinding(
                        id=f"semgrep_{result_item['check_id']}_{result_item['path']}",
                        title=result_item["check_id"],
                        description=result_item.get("extra", {}).get("message", ""),
                        risk_level=self._severity_to_risk(
                            result_item.get("extra", {}).get("severity", "INFO")
                        ),
                        source=VulnerabilitySource.SEMGREP,
                        file=result_item.get("path"),
                        line=result_item.get("start", {}).get("line"),
                        code_snippet=result_item.get("extra", {}).get("lines", ""),
                        tags=[result_item["check_id"]],
                    )
                    findings.append(finding)

                return findings
        except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return []

    @staticmethod
    def _severity_to_risk(severity: str) -> RiskLevel:
        """Convert semgrep severity to risk level."""
        severity = severity.upper()
        if severity == "ERROR":
            return RiskLevel.CRITICAL
        elif severity == "WARNING":
            return RiskLevel.HIGH
        elif severity == "NOTE":
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

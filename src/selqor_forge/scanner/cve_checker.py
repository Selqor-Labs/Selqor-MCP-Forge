# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""CVE and vulnerability database checking using OSV and Trivy."""

from __future__ import annotations

import json
import subprocess

import httpx

from .models import RiskLevel, SecurityFinding, VulnerabilitySource


class CVEChecker:
    """Check dependencies for known vulnerabilities."""

    @staticmethod
    async def check_dependencies(
        dependencies: dict[str, str],
        language: str = "javascript",
    ) -> list[SecurityFinding]:
        """Check dependencies for known CVEs using OSV API.

        Args:
            dependencies: dict of {package_name: version}
            language: npm, pip, cargo, go, maven, etc.

        Returns:
            List of security findings for vulnerable packages.
        """
        findings = []

        # Map language to OSV ecosystem
        ecosystem_map = {
            "typescript": "npm",
            "javascript": "npm",
            "python": "PyPI",
            "rust": "crates.io",
            "go": "Go",
            "java": "Maven",
        }

        ecosystem = ecosystem_map.get(language, "npm")

        async with httpx.AsyncClient(timeout=10.0) as client:
            for package_name, version in dependencies.items():
                try:
                    # Query OSV API
                    response = await client.post(
                        "https://api.osv.dev/v1/query",
                        json={
                            "package": {"ecosystem": ecosystem, "name": package_name},
                            "version": version,
                        },
                    )

                    if response.status_code == 200:
                        data = response.json()
                        vulns = data.get("vulns", [])

                        for vuln in vulns:
                            severity = vuln.get("severity", "UNKNOWN")
                            risk_level = CVEChecker._severity_to_risk(severity)

                            finding = SecurityFinding(
                                id=vuln.get("id", f"unknown_{package_name}"),
                                title=f"Vulnerable dependency: {package_name}@{version}",
                                description=vuln.get("summary", vuln.get("details", "")),
                                risk_level=risk_level,
                                source=VulnerabilitySource.CVE_DATABASE,
                                cve_id=vuln.get("id"),
                                tags=["cve", "dependency", ecosystem],
                                metadata={
                                    "package": package_name,
                                    "version": version,
                                    "ecosystem": ecosystem,
                                    "affected": vuln.get("affected", []),
                                    "references": vuln.get("references", []),
                                },
                            )
                            findings.append(finding)
                except Exception:
                    # Continue on OSV API errors
                    continue

        return findings

    @staticmethod
    async def scan_with_trivy(directory: str) -> list[SecurityFinding]:
        """Scan using Trivy (requires trivy CLI installed).

        Trivy is more comprehensive but requires installation.
        """
        findings = []

        try:
            result = subprocess.run(
                [
                    "trivy",
                    "fs",
                    "--format", "json",
                    "--severity", "HIGH,CRITICAL,MEDIUM",
                    directory,
                ],
                capture_output=True,
                timeout=120,
                text=True,
            )

            if result.returncode in (0, 1):  # 0 or 1 are success states
                data = json.loads(result.stdout)

                for result_item in data.get("Results", []):
                    for vuln in result_item.get("Misconfigurations", []):
                        risk_level = CVEChecker._severity_to_risk(
                            vuln.get("Severity", "MEDIUM")
                        )

                        finding = SecurityFinding(
                            id=vuln.get("ID", "trivy_unknown"),
                            title=vuln.get("Title", "Security Issue"),
                            description=vuln.get("Description", ""),
                            risk_level=risk_level,
                            source=VulnerabilitySource.CVE_DATABASE,
                            file=result_item.get("Target"),
                            remediation=vuln.get("Resolution", ""),
                            tags=["trivy", "misconfiguration"],
                            metadata={
                                "type": vuln.get("Type"),
                                "cvss_score": vuln.get("CVSS", {}).get("V3Score"),
                            },
                        )
                        findings.append(finding)

                    # Check for vulnerabilities
                    for pkg_vuln in result_item.get("Vulnerabilities", []):
                        risk_level = CVEChecker._severity_to_risk(
                            pkg_vuln.get("Severity", "MEDIUM")
                        )

                        finding = SecurityFinding(
                            id=pkg_vuln.get("VulnerabilityID", "trivy_unknown"),
                            title=f"CVE: {pkg_vuln.get('VulnerabilityID', 'Unknown')}",
                            description=pkg_vuln.get("Title", ""),
                            risk_level=risk_level,
                            source=VulnerabilitySource.CVE_DATABASE,
                            cve_id=pkg_vuln.get("VulnerabilityID"),
                            file=result_item.get("Target"),
                            tags=["cve", "trivy"],
                            metadata={
                                "package": pkg_vuln.get("PkgName"),
                                "version": pkg_vuln.get("InstalledVersion"),
                                "fixed_version": pkg_vuln.get("FixedVersion"),
                                "cvss_score": pkg_vuln.get("CVSS", {}).get("V3Score"),
                            },
                        )
                        findings.append(finding)

        except FileNotFoundError:
            # Trivy not installed, silently skip
            pass
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            pass

        return findings

    @staticmethod
    def _severity_to_risk(severity: str) -> RiskLevel:
        """Convert CVE severity to risk level."""
        severity = severity.upper()
        if severity in ("CRITICAL", "C"):
            return RiskLevel.CRITICAL
        elif severity in ("HIGH", "H"):
            return RiskLevel.HIGH
        elif severity in ("MEDIUM", "M"):
            return RiskLevel.MEDIUM
        elif severity in ("LOW", "L"):
            return RiskLevel.LOW
        else:
            return RiskLevel.INFO

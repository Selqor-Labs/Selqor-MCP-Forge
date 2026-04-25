# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Report generation for security scan results (JSON, SPDX, Markdown, PDF)."""

from __future__ import annotations

import json

from .models import RiskLevel, ScanResult


class ReportGenerator:
    """Generate security reports in multiple formats."""

    @staticmethod
    def generate_json(scan_result: ScanResult) -> str:
        """Generate JSON report (machine-readable, CI/CD friendly)."""
        report = {
            "scan_id": scan_result.id,
            "timestamp": scan_result.scan_timestamp.isoformat(),
            "mcp_manifest": scan_result.mcp_manifest.model_dump(),
            "risk_summary": {
                "overall_score": scan_result.risk_summary.overall_score,
                "risk_level": scan_result.risk_summary.risk_level,
                "top_risks": scan_result.risk_summary.top_risks,
                "recommendation": scan_result.risk_summary.recommendation,
            },
            "statistics": scan_result.statistics.model_dump(),
            "findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "description": f.description,
                    "risk_level": f.risk_level,
                    "source": f.source,
                    "file": f.file,
                    "line": f.line,
                    "cve_id": f.cve_id,
                    "cvss_score": f.cvss_score,
                    "remediation": f.remediation,
                    "tags": f.tags,
                }
                for f in scan_result.findings
            ],
            "ai_bom": scan_result.ai_bom.model_dump() if scan_result.ai_bom else None,
            "suggested_fixes": [
                {
                    "finding_id": fix.finding_id,
                    "title": fix.title,
                    "description": fix.description,
                    "severity": fix.severity,
                    "instructions": fix.instructions,
                    "effort": fix.effort,
                    "precedence": fix.precedence,
                }
                for fix in scan_result.suggested_fixes
            ],
        }
        return json.dumps(report, indent=2)

    @staticmethod
    def generate_markdown(scan_result: ScanResult) -> str:
        """Generate human-readable Markdown report."""
        lines = [
            "# Security Scan Report",
            "",
            f"**Scan ID**: {scan_result.id}",
            f"**Timestamp**: {scan_result.scan_timestamp.isoformat()}",
            "",
            "## Overview",
            "",
            f"**Overall Risk Score**: {scan_result.risk_summary.overall_score}/100",
            f"**Risk Level**: {scan_result.risk_summary.risk_level.upper()}",
            f"**Recommendation**: {scan_result.risk_summary.recommendation}",
            "",
            "## MCP Server Details",
            "",
            f"- **Source**: {scan_result.mcp_manifest.source}",
            f"- **Transport**: {scan_result.mcp_manifest.transport}",
            f"- **Language**: {scan_result.mcp_manifest.language}",
            f"- **Tools**: {len(scan_result.mcp_manifest.tools)}",
            f"- **Dependencies**: {len(scan_result.mcp_manifest.dependencies)}",
            "",
            "## Scan Statistics",
            "",
            f"- **Total Findings**: {scan_result.statistics.total_findings}",
            f"  - Critical: {scan_result.statistics.by_risk_level.get(RiskLevel.CRITICAL, 0)}",
            f"  - High: {scan_result.statistics.by_risk_level.get(RiskLevel.HIGH, 0)}",
            f"  - Medium: {scan_result.statistics.by_risk_level.get(RiskLevel.MEDIUM, 0)}",
            f"  - Low: {scan_result.statistics.by_risk_level.get(RiskLevel.LOW, 0)}",
            f"  - Info: {scan_result.statistics.by_risk_level.get(RiskLevel.INFO, 0)}",
            f"- **Files Scanned**: {scan_result.statistics.files_scanned}",
            f"- **Dependencies Checked**: {scan_result.statistics.dependencies_checked}",
            f"- **Scan Duration**: {scan_result.statistics.scan_duration_seconds:.2f}s",
            "",
        ]

        # Findings by risk level
        if scan_result.findings:
            lines.extend(["## Findings", ""])

            for risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.INFO]:
                findings = [f for f in scan_result.findings if f.risk_level == risk_level]
                if not findings:
                    continue

                lines.append(f"### {risk_level.upper()} Severity ({len(findings)})")
                lines.append("")

                for finding in findings:
                    lines.append(f"#### {finding.title}")
                    lines.append(f"**ID**: {finding.id}")
                    lines.append(f"**Source**: {finding.source}")
                    if finding.file:
                        lines.append(f"**File**: {finding.file}:{finding.line}" if finding.line else f"**File**: {finding.file}")
                    if finding.cve_id:
                        lines.append(f"**CVE**: {finding.cve_id}")
                        if finding.cvss_score:
                            lines.append(f"**CVSS Score**: {finding.cvss_score}")
                    lines.append(f"**Description**: {finding.description}")
                    if finding.code_snippet:
                        lines.append("```")
                        lines.append(finding.code_snippet[:200])  # Truncate
                        lines.append("```")
                    if finding.remediation:
                        lines.append(f"**Remediation**: {finding.remediation}")
                    lines.append(f"**Tags**: {', '.join(finding.tags)}")
                    lines.append("")

        # Suggested fixes
        if scan_result.suggested_fixes:
            lines.extend(["## Suggested Fixes", ""])
            for idx, fix in enumerate(scan_result.suggested_fixes, 1):
                lines.append(f"### Fix #{idx}: {fix.title}")
                lines.append(f"**For Finding**: {fix.finding_id}")
                lines.append(f"**Effort**: {fix.effort}")
                lines.append(f"**Priority**: {fix.precedence}")
                lines.append(f"**Description**: {fix.description}")
                lines.append(f"**Instructions**: {fix.instructions}")
                if fix.patch:
                    lines.append("**Patch**:")
                    lines.append("```diff")
                    lines.append(fix.patch[:400])  # Truncate
                    lines.append("```")
                lines.append("")

        # AI-BOM
        if scan_result.ai_bom:
            lines.extend(["## AI-Generated Bill of Materials", ""])
            lines.append(f"**Components**: {len(scan_result.ai_bom.components)}")
            lines.append(f"**Vulnerabilities**: {len(scan_result.ai_bom.vulnerabilities)}")
            lines.append(f"**Licenses**: {len(scan_result.ai_bom.licenses)}")
            lines.append("")

            if scan_result.ai_bom.components:
                lines.append("### Components")
                lines.append("")
                for comp in scan_result.ai_bom.components:
                    lines.append(f"- **{comp.name}** ({comp.component_type}) v{comp.version}")
                    if comp.licenses:
                        lines.append(f"  - Licenses: {', '.join(comp.licenses)}")
                lines.append("")

            if scan_result.ai_bom.vulnerabilities:
                lines.append("### Vulnerabilities")
                lines.append("")
                for vuln in scan_result.ai_bom.vulnerabilities:
                    lines.append(f"- **{vuln.cve_id}** ({vuln.severity})")
                    lines.append(f"  - Component: {vuln.component}@{vuln.version}")
                    if vuln.cvss_score:
                        lines.append(f"  - CVSS: {vuln.cvss_score}")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_spdx_sbom(scan_result: ScanResult) -> str:
        """Generate SPDX JSON BoM (industry standard for supply chain)."""
        # SPDX 2.3 JSON format
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": f"SPDXRef-DOCUMENT-{scan_result.id}",
            "name": f"MCP Server Security Scan - {scan_result.mcp_manifest.source}",
            "documentNamespace": f"https://selqor.io/sbom/{scan_result.id}",
            "creationInfo": {
                "created": scan_result.scan_timestamp.isoformat(),
                "creators": ["Tool: selqor-mcp-forge-scanner"],
                "licenseListVersion": "3.21",
            },
            "packages": [],
            "vulnerabilities": [],
        }

        # Add MCP server as main package
        if scan_result.ai_bom and scan_result.ai_bom.components:
            for idx, comp in enumerate(scan_result.ai_bom.components):
                package_id = f"SPDXRef-Package-{idx}"
                package = {
                    "SPDXID": package_id,
                    "name": comp.name,
                    "version": comp.version,
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseDeclared": " OR ".join(comp.licenses) if comp.licenses else "NOASSERTION",
                    "licenseConcluded": "NOASSERTION",
                }

                # Add PURL if available
                if comp.purl:
                    package["externalRefs"] = [
                        {
                            "referenceCategory": "PACKAGE_MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": comp.purl,
                        }
                    ]

                sbom["packages"].append(package)

        # Add vulnerabilities
        if scan_result.ai_bom and scan_result.ai_bom.vulnerabilities:
            for vuln in scan_result.ai_bom.vulnerabilities:
                sbom["vulnerabilities"].append({
                    "SPDXID": f"SPDXRef-Vuln-{vuln.cve_id}",
                    "vulnerabilityFrom": vuln.cve_id,
                    "affectedComponent": f"SPDXRef-{vuln.component}",
                    "vulnerabilityStatus": vuln.status,
                    "versionRange": f"vers:{vuln.version}",
                    "vulnerability": {
                        "id": vuln.cve_id,
                        "score": vuln.cvss_score,
                        "severity": vuln.severity.upper(),
                    },
                })

        return json.dumps(sbom, indent=2)

    @staticmethod
    def generate_pdf(scan_result: ScanResult) -> bytes:
        """Generate a full-featured PDF security scan report.

        Uses reportlab to produce a styled document with risk overview,
        findings table, AI-BOM components, and suggested fixes.
        Falls back to a minimal text-based PDF when reportlab is absent.
        """
        try:
            from io import BytesIO

            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            # ── Styles ───────────────────────────────────────────────
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "RptTitle",
                parent=styles["Heading1"],
                fontSize=20,
                textColor=colors.HexColor("#1f2937"),
                spaceAfter=14,
            )
            h2_style = ParagraphStyle(
                "RptH2",
                parent=styles["Heading2"],
                fontSize=14,
                textColor=colors.HexColor("#374151"),
                spaceBefore=16,
                spaceAfter=8,
            )
            h3_style = ParagraphStyle(
                "RptH3",
                parent=styles["Heading3"],
                fontSize=11,
                textColor=colors.HexColor("#4b5563"),
                spaceBefore=10,
                spaceAfter=4,
            )
            body_style = ParagraphStyle(
                "RptBody",
                parent=styles["Normal"],
                fontSize=9,
                leading=12,
                textColor=colors.HexColor("#374151"),
            )
            small_style = ParagraphStyle(
                "RptSmall",
                parent=styles["Normal"],
                fontSize=8,
                leading=10,
                textColor=colors.HexColor("#6b7280"),
            )

            # Severity colour map
            SEV_COLORS = {
                "critical": colors.HexColor("#dc2626"),
                "high": colors.HexColor("#ea580c"),
                "medium": colors.HexColor("#d97706"),
                "low": colors.HexColor("#2563eb"),
                "info": colors.HexColor("#6b7280"),
            }

            def sev_color(level: str) -> colors.Color:
                return SEV_COLORS.get(str(level).lower(), colors.grey)

            # ── Build document ───────────────────────────────────────
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                topMargin=0.6 * inch,
                bottomMargin=0.6 * inch,
                leftMargin=0.7 * inch,
                rightMargin=0.7 * inch,
            )
            elements: list = []

            # Title
            elements.append(Paragraph("Security Scan Report", title_style))
            elements.append(
                Paragraph(
                    f"Scan ID: {scan_result.id} &mdash; "
                    f"{scan_result.scan_timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
                    small_style,
                )
            )
            elements.append(Spacer(1, 0.25 * inch))

            # ── Risk Summary Table ───────────────────────────────────
            elements.append(Paragraph("Risk Summary", h2_style))
            risk = scan_result.risk_summary
            summary_data = [
                ["Overall Score", f"{risk.overall_score}/100"],
                ["Risk Level", str(risk.risk_level).upper()],
                ["Recommendation", risk.recommendation[:120]],
                ["Total Findings", str(scan_result.statistics.total_findings)],
                [
                    "Critical / High / Medium / Low",
                    " / ".join(
                        str(scan_result.statistics.by_risk_level.get(rl, 0))
                        for rl in [
                            RiskLevel.CRITICAL,
                            RiskLevel.HIGH,
                            RiskLevel.MEDIUM,
                            RiskLevel.LOW,
                        ]
                    ),
                ],
                [
                    "Scan Duration",
                    f"{scan_result.statistics.scan_duration_seconds:.1f}s",
                ],
            ]
            summary_table = Table(summary_data, colWidths=[2.2 * inch, 4.5 * inch])
            summary_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9fafb")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1f2937")),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            elements.append(summary_table)
            elements.append(Spacer(1, 0.15 * inch))

            # ── MCP Server Details ───────────────────────────────────
            manifest = scan_result.mcp_manifest
            elements.append(Paragraph("MCP Server Details", h2_style))
            mcp_data = [
                ["Source", str(manifest.source)[:80]],
                ["Transport", str(manifest.transport)],
                ["Language", manifest.language],
                ["Tools", str(len(manifest.tools))],
                ["Dependencies", str(len(manifest.dependencies))],
            ]
            mcp_table = Table(mcp_data, colWidths=[2.2 * inch, 4.5 * inch])
            mcp_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9fafb")),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                    ]
                )
            )
            elements.append(mcp_table)
            elements.append(Spacer(1, 0.15 * inch))

            # ── Findings Table ───────────────────────────────────────
            if scan_result.findings:
                elements.append(Paragraph("Findings", h2_style))
                for risk_level in [
                    RiskLevel.CRITICAL,
                    RiskLevel.HIGH,
                    RiskLevel.MEDIUM,
                    RiskLevel.LOW,
                    RiskLevel.INFO,
                ]:
                    bucket = [
                        f for f in scan_result.findings if f.risk_level == risk_level
                    ]
                    if not bucket:
                        continue

                    elements.append(
                        Paragraph(
                            f"{str(risk_level).upper()} ({len(bucket)})", h3_style
                        )
                    )

                    header = ["Title", "Source", "Description", "Remediation"]
                    rows = [header]
                    for finding in bucket[:40]:  # cap per severity
                        rows.append(
                            [
                                Paragraph(finding.title[:60], body_style),
                                Paragraph(str(finding.source)[:20], small_style),
                                Paragraph(
                                    (finding.description or "")[:140], small_style
                                ),
                                Paragraph(
                                    (finding.remediation or "—")[:140], small_style
                                ),
                            ]
                        )

                    col_widths = [1.6 * inch, 0.9 * inch, 2.2 * inch, 2.0 * inch]
                    findings_table = Table(rows, colWidths=col_widths, repeatRows=1)
                    findings_table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    sev_color(risk_level),
                                ),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, 0), 8),
                                ("FONTSIZE", (0, 1), (-1, -1), 8),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    0.5,
                                    colors.HexColor("#e5e7eb"),
                                ),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                (
                                    "ROWBACKGROUNDS",
                                    (0, 1),
                                    (-1, -1),
                                    [colors.white, colors.HexColor("#f9fafb")],
                                ),
                            ]
                        )
                    )
                    elements.append(findings_table)
                    elements.append(Spacer(1, 0.1 * inch))

            # ── AI-BOM Section ───────────────────────────────────────
            if scan_result.ai_bom:
                bom = scan_result.ai_bom
                elements.append(
                    Paragraph("AI Bill of Materials", h2_style)
                )
                elements.append(
                    Paragraph(
                        f"{len(bom.components)} components &middot; "
                        f"{len(bom.vulnerabilities)} vulnerabilities &middot; "
                        f"{len(bom.licenses)} licenses",
                        body_style,
                    )
                )
                elements.append(Spacer(1, 0.08 * inch))

                if bom.components:
                    elements.append(Paragraph("Components", h3_style))
                    comp_rows = [["Name", "Version", "Type", "Licenses"]]
                    for comp in bom.components[:60]:
                        comp_rows.append(
                            [
                                comp.name[:40],
                                comp.version[:20],
                                comp.component_type,
                                ", ".join(comp.licenses)[:40] if comp.licenses else "—",
                            ]
                        )
                    comp_table = Table(
                        comp_rows,
                        colWidths=[2 * inch, 1.2 * inch, 1 * inch, 2.5 * inch],
                        repeatRows=1,
                    )
                    comp_table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#1f2937"),
                                ),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    0.5,
                                    colors.HexColor("#e5e7eb"),
                                ),
                                (
                                    "ROWBACKGROUNDS",
                                    (0, 1),
                                    (-1, -1),
                                    [colors.white, colors.HexColor("#f9fafb")],
                                ),
                            ]
                        )
                    )
                    elements.append(comp_table)
                    elements.append(Spacer(1, 0.1 * inch))

                if bom.vulnerabilities:
                    elements.append(Paragraph("Vulnerabilities", h3_style))
                    vuln_rows = [["CVE", "Component", "Severity", "CVSS"]]
                    for vuln in bom.vulnerabilities[:40]:
                        vuln_rows.append(
                            [
                                vuln.cve_id[:20],
                                f"{vuln.component}@{vuln.version}"[:30],
                                str(vuln.severity).upper(),
                                str(vuln.cvss_score or "—"),
                            ]
                        )
                    vuln_table = Table(
                        vuln_rows,
                        colWidths=[1.6 * inch, 2.2 * inch, 1.2 * inch, 1.0 * inch],
                        repeatRows=1,
                    )
                    vuln_table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#dc2626"),
                                ),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    0.5,
                                    colors.HexColor("#e5e7eb"),
                                ),
                            ]
                        )
                    )
                    elements.append(vuln_table)
                    elements.append(Spacer(1, 0.1 * inch))

                if bom.licenses:
                    elements.append(Paragraph("Licenses", h3_style))
                    lic_rows = [["License", "SPDX ID", "Components"]]
                    for lic in bom.licenses[:30]:
                        lic_rows.append(
                            [
                                lic.name[:40],
                                lic.spdx_id or "—",
                                ", ".join(lic.components[:5])[:50],
                            ]
                        )
                    lic_table = Table(
                        lic_rows,
                        colWidths=[2.2 * inch, 1.5 * inch, 3.0 * inch],
                        repeatRows=1,
                    )
                    lic_table.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    colors.HexColor("#374151"),
                                ),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                (
                                    "GRID",
                                    (0, 0),
                                    (-1, -1),
                                    0.5,
                                    colors.HexColor("#e5e7eb"),
                                ),
                            ]
                        )
                    )
                    elements.append(lic_table)

            # ── Suggested Fixes ──────────────────────────────────────
            if scan_result.suggested_fixes:
                elements.append(Paragraph("Suggested Fixes", h2_style))
                fix_rows = [["#", "Title", "Severity", "Effort", "Instructions"]]
                for fix in scan_result.suggested_fixes[:40]:
                    fix_rows.append(
                        [
                            str(fix.precedence),
                            Paragraph(fix.title[:50], body_style),
                            fix.severity,
                            fix.effort,
                            Paragraph(fix.instructions[:120], small_style),
                        ]
                    )
                fix_table = Table(
                    fix_rows,
                    colWidths=[0.4 * inch, 1.8 * inch, 0.8 * inch, 0.7 * inch, 3.0 * inch],
                    repeatRows=1,
                )
                fix_table.setStyle(
                    TableStyle(
                        [
                            (
                                "BACKGROUND",
                                (0, 0),
                                (-1, 0),
                                colors.HexColor("#059669"),
                            ),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            (
                                "GRID",
                                (0, 0),
                                (-1, -1),
                                0.5,
                                colors.HexColor("#e5e7eb"),
                            ),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            (
                                "ROWBACKGROUNDS",
                                (0, 1),
                                (-1, -1),
                                [colors.white, colors.HexColor("#f0fdf4")],
                            ),
                        ]
                    )
                )
                elements.append(fix_table)

            # ── Footer ───────────────────────────────────────────────
            elements.append(Spacer(1, 0.3 * inch))
            elements.append(
                Paragraph(
                    "Generated by Selqor MCP Forge Scanner &mdash; https://selqor.io",
                    small_style,
                )
            )

            doc.build(elements)
            return buffer.getvalue()

        except ImportError:
            # Fallback: build a minimal plain-text PDF when reportlab is absent.
            return _build_fallback_pdf(scan_result)


def _build_fallback_pdf(scan_result: ScanResult) -> bytes:
    """Produce a bare-bones but *valid* PDF without any third-party library.

    This outputs a PDF 1.4 document with a single page of plain text so
    the browser can at least display something useful.
    """
    lines = [
        f"Security Scan Report  -  {scan_result.id}",
        f"Timestamp: {scan_result.scan_timestamp.isoformat()}",
        "",
        f"Overall Score: {scan_result.risk_summary.overall_score}/100",
        f"Risk Level: {scan_result.risk_summary.risk_level.upper()}",
        f"Total Findings: {scan_result.statistics.total_findings}",
        f"Recommendation: {scan_result.risk_summary.recommendation}",
        "",
        f"Source: {scan_result.mcp_manifest.source}",
        f"Transport: {scan_result.mcp_manifest.transport}",
        f"Language: {scan_result.mcp_manifest.language}",
        "",
    ]
    for f in scan_result.findings[:20]:
        lines.append(f"[{str(f.risk_level).upper()}]  {f.title}")
    if scan_result.ai_bom:
        lines.append("")
        lines.append(f"AI-BOM: {len(scan_result.ai_bom.components)} components")
    lines.append("")
    lines.append("Install reportlab for full PDF reports: pip install reportlab")

    text = "\n".join(lines)

    # Build a minimal valid PDF 1.4 by hand.
    stream = "BT /F1 10 Tf 50 750 Td 12 TL\n"
    for line in text.split("\n"):
        safe = (
            line.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        stream += f"({safe}) '\n"
    stream += "ET"

    stream_bytes = stream.encode("latin-1", errors="replace")

    objs: list[bytes] = []
    offsets: list[int] = []

    def _add(content: bytes) -> int:
        idx = len(objs) + 1
        offsets.append(0)  # placeholder — set below
        objs.append(content)
        return idx

    catalog_id = _add(b"<< /Type /Catalog /Pages 2 0 R >>")
    _add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    _add(
        b"<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 612 792] "
        b"/Contents 5 0 R "
        b"/Resources << /Font << /F1 4 0 R >> >> >>"
    )
    _add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    stream_obj = (
        b"<< /Length " + str(len(stream_bytes)).encode() + b" >>\nstream\n"
        + stream_bytes + b"\nendstream"
    )
    _add(stream_obj)

    # Assemble
    pdf = bytearray(b"%PDF-1.4\n")
    for i, obj in enumerate(objs):
        offsets[i] = len(pdf)
        pdf += f"{i + 1} 0 obj\n".encode()
        pdf += obj
        pdf += b"\nendobj\n"

    xref_offset = len(pdf)
    pdf += b"xref\n"
    pdf += f"0 {len(objs) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()

    pdf += b"trailer\n"
    pdf += f"<< /Size {len(objs) + 1} /Root {catalog_id} 0 R >>\n".encode()
    pdf += b"startxref\n"
    pdf += f"{xref_offset}\n".encode()
    pdf += b"%%EOF\n"

    return bytes(pdf)

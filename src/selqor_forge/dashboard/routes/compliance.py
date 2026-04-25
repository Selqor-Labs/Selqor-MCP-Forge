# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Compliance badge and certificate routes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import SecurityScanRepository

router = APIRouter(prefix="/compliance", tags=["compliance"])


# ---------------------------------------------------------------------------
# SVG badge generation
# ---------------------------------------------------------------------------

def _generate_badge_svg(label: str, status: str, color: str) -> str:
    """Generate an SVG badge similar to shields.io style."""
    label_width = len(label) * 7 + 10
    status_width = len(status) * 7 + 10
    total_width = label_width + status_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{status_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + status_width / 2}" y="15" fill="#010101" fill-opacity=".3">{status}</text>
    <text x="{label_width + status_width / 2}" y="14">{status}</text>
  </g>
</svg>"""


def _scan_to_badge(scan: dict) -> tuple[str, str]:
    """Determine badge status and color from scan data."""
    score = scan.get("overall_score", 0)
    risk_level = scan.get("risk_level", "unknown")

    if risk_level in ("critical", "high") or score < 40:
        return "fail", "#e05d44"
    elif risk_level in ("medium",) or score < 70:
        return "warning", "#dfb317"
    else:
        return "pass", "#4c1"


def _load_scan(ctx: Ctx, scan_id: str) -> dict:
    """Load scan from the database."""
    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        model = repo.get_by_id(scan_id)
        if model is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        return {
            "id": model.id,
            "name": model.name,
            "source": model.source,
            "status": model.status,
            "overall_score": model.overall_score,
            "risk_level": model.risk_level,
            "findings_count": model.findings_count,
            "severity_counts": model.severity_counts,
            "completed_at": model.completed_at,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------

@router.get("/scans/{scan_id}/badge")
async def get_badge(ctx: Ctx, scan_id: str) -> Response:
    """Generate SVG compliance badge for a scan."""
    scan = _load_scan(ctx, scan_id)
    status_text, color = _scan_to_badge(scan)
    score = scan.get("overall_score", 0)

    svg = _generate_badge_svg("selqor-mcp-forge", f"{status_text} ({score})", color)

    return Response(content=svg, media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# Embed codes
# ---------------------------------------------------------------------------

@router.get("/scans/{scan_id}/embed")
async def get_embed(ctx: Ctx, scan_id: str) -> dict:
    """Return embed codes for the compliance badge."""
    scan = _load_scan(ctx, scan_id)
    status_text, color = _scan_to_badge(scan)
    score = scan.get("overall_score", 0)

    badge_url = f"/api/compliance/scans/{scan_id}/badge"

    return {
        "scan_id": scan_id,
        "status": status_text,
        "score": score,
        "badge_url": badge_url,
        "markdown": f"![Selqor MCP Forge Compliance]({badge_url})",
        "html": f'<img src="{badge_url}" alt="Selqor MCP Forge Compliance - {status_text} ({score})" />',
        "url": badge_url,
    }


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------

@router.post("/scans/{scan_id}/certificate")
async def generate_certificate(ctx: Ctx, scan_id: str) -> dict:
    """Generate a compliance certificate for a scan."""
    scan = _load_scan(ctx, scan_id)
    status_text, _ = _scan_to_badge(scan)
    now = datetime.utcnow().isoformat() + "Z"

    # Build a deterministic hash of the scan content
    scan_content = json.dumps(scan, sort_keys=True)
    content_hash = hashlib.sha256(scan_content.encode()).hexdigest()

    certificate = {
        "certificate_id": f"cert-{scan_id[:8]}-{content_hash[:8]}",
        "scan_id": scan_id,
        "scan_name": scan.get("name"),
        "source": scan.get("source"),
        "status": status_text,
        "overall_score": scan.get("overall_score", 0),
        "risk_level": scan.get("risk_level"),
        "findings_count": scan.get("findings_count", 0),
        "severity_counts": scan.get("severity_counts"),
        "scan_completed_at": scan.get("completed_at"),
        "certificate_issued_at": now,
        "content_hash": content_hash,
        "issuer": "Selqor MCPForge Security Scanner",
    }

    return certificate

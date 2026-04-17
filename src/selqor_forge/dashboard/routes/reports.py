# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Run report generation endpoints (CSV and PDF)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from selqor_forge.dashboard.context import is_safe_token, now_utc_string
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import RunRepository

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /integrations/{integration_id}/runs/{run_id}/report/{format}
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/runs/{run_id}/report/{format}")
def get_report(
    ctx: Ctx,
    integration_id: str,
    run_id: str,
    format: str,
) -> Response:
    """Generate and return a CSV or PDF report for a run."""
    if not is_safe_token(integration_id) or not is_safe_token(run_id):
        raise HTTPException(
            status_code=400, detail="invalid integration or run id"
        )

    run = _load_run(ctx, integration_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    fmt = format.strip().lower()

    if fmt == "csv":
        csv_body = _build_csv_report(run)
        filename = f"selqor-forge-{run.get('integration_id', '')}-{run.get('run_id', '')}-report.csv"
        return Response(
            content=csv_body,
            status_code=200,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    if fmt == "pdf":
        pdf_bytes = _build_pdf_report(run)
        filename = f"selqor-forge-{run.get('integration_id', '')}-{run.get('run_id', '')}-report.pdf"
        return Response(
            content=pdf_bytes,
            status_code=200,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    raise HTTPException(status_code=400, detail="unsupported report format")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_run(ctx: Ctx, integration_id: str, run_id: str) -> dict | None:
    """Load run from the database."""
    session = ctx.db_session_factory()
    try:
        repo = RunRepository(session)
        model = repo.get_by_id(integration_id, run_id)
        if model is None:
            return None
        return {
            "run_id": model.run_id,
            "status": model.status,
            "created_at": model.created_at,
            "integration_id": model.integration_id,
            "integration_name": model.integration_name,
            "spec": model.spec,
            "analysis_source": model.analysis_source,
            "model": model.model,
            "score": model.score,
            "tool_count": model.tool_count,
            "endpoint_count": model.endpoint_count,
            "compression_ratio": model.compression_ratio,
            "coverage": model.coverage,
            "warnings": model.warnings or [],
            "error": model.error,
            "artifacts": model.artifacts or [],
        }
    finally:
        session.close()


def _escape_csv(raw: str) -> str:
    if "," in raw or '"' in raw or "\n" in raw or "\r" in raw:
        return f'"{raw.replace(chr(34), chr(34) + chr(34))}"'
    return raw


def _opt_str(val, fmt: str | None = None) -> str:
    if val is None:
        return ""
    if fmt:
        return fmt.format(val)
    return str(val)


def _build_csv_report(run: dict) -> str:
    headers = [
        "integration_id",
        "integration_name",
        "run_id",
        "status",
        "created_at",
        "spec",
        "analysis_source",
        "model",
        "score",
        "tool_count",
        "endpoint_count",
        "compression_ratio",
        "coverage",
        "warnings",
        "error",
        "artifacts",
    ]

    row = [
        run.get("integration_id", ""),
        run.get("integration_name", ""),
        run.get("run_id", ""),
        run.get("status", ""),
        run.get("created_at", ""),
        run.get("spec", ""),
        run.get("analysis_source", ""),
        run.get("model") or "",
        _opt_str(run.get("score")),
        _opt_str(run.get("tool_count")),
        _opt_str(run.get("endpoint_count")),
        _opt_str(run.get("compression_ratio"), "{:.5f}") if run.get("compression_ratio") is not None else "",
        _opt_str(run.get("coverage"), "{:.5f}") if run.get("coverage") is not None else "",
        " | ".join(run.get("warnings", [])),
        run.get("error") or "",
        " | ".join(run.get("artifacts", [])),
    ]

    header_line = ",".join(_escape_csv(h) for h in headers)
    row_line = ",".join(_escape_csv(v) for v in row)
    return f"{header_line}\n{row_line}\n"


def _build_pdf_report(run: dict) -> bytes:
    lines = [
        "Selqor Forge Analysis Run Report",
        f"Generated At (UTC): {now_utc_string()}",
        "",
        f"Integration: {run.get('integration_name', '')} ({run.get('integration_id', '')})",
        f"Run ID: {run.get('run_id', '')}",
        f"Status: {run.get('status', '')}",
        f"Created At: {run.get('created_at', '')}",
        f"Spec: {run.get('spec', '')}",
        f"Analysis Source: {run.get('analysis_source', '')}",
        f"Model: {run.get('model') or 'n/a'}",
        f"Score: {_opt_str(run.get('score')) or 'n/a'}",
        f"Tool Count: {_opt_str(run.get('tool_count')) or 'n/a'}",
        f"Endpoint Count: {_opt_str(run.get('endpoint_count')) or 'n/a'}",
    ]

    cr = run.get("compression_ratio")
    lines.append(
        f"Compression Ratio: {cr:.5f}" if cr is not None else "Compression Ratio: n/a"
    )
    cov = run.get("coverage")
    lines.append(
        f"Coverage: {cov * 100:.2f}%"
        if cov is not None
        else "Coverage: n/a"
    )

    warnings = run.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"- {w}")

    error = run.get("error")
    if error:
        lines.append("")
        lines.append("Error:")
        lines.append(error)

    artifacts = run.get("artifacts", [])
    if artifacts:
        lines.append("")
        lines.append("Artifacts:")
        for a in artifacts:
            lines.append(f"- {a}")

    return _render_simple_pdf(lines)


def _wrap_line(line: str, max_chars: int = 92) -> list[str]:
    if not line:
        return [""]
    result: list[str] = []
    current = ""
    for ch in line:
        c = ch if ch.isascii() else "?"
        if len(current) >= max_chars:
            result.append(current)
            current = ""
        current += c
    if current:
        result.append(current)
    return result


def _escape_pdf_text(raw: str) -> str:
    out: list[str] = []
    for ch in raw:
        c = ch if ch.isascii() else "?"
        if c == "\\":
            out.append("\\\\")
        elif c == "(":
            out.append("\\(")
        elif c == ")":
            out.append("\\)")
        elif c in ("\n", "\r"):
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def _render_simple_pdf(lines: list[str]) -> bytes:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_line(line))

    if len(wrapped) > 48:
        wrapped = wrapped[:47]
        wrapped.append("... output truncated for one-page export ...")

    content = "BT\n/F1 11 Tf\n50 760 Td\n14 TL\n"
    for line in wrapped:
        content += f"({_escape_pdf_text(line)}) Tj\nT*\n"
    content += "ET\n"

    obj1 = "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        "3 0 obj\n<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> "
        "/Contents 5 0 R >>\nendobj\n"
    )
    obj4 = "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    obj5 = f"5 0 obj\n<< /Length {len(content)} >>\nstream\n{content}endstream\nendobj\n"

    objects = [obj1, obj2, obj3, obj4, obj5]
    pdf = bytearray(b"%PDF-1.4\n")

    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj.encode("ascii", errors="replace"))

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets:
        pdf.extend(f"{off:010d} 00000 n \n".encode())

    pdf.extend(
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf)

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Security scanner routes for dashboard."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from selqor_forge.scanner import (
    ReportGenerator,
    SecurityScanner,
    ScanResult,
)
from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import LLMLogRepository, ScanPolicyRepository, SecurityScanRepository

router = APIRouter(prefix="/scans", tags=["scans"])


def _model_to_dict(model) -> dict:
    """Convert an ORM model to a plain dict, filtering SQLAlchemy internals."""
    return {k: v for k, v in model.__dict__.items() if not k.startswith("_")}

# ---------------------------------------------------------------------------
# Concurrency control â€” limit simultaneous scans
# ---------------------------------------------------------------------------
_MAX_CONCURRENT_SCANS = 3
_scan_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SCANS)
_running_tasks: dict[str, asyncio.Task] = {}


class ScanRequestBody(BaseModel):
    """Request to trigger a new scan."""
    name: str
    description: str | None = None
    source: str  # local path, GitHub URL, or server URL
    full_mode: bool = False
    use_semgrep: bool = False
    use_llm: bool = True


# ---------------------------------------------------------------------------
# List scans
# ---------------------------------------------------------------------------

@router.get("")
async def list_scans(
    ctx: Ctx,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """List all scans, sorted by creation date (newest first)."""
    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        all_scans = repo.list_all()
        total = len(all_scans)
        paginated = all_scans[offset : offset + limit]
        return {
            "scans": [
                {
                    "id": s.id,
                    "name": s.name,
                    "source": s.source,
                    "status": s.status or "completed",
                    "created_at": s.created_at,
                    "completed_at": s.completed_at,
                    "findings_count": s.findings_count or 0,
                    "risk_level": s.risk_level,
                    "overall_score": s.overall_score,
                    "severity_counts": s.severity_counts,
                    "current_step": s.current_step,
                    "progress_percent": s.progress_percent or 0,
                }
                for s in paginated
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Trigger scan
# ---------------------------------------------------------------------------

@router.post("")
async def trigger_scan(ctx: Ctx, body: ScanRequestBody) -> dict:
    """Trigger a new security scan with progress tracking and concurrency control."""
    scan_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"

    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        repo.create(
            id=scan_id,
            name=body.name,
            description=body.description,
            source=body.source,
            status="pending",
            created_at=created_at,
            completed_at=None,
            findings_count=0,
            risk_level=None,
            overall_score=0,
            current_step="queued",
            progress_percent=0,
            severity_counts={},
            statistics=None,
            risk_summary=None,
            mcp_manifest=None,
            findings=[],
            suggested_fixes=[],
            ai_bom=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create scan: {e}")
    finally:
        session.close()

    async def run_scan_background() -> None:
        bg_session = ctx.db_session_factory()
        try:
            bg_repo = SecurityScanRepository(bg_session)

            async def progress_callback(step: str, step_number: int, total_steps: int, message: str = "") -> None:
                try:
                    bg_repo.update(
                        scan_id,
                        current_step=message or step,
                        progress_percent=round((step_number / total_steps) * 100),
                        status="running",
                    )
                except Exception:
                    pass

            async with _scan_semaphore:
                try:
                    bg_repo.update(
                        scan_id,
                        status="running",
                        current_step="Initializing scanner...",
                    )

                    # Resolve LLM config from user's settings (database-driven)
                    llm_api_key = None
                    llm_provider = "anthropic"
                    llm_model = None
                    llm_base_url = None
                    if body.use_llm:
                        llm_cfg = _resolve_scanner_llm_config(ctx)
                        if llm_cfg:
                            llm_api_key = llm_cfg["api_key"]
                            llm_provider = llm_cfg["provider"]
                            llm_model = llm_cfg["model"]
                            llm_base_url = llm_cfg.get("base_url")
                        # NOTE: No fallback to ANTHROPIC_API_KEY env var
                        # LLM configuration is now entirely database-driven

                    scanner = SecurityScanner(
                        api_key=llm_api_key,
                        use_semgrep=body.use_semgrep,
                        enable_trivy=body.full_mode,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                    )

                    if body.source.startswith("http://") or body.source.startswith("https://"):
                        if "github.com" in body.source:
                            result = await asyncio.wait_for(
                                scanner.scan_github_server(
                                    body.source,
                                    full_mode=body.full_mode,
                                    progress_callback=progress_callback,
                                ),
                                timeout=300,
                            )
                        else:
                            result = await asyncio.wait_for(
                                scanner.scan_running_server(
                                    body.source,
                                    progress_callback=progress_callback,
                                ),
                                timeout=120,
                            )
                    else:
                        result = await asyncio.wait_for(
                            scanner.scan_local_server(
                                body.source,
                                full_mode=body.full_mode,
                                progress_callback=progress_callback,
                            ),
                            timeout=600,
                        )

                    _save_scan_result_db(bg_repo, scan_id, body.name, result)

                    # Persist LLM call logs from the scanner
                    _persist_scanner_llm_logs(ctx, scan_id, body.name, scanner)

                    # Enforce scan policy after completion
                    try:
                        policy_result = _enforce_scan_policy(ctx.db_session_factory, scan_id, result)
                        if policy_result and not policy_result["passed"]:
                            bg_repo.update(
                                scan_id,
                                status="policy_violation",
                                current_step=f"Policy check failed: {len(policy_result['violations'])} violation(s)",
                            )
                    except Exception:
                        pass  # Policy check is non-blocking

                except asyncio.TimeoutError:
                    ctx.logger.error(f"Scan {scan_id} timed out")
                    try:
                        bg_repo.update(
                            scan_id,
                            status="failed",
                            current_step="Scan timed out",
                            completed_at=datetime.utcnow().isoformat() + "Z",
                        )
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    ctx.logger.info(f"Scan {scan_id} was cancelled")
                    try:
                        bg_repo.update(
                            scan_id,
                            status="cancelled",
                            current_step="Scan cancelled by user",
                            completed_at=datetime.utcnow().isoformat() + "Z",
                        )
                    except Exception:
                        pass
                except Exception as e:
                    ctx.logger.exception(f"Scan {scan_id} failed: {e}")
                    try:
                        bg_repo.update(
                            scan_id,
                            status="failed",
                            current_step=f"Error: {str(e)[:200]}",
                            completed_at=datetime.utcnow().isoformat() + "Z",
                        )
                    except Exception:
                        pass
                finally:
                    _running_tasks.pop(scan_id, None)
        finally:
            bg_session.close()

    task = asyncio.create_task(run_scan_background())
    _running_tasks[scan_id] = task

    return {
        "id": scan_id,
        "name": body.name,
        "source": body.source,
        "status": "pending",
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Cancel scan
# ---------------------------------------------------------------------------

@router.post("/{scan_id}/cancel")
async def cancel_scan(ctx: Ctx, scan_id: str) -> dict:
    """Cancel a running scan."""
    task = _running_tasks.get(scan_id)
    if task and not task.done():
        task.cancel()
        return {"message": "Scan cancellation requested", "id": scan_id}

    # Check if scan exists
    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        scan = repo.get_by_id(scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
    finally:
        session.close()

    return {"message": "Scan is not running", "id": scan_id}


# ---------------------------------------------------------------------------
# Get scan detail
# ---------------------------------------------------------------------------

@router.get("/{scan_id}")
async def get_scan(ctx: Ctx, scan_id: str) -> dict:
    """Get full scan result including all data."""
    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        scan = repo.get_by_id(scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        return {
            "id": scan.id,
            "name": scan.name,
            "source": scan.source,
            "status": scan.status,
            "created_at": scan.created_at,
            "completed_at": scan.completed_at,
            "findings_count": scan.findings_count or 0,
            "risk_level": scan.risk_level,
            "overall_score": scan.overall_score,
            "current_step": scan.current_step,
            "progress_percent": scan.progress_percent or 0,
            "mcp_manifest": scan.mcp_manifest,
            "findings": _findings_to_view(scan.findings or []),
            "severity_counts": scan.severity_counts,
            "statistics": scan.statistics,
            "risk_summary": scan.risk_summary,
            "suggested_fixes": scan.suggested_fixes or [],
            "ai_bom": scan.ai_bom,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get scan: {e}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Download report
# ---------------------------------------------------------------------------

@router.get("/{scan_id}/report/{format}")
async def download_report(ctx: Ctx, scan_id: str, format: str) -> dict:
    """Download scan report in specified format."""
    if format not in ("json", "markdown", "spdx", "pdf"):
        raise HTTPException(status_code=400, detail="Invalid format")

    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        scan_model = repo.get_by_id(scan_id)
        if not scan_model:
            raise HTTPException(status_code=404, detail="Scan not found")
        scan = _model_to_dict(scan_model)
        result = _reconstruct_scan_result(scan)

        if format == "json":
            report_content = ReportGenerator.generate_json(result)
            filename = "scan-report.json"
            content_type = "application/json"
        elif format == "markdown":
            report_content = ReportGenerator.generate_markdown(result)
            filename = "scan-report.md"
            content_type = "text/markdown"
        elif format == "spdx":
            report_content = ReportGenerator.generate_spdx_sbom(result)
            filename = "sbom.spdx.json"
            content_type = "application/json"
        elif format == "pdf":
            pdf_bytes = ReportGenerator.generate_pdf(result)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="scan-report.pdf"',
                },
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid format")

        return Response(
            content=report_content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Delete scan
# ---------------------------------------------------------------------------

@router.delete("/{scan_id}")
async def delete_scan(ctx: Ctx, scan_id: str) -> dict:
    """Delete a scan. Also cancels if running."""
    # Cancel if running
    task = _running_tasks.pop(scan_id, None)
    if task and not task.done():
        task.cancel()

    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        deleted = repo.delete(scan_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Scan not found")
        return {"message": "Scan deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete scan: {e}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Save / reconstruct helpers
# ---------------------------------------------------------------------------

def _findings_to_view(findings: list[dict]) -> list[dict]:
    """Project internal SecurityFinding dicts to the shape the frontend expects.

    The UI reads ``severity`` and an optional ``endpoint`` string. Internally
    findings carry ``risk_level`` and an arbitrary ``metadata`` blob. This
    helper bridges the two without forcing every consumer to know the mapping.
    """
    out: list[dict] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        merged = dict(f)
        merged["severity"] = f.get("severity") or f.get("risk_level") or "info"
        meta = f.get("metadata") or {}
        endpoint = meta.get("endpoint")
        if not endpoint:
            endpoints = meta.get("endpoints")
            if isinstance(endpoints, list) and endpoints:
                endpoint = endpoints[0]
        if endpoint and not merged.get("endpoint"):
            merged["endpoint"] = endpoint
        out.append(merged)
    return out


def _save_scan_result_db(
    repo: SecurityScanRepository,
    scan_id: str,
    name: str,
    result: ScanResult,
) -> None:
    """Save complete scan result to the database â€” preserves ALL data."""
    # Build severity counts from statistics
    severity_counts = {}
    if result.statistics and result.statistics.by_risk_level:
        for level, count in result.statistics.by_risk_level.items():
            key = level.value if hasattr(level, "value") else str(level)
            severity_counts[key] = count
    else:
        for f in result.findings:
            lvl = f.risk_level.value if hasattr(f.risk_level, "value") else str(f.risk_level)
            severity_counts[lvl] = severity_counts.get(lvl, 0) + 1

    stats_dict = None
    if result.statistics:
        stats_dict = {
            "total_findings": result.statistics.total_findings,
            "files_scanned": result.statistics.files_scanned,
            "lines_analyzed": result.statistics.lines_analyzed,
            "dependencies_checked": result.statistics.dependencies_checked,
            "scan_duration_seconds": round(result.statistics.scan_duration_seconds, 2),
        }

    risk_dict = None
    if result.risk_summary:
        risk_dict = {
            "overall_score": result.risk_summary.overall_score,
            "risk_level": result.risk_summary.risk_level.value if hasattr(result.risk_summary.risk_level, "value") else str(result.risk_summary.risk_level),
            "top_risks": result.risk_summary.top_risks,
            "recommendation": result.risk_summary.recommendation,
        }

    repo.update(
        scan_id,
        name=name,
        source=result.mcp_manifest.source,
        status="completed",
        created_at=result.scan_timestamp.isoformat() + "Z",
        completed_at=datetime.utcnow().isoformat() + "Z",
        findings_count=result.statistics.total_findings if result.statistics else len(result.findings),
        risk_level=result.risk_summary.risk_level.value if hasattr(result.risk_summary.risk_level, "value") else str(result.risk_summary.risk_level),
        overall_score=result.risk_summary.overall_score,
        current_step="Scan complete",
        progress_percent=100,
        severity_counts=severity_counts,
        statistics=stats_dict,
        risk_summary=risk_dict,
        mcp_manifest=result.mcp_manifest.model_dump(),
        findings=[f.model_dump() for f in result.findings],
        suggested_fixes=[f.model_dump() for f in result.suggested_fixes],
        ai_bom=result.ai_bom.model_dump() if result.ai_bom else None,
    )


def _reconstruct_scan_result(scan: dict) -> ScanResult:
    """Reconstruct ScanResult from stored data â€” uses saved stats/risk if available."""
    from selqor_forge.scanner.models import (
        MCPManifest,
        SecurityFinding,
        ScanStatistics,
        RiskSummary,
        RiskLevel,
    )

    mcp_manifest = MCPManifest(**scan["mcp_manifest"])

    findings = [
        SecurityFinding(**f) for f in scan.get("findings", [])
    ]

    # Use saved statistics if available
    saved_stats = scan.get("statistics")
    if saved_stats:
        sev_counts = scan.get("severity_counts", {})
        by_risk = {}
        for level in RiskLevel:
            by_risk[level] = sev_counts.get(level.value, 0)

        stats = ScanStatistics(
            total_findings=saved_stats.get("total_findings", len(findings)),
            by_risk_level=by_risk,
            files_scanned=saved_stats.get("files_scanned", 0),
            lines_analyzed=saved_stats.get("lines_analyzed", 0),
            dependencies_checked=saved_stats.get("dependencies_checked", 0),
            scan_duration_seconds=saved_stats.get("scan_duration_seconds", 0),
        )
    else:
        # Fallback: compute from findings
        by_risk = {}
        for level in RiskLevel:
            by_risk[level] = len([f for f in findings if f.risk_level == level])
        stats = ScanStatistics(
            total_findings=scan.get("findings_count", len(findings)),
            by_risk_level=by_risk,
        )

    # Use saved risk summary if available
    saved_risk = scan.get("risk_summary")
    if saved_risk:
        risk_summary = RiskSummary(
            overall_score=saved_risk.get("overall_score", scan.get("overall_score", 0)),
            risk_level=saved_risk.get("risk_level", scan.get("risk_level", "info")),
            top_risks=saved_risk.get("top_risks", []),
            recommendation=saved_risk.get("recommendation", ""),
        )
    else:
        risk_summary = RiskSummary(
            overall_score=scan.get("overall_score", 0),
            risk_level=scan.get("risk_level", "info"),
            top_risks=[],
            recommendation="",
        )

    # Reconstruct suggested fixes
    suggested_fixes = []
    for fix_data in scan.get("suggested_fixes", []):
        try:
            from selqor_forge.scanner.models import SuggestedFix
            suggested_fixes.append(SuggestedFix(**fix_data))
        except Exception:
            continue

    # Reconstruct AI-BOM
    ai_bom = None
    if scan.get("ai_bom"):
        try:
            from selqor_forge.scanner.models import AIBillOfMaterials
            ai_bom = AIBillOfMaterials(**scan["ai_bom"])
        except Exception:
            pass

    result = ScanResult(
        id=scan["id"],
        mcp_manifest=mcp_manifest,
        scan_timestamp=datetime.fromisoformat(scan["created_at"].rstrip("Z")),
        findings=findings,
        statistics=stats,
        risk_summary=risk_summary,
        ai_bom=ai_bom,
        suggested_fixes=suggested_fixes,
    )

    return result


# ---------------------------------------------------------------------------
# Scan policy enforcement
# ---------------------------------------------------------------------------


def _enforce_scan_policy(
    session_factory,
    scan_id: str,
    result: ScanResult,
) -> dict | None:
    """Evaluate the completed scan against the organisation scan policy.

    Returns a dict with ``{"passed": bool, "violations": [...]}`` or None
    if no policy is configured / DB is unavailable.
    """
    if session_factory is None:
        return None

    session = session_factory()
    try:
        policy_repo = ScanPolicyRepository(session)
        policy = policy_repo.get(policy_id="default")
        if policy is None:
            return None

        violations: list[str] = []

        # --- Score threshold ---
        if result.risk_summary and policy.min_score_threshold:
            if result.risk_summary.overall_score < policy.min_score_threshold:
                violations.append(
                    f"Score {result.risk_summary.overall_score} is below minimum threshold {policy.min_score_threshold}"
                )

        # --- Blocked severities ---
        blocked = policy.blocked_severities or []
        if blocked and result.statistics and result.statistics.by_risk_level:
            from selqor_forge.scanner.models import RiskLevel
            for sev_str in blocked:
                try:
                    level = RiskLevel(sev_str.lower())
                except ValueError:
                    continue
                count = result.statistics.by_risk_level.get(level, 0)
                if count > 0:
                    violations.append(
                        f"Found {count} {sev_str} findings (blocked by policy)"
                    )

        # --- Max critical findings ---
        if policy.max_critical_findings is not None and result.statistics:
            from selqor_forge.scanner.models import RiskLevel
            critical_count = result.statistics.by_risk_level.get(RiskLevel.CRITICAL, 0)
            if critical_count > policy.max_critical_findings:
                violations.append(
                    f"Found {critical_count} critical findings (max allowed: {policy.max_critical_findings})"
                )

        # --- Max high findings ---
        if policy.max_high_findings is not None and result.statistics:
            from selqor_forge.scanner.models import RiskLevel
            high_count = result.statistics.by_risk_level.get(RiskLevel.HIGH, 0)
            if high_count > policy.max_high_findings:
                violations.append(
                    f"Found {high_count} high findings (max allowed: {policy.max_high_findings})"
                )

        # --- Auto-fail on critical ---
        if policy.auto_fail_on_critical and result.statistics:
            from selqor_forge.scanner.models import RiskLevel
            critical_count = result.statistics.by_risk_level.get(RiskLevel.CRITICAL, 0)
            if critical_count > 0:
                violations.append(
                    f"Auto-fail: {critical_count} critical findings detected"
                )

        passed = len(violations) == 0
        return {"passed": passed, "violations": violations}

    except Exception:
        return None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# GET /scans/{scan_id}/policy-check â€" run policy check on a completed scan
# ---------------------------------------------------------------------------


@router.get("/{scan_id}/policy-check")
async def check_scan_policy(ctx: Ctx, scan_id: str) -> dict:
    """Check a completed scan against the organisation scan policy."""
    session = ctx.db_session_factory()
    try:
        repo = SecurityScanRepository(session)
        scan_model = repo.get_by_id(scan_id)
        if not scan_model:
            raise HTTPException(status_code=404, detail="Scan not found")
        if scan_model.status != "completed":
            return {"passed": None, "violations": [], "message": "Scan not yet completed"}

        scan = _model_to_dict(scan_model)
        result = _reconstruct_scan_result(scan)
        policy_result = _enforce_scan_policy(ctx.db_session_factory, scan_id, result)

        if policy_result is None:
            return {"passed": None, "violations": [], "message": "No scan policy configured"}
        return policy_result
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Scanner LLM log persistence
# ---------------------------------------------------------------------------


def _resolve_scanner_llm_config(ctx) -> dict | None:
    """Resolve the user's default LLM configuration for scanner use.

    Returns the default LLM config with keys: api_key, provider, model, base_url.
    Returns None if no LLM config is available.

    NOTE: This no longer falls back to ANTHROPIC_API_KEY environment variable.
    LLM configuration is now entirely database-driven via the dashboard.
    """
    import logging
    logger = logging.getLogger(__name__)

    if ctx.db_session_factory is None:
        return None

    from selqor_forge.dashboard.repositories import LLMConfigRepository

    session = ctx.db_session_factory()
    try:
        repo = LLMConfigRepository(session, ctx.secret_manager)
        # Use the new get_default() method which handles auto-selection
        chosen = repo.get_default()
        if chosen is None:
            logger.debug("No default LLM config found; scanner will use heuristic analysis")
            return None

        # Decrypt the API key while session is still active
        api_key = chosen.api_key
        if ctx.secret_manager and api_key:
            try:
                api_key = ctx.secret_manager.decrypt_text(api_key)
            except Exception as e:
                logger.warning("Failed to decrypt API key: %s", e)
                api_key = None

        if not api_key:
            logger.debug("Default LLM config found but no API key; scanner will use heuristic analysis")
            return None

        # Extract all needed data from ORM object BEFORE closing session
        result = {
            "api_key": api_key,
            "provider": (chosen.provider or "anthropic").strip().lower(),
            "model": (chosen.model or "").strip() or None,
            "base_url": (chosen.base_url or "").strip() or None,
        }
        logger.info(f"Using {result['provider']} {result['model']} for security analysis")
        return result

    except Exception as e:
        logger.debug("Failed to resolve scanner LLM config: %s", e, exc_info=True)
        return None
    finally:
        session.close()


def _persist_scanner_llm_logs(ctx, scan_id: str, scan_name: str, scanner: SecurityScanner) -> None:
    """Persist any LLM call records captured by the scanner's LLMJudge."""
    import logging

    logger = logging.getLogger(__name__)

    if not hasattr(scanner, "llm_judge") or not hasattr(scanner.llm_judge, "call_records"):
        return
    records = scanner.llm_judge.call_records
    if not records:
        return
    if ctx.db_session_factory is None:
        return

    session = ctx.db_session_factory()
    try:
        repo = LLMLogRepository(session)
        for idx, rec in enumerate(records):
            try:
                repo.create(
                    log_id=f"scan-{scan_id}-{idx}",
                    integration_id=None,
                    integration_name=f"[scan] {scan_name}",
                    run_id=scan_id,
                    run_mode="security_scan",
                    provider=scanner.llm_judge.provider or "unknown",
                    model=rec.model,
                    endpoint=rec.endpoint,
                    success=rec.success,
                    latency_ms=rec.latency_ms,
                    request_payload={"summary": rec.request_summary},
                    response_payload=None,
                    response_text=rec.response_text,
                    error=rec.error,
                    created_at=datetime.utcnow().isoformat() + "Z",
                )
            except Exception:
                session.rollback()
                logger.debug("Failed persisting scanner LLM log %d", idx, exc_info=True)
        logger.info("Persisted %d scanner LLM log(s) for scan %s", len(records), scan_id)
    except Exception:
        session.rollback()
        logger.debug("Failed persisting scanner LLM logs", exc_info=True)
    finally:
        session.close()

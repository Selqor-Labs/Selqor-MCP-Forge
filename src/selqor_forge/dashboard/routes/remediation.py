# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Auto-remediation routes for applying suggested fixes."""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import (
    SecurityScanRepository,
    RemediationStatusRepository,
)

router = APIRouter(prefix="/remediation", tags=["remediation"])


class ApplyFixesBody(BaseModel):
    """Request to apply specific fixes."""
    fix_ids: list[str]


# ---------------------------------------------------------------------------
# Apply selected fixes
# ---------------------------------------------------------------------------

@router.post("/scans/{scan_id}/apply")
async def apply_fixes(ctx: Ctx, scan_id: str, body: ApplyFixesBody) -> dict:
    """Apply selected suggested fixes for a scan."""
    session = ctx.db_session_factory()
    try:
        scan_repo = SecurityScanRepository(session)
        scan_model = scan_repo.get_by_id(scan_id)
        if scan_model is None:
            raise HTTPException(status_code=404, detail="Scan not found")

        suggested_fixes = scan_model.suggested_fixes or []

        # Load or create remediation state
        rem_repo = RemediationStatusRepository(session)
        rem_model = rem_repo.get_by_scan_id(scan_id)
        if rem_model:
            remediation = {
                "scan_id": scan_id,
                "applied": rem_model.applied or [],
                "failed": rem_model.failed or [],
                "pending": rem_model.pending or [],
                "created_at": rem_model.created_at,
                "updated_at": rem_model.updated_at,
            }
        else:
            remediation = {
                "scan_id": scan_id,
                "applied": [],
                "failed": [],
                "pending": [f.get("id", f.get("finding_id", "")) for f in suggested_fixes],
                "created_at": datetime.utcnow().isoformat() + "Z",
                "updated_at": None,
            }

        results = _apply_fix_ids(body.fix_ids, suggested_fixes, scan_model.source, remediation)

        remediation["updated_at"] = datetime.utcnow().isoformat() + "Z"
        rem_repo.upsert(
            scan_id,
            applied=remediation["applied"],
            failed=remediation["failed"],
            pending=remediation["pending"],
        )

        return {"scan_id": scan_id, "results": results}
    finally:
        session.close()


def _apply_fix_ids(
    fix_ids: list[str],
    suggested_fixes: list[dict],
    source_dir: str,
    remediation: dict,
) -> list[dict]:
    """Shared logic to apply patches for the given fix IDs.

    Mutates *remediation* in place (applied / failed / pending lists).
    Returns the per-fix result list.
    """
    results = []
    for fix_id in fix_ids:
        fix = next((f for f in suggested_fixes if f.get("id", f.get("finding_id", "")) == fix_id), None)
        if fix is None:
            results.append({"fix_id": fix_id, "status": "not_found", "message": "Fix not found in scan"})
            continue

        diff_patch = fix.get("diff_patch")
        if not diff_patch:
            results.append({"fix_id": fix_id, "status": "skipped", "message": "No diff_patch available"})
            continue

        tmp_path: str | None = None
        try:
            # Write patch to temp file and apply
            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tmp:
                tmp.write(diff_patch)
                tmp_path = tmp.name

            result = subprocess.run(
                ["git", "apply", "--check", tmp_path],
                cwd=source_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                results.append({
                    "fix_id": fix_id,
                    "status": "failed",
                    "message": f"Patch check failed: {result.stderr.strip()[:200]}",
                })
                if fix_id not in remediation["failed"]:
                    remediation["failed"].append(fix_id)
                continue

            # Actually apply the patch
            apply_result = subprocess.run(
                ["git", "apply", tmp_path],
                cwd=source_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if apply_result.returncode == 0:
                results.append({"fix_id": fix_id, "status": "applied", "message": "Fix applied successfully"})
                if fix_id not in remediation["applied"]:
                    remediation["applied"].append(fix_id)
                if fix_id in remediation.get("pending", []):
                    remediation["pending"].remove(fix_id)
            else:
                results.append({
                    "fix_id": fix_id,
                    "status": "failed",
                    "message": f"Apply failed: {apply_result.stderr.strip()[:200]}",
                })
                if fix_id not in remediation["failed"]:
                    remediation["failed"].append(fix_id)

        except subprocess.TimeoutExpired:
            results.append({"fix_id": fix_id, "status": "failed", "message": "Patch apply timed out"})
            if fix_id not in remediation["failed"]:
                remediation["failed"].append(fix_id)
        except Exception as e:
            results.append({"fix_id": fix_id, "status": "failed", "message": str(e)[:200]})
            if fix_id not in remediation["failed"]:
                remediation["failed"].append(fix_id)
        finally:
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# Apply all fixes
# ---------------------------------------------------------------------------

@router.post("/scans/{scan_id}/apply-all")
async def apply_all_fixes(ctx: Ctx, scan_id: str) -> dict:
    """Apply all suggested fixes for a scan."""
    session = ctx.db_session_factory()
    try:
        scan_repo = SecurityScanRepository(session)
        scan_model = scan_repo.get_by_id(scan_id)
        if scan_model is None:
            raise HTTPException(status_code=404, detail="Scan not found")

        suggested_fixes = scan_model.suggested_fixes or []
        if not suggested_fixes:
            return {"scan_id": scan_id, "results": [], "message": "No suggested fixes available"}

        all_fix_ids = [f.get("id", f.get("finding_id", "")) for f in suggested_fixes if f.get("diff_patch")]
        if not all_fix_ids:
            return {"scan_id": scan_id, "results": [], "message": "No fixes with patches available"}

        body = ApplyFixesBody(fix_ids=all_fix_ids)
        return await apply_fixes(ctx, scan_id, body)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Remediation status
# ---------------------------------------------------------------------------

@router.get("/scans/{scan_id}/status")
async def remediation_status(ctx: Ctx, scan_id: str) -> dict:
    """Get remediation status for a scan."""
    session = ctx.db_session_factory()
    try:
        scan_repo = SecurityScanRepository(session)
        scan_model = scan_repo.get_by_id(scan_id)
        if scan_model is None:
            raise HTTPException(status_code=404, detail="Scan not found")

        rem_repo = RemediationStatusRepository(session)
        rem_model = rem_repo.get_by_scan_id(scan_id)

        if rem_model is None:
            suggested_fixes = scan_model.suggested_fixes or []
            return {
                "scan_id": scan_id,
                "applied": [],
                "failed": [],
                "pending": [f.get("id", f.get("finding_id", "")) for f in suggested_fixes],
                "total_fixes": len(suggested_fixes),
                "has_patches": len([f for f in suggested_fixes if f.get("diff_patch")]),
            }

        applied = rem_model.applied or []
        failed = rem_model.failed or []
        pending = rem_model.pending or []
        return {
            "scan_id": scan_id,
            "applied": applied,
            "failed": failed,
            "pending": pending,
            "total_fixes": len(applied) + len(failed) + len(pending),
            "has_patches": len(applied) + len(pending),
            "created_at": rem_model.created_at,
            "updated_at": rem_model.updated_at,
        }
    finally:
        session.close()

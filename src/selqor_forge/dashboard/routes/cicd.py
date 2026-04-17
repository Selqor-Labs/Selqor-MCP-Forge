# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""CI/CD integration routes for generating pipeline configs.

The generator emits *correct* shell commands that match the real
``selqor-forge scan`` CLI signature (see ``selqor_forge/cli.py``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shlex
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from selqor_forge.dashboard.middleware import Ctx
from selqor_forge.dashboard.repositories import CiRunRepository, CiWebhookRepository

router = APIRouter(prefix="/cicd", tags=["cicd"])


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------


VALID_TARGETS = {"github_actions", "gitlab_ci", "pre_commit"}
VALID_OUTPUT_FORMATS = {"json", "markdown", "spdx", "pdf"}


class CICDConfigBody(BaseModel):
    """Inputs for the CI/CD config generator.

    The legacy ``formats`` field used to mean two contradictory things at once
    — both "which CI files to make" and "which ``--format`` arguments to pass
    to ``selqor-forge scan``". They are now split into ``targets`` (CI files)
    and ``output_formats`` (scan output formats).
    """

    # Scan inputs
    source_path: str = "."
    branches: list[str] = Field(default_factory=lambda: ["main"])
    output_dir: str = "scan-results"
    scan_threshold: int = Field(70, ge=0, le=100)

    # CI targets — which provider files to generate
    targets: list[str] = Field(default_factory=lambda: ["github_actions"])

    # Scan output formats — passed to ``selqor-forge scan --format``
    output_formats: list[str] = Field(default_factory=lambda: ["json"])

    # Behaviour flags
    fail_on_threshold: bool = True
    use_semgrep: bool = False
    use_llm: bool = True

    # Legacy aliases — accept the old field names from existing clients so
    # nothing crashes mid-rollout. ``formats`` historically held CI provider
    # names, so it maps onto ``targets``.
    formats: list[str] | None = None
    fail_on_critical: bool | None = None

    @field_validator("source_path")
    @classmethod
    def _strip_source(cls, v: str) -> str:
        v = (v or "").strip()
        return v or "."

    @field_validator("branches")
    @classmethod
    def _clean_branches(cls, v: list[str]) -> list[str]:
        cleaned = [b.strip() for b in (v or []) if b and b.strip()]
        return cleaned or ["main"]

    @field_validator("output_dir")
    @classmethod
    def _clean_output_dir(cls, v: str) -> str:
        v = (v or "").strip().rstrip("/")
        return v or "scan-results"

    @field_validator("targets")
    @classmethod
    def _clean_targets(cls, v: list[str]) -> list[str]:
        cleaned = [t for t in (v or []) if t in VALID_TARGETS]
        return cleaned or []

    @field_validator("output_formats")
    @classmethod
    def _clean_output_formats(cls, v: list[str]) -> list[str]:
        cleaned = [f for f in (v or []) if f in VALID_OUTPUT_FORMATS]
        return cleaned or ["json"]

    def resolved_targets(self) -> list[str]:
        """Effective list of CI targets, applying legacy ``formats`` if set."""
        if self.targets:
            return self.targets
        if self.formats:
            return [t for t in self.formats if t in VALID_TARGETS] or ["github_actions"]
        return ["github_actions"]

    def resolved_fail_on_threshold(self) -> bool:
        if self.fail_on_critical is not None:
            return self.fail_on_critical
        return self.fail_on_threshold


# ---------------------------------------------------------------------------
# Helpers — build the actual `selqor-forge scan` command
# ---------------------------------------------------------------------------


def _scan_command(body: CICDConfigBody) -> str:
    """Return the shell command that runs the scan, matching the real CLI."""
    parts = ["selqor-forge", "scan", shlex.quote(body.source_path)]
    parts.append(f"--out {shlex.quote(body.output_dir)}")
    parts.append(f"--format {','.join(body.output_formats)}")
    if body.use_semgrep:
        parts.append("--semgrep")
    if not body.use_llm:
        parts.append("--no-llm")
    return " ".join(parts)


def _report_path(body: CICDConfigBody) -> str:
    """Path of the JSON report the scanner writes (used by the score check)."""
    return f"{body.output_dir}/scan-report.json"


# ---------------------------------------------------------------------------
# Generators — one per CI target
# ---------------------------------------------------------------------------


def _generate_github_actions(body: CICDConfigBody) -> str:
    cmd = _scan_command(body)
    report = _report_path(body)
    branches = body.branches
    threshold = body.scan_threshold
    needs_llm_secret = body.use_llm

    branches_yaml = ", ".join(f'"{b}"' for b in branches)

    lines: list[str] = [
        "name: Selqor Forge Security Scan",
        "",
        "on:",
        "  push:",
        f"    branches: [{branches_yaml}]",
        "  pull_request:",
        f"    branches: [{branches_yaml}]",
        "  workflow_dispatch:",
        "",
        "jobs:",
        "  security-scan:",
        "    runs-on: ubuntu-latest",
        "    permissions:",
        "      contents: read",
        "      pull-requests: write",
        "      security-events: write",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "",
        "      - name: Set up Python",
        "        uses: actions/setup-python@v5",
        "        with:",
        '          python-version: "3.11"',
        "          cache: pip",
        "",
        "      - name: Install Selqor Forge",
        "        run: pip install --upgrade selqor-forge",
        "",
        "      - name: Run security scan",
    ]

    if needs_llm_secret:
        lines += [
            "        env:",
            "          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",
        ]

    lines += [
        f"        run: {cmd}",
        "",
        "      - name: Upload scan report",
        "        if: always()",
        "        uses: actions/upload-artifact@v4",
        "        with:",
        "          name: selqor-forge-scan",
        f"          path: {body.output_dir}/",
        "          retention-days: 30",
    ]

    if body.resolved_fail_on_threshold():
        lines += [
            "",
            "      - name: Enforce security score threshold",
            "        if: always()",
            "        run: |",
            f'          REPORT="{report}"',
            '          if [ ! -f "$REPORT" ]; then',
            '            echo "Scan report missing at $REPORT — failing build"',
            "            exit 1",
            "          fi",
            "          score=$(python3 -c \"import json,sys; print(json.load(open(sys.argv[1])).get('risk_summary',{}).get('overall_score',0))\" \"$REPORT\")",
            f'          echo "Security score: $score (threshold: {threshold})"',
            f"          if [ \"$(printf '%.0f' \"$score\")\" -lt \"{threshold}\" ]; then",
            f'            echo "::error::Security score $score is below threshold {threshold}"',
            "            exit 1",
            "          fi",
        ]

    if needs_llm_secret:
        lines += [
            "",
            "    # NOTE: this workflow needs an ANTHROPIC_API_KEY repository",
            "    # secret. Add it under Settings → Secrets and variables → Actions.",
        ]

    return "\n".join(lines) + "\n"


def _generate_gitlab_ci(body: CICDConfigBody) -> str:
    cmd = _scan_command(body)
    report = _report_path(body)
    branches = body.branches
    threshold = body.scan_threshold
    needs_llm_secret = body.use_llm

    branch_rules = "\n".join(
        f'    - if: $CI_COMMIT_BRANCH == "{b}"' for b in branches
    )

    lines: list[str] = [
        "stages:",
        "  - security",
        "",
        "selqor-forge-scan:",
        "  stage: security",
        "  image: python:3.11-slim",
        "  cache:",
        "    paths:",
        "      - .cache/pip",
        "  variables:",
        "    PIP_CACHE_DIR: .cache/pip",
        "  before_script:",
        "    - pip install --upgrade selqor-forge",
        "  script:",
        f"    - {cmd}",
    ]

    if body.resolved_fail_on_threshold():
        lines += [
            "    - |",
            f'      REPORT="{report}"',
            '      if [ ! -f "$REPORT" ]; then',
            '        echo "Scan report missing at $REPORT — failing build"',
            "        exit 1",
            "      fi",
            "      score=$(python3 -c \"import json,sys; print(json.load(open(sys.argv[1])).get('risk_summary',{}).get('overall_score',0))\" \"$REPORT\")",
            f'      echo "Security score: $score (threshold: {threshold})"',
            f"      if [ \"$(printf '%.0f' \"$score\")\" -lt \"{threshold}\" ]; then",
            f'        echo "Security score $score is below threshold {threshold}"',
            "        exit 1",
            "      fi",
        ]

    lines += [
        "  artifacts:",
        "    when: always",
        "    paths:",
        f"      - {body.output_dir}/",
        "    expire_in: 30 days",
        "  rules:",
        '    - if: $CI_PIPELINE_SOURCE == "merge_request_event"',
        branch_rules,
    ]

    if needs_llm_secret:
        lines.insert(0, "# NOTE: define an ANTHROPIC_API_KEY CI/CD variable in")
        lines.insert(1, "# Settings → CI/CD → Variables (masked + protected).")
        lines.insert(2, "")

    return "\n".join(lines) + "\n"


def _generate_pre_commit(body: CICDConfigBody) -> str:
    """Generate a `.pre-commit-config.yaml` for the pre-commit framework.

    The previous implementation wrote a raw shell script directly into
    ``.git/hooks/pre-commit``. That path is gitignored, has to be re-installed
    by every contributor, and the script tried to scan individual files which
    selqor-forge does not support. The pre-commit framework is the modern,
    version-controlled answer.
    """
    cmd_parts = ["selqor-forge", "scan", body.source_path]
    cmd_parts.append("--out")
    cmd_parts.append(body.output_dir)
    cmd_parts.append("--format")
    cmd_parts.append(",".join(body.output_formats))
    if body.use_semgrep:
        cmd_parts.append("--semgrep")
    if not body.use_llm:
        cmd_parts.append("--no-llm")

    args_yaml = "\n".join(f"          - {json.dumps(p)}" for p in cmd_parts[2:])

    lines = [
        "# .pre-commit-config.yaml — managed by Selqor Forge",
        "#",
        "# Install once per clone:",
        "#   pip install pre-commit",
        "#   pre-commit install",
        "#",
        "# The hook scans the whole project (selqor-forge does not operate on",
        "# individual files). pass_filenames is intentionally false.",
        "",
        "repos:",
        "  - repo: local",
        "    hooks:",
        "      - id: selqor-forge-scan",
        "        name: Selqor Forge Security Scan",
        "        language: system",
        "        entry: selqor-forge",
        "        args:",
        args_yaml,
        "        pass_filenames: false",
        "        always_run: true",
        "        stages: [pre-commit]",
    ]

    if body.use_llm:
        lines.insert(
            0,
            "# This hook needs ANTHROPIC_API_KEY in the environment when LLM analysis is on.",
        )

    return "\n".join(lines) + "\n"


# Filename each target writes to (used by the frontend for download).
TARGET_FILENAMES = {
    "github_actions": ".github/workflows/selqor-forge-scan.yml",
    "gitlab_ci": ".gitlab-ci.yml",
    "pre_commit": ".pre-commit-config.yaml",
}


# ---------------------------------------------------------------------------
# Helper — serialise a CiRun ORM model to a plain dict
# ---------------------------------------------------------------------------


def _run_to_dict(run) -> dict:
    """Convert a CiRun ORM object to the JSON-serialisable dict the API returns."""
    return {
        "id": run.id,
        "project_name": run.project_name,
        "score": run.score,
        "risk_level": run.risk_level,
        "findings_count": run.findings_count,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "ci_provider": run.ci_provider,
        "duration_seconds": run.duration_seconds,
        "report_url": run.report_url,
        "status": run.status,
        "threshold": run.threshold,
        "timestamp": run.timestamp,
        "severity_counts": run.severity_counts,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/generate")
async def generate_cicd(ctx: Ctx, body: CICDConfigBody) -> dict:
    """Generate CI/CD configuration files for the selected targets only."""
    targets = body.resolved_targets()
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="At least one CI target must be selected (github_actions, gitlab_ci, pre_commit).",
        )

    response: dict = {"config": body.model_dump(), "targets": targets, "files": {}}
    try:
        for target in targets:
            if target == "github_actions":
                content = _generate_github_actions(body)
            elif target == "gitlab_ci":
                content = _generate_gitlab_ci(body)
            elif target == "pre_commit":
                content = _generate_pre_commit(body)
            else:
                continue
            response["files"][target] = {
                "filename": TARGET_FILENAMES[target],
                "content": content,
            }
            # Backwards-compat top-level keys for older clients.
            response[target] = content
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate CI/CD configs: {exc}")

    return response


@router.get("/templates")
async def list_templates(ctx: Ctx) -> dict:
    """Return descriptive metadata for the available CI targets."""
    return {
        "templates": [
            {
                "id": "github_actions",
                "name": "GitHub Actions",
                "description": "Workflow that scans on push, pull_request, and manual dispatch. Uploads the scan report as an artifact and fails when the score drops below the threshold.",
                "filename": TARGET_FILENAMES["github_actions"],
            },
            {
                "id": "gitlab_ci",
                "name": "GitLab CI",
                "description": "Security stage that runs on merge requests and your default branch. Caches pip installs and saves the scan directory as an artifact.",
                "filename": TARGET_FILENAMES["gitlab_ci"],
            },
            {
                "id": "pre_commit",
                "name": "Pre-commit Framework",
                "description": "Version-controlled .pre-commit-config.yaml. Runs the scanner on every commit; install once with 'pre-commit install'.",
                "filename": TARGET_FILENAMES["pre_commit"],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Webhook management — projects register for a secret, CI posts results back
# ---------------------------------------------------------------------------


class WebhookProjectBody(BaseModel):
    """Register a project for webhook callbacks."""
    project_name: str = Field(..., min_length=1, max_length=120)


@router.post("/webhooks/register")
async def register_webhook(ctx: Ctx, body: WebhookProjectBody) -> dict:
    """Register a project and get a webhook secret + URL.

    The CI pipeline POSTs scan results to ``/api/cicd/webhooks/ingest``
    with a header ``X-Selqor-Signature: sha256=<hmac>`` so we can verify
    the payload came from the real pipeline.
    """
    name = body.project_name.strip()
    session = ctx.db_session_factory()
    try:
        repo = CiWebhookRepository(session)
        existing = repo.get_by_name(name)
        if existing:
            secret = ctx.secret_manager.decrypt_text(existing.secret)
        else:
            secret = secrets.token_hex(24)
            repo.create(
                project_name=name,
                secret=ctx.secret_manager.encrypt_text(secret),
                created_at=datetime.utcnow().isoformat() + "Z",
            )
    finally:
        session.close()

    return {
        "project_name": name,
        "webhook_secret": secret,
        "webhook_url": "/api/cicd/webhooks/ingest",
        "header_name": "X-Selqor-Signature",
        "header_format": "sha256=<HMAC-SHA256 of request body using webhook_secret>",
        "instructions": (
            "Add these as CI secrets. After each scan, POST the JSON report to "
            "the webhook URL with the signature header to record the result."
        ),
    }


@router.get("/webhooks")
async def list_webhooks(ctx: Ctx) -> dict:
    """List all registered webhook projects."""
    session = ctx.db_session_factory()
    try:
        repo = CiWebhookRepository(session)
        webhooks = repo.list_all()
        projects = []
        for wh in webhooks:
            decrypted = ctx.secret_manager.decrypt_text(wh.secret)
            if decrypted:
                masked = f"{decrypted[:6]}...{decrypted[-4:]}"
            else:
                masked = "••••••••"
            projects.append({
                "project_name": wh.project_name,
                "webhook_secret": masked,
            })
        total = len(projects)
    finally:
        session.close()

    return {"projects": projects, "total": total}


@router.delete("/webhooks/{project_name}")
async def delete_webhook(ctx: Ctx, project_name: str) -> dict:
    """Remove a webhook registration."""
    session = ctx.db_session_factory()
    try:
        repo = CiWebhookRepository(session)
        deleted = repo.delete(project_name)
    finally:
        session.close()

    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Webhook removed", "project_name": project_name}


@router.post("/webhooks/ingest")
async def ingest_webhook(ctx: Ctx, request: Request) -> dict:
    """Receive scan results from a CI pipeline via webhook.

    Expects JSON body with at minimum:
      - project_name: str
      - score: number
      - findings_count: number
    Optional: branch, commit_sha, ci_provider, risk_level, duration_seconds, report_url
    """
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    project_name = payload.get("project_name", "")
    if not project_name:
        raise HTTPException(status_code=400, detail="project_name is required")

    session = ctx.db_session_factory()
    try:
        webhook_repo = CiWebhookRepository(session)
        webhook = webhook_repo.get_by_name(project_name)

        # Verify HMAC signature if project is registered
        if webhook is not None:
            plain_secret = ctx.secret_manager.decrypt_text(webhook.secret)
            sig_header = request.headers.get("X-Selqor-Signature", "")
            if sig_header.startswith("sha256="):
                received_sig = sig_header[7:]
                expected_sig = hmac.new(
                    plain_secret.encode(),
                    raw_body,
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(received_sig, expected_sig):
                    raise HTTPException(status_code=403, detail="Invalid webhook signature")
            # If no signature header, allow (for easier testing) but warn
        else:
            # Auto-register unknown projects (makes onboarding easier)
            auto_secret = secrets.token_hex(24)
            webhook_repo.create(
                project_name=project_name,
                secret=ctx.secret_manager.encrypt_text(auto_secret),
                created_at=datetime.utcnow().isoformat() + "Z",
            )

        run_repo = CiRunRepository(session)
        run = run_repo.create(
            id=secrets.token_hex(8),
            project_name=project_name,
            score=payload.get("score", 0),
            risk_level=payload.get("risk_level", "unknown"),
            findings_count=payload.get("findings_count", 0),
            branch=payload.get("branch", "unknown"),
            commit_sha=payload.get("commit_sha", ""),
            ci_provider=payload.get("ci_provider", "unknown"),
            duration_seconds=payload.get("duration_seconds", 0),
            report_url=payload.get("report_url", ""),
            status="pass" if payload.get("score", 0) >= payload.get("threshold", 70) else "fail",
            threshold=payload.get("threshold", 70),
            timestamp=datetime.utcnow().isoformat() + "Z",
            severity_counts=payload.get("severity_counts", {}),
        )
        run_dict = _run_to_dict(run)

        # Trim old runs
        run_repo.prune(keep=200)
    finally:
        session.close()

    return {"message": "Run recorded", "run": run_dict}


# ---------------------------------------------------------------------------
# CI Run History — view past results from pipeline scans
# ---------------------------------------------------------------------------


@router.get("/runs")
async def list_ci_runs(
    ctx: Ctx,
    project_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List CI scan runs, optionally filtered by project."""
    session = ctx.db_session_factory()
    try:
        repo = CiRunRepository(session)
        runs = repo.list_all(project_name=project_name, limit=limit, offset=offset)
        total = repo.count(project_name=project_name)
        page = [_run_to_dict(r) for r in runs]
    finally:
        session.close()

    return {"runs": page, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/stats")
async def ci_run_stats(ctx: Ctx, project_name: str | None = None) -> dict:
    """Aggregate stats across CI runs."""
    session = ctx.db_session_factory()
    try:
        repo = CiRunRepository(session)
        # Fetch all runs for the project (or all) to compute stats
        runs = repo.list_all(project_name=project_name, limit=10000, offset=0)
        run_dicts = [_run_to_dict(r) for r in runs]
    finally:
        session.close()

    if not run_dicts:
        return {
            "total_runs": 0,
            "pass_count": 0,
            "fail_count": 0,
            "pass_rate": 0,
            "avg_score": 0,
            "avg_duration": 0,
            "projects": [],
            "latest_run": None,
        }

    pass_count = sum(1 for r in run_dicts if r.get("status") == "pass")
    scores = [r.get("score", 0) for r in run_dicts]
    durations = [r.get("duration_seconds", 0) for r in run_dicts if r.get("duration_seconds")]
    projects = list({r["project_name"] for r in run_dicts})

    return {
        "total_runs": len(run_dicts),
        "pass_count": pass_count,
        "fail_count": len(run_dicts) - pass_count,
        "pass_rate": round(pass_count / len(run_dicts) * 100, 1) if run_dicts else 0,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "avg_duration": round(sum(durations) / len(durations), 1) if durations else 0,
        "projects": projects,
        "latest_run": run_dicts[0] if run_dicts else None,
    }


# ---------------------------------------------------------------------------
# Status Badge — embeddable SVG for READMEs
# ---------------------------------------------------------------------------


def _badge_svg(label: str, value: str, color: str) -> str:
    """Generate a shields.io-style SVG badge."""
    label_width = len(label) * 6.5 + 12
    value_width = len(value) * 6.5 + 12
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {value}">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + value_width / 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width / 2}" y="14">{value}</text>
  </g>
</svg>"""


@router.get("/badge/{project_name}")
async def get_badge(ctx: Ctx, project_name: str) -> Response:
    """Return an SVG status badge for the latest CI run of a project.

    Embed in README: ``![Security](https://your-host/api/cicd/badge/my-project)``
    """
    session = ctx.db_session_factory()
    try:
        repo = CiRunRepository(session)
        runs = repo.list_all(project_name=project_name, limit=1, offset=0)
        if not runs:
            svg = _badge_svg("security", "no data", "#9f9f9f")
        else:
            latest = runs[0]
            score = latest.score or 0
            status = latest.status or "unknown"
            if status == "pass":
                color = "#4c1" if score >= 80 else "#97ca00"
            else:
                color = "#e05d44" if score < 50 else "#dfb317"
            svg = _badge_svg("security", f"{score}/100", color)
    finally:
        session.close()

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "ETag": f'"{secrets.token_hex(4)}"',
        },
    )

"""Drive the full Forge pipeline end-to-end against the public petstore spec.

Stages, in order:

  1. Create an integration pointing at the Swagger petstore OpenAPI v2 spec.
  2. Trigger the analysis/curation run. Poll until it completes.
  3. Scan the generated MCP server directory.
  4. Prepare the deployment (writes .env, registers deployment record).
  5. Print a one-line summary + the UI steps to finish verification.

The script is idempotent per run. If a previous integration named
``petstore-flow`` already exists, it is deleted first so you always get a
clean end-to-end pass.

Usage::

    # Terminal 1 â€” start the dashboard
    python -m selqor_forge.dashboard.app --state-dir dashboard

    # Terminal 2 â€” drive the flow
    python tools/run_petstore_flow.py

The dashboard must already be running (default http://127.0.0.1:9780). The
script fails fast with a clear message if it can't reach it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx


PETSTORE_SPEC = "https://petstore.swagger.io/v2/swagger.json"
INTEGRATION_NAME = "petstore-flow"
DEFAULT_API = "http://127.0.0.1:8787/api"
POLL_INTERVAL = 1.5  # seconds
RUN_TIMEOUT = 300  # seconds
SCAN_TIMEOUT = 180


class FlowError(RuntimeError):
    """Raised on any stage failure. Printed verbatim to stderr."""


def _stage(n: int, title: str) -> None:
    print(f"\n[{n}/5] {title}", flush=True)


def _ok(msg: str) -> None:
    print(f"    {msg}", flush=True)


def _bail(msg: str) -> "FlowError":
    return FlowError(msg)


def _post(client: httpx.Client, path: str, json_body: Any | None = None, **kw) -> httpx.Response:
    resp = client.post(path, json=json_body, **kw)
    if resp.status_code >= 400:
        raise _bail(f"POST {path} â†’ {resp.status_code}: {resp.text[:400]}")
    return resp


def _get(client: httpx.Client, path: str, **kw) -> httpx.Response:
    resp = client.get(path, **kw)
    if resp.status_code >= 400:
        raise _bail(f"GET {path} â†’ {resp.status_code}: {resp.text[:400]}")
    return resp


def _delete(client: httpx.Client, path: str) -> httpx.Response:
    return client.delete(path)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage_create_integration(client: httpx.Client) -> str:
    """Return the created integration id. Wipes any previous one with this name."""
    _stage(1, f"Create integration ({INTEGRATION_NAME})")

    # Drop any prior integration with this name so the script is re-runnable.
    existing = _get(client, "/integrations").json().get("integrations", [])
    victims = [i for i in existing if (i.get("name") or "").strip() == INTEGRATION_NAME]
    for v in victims:
        vid = v.get("id")
        if vid:
            _delete(client, f"/integrations/{vid}")
            _ok(f"removed existing integration {vid}")

    body = {"name": INTEGRATION_NAME, "spec": PETSTORE_SPEC}
    created = _post(client, "/integrations", body).json()
    integration_id = created.get("id")
    if not integration_id:
        raise _bail(f"POST /integrations returned no id: {created!r}")
    _ok(f"integration_id={integration_id}")
    _ok(f"spec={PETSTORE_SPEC}")
    return integration_id


def stage_run_curation(client: httpx.Client, integration_id: str) -> tuple[str, dict]:
    """Trigger the pipeline run and poll until done. Returns (run_id, final_run_row)."""
    _stage(2, "Run curation pipeline")

    started = _post(
        client,
        f"/integrations/{integration_id}/run",
        {"mode": "llm"},  # falls back to heuristic if no LLM config â€” fine
    ).json()
    job = started.get("job") or {}
    job_id = job.get("job_id") or job.get("id")
    run_id = job.get("run_id")
    if not job_id or not run_id:
        raise _bail(f"POST /run returned no job id: {started!r}")
    _ok(f"job_id={job_id} run_id={run_id}")

    deadline = time.time() + RUN_TIMEOUT
    last_stage = ""
    while time.time() < deadline:
        status_resp = _get(
            client,
            f"/integrations/{integration_id}/run-jobs/{job_id}/status",
        ).json()
        j = status_resp.get("job") or {}
        status = (j.get("status") or "").lower()
        current_stage = j.get("current_stage") or j.get("detail") or ""
        if current_stage and current_stage != last_stage:
            _ok(f"stage: {current_stage}")
            last_stage = current_stage
        if status in ("completed", "success", "succeeded", "done"):
            break
        if status in ("failed", "error", "cancelled", "canceled"):
            raise _bail(f"run failed: {j!r}")
        time.sleep(POLL_INTERVAL)
    else:
        raise _bail(f"run did not complete within {RUN_TIMEOUT}s")

    # Load the final run row for summary info (tool counts, etc.).
    runs_resp = _get(
        client, f"/integrations/{integration_id}/runs"
    ).json()
    runs = runs_resp.get("runs") or []
    final_run = next((r for r in runs if r.get("run_id") == run_id), None) or {}

    baseline = final_run.get("endpoint_count") or final_run.get("baseline_tool_count")
    curated = final_run.get("tool_count") or final_run.get("curated_tool_count")
    if baseline is not None and curated is not None:
        _ok(f"baseline endpoints={baseline}  curated tools={curated}")
    return run_id, final_run


def stage_scan(client: httpx.Client, integration_id: str, run_id: str) -> str | None:
    """Run a scan against the generated typescript-server directory."""
    _stage(3, "Scan generated MCP server")

    # The dashboard stores runs under state_dir/runs/{int}/{run}/typescript-server.
    # We just hand the scanner the absolute path â€” the backend resolves it.
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    server_path = (
        repo_root / "dashboard" / "runs" / integration_id / run_id / "typescript-server"
    )
    if not server_path.exists():
        _ok(f"no typescript-server at {server_path} â€” skipping scan")
        return None

    body = {
        "name": f"{INTEGRATION_NAME}-{int(time.time())}",
        "source": str(server_path),
        "use_llm": False,
        "use_semgrep": False,
        "full_mode": False,
    }
    started = _post(client, "/scans", body).json()
    scan_id = started.get("id")
    if not scan_id:
        raise _bail(f"POST /scans returned no id: {started!r}")
    _ok(f"scan_id={scan_id} source={server_path}")

    deadline = time.time() + SCAN_TIMEOUT
    last_step = ""
    while time.time() < deadline:
        row = _get(client, f"/scans/{scan_id}").json()
        status = (row.get("status") or "").lower()
        step = row.get("current_step") or ""
        if step and step != last_step:
            _ok(f"step: {step}")
            last_step = step
        if status in ("completed", "success", "succeeded"):
            findings = row.get("findings_count") or 0
            risk = row.get("risk_level") or "?"
            _ok(f"done. findings={findings}  risk={risk}")
            return scan_id
        if status in ("failed", "error", "cancelled", "canceled"):
            raise _bail(f"scan failed: {row!r}")
        time.sleep(POLL_INTERVAL)
    raise _bail(f"scan did not complete within {SCAN_TIMEOUT}s")


def stage_deploy(client: httpx.Client, integration_id: str, run_id: str) -> dict:
    """Prepare a deployment. Returns the deployment record."""
    _stage(4, "Prepare deployment")
    body = {"target": "typescript", "transport": "http", "http_port": 3333}
    dep = _post(
        client,
        f"/integrations/{integration_id}/runs/{run_id}/deploy",
        body,
    ).json()
    _ok(f"deployment_id={dep.get('deployment_id')}")
    _ok(f"server_path={dep.get('server_path')}")
    _ok(f"command={dep.get('command')}")
    return dep


def stage_playground_summary(api_base: str, integration_id: str, deployment: dict) -> None:
    _stage(5, "Playground hand-off")
    # Strip the /api suffix so we show the browsable dashboard URL.
    ui_base = api_base[: -len("/api")] if api_base.endswith("/api") else api_base
    print(
        "\n    The backend flow is complete. To finish the manual playground check:\n"
        f"      1. Open the dashboard UI ({ui_base}).\n"
        "      2. Go to Playground â†’ Available Integrations.\n"
        f"      3. Select '{INTEGRATION_NAME}' and click Auto-Connect.\n"
        "         (This triggers POST /api/playground/auto-connect/"
        f"{integration_id} which runs `{deployment.get('command')}`.)\n"
        "      4. Confirm the tool count matches the curated count from stage 2.\n"
        "      5. Execute one tool (list_pets or equivalent) and verify it returns real data.\n"
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--skip-scan", action="store_true",
                        help="Skip the scan stage (faster).")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30.0) as client:
        # Sanity check the dashboard is actually reachable.
        try:
            client.get("/integrations", timeout=3.0)
        except httpx.HTTPError as exc:
            print(
                f"ERROR: cannot reach dashboard API at {args.api}: {exc}\n"
                "Start it with: python -m selqor_forge.dashboard.app --state-dir dashboard",
                file=sys.stderr,
            )
            return 2

        try:
            integration_id = stage_create_integration(client)
            run_id, run_row = stage_run_curation(client, integration_id)
            if not args.skip_scan:
                stage_scan(client, integration_id, run_id)
            deployment = stage_deploy(client, integration_id, run_id)
            stage_playground_summary(args.api, integration_id, deployment)
        except FlowError as exc:
            print(f"\nFLOW FAILED: {exc}", file=sys.stderr)
            return 1

    print("\nAll backend stages passed. Integration is ready for playground verification.")
    print(f"  integration_id = {integration_id}")
    print(f"  run_id         = {run_id}")
    print(
        "  curated tools  = "
        f"{run_row.get('tool_count') or run_row.get('curated_tool_count') or '?'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

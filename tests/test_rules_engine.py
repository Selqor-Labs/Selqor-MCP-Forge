# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for heuristic scanner file filtering."""

from pathlib import Path

import pytest

from selqor_forge.scanner.rules_engine import HeuristicRuleEngine


@pytest.mark.asyncio
async def test_heuristic_engine_skips_generated_artifacts_and_lockfiles(tmp_state_dir):
    src_dir = tmp_state_dir / "src"
    src_dir.mkdir()

    (src_dir / "index.ts").write_text(
        """
app.get("/api/test", async (_req, res) => {
  res.json({ ok: true });
});
""".strip(),
        encoding="utf-8",
    )
    (src_dir / "plan.json").write_text(
        """
{"name":"manage_admin_api_keys","description":"admin role operations"}
""".strip(),
        encoding="utf-8",
    )
    (tmp_state_dir / "package-lock.json").write_text(
        """
{"packages":{"":{"name":"demo"},"node_modules/example":{"resolved":"https://registry.npmjs.org/example"}}}
""".strip(),
        encoding="utf-8",
    )

    findings = await HeuristicRuleEngine().scan_directory(str(tmp_state_dir))

    scanned_files = {finding.file.replace("\\", "/") for finding in findings}
    assert "src/index.ts" in scanned_files
    assert "src/plan.json" not in scanned_files
    assert "package-lock.json" not in scanned_files


def test_heuristic_engine_should_scan_source_but_not_generated_artifacts():
    engine = HeuristicRuleEngine()

    assert engine._should_scan_file(Path("src/index.ts"))
    assert not engine._should_scan_file(Path("src/plan.json"))
    assert not engine._should_scan_file(Path("package-lock.json"))

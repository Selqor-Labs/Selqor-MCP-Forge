# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Output artifact generation: JSON files and target server scaffolds."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from selqor_forge.config import AppConfig, OutputTarget, TransportMode
from selqor_forge.models import AnalysisPlan, QualityReport, ToolPlan, UasfSurface
from selqor_forge import templates

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class GenerationSummary:
    root: Path
    targets: list[OutputTarget] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate(
    out_dir: Path,
    surface: UasfSurface,
    analysis: AnalysisPlan,
    plan: ToolPlan,
    quality: QualityReport,
    config: AppConfig,
) -> GenerationSummary:
    """Write all output artifacts and scaffold target servers."""
    logger.info(
        "generating output artifacts: out_dir=%s endpoints=%d tools=%d targets=%d",
        out_dir,
        len(surface.endpoints),
        len(plan.tools),
        len(config.output_targets),
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    _write_json(out_dir / "uasf.json", surface)
    _write_json(out_dir / "analysis-plan.json", analysis)
    _write_json(out_dir / "tool-plan.json", plan)
    _write_json(out_dir / "forge.report.json", quality)

    default_transport = _transport_name(config.default_transport)

    for target in config.output_targets:
        logger.debug(
            "generating target scaffold: target=%s default_transport=%s",
            target,
            default_transport,
        )
        if target == OutputTarget.TYPESCRIPT:
            _generate_typescript_target(out_dir, plan, default_transport)
        elif target == OutputTarget.RUST:
            _generate_rust_target(out_dir, plan, default_transport)

    summary = GenerationSummary(
        root=out_dir,
        targets=list(config.output_targets),
    )
    logger.info(
        "generation finished: out_dir=%s target_count=%d",
        summary.root,
        len(summary.targets),
    )
    return summary


# ---------------------------------------------------------------------------
# TypeScript target
# ---------------------------------------------------------------------------


def _generate_typescript_target(
    out_dir: Path,
    plan: ToolPlan,
    default_transport: str,
) -> None:
    logger.debug(
        "writing TypeScript target files: out_dir=%s tools=%d default_transport=%s",
        out_dir,
        len(plan.tools),
        default_transport,
    )

    target_root = out_dir / "typescript-server"
    src_dir = target_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    (target_root / "package.json").write_text(templates.ts_package_json(), encoding="utf-8")
    (target_root / "tsconfig.json").write_text(templates.ts_tsconfig(), encoding="utf-8")
    (target_root / ".env.example").write_text(templates.ts_env_example(), encoding="utf-8")
    (target_root / "README.md").write_text(templates.ts_readme(), encoding="utf-8")

    _write_json(src_dir / "plan.json", plan)
    (src_dir / "index.ts").write_text(templates.ts_index(default_transport), encoding="utf-8")


# ---------------------------------------------------------------------------
# Rust target
# ---------------------------------------------------------------------------


def _generate_rust_target(
    out_dir: Path,
    plan: ToolPlan,
    default_transport: str,
) -> None:
    logger.debug(
        "writing Rust target files: out_dir=%s tools=%d default_transport=%s",
        out_dir,
        len(plan.tools),
        default_transport,
    )

    target_root = out_dir / "rust-server"
    src_dir = target_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    (target_root / "Cargo.toml").write_text(templates.rust_cargo_toml(), encoding="utf-8")
    (target_root / "README.md").write_text(templates.rust_readme(), encoding="utf-8")

    _write_json(src_dir / "plan.json", plan)
    (src_dir / "main.rs").write_text(templates.rust_main(default_transport), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, value: object) -> None:
    """Serialize a Pydantic model (or dataclass) to pretty-printed JSON."""
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        data = value.model_dump(by_alias=True, mode="json")
    else:
        data = value  # type: ignore[assignment]

    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _transport_name(mode: TransportMode) -> str:
    if mode == TransportMode.STDIO:
        return "stdio"
    if mode == TransportMode.HTTP:
        return "http"
    return "stdio"

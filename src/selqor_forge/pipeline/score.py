# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Quality scoring for curated tool plans."""

from __future__ import annotations

import logging

from selqor_forge.models import QualityReport, ToolPlan, UasfSurface

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score(surface: UasfSurface, plan: ToolPlan) -> QualityReport:
    """Score a tool plan against the UASF surface using weighted metrics.

    Weights:
        compression  0.35
        coverage     0.35
        clarity      0.15
        completeness 0.15
    """
    logger.debug(
        "scoring tool plan quality: endpoints=%d tools=%d",
        len(surface.endpoints),
        len(plan.tools),
    )

    endpoint_count = max(len(surface.endpoints), 1)
    curated_tools = sum(
        1 for t in plan.tools if t.name != "custom_request"
    )

    compression_ratio = curated_tools / endpoint_count

    # Adaptive compression target: for large APIs (100+ endpoints), a lower
    # ratio is expected and healthy.  1 tool per 25-35 endpoints is good
    # curation, not over-compression.
    target_lo, target_hi = _adaptive_compression_target(endpoint_count)
    compression_component = _compression_score(compression_ratio, target_lo, target_hi)

    covered_endpoints: set[str] = set()
    for tool in plan.tools:
        covered_endpoints.update(tool.covered_endpoints)
    coverage = len(covered_endpoints) / endpoint_count

    description_clarity = _description_clarity(plan)
    schema_completeness = _schema_completeness(plan)

    weighted = (
        (compression_component * 0.35)
        + (coverage * 0.35)
        + (description_clarity * 0.15)
        + (schema_completeness * 0.15)
    )

    warnings = list(plan.warnings)
    if coverage < 1.0:
        warnings.append("Not all endpoints are mapped to at least one tool")
    if not (target_lo <= compression_ratio <= target_hi):
        warnings.append(
            f"Tool compression ratio {compression_ratio:.3f} is outside the "
            f"target range ({target_lo:.2f} to {target_hi:.2f}) for {endpoint_count} endpoints"
        )

    raw_score = round(weighted * 100.0)
    clamped_score = max(0, min(raw_score, 100))

    report = QualityReport(
        score=clamped_score,
        compression_ratio=compression_ratio,
        coverage=coverage,
        description_clarity=description_clarity,
        schema_completeness=schema_completeness,
        warnings=warnings,
    )

    logger.debug(
        "quality scoring completed: score=%d coverage=%.3f "
        "compression_ratio=%.3f warnings=%d",
        report.score,
        report.coverage,
        report.compression_ratio,
        len(report.warnings),
    )

    return report


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------


def _adaptive_compression_target(endpoint_count: int) -> tuple[float, float]:
    """Return (low, high) compression ratio target based on spec size.

    Small APIs (≤30):  0.20–0.40  (5–12 tools)
    Medium (31–200):   0.08–0.35  (3–70 tools)
    Large (201–1000):  0.03–0.20  (6–200 tools)
    Very large (1000+): 0.02–0.10 (20–100 tools)
    """
    if endpoint_count <= 30:
        return 0.20, 0.40
    if endpoint_count <= 200:
        return 0.08, 0.35
    if endpoint_count <= 1000:
        return 0.03, 0.20
    return 0.02, 0.10


def _compression_score(ratio: float, target_lo: float = 0.2, target_hi: float = 0.4) -> float:
    """Score how well the tool/endpoint ratio fits the target range."""
    if target_lo <= ratio <= target_hi:
        return 1.0

    distance = (target_lo - ratio) if ratio < target_lo else (ratio - target_hi)
    max_distance = max(target_hi - target_lo, 0.1)
    return max(0.0, min(1.0 - (distance / max_distance), 1.0))


def _description_clarity(plan: ToolPlan) -> float:
    """Average clarity of tool descriptions (length + imperative verb check)."""
    if not plan.tools:
        return 0.0

    verbs = {
        "manage",
        "list",
        "search",
        "create",
        "update",
        "delete",
        "execute",
        "send",
        "run",
        "handle",
        "administer",
    }

    total = 0.0
    for tool in plan.tools:
        tokens = len(tool.description.split())
        length_score = 1.0 if tokens <= 35 else 0.6

        first_word = (
            tool.description.split()[0].lower()
            if tool.description.split()
            else ""
        )
        verb_score = 1.0 if first_word in verbs else 0.5

        total += (length_score + verb_score) / 2.0

    return total / len(plan.tools)


def _schema_completeness(plan: ToolPlan) -> float:
    """Fraction of tools with a complete input schema (has operation key or is custom_request)."""
    if not plan.tools:
        return 0.0

    complete = 0.0
    for tool in plan.tools:
        schema = tool.input_schema
        if not isinstance(schema, dict):
            continue

        schema_type = schema.get("type")
        if schema_type != "object":
            continue

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue

        if "operation" in properties or tool.name == "custom_request":
            complete += 1.0

    return complete / len(plan.tools)

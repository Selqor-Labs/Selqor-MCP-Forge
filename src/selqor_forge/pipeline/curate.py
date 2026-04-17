# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tool plan curation: groups UASF endpoints into MCP tool definitions."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import inflection

from selqor_forge.config import AppConfig
from selqor_forge.models import (
    AnalysisPlan,
    EndpointIntent,
    ToolDefinition,
    ToolPlan,
    UasfEndpoint,
    UasfSurface,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _adaptive_tool_bounds(
    endpoint_count: int,
    config_min: int,
    config_max: int,
) -> tuple[int, int]:
    """Compute adaptive min/max tool counts based on endpoint volume.

    For small APIs (≤50 endpoints) the config defaults (5–15) are fine.
    For larger surfaces, we scale up so the LLM's semantic groupings are
    preserved rather than crushed into catch-all buckets.

    Heuristic: roughly 1 tool per 25–35 endpoints, capped at 80.
    """
    if endpoint_count <= 50:
        return max(config_min, 1), max(config_max, config_min)

    # Scale: floor at config values, ceil at 80
    scaled_min = max(config_min, endpoint_count // 50)
    scaled_max = max(config_max, min(endpoint_count // 25, 80))
    scaled_max = max(scaled_max, scaled_min)

    return scaled_min, scaled_max


def curate(
    surface: UasfSurface,
    config: AppConfig,
    analysis: AnalysisPlan | None = None,
    *,
    agent_prompt: str | None = None,
) -> ToolPlan:
    """Curate a tool plan from a UASF surface and optional analysis plan."""
    endpoint_count = len(surface.endpoints)
    min_tools, max_tools = _adaptive_tool_bounds(
        endpoint_count, config.target_tool_count.min, config.target_tool_count.max,
    )

    logger.debug(
        "curating tool plan: endpoints=%d has_analysis=%s adaptive_bounds=[%d, %d]",
        endpoint_count,
        analysis is not None,
        min_tools,
        max_tools,
    )

    warnings: list[str] = []
    tools: list[ToolDefinition] = []

    if analysis is not None:
        warnings.extend(analysis.warnings)
        tools = _build_tools_from_analysis(surface, analysis, warnings)

    if not tools:
        logger.warning(
            "no tools produced from analysis; building domain-based fallback tools"
        )
        tools = _build_domain_tools(surface)

    # Expand if below minimum
    if len(tools) < min_tools:
        expanded = _build_intent_tools(surface, tools, min_tools)
        if len(expanded) > len(tools):
            logger.debug(
                "expanded tools to satisfy min bound: from=%d to=%d",
                len(tools),
                len(expanded),
            )
            tools = expanded

    # Merge if above maximum — use domain-aware merging
    if len(tools) > max_tools:
        logger.debug(
            "merging tools to satisfy max bound: current=%d max_tools=%d",
            len(tools),
            max_tools,
        )
        tools = _merge_tools_by_affinity(surface, tools, max_tools, warnings)

    _ensure_endpoint_coverage(surface, tools, warnings)

    # --- Single-pass overflow handling (Bugs #5 + #6) ---
    # Collects all overflow into one accumulator, creates one search_api at end.
    _MAX_TOOL_SIZE = 50
    _HARD_TOOL_CAP = 30
    search_api_overflow: list[str] = []

    # Phase 1: Per-tool size cap — split oversized tools by domain/intent.
    # Only endpoints that can't be split further go to search_api.
    capped: list[ToolDefinition] = []
    endpoint_by_id = {ep.id: ep for ep in surface.endpoints}
    for tool in tools:
        if len(tool.covered_endpoints) <= _MAX_TOOL_SIZE:
            capped.append(tool)
        else:
            # Recursive bisection: split by domain, then by intent
            split_result = _split_oversized_tool(
                tool, endpoint_by_id, _MAX_TOOL_SIZE, warnings,
            )
            capped.extend(split_result)
    tools = capped

    # Phase 2: Hard tool count cap — move smallest tools to search_api.
    if len(tools) > _HARD_TOOL_CAP:
        ranked = sorted(tools, key=lambda t: len(t.covered_endpoints), reverse=True)
        keep = ranked[: _HARD_TOOL_CAP]
        for t in ranked[_HARD_TOOL_CAP:]:
            search_api_overflow.extend(t.covered_endpoints)
        tools = keep
        warnings.append(
            f"Tool count exceeded cap {_HARD_TOOL_CAP}; moved "
            f"{len(ranked) - _HARD_TOOL_CAP} smallest tools to search_api"
        )

    # Phase 3: Create one search_api if there's any overflow
    if search_api_overflow:
        deduped = sorted(set(search_api_overflow))
        tools.append(_search_api_tool(surface, deduped))

    if config.include_custom_request_tool and not any(
        t.name == "custom_request" for t in tools
    ):
        tools.append(_custom_request_tool())

    # Sort by endpoint count descending, then name ascending
    tools.sort(key=lambda t: (-len(t.covered_endpoints), t.name))

    endpoint_catalog = {ep.id: ep for ep in surface.endpoints}

    # Final pass: compute a real confidence score for every curated tool so
    # scores reflect actual quality uniformly regardless of analysis source.
    # custom_request is the built-in escape hatch and intentionally keeps 0.0.
    agent_keywords = _extract_prompt_keywords(agent_prompt)
    for tool in tools:
        if tool.name == "custom_request":
            tool.confidence = 0.0
            continue
        tool.confidence = _compute_tool_confidence(
            tool, endpoint_catalog, agent_keywords
        )

    logger.debug(
        "tool curation completed: tools=%d warnings=%d",
        len(tools),
        len(warnings),
    )

    return ToolPlan(
        tools=tools,
        endpoint_catalog=endpoint_catalog,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Analysis-driven tool building
# ---------------------------------------------------------------------------


def _build_tools_from_analysis(
    surface: UasfSurface,
    analysis: AnalysisPlan,
    warnings: list[str],
) -> list[ToolDefinition]:
    endpoint_by_id: dict[str, UasfEndpoint] = {
        ep.id: ep for ep in surface.endpoints
    }

    tools: list[ToolDefinition] = []
    seen_names: set[str] = set()

    for candidate in analysis.tools:
        endpoint_refs: list[UasfEndpoint] = []
        endpoint_ids: list[str] = []

        for eid in candidate.covered_endpoints:
            ep = endpoint_by_id.get(eid)
            if ep is not None:
                endpoint_refs.append(ep)
                endpoint_ids.append(eid)

        if not endpoint_refs:
            warnings.append(
                f"Skipped analyzed tool '{candidate.name}' because it had no "
                f"valid endpoint coverage."
            )
            continue

        endpoint_ids = sorted(set(endpoint_ids))

        name = _sanitize_tool_name(candidate.name)
        if not name:
            name = "tool"

        if name in seen_names:
            idx = 2
            while f"{name}_{idx}" in seen_names:
                idx += 1
            name = f"{name}_{idx}"
        seen_names.add(name)

        tools.append(
            ToolDefinition(
                name=name,
                description=_normalize_description(candidate.description),
                covered_endpoints=endpoint_ids,
                input_schema=_build_schema_for_endpoints(endpoint_refs, endpoint_ids),
                confidence=max(0.0, min(candidate.confidence, 1.0)),
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Domain-based fallback grouping
# ---------------------------------------------------------------------------


def _build_domain_tools(surface: UasfSurface) -> list[ToolDefinition]:
    grouped: dict[str, list[UasfEndpoint]] = {}
    for ep in surface.endpoints:
        grouped.setdefault(ep.domain, []).append(ep)

    tools: list[ToolDefinition] = []
    for domain in sorted(grouped):
        tools.append(_build_domain_tool(domain, grouped[domain]))
    return tools


def _build_domain_tool(
    domain: str, endpoints: list[UasfEndpoint]
) -> ToolDefinition:
    endpoint_ids = [ep.id for ep in endpoints]

    dominant = _dominant_intent(endpoints)
    action_phrase = {
        EndpointIntent.READ: "list and fetch",
        EndpointIntent.SEARCH: "search and filter",
        EndpointIntent.CREATE: "create and submit",
        EndpointIntent.UPDATE: "update and sync",
        EndpointIntent.DELETE: "remove and archive",
        EndpointIntent.WORKFLOW: "run workflow",
        EndpointIntent.ADMIN: "administer",
        EndpointIntent.UNKNOWN: "manage",
    }.get(dominant, "manage")

    cleaned_domain = inflection.titleize(domain.strip())
    description = f"Manage {cleaned_domain} operations to {action_phrase} resources."

    return ToolDefinition(
        name=f"{_sanitize_tool_name(domain)}_operations",
        description=description,
        covered_endpoints=endpoint_ids,
        input_schema=_build_schema_for_endpoints(endpoints, endpoint_ids),
        confidence=_confidence_from_endpoint_count(len(endpoints)),
    )


# ---------------------------------------------------------------------------
# Intent-based expansion
# ---------------------------------------------------------------------------


def _build_intent_tools(
    surface: UasfSurface,
    existing: list[ToolDefinition],
    min_tools: int,
) -> list[ToolDefinition]:
    tools = list(existing)

    grouped: dict[tuple[str, str], list[UasfEndpoint]] = {}
    for ep in surface.endpoints:
        label = _intent_label(ep.intent)
        grouped.setdefault((ep.domain, label), []).append(ep)

    for (domain, intent) in sorted(grouped):
        if len(tools) >= min_tools:
            break

        endpoints = grouped[(domain, intent)]
        if len(endpoints) < 2:
            continue

        endpoint_ids = [ep.id for ep in endpoints]

        if any(_same_endpoint_set(t.covered_endpoints, endpoint_ids) for t in tools):
            continue

        domain_snake = _sanitize_tool_name(domain)
        intent_snake = inflection.underscore(intent).replace(" ", "_")
        tool_name = f"{domain_snake}_{intent_snake}_ops"

        cleaned_domain = inflection.titleize(domain)
        description = (
            f"Handle {cleaned_domain} {intent.lower()} operations with focused intent."
        )

        tools.append(
            ToolDefinition(
                name=tool_name,
                description=description,
                covered_endpoints=endpoint_ids,
                input_schema=_build_schema_for_endpoints(endpoints, endpoint_ids),
                # confidence is computed by curate() final pass
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Merge smallest tools when above max
# ---------------------------------------------------------------------------


def _merge_small_tools(
    tools: list[ToolDefinition],
    max_tools: int,
    warnings: list[str],
) -> list[ToolDefinition]:
    """Legacy merge: keeps N largest, dumps rest into misc_operations."""
    tools = sorted(tools, key=lambda t: len(t.covered_endpoints))

    keep_count = max(max_tools - 1, 0)
    split_at = max(len(tools) - keep_count, 0)

    to_merge = tools[:split_at]
    kept = tools[split_at:]

    merged_endpoints: list[str] = []
    for t in to_merge:
        merged_endpoints.extend(t.covered_endpoints)

    if merged_endpoints:
        warnings.append(
            f"Tool count exceeded max {max_tools}; merged {len(to_merge)} tools "
            f"into misc_operations"
        )

        kept.append(
            ToolDefinition(
                name="misc_operations",
                description="Handle mixed API operations that were merged for tool-count limits.",
                covered_endpoints=merged_endpoints,
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": merged_endpoints,
                            "description": "Operation id to execute",
                        },
                        "path_params": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "query": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "body": {
                            "type": [
                                "object",
                                "array",
                                "string",
                                "number",
                                "boolean",
                                "null",
                            ],
                        },
                        "headers": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["operation"],
                },
            )
        )

    return kept


def _merge_tools_by_affinity(
    surface: UasfSurface,
    tools: list[ToolDefinition],
    max_tools: int,
    warnings: list[str],
) -> list[ToolDefinition]:
    """Smart merge: groups small tools by domain/name affinity instead of
    dumping everything into a single misc_operations bucket.

    Strategy:
    1. Sort tools by endpoint count descending — large, well-formed tools survive.
    2. Keep the top ``max_tools * 0.7`` tools as-is (the "anchor" tools).
    3. Group remaining tools by their dominant domain (extracted from endpoint paths).
    4. Merge each domain group into a single ``{domain}_operations`` tool.
    5. If we're still over max, merge smallest domain-tools iteratively.
    """
    endpoint_by_id = {ep.id: ep for ep in surface.endpoints}

    # Sort by quality: larger endpoint coverage = more valuable
    ranked = sorted(tools, key=lambda t: len(t.covered_endpoints), reverse=True)

    anchor_count = max(int(max_tools * 0.7), 1)
    anchors = ranked[:anchor_count]
    overflow = ranked[anchor_count:]

    if not overflow:
        return anchors

    remaining_slots = max(max_tools - len(anchors), 1)

    # Group overflow tools by their dominant domain
    domain_groups: dict[str, list[ToolDefinition]] = {}
    for tool in overflow:
        domain = _tool_dominant_domain(tool, endpoint_by_id)
        domain_groups.setdefault(domain, []).append(tool)

    # Merge each domain group into a single tool
    merged_tools: list[ToolDefinition] = []
    for domain, group in sorted(domain_groups.items(), key=lambda kv: -sum(len(t.covered_endpoints) for t in kv[1])):
        all_endpoints: list[str] = []
        descriptions: list[str] = []
        for t in group:
            all_endpoints.extend(t.covered_endpoints)
            if t.description and t.description not in descriptions:
                descriptions.append(t.description)

        all_endpoints = sorted(set(all_endpoints))
        clean_domain = inflection.titleize(domain.strip())
        desc = f"Manage {clean_domain} operations: " + "; ".join(descriptions[:3])
        if len(desc) > 200:
            desc = desc[:197] + "..."

        resolved_eps = [endpoint_by_id[eid] for eid in all_endpoints if eid in endpoint_by_id]

        merged_tools.append(
            ToolDefinition(
                name=f"{_sanitize_tool_name(domain)}_operations",
                description=desc,
                covered_endpoints=all_endpoints,
                input_schema=_build_schema_for_endpoints(resolved_eps, all_endpoints),
            )
        )

    # If merged domain tools fit within remaining slots, keep them all
    if len(merged_tools) <= remaining_slots:
        result = anchors + merged_tools
    else:
        # Still too many — keep the largest domain groups, merge the rest
        merged_tools.sort(key=lambda t: len(t.covered_endpoints), reverse=True)
        keep_merged = merged_tools[:remaining_slots - 1]
        leftover = merged_tools[remaining_slots - 1:]

        leftover_endpoints: list[str] = []
        for t in leftover:
            leftover_endpoints.extend(t.covered_endpoints)

        if leftover_endpoints:
            leftover_eps = [endpoint_by_id[eid] for eid in leftover_endpoints if eid in endpoint_by_id]
            keep_merged.append(
                ToolDefinition(
                    name="additional_operations",
                    description="Handle additional API operations across multiple domains.",
                    covered_endpoints=sorted(set(leftover_endpoints)),
                    input_schema=_build_schema_for_endpoints(leftover_eps, sorted(set(leftover_endpoints))),
                )
            )

        result = anchors + keep_merged

    merged_into = len(result) - len(anchors)
    warnings.append(
        f"Reduced {len(tools)} tools to {len(result)} "
        f"(kept {len(anchors)} anchors, merged {len(overflow)} into {merged_into} domain groups)"
    )

    return result


def _tool_dominant_domain(
    tool: ToolDefinition, endpoint_by_id: dict[str, UasfEndpoint]
) -> str:
    """Extract the most common domain from a tool's covered endpoints."""
    domain_counts: Counter[str] = Counter()
    for eid in tool.covered_endpoints:
        ep = endpoint_by_id.get(eid)
        if ep is not None:
            domain_counts[ep.domain] += 1
    if domain_counts:
        return domain_counts.most_common(1)[0][0]
    # Fall back to the tool name prefix
    parts = (tool.name or "").split("_")
    return parts[0] if parts else "misc"


# ---------------------------------------------------------------------------
# Endpoint coverage gap-fill
# ---------------------------------------------------------------------------


def _ensure_endpoint_coverage(
    surface: UasfSurface,
    tools: list[ToolDefinition],
    warnings: list[str],
) -> None:
    covered: set[str] = set()
    for t in tools:
        covered.update(t.covered_endpoints)

    uncovered = [ep for ep in surface.endpoints if ep.id not in covered]

    if not uncovered:
        logger.debug("all endpoints covered by curated tools")
        return

    # Try to absorb uncovered endpoints into existing tools by domain match.
    # This avoids creating a massive catch-all that degrades agent intelligence.
    tool_by_domain: dict[str, ToolDefinition] = {}
    endpoint_by_id = {ep.id: ep for ep in surface.endpoints}
    for t in tools:
        domain_counts: Counter[str] = Counter()
        for eid in t.covered_endpoints:
            ep = endpoint_by_id.get(eid)
            if ep:
                domain_counts[ep.domain] += 1
        if domain_counts:
            dominant = domain_counts.most_common(1)[0][0]
            # Prefer the tool with the most endpoints for this domain
            if dominant not in tool_by_domain or len(t.covered_endpoints) > len(tool_by_domain[dominant].covered_endpoints):
                tool_by_domain[dominant] = t

    absorbed = 0
    still_uncovered: list[UasfEndpoint] = []
    for ep in uncovered:
        matching_tool = tool_by_domain.get(ep.domain)
        if matching_tool is not None:
            matching_tool.covered_endpoints.append(ep.id)
            # Update the operation enum in the schema
            op_schema = matching_tool.input_schema.get("properties", {}).get("operation", {})
            if isinstance(op_schema.get("enum"), list):
                op_schema["enum"].append(ep.id)
            absorbed += 1
        else:
            still_uncovered.append(ep)

    if absorbed > 0:
        logger.debug(
            "absorbed %d uncovered endpoints into existing domain tools",
            absorbed,
        )

    if not still_uncovered:
        if absorbed > 0:
            warnings.append(
                f"{absorbed} uncovered endpoints absorbed into matching domain tools"
            )
        return

    # Group remaining uncovered by domain into focused tools
    domain_groups: dict[str, list[UasfEndpoint]] = {}
    for ep in still_uncovered:
        domain_groups.setdefault(ep.domain, []).append(ep)

    new_tool_count = 0
    for domain, eps in sorted(domain_groups.items(), key=lambda kv: -len(kv[1])):
        ep_ids = [ep.id for ep in eps]
        clean_domain = inflection.titleize(domain.strip())
        tools.append(
            ToolDefinition(
                name=f"{_sanitize_tool_name(domain)}_extra_operations",
                description=f"Handle additional {clean_domain} operations not covered by primary tools.",
                covered_endpoints=ep_ids,
                input_schema=_build_schema_for_endpoints(eps, ep_ids),
            )
        )
        new_tool_count += 1

    total_gap = absorbed + len(still_uncovered)
    warnings.append(
        f"{total_gap} uncovered endpoints handled: {absorbed} absorbed into existing tools, "
        f"{len(still_uncovered)} grouped into {new_tool_count} domain tools"
    )


# ---------------------------------------------------------------------------
# Oversized tool splitting (recursive domain/intent bisection)
# ---------------------------------------------------------------------------


def _split_oversized_tool(
    tool: ToolDefinition,
    endpoint_by_id: dict[str, UasfEndpoint],
    max_size: int,
    warnings: list[str],
) -> list[ToolDefinition]:
    """Split an oversized tool into smaller ones by domain, then by intent.

    Recursive bisection: first groups endpoints by domain. If any domain
    group still exceeds ``max_size``, splits again by intent (read vs write).
    Preserves semantic coherence — endpoints stay in meaningful groups, not
    dumped into a search-only meta-tool.
    """
    eps = [endpoint_by_id[eid] for eid in tool.covered_endpoints if eid in endpoint_by_id]
    if not eps:
        return [tool]

    original_name = tool.name
    warnings.append(
        f"Split oversized tool '{original_name}' ({len(eps)} eps) by domain/intent"
    )

    intent_label_map = {
        EndpointIntent.READ: "read",
        EndpointIntent.SEARCH: "read",
        EndpointIntent.CREATE: "write",
        EndpointIntent.UPDATE: "write",
        EndpointIntent.DELETE: "write",
        EndpointIntent.WORKFLOW: "workflow",
        EndpointIntent.ADMIN: "admin",
        EndpointIntent.UNKNOWN: "misc",
    }

    # Step 1: group by domain
    by_domain: dict[str, list[UasfEndpoint]] = {}
    for ep in eps:
        by_domain.setdefault(ep.domain, []).append(ep)

    result: list[ToolDefinition] = []
    for domain, domain_eps in sorted(by_domain.items()):
        if len(domain_eps) <= max_size:
            result.append(_make_split_tool(domain, None, domain_eps, tool.confidence))
        else:
            # Step 2: split further by intent family
            by_intent: dict[str, list[UasfEndpoint]] = {}
            for ep in domain_eps:
                family = intent_label_map.get(ep.intent, "misc")
                by_intent.setdefault(family, []).append(ep)

            for intent_key, intent_eps in sorted(by_intent.items()):
                result.append(
                    _make_split_tool(domain, intent_key, intent_eps, tool.confidence)
                )

    return result


def _make_split_tool(
    domain: str,
    intent_key: str | None,
    endpoints: list[UasfEndpoint],
    confidence: float,
) -> ToolDefinition:
    """Build a ToolDefinition from a domain (+ optional intent) split."""
    ep_ids = [ep.id for ep in endpoints]
    clean_domain = inflection.titleize(domain.strip())
    domain_snake = _sanitize_tool_name(domain)

    if intent_key:
        name = f"{domain_snake}_{intent_key}"
        description = f"Manage {clean_domain} {intent_key} operations."
    else:
        name = f"manage_{domain_snake}"
        description = f"Manage {clean_domain} operations."

    return ToolDefinition(
        name=name,
        description=description,
        covered_endpoints=ep_ids,
        input_schema=_build_schema_for_endpoints(endpoints, ep_ids),
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Search API meta-tool (overflow handler)
# ---------------------------------------------------------------------------


def _search_api_tool(
    surface: UasfSurface,
    searchable_endpoint_ids: list[str],
) -> ToolDefinition:
    """Build a search_api meta-tool that lets the agent discover operations.

    The tool exposes a searchable index of endpoint summaries, paths, and
    domains so the agent can find the right operation by intent rather than
    browsing a long tool list.
    """
    ep_by_id = {ep.id: ep for ep in surface.endpoints}
    catalog_entries: list[str] = []
    for eid in searchable_endpoint_ids:
        ep = ep_by_id.get(eid)
        if ep:
            catalog_entries.append(
                f"{eid}: {ep.method.upper()} {ep.path} — {ep.summary or ep.domain}"
            )

    return ToolDefinition(
        name="search_api",
        description=(
            "Search for API operations not covered by the primary tools. "
            "Describe what you need (e.g., 'get user playlists', 'delete a track') "
            "and this tool returns matching operations you can call via custom_request. "
            f"Covers {len(searchable_endpoint_ids)} additional operations."
        ),
        covered_endpoints=searchable_endpoint_ids,
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language description of the operation you need. "
                        "The search matches against endpoint paths, summaries, and domains."
                    ),
                },
                "operation": {
                    "type": "string",
                    "description": (
                        "If you already know the operation id, pass it directly to "
                        "get its full details (method, path, parameters)."
                    ),
                    "enum": searchable_endpoint_ids,
                },
            },
            "required": [],
        },
        confidence=0.0,
    )


# ---------------------------------------------------------------------------
# Custom request tool
# ---------------------------------------------------------------------------


def _custom_request_tool() -> ToolDefinition:
    return ToolDefinition(
        name="custom_request",
        description="Send a custom API request for operations outside the curated tool plan.",
        covered_endpoints=[],
        input_schema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": [
                        "GET",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "OPTIONS",
                        "HEAD",
                    ],
                    "description": "HTTP method",
                },
                "path": {
                    "type": "string",
                    "description": "Path relative to API base URL",
                },
                "query": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "body": {
                    "type": [
                        "object",
                        "array",
                        "string",
                        "number",
                        "boolean",
                        "null",
                    ],
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["method", "path"],
        },
        # No confidence score: this is a built-in escape-hatch tool appended
        # by the curator, not a scored analysis candidate.
    )


# ---------------------------------------------------------------------------
# Schema construction
# ---------------------------------------------------------------------------


def _build_schema_for_endpoints(
    endpoints: list[UasfEndpoint],
    endpoint_ids: list[str],
) -> dict[str, Any]:
    path_params = _parameters_schema(endpoints, "path")
    query_params = _parameters_schema(endpoints, "query")

    return {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "Operation id to execute",
                "enum": endpoint_ids,
            },
            "path_params": path_params,
            "query": query_params,
            "body": {
                "description": "Optional request body",
                "type": [
                    "object",
                    "array",
                    "string",
                    "number",
                    "boolean",
                    "null",
                ],
            },
            "headers": {
                "type": "object",
                "description": "Optional request headers",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["operation"],
    }


def _parameters_schema(
    endpoints: list[UasfEndpoint], location: str
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: set[str] = set()

    for ep in endpoints:
        for param in ep.parameters:
            if param.location != location:
                continue
            properties[param.name] = param.schema_ if param.schema_ is not None else {}
            if param.required:
                required.add(param.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }

    if required:
        schema["required"] = sorted(required)

    return schema


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _dominant_intent(endpoints: list[UasfEndpoint]) -> EndpointIntent:
    counts: Counter[str] = Counter()
    for ep in endpoints:
        counts[_intent_label(ep.intent)] += 1

    winner = counts.most_common(1)[0][0] if counts else "unknown"

    mapping = {
        "read": EndpointIntent.READ,
        "search": EndpointIntent.SEARCH,
        "create": EndpointIntent.CREATE,
        "update": EndpointIntent.UPDATE,
        "delete": EndpointIntent.DELETE,
        "workflow": EndpointIntent.WORKFLOW,
        "admin": EndpointIntent.ADMIN,
    }
    return mapping.get(winner, EndpointIntent.UNKNOWN)


def _same_endpoint_set(left: list[str], right: list[str]) -> bool:
    return set(left) == set(right)


def _confidence_from_endpoint_count(count: int) -> float:
    if count == 0:
        return 0.45
    if count == 1:
        return 0.58
    if 2 <= count <= 4:
        return 0.75
    if 5 <= count <= 12:
        return 0.87
    return 0.8


def _sanitize_tool_name(raw: str) -> str:
    snake = inflection.underscore(raw).replace(" ", "_")
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch == "_") else "_" for ch in snake
    )
    collapsed = "_".join(seg for seg in sanitized.split("_") if seg)
    return collapsed if collapsed else "default"


def _normalize_description(raw: str) -> str:
    trimmed = raw.strip()
    if not trimmed:
        return "Manage grouped API operations."

    first_word = trimmed.split()[0].lower() if trimmed.split() else ""

    imperative_verbs = {
        "manage",
        "list",
        "search",
        "create",
        "update",
        "delete",
        "run",
        "send",
        "execute",
        "handle",
        "administer",
    }

    if first_word in imperative_verbs:
        return trimmed
    return f"Manage {trimmed}"


# ---------------------------------------------------------------------------
# Real confidence scoring
# ---------------------------------------------------------------------------


_SCORE_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "by",
        "with", "from", "as", "is", "are", "be", "that", "this", "it", "at",
        "api", "apis", "operations", "operation", "manage", "handle", "tool",
        "tools", "agent", "endpoint", "endpoints", "user", "users", "resource",
        "resources", "data", "service", "services", "run", "runs",
    }
)


def _extract_prompt_keywords(prompt: str | None) -> set[str]:
    if not prompt:
        return set()
    tokens = inflection.underscore(prompt).replace("-", "_").split()
    keywords: set[str] = set()
    for token in tokens:
        for part in token.split("_"):
            cleaned = "".join(
                ch for ch in part.lower() if ch.isascii() and ch.isalnum()
            )
            if len(cleaned) >= 3 and cleaned not in _SCORE_STOPWORDS:
                keywords.add(cleaned)
    return keywords


def _compute_tool_confidence(
    tool: ToolDefinition,
    endpoint_catalog: dict[str, UasfEndpoint],
    agent_keywords: set[str],
) -> float:
    """Compute a real confidence score from schema, intent, and coverage.

    Formula: 0.4 * schema_completeness + 0.3 * intent_match + 0.3 * coverage_ratio
    """
    covered_ids = tool.covered_endpoints or []

    # Endpoint coverage ratio: fraction of covered ids that resolve in surface.
    if not covered_ids:
        coverage_ratio = 0.0
        resolved: list[UasfEndpoint] = []
    else:
        resolved = [
            endpoint_catalog[eid] for eid in covered_ids if eid in endpoint_catalog
        ]
        coverage_ratio = len(resolved) / len(covered_ids)

    # Schema completeness against the resolved endpoints' actual needs.
    schema_completeness = _schema_completeness_for_endpoints(
        tool.input_schema or {}, resolved
    )

    # Intent match: keyword overlap between prompt and tool text + endpoints.
    intent_match = _intent_match_score(tool, resolved, agent_keywords)

    score = (
        0.4 * schema_completeness
        + 0.3 * intent_match
        + 0.3 * coverage_ratio
    )
    return round(max(0.0, min(score, 1.0)), 3)


def _schema_completeness_for_endpoints(
    input_schema: dict[str, Any],
    endpoints: list[UasfEndpoint],
) -> float:
    """Fraction of required schema features present for these endpoints."""
    if not endpoints:
        # Tool with no resolvable endpoints can't be judged on schema shape.
        return 0.0

    props = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(props, dict):
        return 0.0

    # Always-required features.
    checks: list[bool] = []

    # 1. operation enum covers all endpoints
    op_schema = props.get("operation")
    op_enum = op_schema.get("enum") if isinstance(op_schema, dict) else None
    if isinstance(op_enum, list) and op_enum:
        endpoint_ids = {ep.id for ep in endpoints}
        checks.append(endpoint_ids.issubset(set(op_enum)))
    else:
        checks.append(False)

    # Feature needs driven by endpoint parameters / bodies.
    needs_path = any(
        any(p.location == "path" for p in ep.parameters) for ep in endpoints
    )
    needs_query = any(
        any(p.location == "query" for p in ep.parameters) for ep in endpoints
    )
    needs_body = any(
        getattr(ep, "request_body_schema", None) is not None for ep in endpoints
    )

    if needs_path:
        checks.append(_has_object_property(props, "path_params"))
    if needs_query:
        checks.append(_has_object_property(props, "query"))
    if needs_body:
        checks.append("body" in props)

    # Required path params present in path_params.required
    required_path_names = {
        p.name
        for ep in endpoints
        for p in ep.parameters
        if p.location == "path" and p.required
    }
    if required_path_names:
        pp = props.get("path_params")
        pp_required = (
            set(pp.get("required", [])) if isinstance(pp, dict) else set()
        )
        checks.append(required_path_names.issubset(pp_required))

    if not checks:
        return 0.0
    return sum(1 for c in checks if c) / len(checks)


def _has_object_property(props: dict[str, Any], key: str) -> bool:
    val = props.get(key)
    return isinstance(val, dict) and val.get("type") == "object"


def _intent_match_score(
    tool: ToolDefinition,
    endpoints: list[UasfEndpoint],
    agent_keywords: set[str],
) -> float:
    """Keyword overlap between agent prompt and tool/endpoint text."""
    if not agent_keywords:
        # Neutral baseline when user supplied no intent.
        return 0.7

    haystack_parts: list[str] = [tool.name or "", tool.description or ""]
    for ep in endpoints:
        haystack_parts.append(ep.id or "")
        haystack_parts.append(ep.path or "")
        haystack_parts.append(getattr(ep, "summary", "") or "")
        haystack_parts.append(getattr(ep, "domain", "") or "")
        for tag in getattr(ep, "tags", []) or []:
            haystack_parts.append(tag or "")

    haystack = inflection.underscore(" ".join(haystack_parts)).lower()
    haystack = haystack.replace("-", " ").replace("_", " ").replace("/", " ")
    tokens = {t for t in haystack.split() if t}

    hits = sum(1 for kw in agent_keywords if kw in tokens)
    return hits / len(agent_keywords)


def _intent_label(intent: EndpointIntent) -> str:
    return {
        EndpointIntent.READ: "read",
        EndpointIntent.SEARCH: "search",
        EndpointIntent.CREATE: "create",
        EndpointIntent.UPDATE: "update",
        EndpointIntent.DELETE: "delete",
        EndpointIntent.WORKFLOW: "workflow",
        EndpointIntent.ADMIN: "admin",
        EndpointIntent.UNKNOWN: "unknown",
    }.get(intent, "unknown")

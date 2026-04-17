# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Normalize a ParsedSpec into a UASF surface with domain and intent annotations."""

from __future__ import annotations

import logging

from selqor_forge.models import (
    EndpointIntent,
    ParsedEndpoint,
    ParsedSpec,
    UasfEndpoint,
    UasfSurface,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def normalize(parsed: ParsedSpec) -> UasfSurface:
    """Convert a *ParsedSpec* into a *UasfSurface*.

    Each endpoint is annotated with a ``domain`` (derived from its first tag)
    and an ``intent`` (inferred from the HTTP method and textual cues).
    """
    logger.debug(
        "normalizing ParsedSpec into UASF surface: source=%s endpoints=%d",
        parsed.source,
        len(parsed.endpoints),
    )

    # Collect all unique tags to detect useless single-tag specs (e.g., all tagged "v1")
    all_tags = {tag for ep in parsed.endpoints for tag in ep.tags}

    # Pre-compute structural prefixes: first-segments that fan out to many
    # distinct second-segments are routing prefixes (api, v1), not resources.
    structural_prefixes = _detect_structural_prefixes(parsed.endpoints)

    endpoints = [
        _normalize_endpoint(ep, all_tags, structural_prefixes)
        for ep in parsed.endpoints
    ]

    logger.debug("UASF endpoint normalization complete: %d endpoints", len(endpoints))

    return UasfSurface(
        source=parsed.source,
        title=parsed.title,
        version=parsed.version,
        endpoints=endpoints,
        auth_schemes=parsed.auth_schemes,
    )


# ---------------------------------------------------------------------------
# Per-endpoint normalisation
# ---------------------------------------------------------------------------


def _normalize_endpoint(
    endpoint: ParsedEndpoint,
    all_tags: set[str] | None = None,
    structural_prefixes: set[str] | None = None,
) -> UasfEndpoint:
    # Use the first tag as domain, but only if it's a meaningful resource name.
    # Skip tags that are version prefixes (v1, api) or are the only tag across
    # all endpoints (meaning the spec author didn't use tags for domain grouping).
    tag_domain = endpoint.tags[0] if endpoint.tags else None
    if tag_domain:
        low = tag_domain.lower()
        # Reject version-like tags
        if _is_version_or_param_segment(low):
            tag_domain = None
        # Reject tags that are structural prefixes detected from path analysis
        elif structural_prefixes and low in structural_prefixes:
            tag_domain = None
        # Reject singleton-tag specs (all endpoints share one tag)
        elif all_tags and len(all_tags) <= 1:
            tag_domain = None

    domain = (
        tag_domain
        if tag_domain
        else _best_domain_segment(endpoint.path, structural_prefixes)
    )

    intent = _infer_intent(
        endpoint.method,
        endpoint.path,
        endpoint.summary,
        endpoint.description,
    )

    return UasfEndpoint(
        id=endpoint.id,
        method=endpoint.method,
        path=endpoint.path,
        summary=endpoint.summary,
        description=endpoint.description,
        domain=domain,
        intent=intent,
        tags=list(endpoint.tags),
        parameters=list(endpoint.parameters),
        request_body_schema=endpoint.request_body_schema,
        response_schema=endpoint.response_schema,
        security=list(endpoint.security),
    )


# ---------------------------------------------------------------------------
# Intent inference
# ---------------------------------------------------------------------------


def _infer_intent(
    method: str, path: str, summary: str, description: str
) -> EndpointIntent:
    method_lower = method.lower()
    haystack = f"{path.lower()} {summary.lower()} {description.lower()}"

    if "admin" in haystack or "permission" in haystack or "role" in haystack:
        return EndpointIntent.ADMIN

    if "search" in haystack or "query" in haystack or "filter" in haystack:
        return EndpointIntent.SEARCH

    if (
        "approve" in haystack
        or "send" in haystack
        or "execute" in haystack
        or "start" in haystack
        or "stop" in haystack
    ):
        return EndpointIntent.WORKFLOW

    if method_lower in ("get", "head"):
        return EndpointIntent.READ
    if method_lower == "post":
        return EndpointIntent.CREATE
    if method_lower in ("put", "patch"):
        return EndpointIntent.UPDATE
    if method_lower == "delete":
        return EndpointIntent.DELETE

    return EndpointIntent.UNKNOWN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_structural_prefixes(endpoints: list[ParsedEndpoint]) -> set[str]:
    """Detect path segments that are structural prefixes, not domain resources.

    Scans every endpoint path and counts: for each first non-param segment,
    how many distinct second non-param segments follow it? If a first segment
    fans out to ≥3 distinct children, it's a routing prefix (like ``v1``,
    ``api``), not a resource. No hardcoded lists needed.
    """
    from collections import Counter

    children_per_first: dict[str, set[str]] = {}
    first_segment_count: Counter[str] = Counter()

    for ep in endpoints:
        segments = [
            s.lower() for s in ep.path.strip("/").split("/")
            if s and not (s.startswith("{") and s.endswith("}"))
        ]
        if len(segments) >= 1:
            first = segments[0]
            first_segment_count[first] += 1
            if len(segments) >= 2:
                children_per_first.setdefault(first, set()).add(segments[1])

    prefixes: set[str] = set()
    for seg, children in children_per_first.items():
        if len(children) >= 3:
            prefixes.add(seg)

    return prefixes


def _is_version_or_param_segment(segment: str) -> bool:
    """Check if a path segment is a version prefix or parameter placeholder.

    Purely pattern-based — no hardcoded resource lists:
    - Version patterns: v1, v2, v1.0, v2beta, etc.
    - Parameter placeholders: {id}, {userId}, etc.
    - Pure numeric segments
    - Segments ≤ 2 characters (too short to be a meaningful resource)
    """
    s = segment.lower().strip()
    if not s:
        return True
    if s.startswith("{") and s.endswith("}"):
        return True
    if s.isdigit():
        return True
    if s[0] == "v" and len(s) >= 2 and s[1].isdigit():
        return True
    if len(s) <= 2:
        return True
    return False


def _best_domain_segment(
    path: str,
    structural_prefixes: set[str] | None = None,
) -> str:
    """Extract the most meaningful path segment for use as a domain name.

    Skips version prefixes, parameter placeholders, and structurally-detected
    prefixes. For ``/v1/customers/{id}/sources`` returns ``customers``.
    """
    stripped = path.lstrip("/")
    segments = [s for s in stripped.split("/") if s]
    prefixes = structural_prefixes or set()
    for segment in segments:
        clean = segment.replace("{", "").replace("}", "")
        if _is_version_or_param_segment(segment):
            continue
        if clean.lower() in prefixes:
            continue
        if clean:
            return clean
    # Fallback: use the first non-empty segment regardless
    return _first_path_segment(path)


def _first_path_segment(path: str) -> str:
    stripped = path.lstrip("/")
    for segment in stripped.split("/"):
        if segment:
            return segment.replace("{", "").replace("}", "")
    return "default"

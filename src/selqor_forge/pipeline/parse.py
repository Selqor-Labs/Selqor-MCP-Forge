# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Parse OpenAPI 3.x and Swagger 2.0 specifications into a normalised ParsedSpec."""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from selqor_forge.models import (
    ApiParameter,
    AuthKind,
    AuthScheme,
    ParsedEndpoint,
    ParsedSpec,
    SpecKind,
)

logger = logging.getLogger(__name__)

_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_spec(spec_input: str) -> ParsedSpec:
    """Parse an API specification from a file path, URL, or raw content string.

    Raises on any parse error.
    """
    logger.debug("parsing API specification: %s", spec_input)
    raw = _load_spec_content(spec_input)
    logger.debug("loaded specification content (%d bytes)", len(raw))
    doc = _parse_document(raw)
    parsed = _to_parsed_spec(doc, spec_input)
    logger.debug(
        "parsed specification successfully: source=%s spec_kind=%s endpoints=%d auth_schemes=%d",
        parsed.source,
        parsed.spec_kind,
        len(parsed.endpoints),
        len(parsed.auth_schemes),
    )
    return parsed


def merge_parsed_specs(specs: list[ParsedSpec], combined_title: str | None = None) -> ParsedSpec:
    """Merge multiple :class:`ParsedSpec` instances into one.

    Endpoints from different specs that share the same operation ID are
    disambiguated by prefixing the spec's slugified title (e.g.
    ``petstore_listpets``).  Auth schemes are deduplicated by name.
    """
    if not specs:
        raise ValueError("merge_parsed_specs requires at least one spec")
    if len(specs) == 1:
        return specs[0]

    def _slug(title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:24]

    # Collect all endpoint ids across specs to detect collisions.
    from collections import Counter
    id_counts: Counter[str] = Counter()
    for spec in specs:
        for ep in spec.endpoints:
            id_counts[ep.id] += 1

    merged_endpoints: list[ParsedEndpoint] = []
    seen_ids: set[str] = set()

    for spec in specs:
        prefix = _slug(spec.title) if any(
            id_counts[ep.id] > 1 for ep in spec.endpoints
        ) else ""
        for ep in spec.endpoints:
            new_id = f"{prefix}_{ep.id}" if prefix and id_counts[ep.id] > 1 else ep.id
            # Ensure uniqueness even within the same spec after prefixing.
            candidate = new_id
            suffix = 2
            while candidate in seen_ids:
                candidate = f"{new_id}_{suffix}"
                suffix += 1
            seen_ids.add(candidate)
            merged_endpoints.append(ep.model_copy(update={"id": candidate}))

    # Merge auth schemes â€” deduplicate by name.
    seen_scheme_names: set[str] = set()
    merged_schemes: list[AuthScheme] = []
    for spec in specs:
        for scheme in spec.auth_schemes:
            if scheme.name not in seen_scheme_names:
                seen_scheme_names.add(scheme.name)
                merged_schemes.append(scheme)

    # Merge global security (union).
    global_security = list({s for spec in specs for s in spec.global_security})

    title = combined_title or " + ".join(s.title for s in specs)
    version = specs[0].version

    logger.debug(
        "merged %d specs into combined surface: title=%r endpoints=%d",
        len(specs),
        title,
        len(merged_endpoints),
    )

    return ParsedSpec(
        source=specs[0].source,
        title=title,
        version=version,
        spec_kind=specs[0].spec_kind,
        auth_schemes=merged_schemes,
        global_security=global_security,
        endpoints=merged_endpoints,
    )


# ---------------------------------------------------------------------------
# Content loading
# ---------------------------------------------------------------------------


def _is_blocked_host(url: str) -> bool:
    """Block requests to internal/private IP ranges to prevent SSRF."""
    from ipaddress import IPv4Address, ip_address as parse_ip
    import socket

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Unresolvable: let httpx surface the real network error.
        return False

    for _, _, _, _, sockaddr in resolved:
        raw = sockaddr[0]
        # Strip IPv6 zone identifiers (e.g. "fe80::1%eth0") before parsing.
        raw = raw.split("%", 1)[0]
        try:
            addr = parse_ip(raw)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_unspecified
            or addr.is_multicast
        ):
            return True
        # `is_reserved` is only meaningful for IPv4 here; in IPv6 it covers
        # broad public ranges such as NAT64 (64:ff9b::/96, RFC 6052) which
        # legitimately route to public IPv4 services.
        if isinstance(addr, IPv4Address) and addr.is_reserved:
            return True

    return False


# Maximum response size for fetched specs (20 MB)
_MAX_SPEC_RESPONSE_BYTES = 20 * 1024 * 1024


def _load_spec_content(input_: str) -> str:
    if _looks_like_url(input_):
        logger.debug("loading specification from URL: %s", input_)

        if _is_blocked_host(input_):
            raise RuntimeError(
                f"spec URL points to a private/internal address and is blocked: {input_}"
            )

        client = httpx.Client(
            headers={"User-Agent": "selqor-forge/0.1.0"},
            follow_redirects=True,
            max_redirects=5,
        )
        try:
            response = client.get(input_)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"failed to fetch spec URL: {input_}") from exc
        finally:
            client.close()

        if not response.is_success:
            raise RuntimeError(
                f"spec URL returned non-success status {response.status_code} for {input_}"
            )

        if len(response.content) > _MAX_SPEC_RESPONSE_BYTES:
            raise RuntimeError(
                f"spec response exceeds maximum size ({_MAX_SPEC_RESPONSE_BYTES // (1024*1024)}MB)"
            )

        text = response.text
        logger.debug("fetched specification body (%d bytes)", len(text))
        return text

    logger.debug("loading specification from local file: %s", input_)
    try:
        return Path(input_).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"failed to read spec file: {input_}") from exc


def _looks_like_url(input_: str) -> bool:
    try:
        parsed = urlparse(input_)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Document parsing (JSON / YAML)
# ---------------------------------------------------------------------------


def _parse_document(raw: str) -> dict[str, Any]:
    try:
        doc = json.loads(raw)
        logger.debug("parsed specification as JSON")
        return doc
    except (json.JSONDecodeError, ValueError):
        pass

    logger.debug("JSON parse failed; trying YAML parser")
    try:
        doc = yaml.safe_load(raw)
        if isinstance(doc, dict):
            return doc
        raise ValueError("YAML document is not a mapping")
    except yaml.YAMLError as exc:
        raise RuntimeError("failed to parse input as JSON or YAML") from exc


# ---------------------------------------------------------------------------
# Spec transformation
# ---------------------------------------------------------------------------


def _to_parsed_spec(doc: dict[str, Any], source: str) -> ParsedSpec:
    spec_kind = _detect_spec_kind(doc)

    info: dict[str, Any] = doc.get("info") or {}
    title = info.get("title", "Generated API")
    version = info.get("version", "unknown")

    auth_schemes = _extract_auth_schemes(doc, spec_kind)
    global_security = _extract_security_names(doc.get("security"))

    paths = doc.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("spec is missing paths object")

    endpoints: list[ParsedEndpoint] = []
    seen_ids: dict[str, int] = {}

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        path_level_parameters = _parse_parameters(path_item.get("parameters"), doc)

        for method in _METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            operation_parameters = _parse_parameters(operation.get("parameters"), doc)
            parameters = _merge_parameters(
                copy.deepcopy(path_level_parameters), operation_parameters
            )

            op_id_raw = operation.get("operationId")
            if isinstance(op_id_raw, str):
                generated_id = _normalize_identifier(op_id_raw)
            else:
                generated_id = _normalize_identifier(f"{method}_{path}")

            id_ = _make_unique_id(generated_id, seen_ids)

            tags = _collect_tags(operation, path)
            summary = operation.get("summary") or id_
            description = operation.get("description") or summary

            request_body_schema = _extract_request_body_schema(
                operation, spec_kind, doc
            )
            response_schema = _extract_response_schema(operation, spec_kind, doc)

            if "security" in operation:
                security = _extract_security_names(operation.get("security"))
            else:
                security = list(global_security)

            endpoints.append(
                ParsedEndpoint(
                    id=id_,
                    method=method,
                    path=path,
                    summary=summary,
                    description=description,
                    tags=tags,
                    parameters=parameters,
                    request_body_schema=request_body_schema,
                    response_schema=response_schema,
                    security=security,
                )
            )

    if not endpoints:
        raise RuntimeError("no valid HTTP operations found in paths")

    logger.debug(
        "specification transformed into ParsedSpec: source=%s paths=%d endpoints=%d global_security=%d",
        source,
        len(paths),
        len(endpoints),
        len(global_security),
    )

    return ParsedSpec(
        source=source,
        title=title,
        version=version,
        spec_kind=spec_kind,
        auth_schemes=auth_schemes,
        global_security=global_security,
        endpoints=endpoints,
    )


# ---------------------------------------------------------------------------
# Spec kind detection
# ---------------------------------------------------------------------------


def _detect_spec_kind(doc: dict[str, Any]) -> SpecKind:
    if "openapi" in doc:
        return SpecKind.OPEN_API_3

    if isinstance(doc.get("swagger"), str):
        return SpecKind.SWAGGER_2

    raise RuntimeError("unsupported spec format: expected OpenAPI 3.x or Swagger 2.0")


# ---------------------------------------------------------------------------
# Auth scheme extraction
# ---------------------------------------------------------------------------


def _extract_auth_schemes(
    doc: dict[str, Any], kind: SpecKind
) -> list[AuthScheme]:
    if kind == SpecKind.OPEN_API_3:
        schemes = (doc.get("components") or {}).get("securitySchemes")
    else:
        schemes = doc.get("securityDefinitions")

    if not isinstance(schemes, dict):
        return []

    result: list[AuthScheme] = []
    for name, raw in schemes.items():
        raw_type = raw.get("type") if isinstance(raw, dict) else None
        auth_kind = _classify_auth_scheme(raw, kind)
        details = raw.get("description") if isinstance(raw, dict) else None

        result.append(
            AuthScheme(
                name=name,
                kind=auth_kind,
                raw_type=raw_type,
                details=details,
            )
        )

    return result


def _classify_auth_scheme(raw: Any, spec_kind: SpecKind) -> AuthKind:
    if not isinstance(raw, dict):
        return AuthKind.UNKNOWN

    raw_type = raw.get("type", "")

    if raw_type == "apiKey":
        location = raw.get("in")
        if location == "header":
            return AuthKind.API_KEY_HEADER
        if location == "query":
            return AuthKind.API_KEY_QUERY
        return AuthKind.UNKNOWN

    if raw_type == "http":
        scheme = (raw.get("scheme") or "").lower()
        if scheme == "bearer":
            return AuthKind.BEARER
        if scheme == "basic":
            return AuthKind.BASIC
        return AuthKind.UNKNOWN

    if raw_type == "oauth2":
        if spec_kind == SpecKind.OPEN_API_3:
            flows = raw.get("flows")
            if isinstance(flows, dict) and "clientCredentials" in flows:
                return AuthKind.OAUTH2_CLIENT_CREDENTIALS

        if spec_kind == SpecKind.SWAGGER_2:
            if raw.get("flow") == "application":
                return AuthKind.OAUTH2_CLIENT_CREDENTIALS

        return AuthKind.UNKNOWN

    if raw_type == "basic":
        return AuthKind.BASIC

    return AuthKind.UNKNOWN


# ---------------------------------------------------------------------------
# Security names
# ---------------------------------------------------------------------------


def _extract_security_names(value: Any | None) -> list[str]:
    if not isinstance(value, list):
        return []

    names: list[str] = []
    for requirement in value:
        if isinstance(requirement, dict):
            names.extend(requirement.keys())
    return names


# ---------------------------------------------------------------------------
# Parameter parsing
# ---------------------------------------------------------------------------


def _parse_parameters(
    value: Any | None, root: dict[str, Any]
) -> list[ApiParameter]:
    if not isinstance(value, list):
        return []
    result: list[ApiParameter] = []
    for param in value:
        parsed = _parse_parameter(param, root)
        if parsed is not None:
            result.append(parsed)
    return result


def _parse_parameter(
    value: Any, root: dict[str, Any]
) -> ApiParameter | None:
    return _parse_parameter_with_depth(value, root, 0)


def _parse_parameter_with_depth(
    value: Any, root: dict[str, Any], depth: int
) -> ApiParameter | None:
    if depth > 16:
        return None

    if isinstance(value, dict) and "$ref" in value:
        reference = value["$ref"]
        if isinstance(reference, str):
            resolved = _resolve_local_reference(root, reference)
            if resolved is not None:
                return _parse_parameter_with_depth(resolved, root, depth + 1)

            ref_name = reference.rsplit("/", 1)[-1] if "/" in reference else "referenced_parameter"
            return ApiParameter(
                name=ref_name,
                location="unknown",
                required=False,
                description=f"Unresolved reference: {reference}",
                schema_={"type": "string"},
            )

    if not isinstance(value, dict):
        return None

    name = value.get("name")
    if not isinstance(name, str):
        return None

    location = value.get("in", "query")
    required = bool(value.get("required", False))
    description = value.get("description")
    if not isinstance(description, str):
        description = None

    schema_val = value.get("schema")
    if schema_val is not None:
        schema = _resolve_schema_references(schema_val, root)
    elif isinstance(value.get("type"), str):
        schema = {"type": value["type"]}
    else:
        schema = {"type": "string"}

    return ApiParameter(
        name=name,
        location=location,
        required=required,
        description=description,
        schema_=schema,
    )


# ---------------------------------------------------------------------------
# Parameter merging
# ---------------------------------------------------------------------------


def _merge_parameters(
    path_level: list[ApiParameter],
    operation_level: list[ApiParameter],
) -> list[ApiParameter]:
    merged: dict[str, ApiParameter] = {}

    for param in path_level:
        key = f"{param.location}:{param.name}"
        merged[key] = param

    for param in operation_level:
        key = f"{param.location}:{param.name}"
        merged[key] = param

    return list(merged.values())


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def _collect_tags(operation: dict[str, Any], path: str) -> list[str]:
    tags_raw = operation.get("tags")
    if isinstance(tags_raw, list):
        collected = [t for t in tags_raw if isinstance(t, str)]
        if collected:
            return collected

    return [_first_path_segment(path)]


# ---------------------------------------------------------------------------
# Request body / response schema extraction
# ---------------------------------------------------------------------------


def _extract_request_body_schema(
    operation: dict[str, Any],
    kind: SpecKind,
    root: dict[str, Any],
) -> Any | None:
    if kind == SpecKind.OPEN_API_3:
        request_body_raw = operation.get("requestBody")
        if request_body_raw is None:
            return None
        request_body = _resolve_local_reference_if_needed(request_body_raw, root)
        content = request_body.get("content") if isinstance(request_body, dict) else None
        if not isinstance(content, dict):
            return None
        media_type = content.get("application/json")
        if media_type is None:
            # Fallback to first available media type.
            first_values = list(content.values())
            media_type = first_values[0] if first_values else None
        if media_type is None or not isinstance(media_type, dict):
            return None
        schema = media_type.get("schema")
        if schema is None:
            return None
        return _resolve_schema_references(schema, root)

    # Swagger 2.0
    params = operation.get("parameters")
    if not isinstance(params, list):
        return None
    for param in params:
        if isinstance(param, dict) and param.get("in") == "body":
            schema = param.get("schema")
            if schema is not None:
                return _resolve_schema_references(schema, root)
    return None


def _extract_response_schema(
    operation: dict[str, Any],
    kind: SpecKind,
    root: dict[str, Any],
) -> Any | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None

    candidate_raw = (
        responses.get("200")
        or responses.get("201")
        or responses.get("202")
        or responses.get("default")
    )
    if candidate_raw is None:
        # Fallback to the first response value.
        values = list(responses.values())
        candidate_raw = values[0] if values else None
    if candidate_raw is None:
        return None

    candidate = _resolve_local_reference_if_needed(candidate_raw, root)

    if kind == SpecKind.OPEN_API_3:
        if not isinstance(candidate, dict):
            return None
        content = candidate.get("content")
        if not isinstance(content, dict):
            return None
        media_type = content.get("application/json")
        if media_type is None:
            first_values = list(content.values())
            media_type = first_values[0] if first_values else None
        if media_type is None or not isinstance(media_type, dict):
            return None
        schema = media_type.get("schema")
        if schema is None:
            return None
        return _resolve_schema_references(schema, root)

    # Swagger 2.0
    if not isinstance(candidate, dict):
        return None
    schema = candidate.get("schema")
    if schema is None:
        return None
    return _resolve_schema_references(schema, root)


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def _resolve_local_reference(root: dict[str, Any], reference: str) -> Any | None:
    """Resolve a JSON Pointer reference like ``#/components/schemas/Foo``."""
    if not reference.startswith("#"):
        return None
    pointer = reference[1:]  # strip leading '#'
    parts = pointer.strip("/").split("/")
    current: Any = root
    for part in parts:
        if not part:
            continue
        # JSON Pointer escaping: ~1 -> /, ~0 -> ~
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _resolve_local_reference_if_needed(value: Any, root: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            resolved = _resolve_local_reference(root, reference)
            if resolved is not None:
                # Shallow copy is sufficient here — the resolved value is
                # only used to read "content"/"schema" keys, not mutated.
                return dict(resolved) if isinstance(resolved, dict) else resolved
    # Shallow copy for read-only access
    return dict(value) if isinstance(value, dict) else value


def _resolve_schema_references(schema: Any, root: dict[str, Any]) -> Any:
    seen: set[str] = set()
    cache: dict[str, Any] = {}
    return _resolve_schema_references_inner(schema, root, seen, 0, cache)


# Maximum number of properties to resolve per schema object.  Very large
# schemas (e.g. Stripe's 300+ field objects) don't add analytic value beyond
# the first N properties — keeping them all just wastes memory.
_MAX_SCHEMA_PROPERTIES = 60


def _resolve_schema_references_inner(
    value: Any,
    root: dict[str, Any],
    seen: set[str],
    depth: int,
    cache: dict[str, Any],
) -> Any:
    if depth > 12:
        # Shallow depth limit — beyond 12 levels, schemas are not useful
        # for tool analysis and resolving them wastes enormous memory on
        # specs like Stripe (15MB, 300+ nested $ref chains).
        if isinstance(value, dict) and "$ref" in value:
            ref = value["$ref"]
            ref_name = ref.rsplit("/", 1)[-1] if "/" in ref else "object"
            return {"type": "object", "description": f"(ref: {ref_name})"}
        return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            if reference in seen:
                # Circular reference — return a stub
                ref_name = reference.rsplit("/", 1)[-1] if "/" in reference else "object"
                return {"type": "object", "description": f"(circular ref: {ref_name})"}

            # Return cached result for this $ref (avoids re-resolving the
            # same schema hundreds of times in specs like Stripe/GitHub).
            if reference in cache and len(value) == 1:
                return cache[reference]

            seen.add(reference)

            target = _resolve_local_reference(root, reference)
            if target is not None:
                resolved = _resolve_schema_references_inner(
                    target, root, seen, depth + 1, cache
                )
            else:
                resolved = copy.deepcopy(value)

            seen.discard(reference)

            if len(value) == 1:
                # The dict was *only* a $ref, return the resolved value directly.
                cache[reference] = resolved
                return resolved

            # There are sibling keys alongside $ref -- merge them.
            if isinstance(resolved, dict):
                merged = dict(resolved)  # shallow copy to avoid mutating cache
                for key, child in value.items():
                    if key == "$ref":
                        continue
                    merged[key] = _resolve_schema_references_inner(
                        child, root, seen, depth + 1, cache
                    )
                return merged
            else:
                fallback: dict[str, Any] = {}
                for key, child in value.items():
                    if key == "$ref":
                        continue
                    fallback[key] = _resolve_schema_references_inner(
                        child, root, seen, depth + 1, cache
                    )
                if not fallback:
                    return resolved
                fallback["allOf"] = [resolved]
                return fallback
        else:
            # Regular object -- recurse into every key, but cap property count
            # to prevent memory explosion on enormous schema objects.
            result: dict[str, Any] = {}
            props = value.get("properties")
            if isinstance(props, dict) and len(props) > _MAX_SCHEMA_PROPERTIES:
                # Truncate properties to a reasonable count
                truncated_props: dict[str, Any] = {}
                for i, (pk, pv) in enumerate(props.items()):
                    if i >= _MAX_SCHEMA_PROPERTIES:
                        break
                    truncated_props[pk] = _resolve_schema_references_inner(
                        pv, root, seen, depth + 1, cache
                    )
                result["properties"] = truncated_props
                for key, child in value.items():
                    if key == "properties":
                        continue
                    result[key] = _resolve_schema_references_inner(
                        child, root, seen, depth + 1, cache
                    )
                return result

            for key, child in value.items():
                result[key] = _resolve_schema_references_inner(
                    child, root, seen, depth + 1, cache
                )
            return result

    if isinstance(value, list):
        return [
            _resolve_schema_references_inner(item, root, seen, depth + 1, cache)
            for item in value
        ]

    # Scalar -- return as-is (immutable, no deepcopy needed).
    return value


# ---------------------------------------------------------------------------
# Identifier helpers
# ---------------------------------------------------------------------------


def _make_unique_id(base: str, seen: dict[str, int]) -> str:
    count = seen.get(base, 0)
    if count == 0:
        seen[base] = 1
        return base

    id_ = f"{base}_{count}"
    seen[base] = count + 1
    return id_


def _normalize_identifier(raw: str) -> str:
    chars: list[str] = []
    for ch in raw:
        if ch.isascii() and ch.isalnum():
            chars.append(ch.lower())
        else:
            chars.append("_")

    normalized = "".join(chars)

    # Collapse consecutive underscores by splitting on _ and rejoining.
    segments = [s for s in normalized.split("_") if s]
    collapsed = "_".join(segments)

    if not collapsed:
        return "operation"

    if collapsed[0].isdigit():
        return f"op_{collapsed}"

    return collapsed


def _first_path_segment(path: str) -> str:
    stripped = path.lstrip("/")
    for segment in stripped.split("/"):
        if segment:
            return segment.replace("{", "").replace("}", "")
    return "default"

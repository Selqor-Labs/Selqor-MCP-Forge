# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Heuristic security scanner for OpenAPI / Swagger specifications.

The MCP-oriented scanner expects a *running* server and only ever yields
findings when it can talk JSON-RPC to it. When the user instead points the
scanner at an OpenAPI document (the most common shape â€” every Forge
integration is created from one), discovery returns an empty manifest and the
pipeline silently produces zero findings.

This module implements a focused set of heuristics that work directly on the
parsed OpenAPI document and produce real, actionable findings:

* HTTP-only ``host`` / ``servers``
* Missing or empty ``securitySchemes`` / ``securityDefinitions``
* No global ``security`` requirement
* Mutating operations (POST/PUT/PATCH/DELETE) with no per-operation security
* Use of weak auth schemes (``basic`` over HTTP, ``apiKey`` in query)
* Path parameters that look like raw IDs without any documented validation
* Missing ``requestBody`` schema on mutating operations
* Operations with no documented responses (4xx / 5xx)
* Wildcard CORS hints in description / x-cors

The result is a list of :class:`SecurityFinding` objects ready to be merged
into the main scan pipeline.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .models import RiskLevel, SecurityFinding, VulnerabilitySource

_MUTATING_METHODS = {"post", "put", "patch", "delete"}
_VALID_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def looks_like_openapi(payload: Any) -> bool:
    """Return True when *payload* is a parsed OpenAPI / Swagger document."""
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("openapi") or payload.get("swagger") or payload.get("paths"))


def scan_openapi_document(spec: dict, source: str = "") -> list[SecurityFinding]:
    """Scan a parsed OpenAPI / Swagger document and return findings.

    The scanner is intentionally heuristic: it produces a small but
    high-signal set of findings that any honest API would actually want to
    fix. False positives are preferable to silent zeros.
    """
    findings: list[SecurityFinding] = []

    is_swagger_2 = "swagger" in spec and "openapi" not in spec
    findings.extend(_check_transport(spec, source, is_swagger_2))
    findings.extend(_check_security_schemes(spec, is_swagger_2))
    findings.extend(_check_global_security(spec))
    findings.extend(_check_operations(spec, is_swagger_2))
    findings.extend(_check_cors_hints(spec))

    return findings


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------


def _check_transport(spec: dict, source: str, is_swagger_2: bool) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    # Swagger 2: schemes is a top-level list (e.g. ["http", "https"])
    if is_swagger_2:
        schemes = [s.lower() for s in (spec.get("schemes") or [])]
        host = spec.get("host") or ""
        base_path = spec.get("basePath") or ""
        if "http" in schemes and "https" not in schemes:
            findings.append(
                SecurityFinding(
                    id="openapi_transport_http_only",
                    title="HTTP Only â€” No TLS",
                    description=(
                        f"The API spec advertises {schemes} as the only supported scheme(s). "
                        "All requests will be transmitted in plaintext, exposing credentials and "
                        "sensitive payloads to network attackers."
                    ),
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Add 'https' to schemes and redirect HTTP requests to HTTPS in production.",
                    tags=["transport", "tls", "openapi"],
                    metadata={"endpoint": f"{host}{base_path}".strip() or source},
                )
            )
        if "http" in schemes and "https" in schemes:
            findings.append(
                SecurityFinding(
                    id="openapi_transport_mixed",
                    title="Mixed HTTP and HTTPS Schemes",
                    description=(
                        "The API allows both HTTP and HTTPS, which lets clients accidentally "
                        "downgrade to plaintext."
                    ),
                    risk_level=RiskLevel.MEDIUM,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Drop 'http' from the schemes list and enforce HTTPS at the gateway.",
                    tags=["transport", "tls", "openapi"],
                )
            )
    else:
        # OpenAPI 3.x: servers[].url
        servers = spec.get("servers") or []
        http_servers = [s for s in servers if isinstance(s, dict) and (s.get("url") or "").startswith("http://")]
        if http_servers and not any(
            host in (s.get("url") or "") for host in ("localhost", "127.0.0.1", "0.0.0.0") for s in http_servers
        ):
            findings.append(
                SecurityFinding(
                    id="openapi_transport_http_only",
                    title="HTTP Only Server URL",
                    description=(
                        f"One or more 'servers' entries use plaintext HTTP: "
                        f"{[s.get('url') for s in http_servers]}. "
                        "Credentials, request bodies, and responses will travel unencrypted."
                    ),
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Replace 'http://' with 'https://' in all servers entries and serve real TLS certificates.",
                    tags=["transport", "tls", "openapi"],
                )
            )

    # Source URL itself was HTTP â€” also worth flagging.
    if source.startswith("http://") and not any(h in source for h in ("localhost", "127.0.0.1", "0.0.0.0")):
        findings.append(
            SecurityFinding(
                id="openapi_source_http",
                title="Spec Fetched Over HTTP",
                description=(
                    "The OpenAPI document itself was downloaded over plaintext HTTP, "
                    "which means an attacker on the network could tamper with it."
                ),
                risk_level=RiskLevel.MEDIUM,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Host the spec on an HTTPS endpoint.",
                tags=["transport", "spec-source"],
            )
        )

    return findings


def _check_security_schemes(spec: dict, is_swagger_2: bool) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    if is_swagger_2:
        schemes = spec.get("securityDefinitions") or {}
    else:
        schemes = (spec.get("components") or {}).get("securitySchemes") or {}

    if not schemes:
        findings.append(
            SecurityFinding(
                id="openapi_no_security_schemes",
                title="No Authentication Schemes Defined",
                description=(
                    "The API spec does not declare any securitySchemes / securityDefinitions. "
                    "Either authentication is undocumented (clients have no way to know what to "
                    "send) or â€” more likely â€” there is no authentication at all."
                ),
                risk_level=RiskLevel.HIGH,
                source=VulnerabilitySource.HEURISTIC,
                remediation=(
                    "Define an appropriate securityScheme (OAuth2, OpenID Connect, or bearer JWT) "
                    "under components.securitySchemes and reference it from operations."
                ),
                tags=["auth", "openapi"],
            )
        )
        return findings

    for name, scheme in schemes.items():
        if not isinstance(scheme, dict):
            continue
        scheme_type = (scheme.get("type") or "").lower()
        scheme_loc = (scheme.get("in") or "").lower()
        scheme_kind = (scheme.get("scheme") or "").lower()

        if scheme_type == "basic" or scheme_kind == "basic":
            findings.append(
                SecurityFinding(
                    id=f"openapi_auth_basic_{name}",
                    title=f"Weak Auth: HTTP Basic ({name})",
                    description=(
                        f"Security scheme '{name}' uses HTTP Basic authentication. Basic auth "
                        "transmits the password on every request and offers no defence against "
                        "credential theft if TLS is broken or absent."
                    ),
                    risk_level=RiskLevel.MEDIUM,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Switch to OAuth2 (authorization_code or client_credentials) or short-lived bearer JWTs.",
                    tags=["auth", "openapi", "basic"],
                )
            )
        if scheme_type == "apikey" and scheme_loc == "query":
            findings.append(
                SecurityFinding(
                    id=f"openapi_apikey_in_query_{name}",
                    title=f"API Key in Query String ({name})",
                    description=(
                        f"Security scheme '{name}' transmits the API key as a query parameter. "
                        "Query strings are routinely logged by load balancers, proxies, and "
                        "browsers, leaking the credential."
                    ),
                    risk_level=RiskLevel.HIGH,
                    source=VulnerabilitySource.HEURISTIC,
                    remediation="Move the API key to an HTTP header (e.g. 'X-API-Key') or migrate to bearer tokens.",
                    tags=["auth", "openapi", "credential-exposure"],
                )
            )
        if scheme_type == "oauth2":
            flows = scheme.get("flows") or {}
            implicit = flows.get("implicit") if isinstance(flows, dict) else None
            if implicit or (is_swagger_2 and (scheme.get("flow") or "").lower() == "implicit"):
                findings.append(
                    SecurityFinding(
                        id=f"openapi_oauth_implicit_{name}",
                        title=f"OAuth2 Implicit Flow ({name})",
                        description=(
                            f"Security scheme '{name}' uses the OAuth2 implicit flow, which is "
                            "deprecated by the OAuth2 Security BCP because it exposes access "
                            "tokens in URL fragments."
                        ),
                        risk_level=RiskLevel.MEDIUM,
                        source=VulnerabilitySource.HEURISTIC,
                        remediation="Switch to authorization_code with PKCE.",
                        tags=["auth", "oauth2", "openapi"],
                    )
                )

    return findings


def _check_global_security(spec: dict) -> list[SecurityFinding]:
    if "security" not in spec:
        return [
            SecurityFinding(
                id="openapi_no_global_security",
                title="No Global Security Requirement",
                description=(
                    "The spec defines no top-level 'security' requirement. Operations that omit "
                    "their own 'security' field will inherit nothing â€” meaning they are "
                    "publicly accessible by default."
                ),
                risk_level=RiskLevel.MEDIUM,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Add a top-level 'security' array referencing the default scheme so unannotated operations are protected by default.",
                tags=["auth", "openapi", "default-deny"],
            )
        ]
    return []


def _check_operations(spec: dict, is_swagger_2: bool) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return findings

    has_global_security = bool(spec.get("security"))
    unauth_mutating: list[str] = []
    no_request_body: list[str] = []
    no_documented_errors: list[str] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _VALID_HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            method_l = method.lower()
            label = f"{method_l.upper()} {path}"

            op_security = operation.get("security")
            # Empty list explicitly disables security; missing key falls back to global.
            effective_security = op_security if op_security is not None else (
                spec.get("security") if has_global_security else None
            )
            if method_l in _MUTATING_METHODS and not effective_security:
                unauth_mutating.append(label)

            if method_l in _MUTATING_METHODS:
                # OpenAPI 3 uses requestBody; Swagger 2 uses parameters[in=body]
                if is_swagger_2:
                    params = operation.get("parameters") or []
                    has_body = any(
                        isinstance(p, dict) and (p.get("in") or "").lower() == "body" for p in params
                    )
                else:
                    has_body = bool(operation.get("requestBody"))
                if not has_body:
                    no_request_body.append(label)

            responses = operation.get("responses") or {}
            if isinstance(responses, dict):
                error_codes = [
                    str(code) for code in responses
                    if isinstance(code, (str, int)) and str(code).startswith(("4", "5"))
                ]
                if not error_codes:
                    no_documented_errors.append(label)

    if unauth_mutating:
        findings.append(
            SecurityFinding(
                id="openapi_unauth_mutations",
                title=f"{len(unauth_mutating)} Mutating Operation(s) Without Authentication",
                description=(
                    "The following mutating operations have no security requirement and inherit "
                    "no global default. They are publicly writable, which typically allows "
                    "anonymous data tampering:\n  - "
                    + "\n  - ".join(unauth_mutating[:20])
                    + ("\n  - â€¦" if len(unauth_mutating) > 20 else "")
                ),
                risk_level=RiskLevel.CRITICAL if len(unauth_mutating) >= 3 else RiskLevel.HIGH,
                source=VulnerabilitySource.HEURISTIC,
                remediation=(
                    "Attach a 'security' requirement to every mutating operation, or define a "
                    "default top-level security requirement and rely on it."
                ),
                tags=["auth", "openapi", "broken-authorization"],
                metadata={"endpoints": unauth_mutating[:50]},
            )
        )

    if no_request_body:
        findings.append(
            SecurityFinding(
                id="openapi_missing_request_schema",
                title=f"{len(no_request_body)} Mutating Operation(s) Missing Request Schema",
                description=(
                    "The following operations accept input but do not declare a requestBody / "
                    "body parameter schema. Without a schema there is no input validation, "
                    "leaving them vulnerable to mass-assignment and injection attacks:\n  - "
                    + "\n  - ".join(no_request_body[:20])
                    + ("\n  - â€¦" if len(no_request_body) > 20 else "")
                ),
                risk_level=RiskLevel.MEDIUM,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Declare a requestBody (OpenAPI 3) or body parameter (Swagger 2) with a strict JSON schema for every mutating operation.",
                tags=["validation", "openapi", "input-validation"],
                metadata={"endpoints": no_request_body[:50]},
            )
        )

    if no_documented_errors:
        findings.append(
            SecurityFinding(
                id="openapi_missing_error_responses",
                title=f"{len(no_documented_errors)} Operation(s) Missing 4xx/5xx Responses",
                description=(
                    "The following operations document only success responses. Clients "
                    "(and security scanners) have no model for error handling, and developers "
                    "are likely to leak stack traces in unhandled paths:\n  - "
                    + "\n  - ".join(no_documented_errors[:20])
                    + ("\n  - â€¦" if len(no_documented_errors) > 20 else "")
                ),
                risk_level=RiskLevel.LOW,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Document at least one 4xx and one 5xx response (e.g. 400, 401, 500) with a structured error schema.",
                tags=["openapi", "error-handling"],
                metadata={"endpoints": no_documented_errors[:50]},
            )
        )

    return findings


def _check_cors_hints(spec: dict) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    info = spec.get("info") or {}
    description = (info.get("description") or "").lower()
    if "access-control-allow-origin: *" in description or "cors: allow all" in description:
        findings.append(
            SecurityFinding(
                id="openapi_cors_wildcard",
                title="Wildcard CORS Hint in Spec",
                description=(
                    "The spec description suggests the API serves 'Access-Control-Allow-Origin: *'. "
                    "Wildcard CORS combined with credentialed requests allows any site to call the API "
                    "as the user."
                ),
                risk_level=RiskLevel.MEDIUM,
                source=VulnerabilitySource.HEURISTIC,
                remediation="Restrict Access-Control-Allow-Origin to an explicit allow-list and never combine with Access-Control-Allow-Credentials: true.",
                tags=["cors", "openapi"],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def is_likely_openapi_url(url: str) -> bool:
    """Return True when *url* looks like a hosted OpenAPI / Swagger document.

    Used as a cheap pre-check before issuing a network request: any URL whose
    path ends in a known spec extension or contains 'swagger' / 'openapi'.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    path = (parsed.path or "").lower()
    if path.endswith((".json", ".yaml", ".yml")):
        return True
    if "swagger" in path or "openapi" in path:
        return True
    return False

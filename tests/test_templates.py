# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for generated MCP server template quality."""

from selqor_forge.templates import rust_main, ts_index, ts_env_example, ts_package_json


def test_ts_index_contains_resilience_features():
    code = ts_index("stdio")
    # Retry logic
    assert "MAX_RETRIES" in code
    assert "RETRY_BASE_MS" in code
    assert "Math.pow(2, attempt" in code

    # Circuit breaker
    assert "circuitCheck" in code
    assert "circuitSuccess" in code
    assert "circuitFailure" in code
    assert "CB_FAILURE_THRESHOLD" in code
    assert "CB_RESET_MS" in code
    assert '"closed"' in code
    assert '"open"' in code
    assert '"half_open"' in code

    # Configurable timeout via AbortController
    assert "AbortController" in code
    assert "REQUEST_TIMEOUT_MS" in code
    assert "controller.abort()" in code

    # Structured logging
    assert "function log(" in code
    assert "JSON.stringify(entry)" in code

    # Health endpoint
    assert '"/health"' in code
    assert "uptime_seconds" in code
    assert "circuit_breaker" in code

    # Graceful shutdown
    assert "SIGTERM" in code
    assert "SIGINT" in code
    assert "shutdown" in code

    # Retryable status codes
    assert "429" in code
    assert ">= 500" in code

    # HTTP hardening
    assert "validateConfiguredUrl" in code
    assert "validateRelativePath" in code
    assert "FORGE_HTTP_AUTH_TOKEN is required when FORGE_TRANSPORT=http" in code
    assert "createRateLimiter" in code
    assert 'app.get("/sse", rateLimiter, requireHttpAuth' in code
    assert 'app.post("/messages", rateLimiter, requireHttpAuth' in code
    assert 'app.get("/health", rateLimiter' in code
    assert 'fetch(targetApiUrl.toString()' in code
    assert 'fetch(tokenEndpoint.href' in code
    assert 'fetch(oauthEndpoint.href' in code

    # search_api should be discovery-only and direct users to the overflow executor
    assert 'if (tool.name === "search_api")' in code
    assert '"search_api requires query"' in code
    assert "findSearchMatches" in code
    assert "Call execute_overflow_operation with one of the returned operation ids to execute it." in code
    assert 'const limit = getInteger(args.limit) ?? 10;' in code
    assert 'tool.covered_endpoints.length === 1' in code
    assert 'Tool ${tool.name} requires an explicit operation' in code


def test_ts_index_default_transport_substitution():
    stdio = ts_index("stdio")
    assert 'const defaultTransport = "stdio"' in stdio

    http = ts_index("http")
    assert 'const defaultTransport = "http"' in http


def test_ts_env_example_contains_resilience_vars():
    env = ts_env_example()
    assert "FORGE_REQUEST_TIMEOUT_MS" in env
    assert "FORGE_MAX_RETRIES" in env
    assert "FORGE_RETRY_BASE_MS" in env
    assert "FORGE_CB_FAILURE_THRESHOLD" in env
    assert "FORGE_CB_RESET_MS" in env
    assert "FORGE_HTTP_AUTH_TOKEN" in env
    assert "FORGE_HTTP_RATE_LIMIT_WINDOW_MS" in env
    assert "FORGE_HTTP_RATE_LIMIT_MAX" in env
    assert "FORGE_ALLOW_PRIVATE_HOSTS" in env


def test_ts_package_json_valid():
    import json
    pkg = json.loads(ts_package_json())
    assert pkg["dependencies"]["@modelcontextprotocol/sdk"] == "1.29.0"
    assert pkg["dependencies"]["express"] == "4.22.1"
    assert pkg["devDependencies"]["tsx"] == "4.20.5"


def test_rust_main_contains_search_api_guardrails():
    code = rust_main("stdio")
    assert 'if tool_name == "search_api"' in code
    assert 'context("search_api requires query")' in code
    assert "find_search_matches" in code
    assert "Call execute_overflow_operation with one of the returned operation ids to execute it." in code
    assert 'if tool.covered_endpoints.len() == 1' in code
    assert 'requires an explicit operation' in code

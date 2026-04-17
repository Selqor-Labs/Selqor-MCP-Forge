# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for generated MCP server template quality."""

from selqor_forge.templates import ts_index, ts_env_example, ts_package_json


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


def test_ts_package_json_valid():
    import json
    pkg = json.loads(ts_package_json())
    assert "@modelcontextprotocol/sdk" in pkg["dependencies"]
    assert "express" in pkg["dependencies"]
    assert "tsx" in pkg["devDependencies"]

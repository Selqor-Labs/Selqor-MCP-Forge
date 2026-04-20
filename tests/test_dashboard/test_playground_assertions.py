# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Playground assertion engine."""

from selqor_forge.dashboard.playground_assertions import (
    evaluate_all,
    evaluate_assertion,
    resolve_path,
    validate_assertions,
)


def test_resolve_path_dotted_and_indexed():
    obj = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert resolve_path(obj, "a.b[0].c") == 1
    assert resolve_path(obj, "a.b[1].c") == 2


def test_resolve_path_missing_returns_sentinel_not_none():
    obj = {"a": {"b": None}}
    # path exists but is None
    got = resolve_path(obj, "a.b")
    assert got is None
    # path missing
    missing = resolve_path(obj, "a.c")
    assert missing is not None  # sentinel, not None


def test_equals_op_pass_and_fail():
    result = {"content": [{"type": "text", "text": "hello"}]}
    ok = evaluate_assertion(
        {"op": "equals", "path": "content[0].text", "value": "hello"},
        result=result, status="success", latency_ms=12,
    )
    assert ok["passed"] is True

    fail = evaluate_assertion(
        {"op": "equals", "path": "content[0].text", "value": "nope"},
        result=result, status="success", latency_ms=12,
    )
    assert fail["passed"] is False
    assert "!= 'nope'" in fail["message"] or "!=" in fail["message"]


def test_contains_on_string_and_list():
    result = {"items": ["alpha", "beta"], "blurb": "hello world"}
    string_case = evaluate_assertion({"op": "contains", "path": "blurb", "value": "world"},
                                     result=result, status="success", latency_ms=1)
    assert string_case["passed"] is True
    list_case = evaluate_assertion({"op": "contains", "path": "items", "value": "beta"},
                                   result=result, status="success", latency_ms=1)
    assert list_case["passed"] is True


def test_exists_and_not_exists():
    result = {"a": 1, "b": None}
    assert evaluate_assertion({"op": "exists", "path": "a"}, result=result,
                              status="success", latency_ms=None)["passed"]
    # null value counts as not-existing for `exists` (intentional — null is rarely meaningful)
    assert not evaluate_assertion({"op": "exists", "path": "b"}, result=result,
                                  status="success", latency_ms=None)["passed"]
    assert evaluate_assertion({"op": "not_exists", "path": "c"}, result=result,
                              status="success", latency_ms=None)["passed"]


def test_type_assertion():
    result = {"count": 5, "flag": True, "items": []}
    assert evaluate_assertion({"op": "type", "path": "count", "value": "number"},
                              result=result, status="success", latency_ms=None)["passed"]
    assert evaluate_assertion({"op": "type", "path": "flag", "value": "bool"},
                              result=result, status="success", latency_ms=None)["passed"]
    assert evaluate_assertion({"op": "type", "path": "items", "value": "array"},
                              result=result, status="success", latency_ms=None)["passed"]


def test_status_is_and_latency_lt():
    ok = evaluate_assertion({"op": "status_is", "value": "success"},
                            result={}, status="success", latency_ms=20)
    assert ok["passed"] is True
    fail = evaluate_assertion({"op": "latency_lt", "value": 10},
                              result={}, status="success", latency_ms=42)
    assert fail["passed"] is False
    pass_lat = evaluate_assertion({"op": "latency_lt", "value": 100},
                                  result={}, status="success", latency_ms=42)
    assert pass_lat["passed"] is True


def test_text_includes_on_mcp_content():
    result = {
        "content": [
            {"type": "text", "text": "pet #1: Spot"},
            {"type": "text", "text": "pet #2: Rex"},
        ]
    }
    ok = evaluate_assertion({"op": "text_includes", "value": "Rex"},
                            result=result, status="success", latency_ms=None)
    assert ok["passed"] is True
    fail = evaluate_assertion({"op": "text_includes", "value": "Whiskers"},
                              result=result, status="success", latency_ms=None)
    assert fail["passed"] is False


def test_regex_op():
    result = {"msg": "order-12345"}
    ok = evaluate_assertion({"op": "regex", "path": "msg", "value": r"^order-\d+$"},
                            result=result, status="success", latency_ms=None)
    assert ok["passed"] is True
    bad = evaluate_assertion({"op": "regex", "path": "msg", "value": r"^\d+$"},
                             result=result, status="success", latency_ms=None)
    assert bad["passed"] is False


def test_evaluate_all_empty_assertions_passes_on_success():
    status, outcomes = evaluate_all([], result={}, status="success", latency_ms=1)
    assert status == "pass"
    assert outcomes == []

    status, _ = evaluate_all([], result={}, status="error", latency_ms=1)
    assert status == "fail"


def test_evaluate_all_requires_every_assertion_to_pass():
    result = {"a": 1}
    status, outcomes = evaluate_all([
        {"op": "exists", "path": "a"},
        {"op": "equals", "path": "a", "value": 999},
    ], result=result, status="success", latency_ms=1)
    assert status == "fail"
    assert outcomes[0]["passed"] is True
    assert outcomes[1]["passed"] is False


def test_validate_assertions_filters_unknown_ops():
    raw = [
        {"op": "equals", "path": "x", "value": 1},
        {"op": "bogus", "path": "y"},
        {"nonsense": True},
        {"op": "regex", "path": "z", "value": "foo"},
    ]
    cleaned = validate_assertions(raw)
    assert len(cleaned) == 2
    assert {c["op"] for c in cleaned} == {"equals", "regex"}


def test_unknown_op_produces_diagnostic():
    out = evaluate_assertion({"op": "no_such"}, result={}, status="success", latency_ms=None)
    assert out["passed"] is False
    assert "unknown" in out["message"].lower()

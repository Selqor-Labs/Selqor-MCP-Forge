# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Assertion engine for Playground test cases.

Each assertion is a small dict ``{"op": "equals", "path": "content[0].text",
"value": "ok"}``. Evaluating an assertion against a tool-call result returns a
structured outcome that is stored verbatim in ``PlaygroundTestRun.assertion_results``
and surfaced to the UI.

Supported ops (kept deliberately small — this is *not* a jq reimplementation):
  - ``equals``            — ``path`` value deep-equals ``value``
  - ``contains``          — ``path`` (string) or list contains ``value``
  - ``exists``            — ``path`` resolves to a non-null value
  - ``not_exists``        — ``path`` does not resolve (or is null)
  - ``regex``             — ``path`` matches ``value`` (treated as regex)
  - ``type``              — ``path`` is of ``value`` (``"string"|"number"|"bool"|"array"|"object"|"null"``)
  - ``status_is``         — top-level execution status (``"success"|"error"``) equals ``value``
  - ``latency_lt``        — execution ``latency_ms`` less than numeric ``value``
  - ``text_includes``     — convenience for MCP ``content[*].text`` — any text block contains ``value``

Path syntax: dot-separated keys with optional ``[index]``. E.g. ``content[0].text``
or ``structuredContent.items[2].name``.
"""
from __future__ import annotations

import json
import re
from typing import Any

_SENTINEL = object()


def resolve_path(obj: Any, path: str) -> Any:
    """Walk ``obj`` along ``path``. Returns ``_SENTINEL`` if anything is missing.

    We use a sentinel instead of ``None`` because ``None`` is a legal value that
    callers may want to assert on with ``equals: null``.
    """
    if not path:
        return obj
    # Tokenise:  a.b[0].c  ->  ["a", "b", 0, "c"]
    tokens: list[str | int] = []
    for segment in path.split("."):
        if not segment:
            continue
        # pull off trailing [N][M] groups
        bracket_matches = re.findall(r"\[(-?\d+)\]", segment)
        name = re.sub(r"\[-?\d+\]", "", segment)
        if name:
            tokens.append(name)
        for idx in bracket_matches:
            tokens.append(int(idx))

    cur = obj
    for tok in tokens:
        if isinstance(tok, int):
            if not isinstance(cur, list):
                return _SENTINEL
            if tok < 0 or tok >= len(cur):
                return _SENTINEL
            cur = cur[tok]
        else:
            if not isinstance(cur, dict):
                return _SENTINEL
            if tok not in cur:
                return _SENTINEL
            cur = cur[tok]
    return cur


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _iter_text_blocks(result: Any) -> list[str]:
    """Extract text from MCP-style ``content[{type:'text',text:'…'}]`` blocks."""
    if not isinstance(result, dict):
        return []
    content = result.get("content")
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                out.append(t)
    return out


def evaluate_assertion(
    assertion: dict,
    *,
    result: Any,
    status: str,
    latency_ms: float | None,
) -> dict:
    """Evaluate a single assertion. Returns ``{op, path, expected, actual, passed, message}``."""
    op = (assertion or {}).get("op", "")
    path = assertion.get("path", "") or ""
    expected = assertion.get("value", None)

    outcome = {
        "op": op,
        "path": path,
        "expected": expected,
        "actual": None,
        "passed": False,
        "message": "",
    }

    try:
        if op == "status_is":
            outcome["actual"] = status
            outcome["passed"] = status == expected
            if not outcome["passed"]:
                outcome["message"] = f"status was '{status}', expected '{expected}'"
            return outcome

        if op == "latency_lt":
            outcome["actual"] = latency_ms
            try:
                bound = float(expected)
            except (TypeError, ValueError):
                outcome["message"] = f"expected numeric bound, got {expected!r}"
                return outcome
            if latency_ms is None:
                outcome["message"] = "no latency recorded"
                return outcome
            outcome["passed"] = latency_ms < bound
            if not outcome["passed"]:
                outcome["message"] = f"{latency_ms}ms >= {bound}ms"
            return outcome

        if op == "text_includes":
            texts = _iter_text_blocks(result)
            outcome["actual"] = texts
            needle = str(expected)
            outcome["passed"] = any(needle in t for t in texts)
            if not outcome["passed"]:
                outcome["message"] = (
                    f"no text block contained {needle!r}"
                    if texts else "no text content blocks in result"
                )
            return outcome

        actual = resolve_path(result, path)
        if op == "exists":
            outcome["actual"] = None if actual is _SENTINEL else actual
            outcome["passed"] = actual is not _SENTINEL and actual is not None
            if not outcome["passed"]:
                outcome["message"] = f"path '{path}' missing or null"
            return outcome

        if op == "not_exists":
            outcome["actual"] = None if actual is _SENTINEL else actual
            outcome["passed"] = actual is _SENTINEL or actual is None
            if not outcome["passed"]:
                outcome["message"] = f"path '{path}' was present"
            return outcome

        if actual is _SENTINEL:
            outcome["actual"] = None
            outcome["message"] = f"path '{path}' not found in result"
            return outcome

        outcome["actual"] = actual

        if op == "equals":
            outcome["passed"] = actual == expected
            if not outcome["passed"]:
                outcome["message"] = f"{actual!r} != {expected!r}"
            return outcome

        if op == "contains":
            if isinstance(actual, str):
                outcome["passed"] = str(expected) in actual
            elif isinstance(actual, list):
                outcome["passed"] = expected in actual
            else:
                outcome["message"] = f"path '{path}' is {_type_of(actual)}, cannot use 'contains'"
                return outcome
            if not outcome["passed"]:
                outcome["message"] = f"{expected!r} not in value at '{path}'"
            return outcome

        if op == "regex":
            if not isinstance(actual, str):
                outcome["message"] = f"path '{path}' is {_type_of(actual)}, regex needs string"
                return outcome
            try:
                outcome["passed"] = re.search(str(expected), actual) is not None
            except re.error as exc:
                outcome["message"] = f"bad regex: {exc}"
                return outcome
            if not outcome["passed"]:
                outcome["message"] = f"value did not match /{expected}/"
            return outcome

        if op == "type":
            actual_type = _type_of(actual)
            outcome["actual"] = actual_type
            outcome["passed"] = actual_type == str(expected)
            if not outcome["passed"]:
                outcome["message"] = f"type was '{actual_type}', expected '{expected}'"
            return outcome

        outcome["message"] = f"unknown assertion op '{op}'"
        return outcome

    except Exception as exc:  # never let a bad assertion crash the whole run
        outcome["message"] = f"assertion raised: {exc}"
        return outcome


def evaluate_all(
    assertions: list[dict],
    *,
    result: Any,
    status: str,
    latency_ms: float | None,
) -> tuple[str, list[dict]]:
    """Evaluate every assertion. Returns ``(overall_status, per_assertion)``."""
    outcomes = [
        evaluate_assertion(a, result=result, status=status, latency_ms=latency_ms)
        for a in (assertions or [])
    ]
    if not outcomes:
        # No assertions defined — a pass iff the tool call itself succeeded.
        return ("pass" if status == "success" else "fail", outcomes)
    all_passed = all(o.get("passed") for o in outcomes)
    return ("pass" if all_passed else "fail", outcomes)


# --- small helpers used by the route layer -------------------------------------

def normalize_assertion(raw: Any) -> dict:
    """Coerce user input into the canonical assertion shape."""
    if not isinstance(raw, dict):
        return {"op": "", "path": "", "value": None}
    op = (raw.get("op") or "").strip()
    path = (raw.get("path") or "").strip()
    value = raw.get("value", None)
    out: dict = {"op": op, "path": path, "value": value}
    return out


def validate_assertions(raw_list: Any) -> list[dict]:
    """Normalize and return only assertions with a known op."""
    if not isinstance(raw_list, list):
        return []
    valid_ops = {
        "equals", "contains", "exists", "not_exists", "regex", "type",
        "status_is", "latency_lt", "text_includes",
    }
    out: list[dict] = []
    for item in raw_list:
        norm = normalize_assertion(item)
        if norm["op"] in valid_ops:
            out.append(norm)
    return out


def ensure_jsonable(value: Any) -> Any:
    """Coerce values that might contain sentinels/objects into JSON-serialisable form."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)

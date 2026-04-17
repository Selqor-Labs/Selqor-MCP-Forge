# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard static asset routing tests."""

import re
from pathlib import Path

import pytest

_DIST_INDEX = (
    Path(__file__).resolve().parents[2]
    / "src" / "dashboard" / "frontend" / "dist" / "index.html"
)
_frontend_built = _DIST_INDEX.is_file()


@pytest.mark.skipif(not _frontend_built, reason="Frontend dist not built")
def test_dashboard_serves_frontend_index(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "Selqor Forge" in resp.text


@pytest.mark.skipif(not _frontend_built, reason="Frontend dist not built")
def test_dashboard_serves_frontend_bundle_from_index(client):
    index = client.get("/")
    assert index.status_code == 200
    match = re.search(r'src="([^"]+index-[^"]+\.js)"', index.text)
    assert match is not None

    bundle = client.get(match.group(1))

    assert bundle.status_code == 200
    assert "javascript" in bundle.headers["content-type"]


def test_dashboard_serves_logo_assets(client):
    resp = client.get("/assets/selqor-symbol.svg")

    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]

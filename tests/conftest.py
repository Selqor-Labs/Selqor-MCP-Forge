# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Shared pytest fixtures."""

import os
import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_env():
    """Clear DB/MinIO env vars so tests use filesystem mode only."""
    clear = [
        "DATABASE_URL", "POSTGRES_URL", "POSTGRES_DSN",
        "PGHOST", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGPORT",
        "POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD",
        "POSTGRES_DB", "POSTGRES_DATABASE", "POSTGRES_PORT",
        "MINIO_ENDPOINT", "S3_ENDPOINT", "AWS_ENDPOINT_URL",
        "MINIO_BUCKET", "S3_BUCKET",
        "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "FORGE_SECRET_KEY",
    ]
    saved = {k: os.environ.pop(k) for k in clear if k in os.environ}
    yield
    os.environ.update(saved)


@pytest.fixture()
def tmp_state_dir():
    """Provide a fresh temporary state directory per test."""
    root = Path.cwd() / ".tmp-tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"sf_test_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

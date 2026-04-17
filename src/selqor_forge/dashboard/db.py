# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Database session management and utilities."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from selqor_forge.dashboard.models import Base


_DEFAULT_CONNECT_TIMEOUT_SECONDS = 30


def get_database_url() -> str | None:
    """Get the database URL from environment variables."""
    url = os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql://"):
        # Convert to psycopg3 dialect
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _connect_timeout_seconds() -> int:
    raw_value = os.environ.get("FORGE_DB_CONNECT_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return _DEFAULT_CONNECT_TIMEOUT_SECONDS
    try:
        return max(1, int(raw_value))
    except ValueError:
        return _DEFAULT_CONNECT_TIMEOUT_SECONDS


def _sqlite_url(state_dir: Path) -> str:
    state_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = state_dir / "selqor-forge.db"
    return f"sqlite:///{sqlite_path.as_posix()}"


def _build_engine(url: str):
    engine_kwargs: dict[str, object] = {"echo": False}
    if url.startswith("sqlite:///"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_recycle"] = 3600
        engine_kwargs["connect_args"] = {
            "connect_timeout": _connect_timeout_seconds(),
        }

    engine = create_engine(url, **engine_kwargs)

    if url.startswith("sqlite:///"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def _create_session_factory(url: str, logger: logging.Logger) -> sessionmaker[Session]:
    engine = _build_engine(url)

    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    # Drop legacy (non-prefixed) table names if they still exist
    if not url.startswith("sqlite:///"):
        try:
            with engine.begin() as conn:
                legacy_drops = [
                    "DROP TABLE IF EXISTS deployment_records CASCADE",
                    "DROP TABLE IF EXISTS llm_logs CASCADE",
                    "DROP TABLE IF EXISTS llm_configs CASCADE",
                    "DROP TABLE IF EXISTS integration_auth_configs CASCADE",
                    "DROP TABLE IF EXISTS integration_tool_configs CASCADE",
                    "DROP TABLE IF EXISTS artifacts CASCADE",
                    "DROP TABLE IF EXISTS runs CASCADE",
                    "DROP TABLE IF EXISTS integrations CASCADE",
                    "DROP TABLE IF EXISTS org_members CASCADE",
                    "DROP TABLE IF EXISTS organizations CASCADE",
                ]
                for stmt in legacy_drops:
                    try:
                        conn.execute(text(stmt))
                    except Exception:
                        pass
            logger.debug("Cleaned up legacy table names")
        except Exception as e:
            logger.debug(f"Could not drop legacy tables: {e}")

    # Create sf_ tables if they don't exist (non-destructive)
    Base.metadata.create_all(engine)

    # Apply lightweight schema migrations (add columns, relax constraints)
    _apply_sqlite_migrations(engine, logger)
    if not url.startswith("sqlite:///"):
        _apply_column_migrations(engine, logger)

    logger.info("Database initialized with SQLAlchemy ORM")
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(
    url: str | None = None,
    *,
    state_dir: Path | None = None,
) -> sessionmaker[Session] | None:
    """Initialize database engine and return session factory.

    Uses PostgreSQL when configured, otherwise falls back to an embedded SQLite
    database inside the dashboard state directory.
    """
    logger = logging.getLogger(__name__)

    if url is None:
        url = get_database_url()

    if not url:
        if state_dir is None:
            logger.info("No database configured and no state dir available")
            return None
        url = _sqlite_url(state_dir)
        logger.info("PostgreSQL not configured; using embedded SQLite in %s", state_dir)

    try:
        return _create_session_factory(url, logger)
    except Exception as e:
        if state_dir is not None and not url.startswith("sqlite:///"):
            fallback_url = _sqlite_url(state_dir)
            logger.warning(
                "Failed to initialize configured database: %s; falling back to embedded SQLite in %s",
                e,
                state_dir,
            )
            try:
                return _create_session_factory(fallback_url, logger)
            except Exception as fallback_error:
                logger.warning(
                    "Failed to initialize embedded SQLite fallback: %s; falling back to file-based storage",
                    fallback_error,
                )
                return None
        logger.warning(f"Failed to initialize database: {e}; falling back to file-based storage")
        return None


def _apply_sqlite_migrations(engine, logger) -> None:
    """Apply SQLite-compatible schema migrations.

    SQLite doesn't support ALTER COLUMN, so we recreate tables when
    constraints need changing. For now, we handle this by recreating
    the sf_llm_logs table if integration_id has a NOT NULL constraint.
    """
    from sqlalchemy import inspect as sa_inspect

    try:
        insp = sa_inspect(engine)
        if "sf_llm_logs" in insp.get_table_names():
            columns = {c["name"]: c for c in insp.get_columns("sf_llm_logs")}
            int_id_col = columns.get("integration_id")
            if int_id_col and int_id_col.get("nullable") is False:
                logger.info("Migrating sf_llm_logs: making integration_id nullable")
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE sf_llm_logs RENAME TO _sf_llm_logs_old"))
                    # Recreate with the correct schema from models
                    Base.metadata.tables["sf_llm_logs"].create(conn)
                    conn.execute(text(
                        "INSERT INTO sf_llm_logs SELECT * FROM _sf_llm_logs_old"
                    ))
                    conn.execute(text("DROP TABLE _sf_llm_logs_old"))
                logger.info("sf_llm_logs migration complete")

        # Add missing columns (github_id, avatar_url on sf_dashboard_users)
        if "sf_dashboard_users" in insp.get_table_names():
            existing = {c["name"] for c in insp.get_columns("sf_dashboard_users")}
            for col_name, col_def in [
                ("github_id", "TEXT"),
                ("avatar_url", "TEXT"),
            ]:
                if col_name not in existing:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE sf_dashboard_users ADD COLUMN {col_name} {col_def}"))
                    logger.info("Added column %s to sf_dashboard_users", col_name)

        # Playground executions: add raw_rpc / origin for trace + attribution
        if "sf_playground_executions" in insp.get_table_names():
            existing = {c["name"] for c in insp.get_columns("sf_playground_executions")}
            for col_name, col_def in [
                ("raw_rpc", "JSON"),
                ("origin", "TEXT DEFAULT 'manual'"),
            ]:
                if col_name not in existing:
                    with engine.begin() as conn:
                        conn.execute(text(
                            f"ALTER TABLE sf_playground_executions ADD COLUMN {col_name} {col_def}"
                        ))
                    logger.info("Added column %s to sf_playground_executions", col_name)

    except Exception as e:
        logger.debug("SQLite migration skipped: %s", e)


def _apply_column_migrations(engine, logger) -> None:
    """Add missing columns to existing tables. Each ALTER is idempotent."""
    migrations = [
        ("sf_integrations", "specs", "JSONB DEFAULT '[]'::jsonb"),
        ("sf_integrations", "agent_prompt", "TEXT"),
        ("sf_playground_executions", "raw_rpc", "JSONB"),
        ("sf_playground_executions", "origin", "TEXT DEFAULT 'manual'"),
    ]
    with engine.begin() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
                ))
            except Exception as e:
                logger.debug("Migration %s.%s skipped: %s", table, column, e)


def get_session(session_factory: sessionmaker[Session] | None) -> Generator[Session, None, None]:
    """Dependency for FastAPI to provide database sessions."""
    if session_factory is None:
        yield None
    else:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

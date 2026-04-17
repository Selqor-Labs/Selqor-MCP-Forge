# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application factory and server entry-point for the Selqor Forge dashboard."""

from __future__ import annotations

import logging
import os
import sys
from ipaddress import ip_address
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from selqor_forge.config import AppConfig
from selqor_forge.dashboard.context import DashboardContext
from selqor_forge.dashboard.db import init_db
from selqor_forge.dashboard.middleware import is_auth_placeholder_active
from selqor_forge.dashboard.secrets import DashboardSecretManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths relative to the project root
# ---------------------------------------------------------------------------

# Frontend and assets directories
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # src/selqor_forge/dashboard -> repo root
_REACT_DIST_DIR = _PROJECT_ROOT / "src" / "dashboard" / "frontend" / "dist"
_LOGOS_DIR = _PROJECT_ROOT / "selqorLogos"


# ---------------------------------------------------------------------------
# Environment helpers (mirrors Rust first_env_value)
# ---------------------------------------------------------------------------


def _first_env(*keys: str) -> str | None:
    """Return the first non-empty env-var value from *keys*, or ``None``."""
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


# ---------------------------------------------------------------------------
# Postgres initialisation
# ---------------------------------------------------------------------------


def _init_postgres() -> object | None:
    """Create a psycopg connection pool if a Postgres DSN is available.

    Returns a :class:`psycopg_pool.ConnectionPool` or ``None``.
    """
    dsn = _first_env("DATABASE_URL", "POSTGRES_URL", "POSTGRES_DSN")

    host = _first_env("PGHOST", "POSTGRES_HOST")
    user = _first_env("PGUSER", "POSTGRES_USER")
    database = _first_env("PGDATABASE", "POSTGRES_DB", "POSTGRES_DATABASE")
    password = _first_env("PGPASSWORD", "POSTGRES_PASSWORD")
    port = _first_env("PGPORT", "POSTGRES_PORT") or "5432"
    sslmode = _first_env("PGSSLMODE", "POSTGRES_SSLMODE")

    has_partial = any(v is not None for v in (host, user, database, password))

    if dsn is None and not has_partial:
        logger.info("PostgreSQL not configured; using local metadata storage")
        return None

    if dsn is None:
        # Build a libpq-style DSN from individual variables.
        if not host:
            raise RuntimeError("PGHOST (or POSTGRES_HOST) is required when DATABASE_URL is not set")
        if not user:
            raise RuntimeError("PGUSER (or POSTGRES_USER) is required when DATABASE_URL is not set")
        if not database:
            raise RuntimeError(
                "PGDATABASE (or POSTGRES_DB/POSTGRES_DATABASE) is required when DATABASE_URL is not set"
            )

        dsn = f"host={host} port={port} user={user} dbname={database}"
        if password:
            dsn += f" password={password}"
        if sslmode:
            dsn += f" sslmode={sslmode}"

    try:
        from psycopg_pool import ConnectionPool  # type: ignore[import-untyped]

        pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=4, open=True)
        logger.info("PostgreSQL metadata store initialised")
        return pool
    except Exception:
        logger.exception("Failed to connect to PostgreSQL -- falling back to file storage")
        return None


# ---------------------------------------------------------------------------
# MinIO / S3 initialisation
# ---------------------------------------------------------------------------


def _init_minio() -> tuple[object | None, str | None, str]:
    """Create a boto3 S3 client if MinIO/S3 environment variables are set.

    Returns ``(client_or_None, bucket_or_None, key_prefix)``.
    """
    endpoint = _first_env("MINIO_ENDPOINT", "S3_ENDPOINT", "AWS_ENDPOINT_URL")
    bucket = _first_env("MINIO_BUCKET", "S3_BUCKET")
    access_key = _first_env("MINIO_ACCESS_KEY", "AWS_ACCESS_KEY_ID")
    secret_key = _first_env("MINIO_SECRET_KEY", "AWS_SECRET_ACCESS_KEY")
    region = _first_env("MINIO_REGION", "AWS_REGION") or "us-east-1"
    prefix = _first_env("MINIO_PREFIX") or "selqor-forge"

    has_partial = any(v is not None for v in (endpoint, bucket, access_key, secret_key))
    if not has_partial:
        logger.info("MinIO not configured; using filesystem artifact storage")
        return None, None, prefix

    if not endpoint:
        raise RuntimeError("MINIO_ENDPOINT is required when other S3/MinIO vars are set")
    if not bucket:
        raise RuntimeError("MINIO_BUCKET is required")
    if not access_key:
        raise RuntimeError("MINIO_ACCESS_KEY is required")
    if not secret_key:
        raise RuntimeError("MINIO_SECRET_KEY is required")

    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = f"http://{endpoint}"

    try:
        import boto3  # type: ignore[import-untyped]

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        logger.info("MinIO object store initialised (bucket=%s, prefix=%s)", bucket, prefix)
        return client, bucket, prefix
    except Exception:
        logger.exception("Failed to initialise MinIO client -- falling back to filesystem storage")
        return None, None, prefix


# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------


def _validate_environment() -> dict[str, str]:
    """Validate required and optional environment variables at startup.

    Returns a dict of environment status info for health checks.
    """
    status = {}

    # LLM configuration (database-driven)
    # NOTE: LLM configuration is now entirely database-driven via the dashboard LLM Config screen.
    # ANTHROPIC_API_KEY environment variable is no longer used or required.
    # Actual LLM availability is determined at runtime based on database configuration.
    # At startup, we simply note that LLM is configured via database, not environment.
    status["llm_configured"] = "database-driven"
    logger.info("LLM: Configuration is database-driven (configured via dashboard LLM Config screen)")

    # Check storage configuration
    has_postgres = _first_env("DATABASE_URL", "POSTGRES_HOST") is not None
    status["postgres_configured"] = has_postgres

    has_minio = _first_env("MINIO_ENDPOINT") is not None
    status["minio_configured"] = has_minio

    if has_postgres:
        logger.info("Storage: PostgreSQL configured")
    else:
        logger.info("Storage: Using local file storage")

    if has_minio:
        logger.info("Artifacts: Using MinIO/S3")
    else:
        logger.info("Artifacts: Using filesystem storage")

    return status


# ---------------------------------------------------------------------------
# DB seeding (placeholder)
# ---------------------------------------------------------------------------


def _seed_db_from_files(ctx: DashboardContext) -> None:
    """Seed PostgreSQL metadata from local JSON files.

    Mirrors the Rust ``seed_db_from_files`` function.  The actual SQL
    upsert logic will live in a dedicated persistence module; this stub
    ensures the call-site exists in the lifespan.
    """
    logger.info("Seeding PostgreSQL metadata from filesystem state (stub)")
    # TODO: implement full file-to-DB seeding once persistence module is ported.


# ---------------------------------------------------------------------------
# Logo / asset route mapping
# ---------------------------------------------------------------------------

# Maps URL path suffix -> file on disk inside selqorLogos/.
_SVG_ASSET_MAP: dict[str, str] = {
    "selqor-dark.svg": "selqor-labs-dark.svg",
    "selqor-light.svg": "selqor-labs-light.svg",
    "selqor-symbol-dark.svg": "selqor-symbol-dark.svg",
    "selqor-symbol-light.svg": "selqor-symbol-light.svg",
    "selqor-symbol.svg": "selqor-symbol.svg",
    "selqor-mark-dark.svg": "selqor-mark-dark.svg",
    "selqor-mark-light.svg": "selqor-mark-light.svg",
    "selqor-symbol-one-dark.svg": "selqor-symbol-one-dark.svg",
    "selqor-symbol-one-light.svg": "selqor-symbol-one-light.svg",
    "selqor-symbol-two-dark.svg": "selqor-symbol-two-dark.svg",
    "selqor-symbol-two-light.svg": "selqor-symbol-two-light.svg",
    "selqor-symbol-three-dark.svg": "selqor-symbol-three-dark.svg",
    "selqor-symbol-three-light.svg": "selqor-symbol-three-light.svg",
    "selqor-symbol-four-dark.svg": "selqor-symbol-four-dark.svg",
    "selqor-symbol-four-light.svg": "selqor-symbol-four-light.svg",
}

# PNG aliases -- multiple URL paths can map to the same file.
_PNG_ASSET_MAP: dict[str, str] = {
    "selqorSymbol.png": "selqorSymbol-light.png",
    "selqor-symbol.png": "selqorSymbol-light.png",
    "selqorSymbol-light.png": "selqorSymbol-light.png",
    "selqor-symbol-light.png": "selqorSymbol-light.png",
    "selqorSymbol-dark.png": "selqorSymbol-dark.png",
    "selqor-symbol-dark.png": "selqorSymbol-dark.png",
}


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _collect_local_dev_risks(
    *,
    bind_host: str,
    secret_manager: DashboardSecretManager,
    cors_allow_origins: list[str],
) -> dict[str, bool]:
    return {
        "non_loopback_bind": not _is_loopback_host(bind_host),
        "placeholder_auth": is_auth_placeholder_active(),
        "auto_generated_secret_key": secret_manager.auto_generated_this_run,
        "wildcard_cors": "*" in cors_allow_origins,
    }


def _print_local_dev_banner(risks: dict[str, bool]) -> None:
    if not any(risks.values()):
        return

    reasons = []
    if risks.get("non_loopback_bind"):
        reasons.append("bound to a non-loopback host")
    if risks.get("placeholder_auth"):
        reasons.append("dashboard auth is still the placeholder hook")
    if risks.get("auto_generated_secret_key"):
        reasons.append("FORGE_SECRET_KEY was auto-generated for this run")
    if risks.get("wildcard_cors"):
        reasons.append("CORS allow-origins is *")

    color = "\033[91m" if risks.get("non_loopback_bind") or risks.get("placeholder_auth") else "\033[93m"
    reset = "\033[0m"
    line = "=" * 108
    message = (
        "Dashboard running in LOCAL DEV mode. Do not expose to untrusted networks without configuring auth "
        "- see docs/AUTH_MODULE_INTEGRATION.md"
    )
    sys.stdout.write(
        f"{color}{line}\n"
        f"{message}\n"
        f"Safety checks triggered: {', '.join(reasons)}\n"
        f"{line}{reset}\n"
    )
    sys.stdout.flush()


def _resolve_cors_origins() -> list[str]:
    """Resolve CORS origins from environment or defaults.

    Priority:
    1. ``FORGE_CORS_ORIGINS`` env var (comma-separated list of origins)
    2. Default dev-friendly origins when not in production
    3. Wildcard ``*`` only when neither env var nor production mode is set
    """
    env_origins = os.environ.get("FORGE_CORS_ORIGINS", "").strip()
    if env_origins:
        return [o.strip() for o in env_origins.split(",") if o.strip()]

    is_production = os.environ.get("FORGE_PRODUCTION", "").strip().lower() in ("true", "1", "yes")
    if is_production:
        # In production, CORS must be explicitly configured
        logger.warning(
            "FORGE_CORS_ORIGINS not set in production mode. CORS will only allow same-origin requests. "
            "Set FORGE_CORS_ORIGINS to your domain(s) to allow cross-origin requests."
        )
        return []

    # Development defaults — allow common local dev origins
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:8787",
        "http://localhost:9780",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:8787",
        "http://127.0.0.1:9780",
    ]


def _validate_production_secrets(state_dir: Path) -> None:
    """Fail fast if production mode is enabled without required secrets."""
    is_production = os.environ.get("FORGE_PRODUCTION", "").strip().lower() in ("true", "1", "yes")
    if not is_production:
        return

    if not os.environ.get("FORGE_SECRET_KEY", "").strip():
        raise RuntimeError(
            "FORGE_SECRET_KEY is required in production mode. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    logger.info("Production mode: FORGE_SECRET_KEY verified")


def create_app(state_dir: Path, config: AppConfig, *, bind_host: str = "127.0.0.1") -> FastAPI:
    """Build and return the fully-configured :class:`FastAPI` application."""
    frontend_index = _REACT_DIST_DIR / "index.html"
    _validate_production_secrets(state_dir)
    cors_allow_origins = _resolve_cors_origins()

    def _frontend_not_built_response() -> HTMLResponse:
        body = """
        <html>
          <head><title>Selqor Forge Dashboard</title></head>
          <body style="font-family: sans-serif; max-width: 760px; margin: 3rem auto; line-height: 1.6;">
            <h1>Dashboard assets are not built</h1>
            <p>Build the frontend once from the repository root before starting the dashboard UI:</p>
            <pre>cd src/dashboard/frontend
npm ci
npm run build</pre>
            <p>After the build completes, refresh this page.</p>
          </body>
        </html>
        """
        return HTMLResponse(content=body, status_code=503)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        secret_manager = DashboardSecretManager.from_environment(state_dir)
        local_dev_risks = _collect_local_dev_risks(
            bind_host=bind_host,
            secret_manager=secret_manager,
            cors_allow_origins=cors_allow_origins,
        )
        _print_local_dev_banner(local_dev_risks)
        app.state.local_dev_risks = local_dev_risks

        # 1. Validate environment configuration
        env_status = _validate_environment()
        app.state.env_status = env_status

        # 2. State directory info
        logger.info("State directory: %s", state_dir)

        # 3. Initialise SQLAlchemy ORM (PostgreSQL or embedded SQLite)
        db_session_factory = init_db(state_dir=state_dir)

        # Also initialize the legacy psycopg pool for backward compatibility
        db_pool = _init_postgres() if db_session_factory is None else None

        # 4. Initialise MinIO (if configured)
        minio_client, minio_bucket, minio_prefix = _init_minio()

        # 5. Build context
        ctx = DashboardContext(
            state_dir=state_dir,
            config=config,
            db=db_pool,
            db_session_factory=db_session_factory,
            minio=minio_client,
            minio_bucket=minio_bucket,
            minio_prefix=minio_prefix,
            secret_manager=secret_manager,
        )
        app.state.dashboard_ctx = ctx

        if db_session_factory is not None:
            logger.info("Database schema ready")

        persistence = "PostgreSQL (ORM)" if ctx.db_session_factory else ("PostgreSQL (legacy)" if ctx.db else "local files")
        storage = "MinIO" if ctx.minio else "filesystem"
        logger.info("Persistence backend: %s | Artifact storage: %s", persistence, storage)

        # Auto-start the monitoring scheduler so health checks run
        # without requiring a manual POST to /api/monitoring/scheduler/start.
        from selqor_forge.dashboard.routes.monitoring import _scheduler_loop
        import asyncio as _asyncio

        _monitoring_task: _asyncio.Task | None = None
        if ctx.db_session_factory is not None:
            from selqor_forge.dashboard.routes import monitoring as _mon_mod
            _monitoring_task = _asyncio.create_task(_scheduler_loop(ctx))
            _mon_mod._scheduler_task = _monitoring_task
            logger.info("Monitoring scheduler auto-started")

        yield

        # Shutdown: stop the monitoring scheduler
        if _monitoring_task is not None and not _monitoring_task.done():
            _mon_mod._scheduler_running = False
            _monitoring_task.cancel()
            try:
                await _monitoring_task
            except (_asyncio.CancelledError, Exception):
                pass
            logger.info("Monitoring scheduler stopped")

        # Shutdown: close the DB pool if it was opened.
        if ctx.db is not None:
            try:
                ctx.db.close()
                logger.info("PostgreSQL connection pool closed")
            except Exception:
                logger.debug("Error closing DB pool", exc_info=True)
        if ctx.db_session_factory is not None:
            bind = getattr(ctx.db_session_factory, "kw", {}).get("bind")
            if bind is not None:
                try:
                    bind.dispose()
                    logger.info("Database engine disposed")
                except Exception:
                    logger.debug("Error disposing database engine", exc_info=True)

    app = FastAPI(
        title="Selqor Forge Dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    # -- HTTPS redirect in production --
    is_production = os.environ.get("FORGE_PRODUCTION", "").strip().lower() in ("true", "1", "yes")
    if is_production:
        from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
        try:
            app.add_middleware(HTTPSRedirectMiddleware)
            logger.info("HTTPS redirect middleware enabled (production mode)")
        except Exception:
            logger.warning("Failed to add HTTPS redirect middleware")

    # -- CORS --
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if cors_allow_origins and "*" not in cors_allow_origins:
        logger.info("CORS origins restricted to: %s", cors_allow_origins[:5])
    elif not cors_allow_origins:
        logger.info("CORS: same-origin only (no cross-origin allowed)")
    else:
        logger.warning("CORS: wildcard origin (*) — not recommended for production")

    # -- Rate limiting middleware --
    try:
        from slowapi import Limiter  # type: ignore[import-untyped]
        from slowapi.util import get_remote_address  # type: ignore[import-untyped]

        limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
        app.state.limiter = limiter
        app.add_middleware(limiter._middleware_class)
        logger.info("Rate limiting enabled: 200 requests per minute per IP")
    except ImportError:
        logger.debug("slowapi not installed; rate limiting disabled")
        app.state.limiter = None

    # -- Request size limits --
    # Set max upload file size to 100MB
    100 * 1024 * 1024  # 100MB

    # ------------------------------------------------------------------
    # Health check endpoint
    # ------------------------------------------------------------------

    @app.get("/health", include_in_schema=True, tags=["monitoring"])
    async def health_check(request: Request) -> dict:
        """Health check endpoint for monitoring and orchestration."""
        ctx = request.app.state.dashboard_ctx
        env_status = request.app.state.env_status

        checks = {
            "status": "healthy",
            "api": "ok",
            "database": "ok" if (ctx.db or ctx.db_session_factory) else "not_configured",
            "storage": "ok" if ctx.minio else "filesystem",
            "llm": "configured" if env_status.get("llm_configured") else "not_configured",
        }

        # Overall health determination
        critical_ok = checks["api"] == "ok"
        checks["status"] = "healthy" if critical_ok else "degraded"

        return checks

    @app.get("/health/ready", include_in_schema=True, tags=["monitoring"])
    async def readiness_check(request: Request) -> dict:
        """Readiness check endpoint for Kubernetes."""
        ctx = request.app.state.dashboard_ctx
        ready = bool(ctx.db or ctx.db_session_factory or ctx.state_dir.exists())
        return {"ready": ready, "status": "ok" if ready else "not_ready"}

    @app.get("/health/live", include_in_schema=True, tags=["monitoring"])
    async def liveness_check(request: Request) -> dict:
        """Liveness check endpoint for Kubernetes."""
        return {"status": "alive"}

    # ------------------------------------------------------------------
    # React frontend (index.html SPA)
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_index() -> Response:
        if not frontend_index.is_file():
            return _frontend_not_built_response()
        return FileResponse(
            frontend_index,
            media_type="text/html; charset=utf-8",
        )

    # ------------------------------------------------------------------
    # Logo / brand asset routes  (/assets/<name>)
    # ------------------------------------------------------------------

    for url_name, disk_name in _SVG_ASSET_MAP.items():

        def _make_svg_handler(filename: str):  # noqa: E306
            disk_path = _LOGOS_DIR / filename

            async def _handler() -> FileResponse:
                return FileResponse(disk_path, media_type="image/svg+xml; charset=utf-8")

            return _handler

        app.get(f"/assets/{url_name}", include_in_schema=False)(_make_svg_handler(disk_name))

    for url_name, disk_name in _PNG_ASSET_MAP.items():

        def _make_png_handler(filename: str):  # noqa: E306
            disk_path = _LOGOS_DIR / filename

            async def _handler() -> FileResponse:
                return FileResponse(disk_path, media_type="image/png")

            return _handler

        app.get(f"/assets/{url_name}", include_in_schema=False)(_make_png_handler(disk_name))

    # ------------------------------------------------------------------
    # Include API route routers
    # ------------------------------------------------------------------

    from selqor_forge.dashboard.routes import api_router  # noqa: E402

    app.include_router(api_router, prefix="/api")

    # ------------------------------------------------------------------
    # Serve React app assets (hashed bundles)
    # ------------------------------------------------------------------

    _ASSETS_DIR = _REACT_DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets-app", StaticFiles(directory=_ASSETS_DIR), name="react-assets")
    logger.info("Serving React frontend from %s", _REACT_DIST_DIR)

    # ------------------------------------------------------------------
    # SPA catch-all Ã¢â‚¬â€ serves index.html for client-side routes
    # Must be the LAST route registered.
    # ------------------------------------------------------------------

    @app.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
    async def spa_fallback(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        # Check if the path matches a real file in dist/ (e.g., assets, fonts, etc.)
        maybe_file = _REACT_DIST_DIR / path
        if maybe_file.is_file() and _REACT_DIST_DIR in maybe_file.resolve().parents:
            return FileResponse(maybe_file)
        # Otherwise serve index.html for client-side routing
        if not frontend_index.is_file():
            return _frontend_not_built_response()
        return FileResponse(
            frontend_index,
            media_type="text/html; charset=utf-8",
        )

    return app


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


def run(
    state_dir: Path,
    host: str = "127.0.0.1",
    port: int = 9780,
    config: AppConfig | None = None,
) -> None:
    """Create the dashboard app and start the Uvicorn server."""
    if config is None:
        config = AppConfig()

    app = create_app(state_dir, config, bind_host=host)

    logger.info("Starting dashboard at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")

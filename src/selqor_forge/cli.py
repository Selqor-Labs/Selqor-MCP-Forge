# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""CLI entry point for Selqor MCP Forge."""

from __future__ import annotations

import logging
import os
from ipaddress import ip_address
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Optional

import typer

from selqor_forge import __version__
from selqor_forge.config import AppConfig, OutputTarget, TransportMode
from selqor_forge.logging_setup import init as init_logging

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="selqor-mcp-forge",
    help="Generate curated MCP servers from OpenAPI specs",
    add_completion=False,
)


class TargetArg(StrEnum):
    TS = "ts"
    RUST = "rust"
    BOTH = "both"


def _target_override(target: TargetArg) -> list[OutputTarget]:
    match target:
        case TargetArg.TS:
            return [OutputTarget.TYPESCRIPT]
        case TargetArg.RUST:
            return [OutputTarget.RUST]
        case TargetArg.BOTH:
            return [OutputTarget.TYPESCRIPT, OutputTarget.RUST]


def _format_targets(targets: list[OutputTarget]) -> str:
    return ", ".join(t.value for t in targets)


def _analysis_source_name(source: str) -> str:
    return source


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _load_env_file() -> None:
    """Best-effort .env loading for CLI entrypoints only."""
    try:
        import dotenv  # type: ignore[import-untyped]

        dotenv.load_dotenv()
        logger.debug("Loaded .env file")
    except ImportError:
        logger.debug("python-dotenv not installed; skipping .env loading")


def _resolve_dashboard_llm_config(state_dir: Path, llm_config_id: str | None = None):
    """Load an LLM config from the dashboard database for benchmark use.

    Returns an ``LlmRuntimeConfig`` or ``None``.
    """
    try:
        from selqor_forge.dashboard.db import init_db
        from selqor_forge.dashboard.repositories import LLMConfigRepository
        from selqor_forge.dashboard.secrets import DashboardSecretManager
        from selqor_forge.pipeline.analyze import LlmRuntimeConfig

        session_factory = init_db(state_dir=state_dir)
        if session_factory is None:
            return None

        secret_manager = DashboardSecretManager.from_environment(state_dir)
        session = session_factory()
        try:
            repo = LLMConfigRepository(session, secret_manager)
            models = repo.list_all()
            if not models:
                return None

            chosen = None
            if llm_config_id:
                chosen = next((m for m in models if m.id == llm_config_id), None)
            if chosen is None:
                chosen = next((m for m in models if m.is_default and (m.model or "").strip()), None)
            if chosen is None:
                chosen = next((m for m in models if (m.model or "").strip()), None)
            if chosen is None:
                return None

            api_key = (
                secret_manager.decrypt_text(chosen.api_key)
                if secret_manager is not None and chosen.api_key
                else chosen.api_key
            )
            bearer_token = (
                secret_manager.decrypt_text(chosen.bearer_token)
                if secret_manager is not None and chosen.bearer_token
                else chosen.bearer_token
            )
            custom_headers = (
                secret_manager.decrypt_json_blob(chosen.custom_headers, {})
                if secret_manager is not None
                else (chosen.custom_headers or {})
            )

            return LlmRuntimeConfig(
                provider=(chosen.provider or "").strip(),
                model=chosen.model or None,
                base_url=chosen.base_url or None,
                auth_type=chosen.auth_type or "bearer",
                auth_header_name=getattr(chosen, "auth_header_name", None),
                auth_header_prefix=getattr(chosen, "auth_header_prefix", None),
                api_key=api_key or None,
                bearer_token=bearer_token or None,
                custom_headers=custom_headers or {},
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("failed to load LLM config for benchmark: %s", exc)
        return None


def _resolve_env_llm_config():
    """Load an LLM runtime config from environment variables for CLI usage."""
    from selqor_forge.pipeline.analyze import LlmRuntimeConfig

    provider = (os.environ.get("FORGE_LLM_PROVIDER", "").strip() or "").lower()
    model = os.environ.get("FORGE_LLM_MODEL", "").strip() or None
    base_url = os.environ.get("FORGE_LLM_BASE_URL", "").strip() or None
    api_key = os.environ.get("FORGE_LLM_API_KEY", "").strip() or None
    bearer_token = os.environ.get("FORGE_LLM_BEARER_TOKEN", "").strip() or None

    if api_key is None and bearer_token is None:
        if os.environ.get("MISTRAL_API_KEY", "").strip():
            provider = provider or "mistral"
            api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
        elif os.environ.get("ANTHROPIC_API_KEY", "").strip():
            provider = provider or "anthropic"
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if provider == "mistral" and base_url is None:
        base_url = "https://api.mistral.ai"

    if not provider or (api_key is None and bearer_token is None):
        return None

    return LlmRuntimeConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        auth_type="api_key" if api_key else "bearer",
        api_key=api_key,
        bearer_token=bearer_token,
        custom_headers={},
    )


@app.command()
def generate(
    spec: Annotated[str, typer.Argument(help="OpenAPI spec path or URL")],
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("./selqor-mcp-forge-output"),
    config: Annotated[Optional[Path], typer.Option(help="Optional selqor-mcp-forge config JSON file")] = None,
    target: Annotated[TargetArg, typer.Option(help="Generation target")] = TargetArg.BOTH,
    transport: Annotated[Optional[TransportMode], typer.Option(help="Default generated transport mode")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Disable Anthropic analysis and use heuristic curation only")] = False,
) -> None:
    """Run the 6-stage pipeline to generate MCP servers from an OpenAPI spec."""
    init_logging()
    _load_env_file()

    from selqor_forge.pipeline import analyze, curate, generate as gen, normalize, parse, score

    logger.info("starting generate command: spec=%s out=%s", spec, out)
    app_config = (
        AppConfig.load(config)
        .with_targets(_target_override(target))
        .with_transport(transport)
        .with_anthropic_enabled(not no_llm)
    )

    logger.info("[1/6] Parsing spec")
    parsed = parse.parse_spec(spec)
    logger.debug("spec parsed: %d endpoints", len(parsed.endpoints))

    logger.info("[2/6] Normalizing to UASF")
    uasf = normalize.normalize(parsed)
    logger.debug("UASF normalized: %d endpoints", len(uasf.endpoints))

    logger.info("[3/6] Analyzing semantic groups")
    runtime_llm = None if no_llm else _resolve_env_llm_config()
    analysis = (
        analyze.analyze_with_override(uasf, app_config, runtime_llm)
        if runtime_llm is not None
        else analyze.analyze(uasf, app_config)
    )

    logger.info("[4/6] Curating semantic tool plan")
    plan = curate.curate(uasf, app_config, analysis)
    logger.debug("tool plan curated: %d tools, %d warnings", len(plan.tools), len(plan.warnings))

    logger.info("[5/6] Scoring quality")
    quality = score.score(uasf, plan)
    logger.debug("quality report: score=%d coverage=%.2f compression=%.2f", quality.score, quality.coverage, quality.compression_ratio)

    logger.info("[6/6] Generating server targets")
    summary = gen.generate(out, uasf, analysis, plan, quality, app_config)

    logger.info(
        "Selqor MCP Forge generation complete: output=%s api=%s version=%s endpoints=%d source=%s tools=%d score=%d targets=%s",
        summary.root,
        uasf.title,
        uasf.version,
        len(uasf.endpoints),
        _analysis_source_name(analysis.source),
        len(plan.tools),
        quality.score,
        _format_targets(summary.targets),
    )

    for warning in quality.warnings:
        logger.info("quality warning: %s", warning)


@app.command()
def benchmark(
    manifest: Annotated[Path, typer.Option(help="Benchmark manifest JSON file")] = Path("./benchmarks/apis.json"),
    out: Annotated[Path, typer.Option(help="Benchmark output directory")] = Path("./benchmarks/results"),
    config: Annotated[Optional[Path], typer.Option(help="Optional selqor-mcp-forge config JSON file")] = None,
    target: Annotated[TargetArg, typer.Option(help="Generation target used when --generate-servers is enabled")] = TargetArg.BOTH,
    transport: Annotated[Optional[TransportMode], typer.Option(help="Default generated transport mode")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Disable Anthropic analysis and use heuristic curation only")] = False,
    generate_servers: Annotated[bool, typer.Option("--generate-servers", help="Generate curated server outputs for each benchmark API")] = False,
    fail_fast: Annotated[bool, typer.Option("--fail-fast", help="Stop immediately on the first benchmark failure")] = False,
    llm_config_id: Annotated[Optional[str], typer.Option("--llm-config-id", help="Dashboard LLM config ID to use for analysis")] = None,
    state: Annotated[Path, typer.Option(help="Dashboard state directory (for loading LLM configs)")] = Path("./dashboard"),
) -> None:
    """Run benchmarks against a manifest of APIs."""
    init_logging()
    _load_env_file()

    from selqor_forge.benchmark import run as run_benchmark

    logger.info(
        "starting benchmark command: manifest=%s out=%s generate_servers=%s fail_fast=%s",
        manifest, out, generate_servers, fail_fast,
    )
    app_config = (
        AppConfig.load(config)
        .with_targets(_target_override(target))
        .with_transport(transport)
        .with_anthropic_enabled(not no_llm)
    )

    # Load LLM config from dashboard database if available
    llm_config = None
    if not no_llm:
        llm_config = _resolve_dashboard_llm_config(state, llm_config_id)
        if llm_config is None:
            llm_config = _resolve_env_llm_config()
        if llm_config:
            logger.info(
                "benchmark using LLM: provider=%s model=%s",
                llm_config.provider,
                llm_config.model,
            )
        else:
            logger.warning(
                "no LLM configuration found — benchmark will use heuristic analysis only. "
                "Configure an LLM in the dashboard or pass --llm-config-id."
            )

    run_benchmark(
        manifest=manifest,
        out=out,
        app_config=app_config,
        generate_servers=generate_servers,
        fail_fast=fail_fast,
        llm_config=llm_config,
    )


@app.command()
def dashboard(
    state: Annotated[Path, typer.Option(help="Dashboard state directory")] = Path("./dashboard"),
    host: Annotated[str, typer.Option(help="Dashboard host to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Dashboard port to bind")] = 8787,
    config: Annotated[Optional[Path], typer.Option(help="Optional selqor-mcp-forge config JSON file")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Disable Anthropic analysis and use heuristic curation only")] = False,
    i_know_what_im_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-im-doing",
            help="Required to bind the dashboard to a non-loopback host while auth is still optional.",
        ),
    ] = False,
) -> None:
    """Start the Selqor MCP Forge dashboard web server."""
    init_logging()
    _load_env_file()

    from selqor_forge.dashboard.app import run as run_dashboard

    if not _is_loopback_host(host) and not i_know_what_im_doing:
        typer.secho(
            "Refusing to bind the dashboard to a non-loopback host without "
            "--i-know-what-im-doing. The dashboard is intended for local development by default.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    logger.info("starting dashboard command: state_dir=%s host=%s port=%d", state, host, port)
    app_config = AppConfig.load(config).with_anthropic_enabled(not no_llm)

    run_dashboard(state_dir=state, host=host, port=port, config=app_config)


def version_callback(value: bool) -> None:
    if value:
        print(f"selqor-mcp-forge {__version__}")
        raise typer.Exit()


@app.command()
def scan(
    source: Annotated[str, typer.Argument(help="Local directory, GitHub URL, or running server URL to scan")],
    out: Annotated[Path, typer.Option(help="Output directory for scan results")] = Path("./scan-results"),
    format: Annotated[str, typer.Option(help="Output format: json, markdown, spdx, pdf (comma-separated for multiple)")] = "json",
    full_mode: Annotated[bool, typer.Option("--full", help="Run full scan (includes expensive checks like Trivy and LLM analysis)")] = False,
    use_semgrep: Annotated[bool, typer.Option("--semgrep", help="Use Semgrep rules engine (requires semgrep CLI)")] = False,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Disable LLM-based analysis, use heuristics only")] = False,
) -> None:
    """Scan MCP server for security vulnerabilities and compliance issues.

    Supports:
    - Local directories: selqor-mcp-forge scan ./my-server
    - GitHub URLs: selqor-mcp-forge scan https://github.com/owner/repo
    - Running servers: selqor-mcp-forge scan http://localhost:3000
    """
    import asyncio
    from pathlib import Path

    init_logging()
    _load_env_file()

    from selqor_forge.scanner import SecurityScanner, ReportGenerator

    logger.info("starting scan command: source=%s out=%s format=%s full_mode=%s", source, out, format, full_mode)

    # Create output directory
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)

    # Initialize scanner
    api_key = None
    llm_provider = "anthropic"
    llm_model = None
    llm_base_url = None
    if not no_llm:
        runtime_llm = _resolve_env_llm_config()
        if runtime_llm:
            api_key = runtime_llm.api_key or runtime_llm.bearer_token
            llm_provider = runtime_llm.provider
            llm_model = runtime_llm.model
            llm_base_url = runtime_llm.base_url
            logger.info(
                "scanner LLM analysis enabled via environment: provider=%s model=%s",
                llm_provider,
                llm_model,
            )
        else:
            logger.warning(
                "No CLI LLM environment variables found; scanner will use heuristic analysis only"
            )
    scanner = SecurityScanner(
        api_key=api_key,
        use_semgrep=use_semgrep,
        enable_trivy=full_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
    )

    # Run scan
    async def run_scan() -> None:
        if source.startswith("http://") or source.startswith("https://"):
            if "github.com" in source:
                logger.info("[1/6] Discovering MCP server from GitHub")
                result = await scanner.scan_github_server(source, full_mode=full_mode)
            else:
                logger.info("[1/3] Probing running server")
                result = await scanner.scan_running_server(source)
        else:
            logger.info("[1/7] Discovering MCP server from local directory")
            result = await scanner.scan_local_server(source, full_mode=full_mode)

        logger.info("scan complete: %d findings, risk_level=%s", result.statistics.total_findings, result.risk_summary.risk_level)

        # Generate reports
        formats = [f.strip() for f in format.split(",")]

        for fmt in formats:
            if fmt == "json":
                json_report = ReportGenerator.generate_json(result)
                json_path = out_path / "scan-report.json"
                json_path.write_text(json_report)
                logger.info("JSON report: %s", json_path)

            elif fmt == "markdown":
                md_report = ReportGenerator.generate_markdown(result)
                md_path = out_path / "scan-report.md"
                md_path.write_text(md_report)
                logger.info("Markdown report: %s", md_path)

            elif fmt == "spdx":
                sbom_report = ReportGenerator.generate_spdx_sbom(result)
                sbom_path = out_path / "sbom.spdx.json"
                sbom_path.write_text(sbom_report)
                logger.info("SPDX SBOM: %s", sbom_path)

            elif fmt == "pdf":
                pdf_data = ReportGenerator.generate_pdf(result)
                pdf_path = out_path / "scan-report.pdf"
                pdf_path.write_bytes(pdf_data)
                logger.info("PDF report: %s", pdf_path)

        # Print summary
        print(f"\n{'='*60}")
        print("Security Scan Summary")
        print(f"{'='*60}")
        print(f"Risk Level: {result.risk_summary.risk_level.upper()}")
        print(f"Overall Score: {result.risk_summary.overall_score}/100")
        print(f"Total Findings: {result.statistics.total_findings}")
        print(f"  - Critical: {result.statistics.by_risk_level.get('critical', 0)}")
        print(f"  - High: {result.statistics.by_risk_level.get('high', 0)}")
        print(f"  - Medium: {result.statistics.by_risk_level.get('medium', 0)}")
        print(f"  - Low: {result.statistics.by_risk_level.get('low', 0)}")
        print(f"\nRecommendation: {result.risk_summary.recommendation}")
        print(f"{'='*60}\n")

    asyncio.run(run_scan())


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version and exit"),
    ] = None,
) -> None:
    """Generate curated MCP servers from OpenAPI specs."""

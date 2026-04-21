# Public Release Matrix

This matrix is the public-v1 truth table for Selqor Forge.

| Surface | Status | Notes |
| --- | --- | --- |
| CLI generation flow | Supported | Env-driven LLM config works for Anthropic and OpenAI-compatible providers; heuristic fallback remains available |
| CLI scanning flow | Supported | Env-driven LLM config works in CLI and CI; `ANTHROPIC_API_KEY` remains the simplest default contract |
| Dashboard integrations flow | Supported | Local single-user workflow |
| Dashboard auth/org/team flows | Not in public v1 | Disabled with explicit `501 LOCAL_ONLY_BUILD` responses |
| Generated TypeScript targets | Supported | `stdio` and HTTP/SSE generation paths remain available |
| Generated Rust `stdio` target | Supported | Public-v1 supported Rust target |
| Generated Rust HTTP target | Experimental | Do not position as production-ready |
| Scanner heuristics and CVE checks | Supported | Public-v1 baseline |
| Scanner Semgrep and Trivy paths | Supported with external tools | Optional and environment-dependent |
| Dashboard LLM configs | Supported | Database-driven through the dashboard UI |
| PostgreSQL / MinIO fresh installs | Supported | Fresh configuration works; no file-state seeding migration |
| File-state to PostgreSQL seeding | Not in public v1 | Stub remains documented honestly |
| Generated CI/CD templates | Supported | Install from pinned GitHub tarball, not PyPI |
| PyPI install | Not in public v1 | Source checkout and Docker are the supported distribution paths |

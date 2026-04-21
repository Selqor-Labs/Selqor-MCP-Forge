# Public Release Audit

Date: April 20, 2026
Repository: `Selqor-Labs/Selqor-MCP-Forge`
Scope: Public v1 hardening pass for source checkout + Docker distribution, with the dashboard positioned as a local-only single-user tool.

## Executive Summary

This audit reviewed the public-facing product story, install paths, dashboard behavior, generated CI/CD output, release documentation, and key smoke-test flows.

The main goal was to reduce public-facing embarrassment risk by aligning the repo's claims with what the code actually supports, removing misleading shared-auth behavior, fixing real day-one breakage in Docker, and tightening the public release documentation.

The repository is now in a much safer public-release state:

- Docker build and runtime path were fixed and verified.
- Shared-user auth, org, and team flows now fail honestly with explicit local-only responses.
- Generated CI/CD templates no longer assume PyPI distribution.
- CLI LLM usage now supports env-driven provider configuration, including Mistral-compatible settings.
- README and release docs now reflect the actual supported surface area.
- Additional real-world testing against the official OpenAI API spec found and fixed generator/runtime issues that smaller fixtures did not reveal.

## What Was Reviewed

The following areas were reviewed during the release pass:

### Product and UX surfaces

- `README.md`
- Dashboard UI messaging
- Dashboard auth/org/team API behavior
- Generated CI/CD templates
- CLI generation flow
- CLI scanning flow
- Docker install path
- Frontend build and serving path

### Backend and platform surfaces

- Dashboard startup and asset serving
- Local-only auth contract
- Organization and team-management endpoints
- CI/CD template generation
- Packaging metadata in `pyproject.toml`
- PostgreSQL and Docker startup behavior
- LLM provider resolution for CLI and scanning

### Repo hygiene

- Stale branch references
- Stray root lockfile
- Duplicate legacy frontend file
- Public release truth-table docs

## Key Findings and Fixes

## 1. Docker Runtime Was Broken

### What was reviewed

- `Dockerfile`
- `docker-compose.yml`
- Container startup logs
- Dashboard health endpoints

### Bugs found

- The image attempted to install the Python package before the full source tree was available in the runtime image.
- The dashboard container was started on `0.0.0.0`, but the CLI intentionally refused non-loopback binding unless `--i-know-what-im-doing` was passed.
- After bypassing the host-bind guard, the non-root container still crashed because it could not create the default `dashboard` state directory.
- The runtime needed bundled frontend assets and logo assets in the expected locations to serve the UI correctly.

### Fixes implemented

- Reworked the `Dockerfile` so source files are copied before package installation.
- Ensured the built frontend `dist` directory is copied into the runtime image.
- Ensured logo assets are copied into the runtime image.
- Added `--i-know-what-im-doing` to the container startup command for the explicitly supported local demo path.
- Changed the container state path to a writable user-owned directory: `/home/selqor/dashboard`.
- Created and owned that directory during image build.
- Kept `docker-compose.yml` clearly framed as local demo and smoke testing only.

### Outcome

- `docker compose up -d --build` succeeded.
- `GET /health/ready` returned a healthy readiness response.
- `GET /` returned `200`.

## 2. Dashboard Public Contract Was Misleading

### What was reviewed

- `src/selqor_forge/dashboard/middleware.py`
- `src/selqor_forge/dashboard/routes/auth_routes.py`
- `src/selqor_forge/dashboard/routes/org_routes.py`
- `src/selqor_forge/dashboard/routes/settings.py`
- Frontend auth and settings UX

### Bugs found

- The dashboard previously exposed behavior that implied a functioning shared-user/team product even though public auth integration was not actually present.
- Some routes returned fake success-style data instead of clearly communicating that the feature was unsupported in the public build.
- That created a "demo looks real, product is not real" risk for public users.

### Fixes implemented

- Standardized `/api/auth/config` as the capability-discovery endpoint for the public build.
- Marked the public dashboard as:
  - `local_only: true`
  - `auth_routes_enabled: false`
  - `organizations_enabled: false`
  - `team_management_enabled: false`
- Changed shared-user auth, onboarding, invite, org, and team-management endpoints to return explicit `501 LOCAL_ONLY_BUILD` responses instead of fake operational payloads.
- Updated frontend state loading so the app fetches auth capability config on startup.
- Added local-only UI messaging in the top bar and settings page.
- Removed a leftover fake "Default Team" fallback from export behavior and replaced it with an honest disabled-state payload.

### Outcome

- The public dashboard now behaves like a local-only tool instead of pretending to be a partially working multi-user SaaS surface.

## 3. Generated CI/CD Templates Assumed PyPI

### What was reviewed

- `src/selqor_forge/dashboard/routes/cicd.py`
- README install guidance
- Release matrix docs

### Bugs found

- Generated CI/CD files assumed `selqor-forge` would be installed from PyPI.
- That was inconsistent with the actual public release strategy.
- Public users copying those templates would hit an avoidable installation failure or distribution mismatch.

### Fixes implemented

- Switched generated GitHub Actions and GitLab CI install steps away from PyPI, and later tightened them further to use a pinned GitHub commit tarball URL.
- Updated generated CI comments so they no longer imply PyPI as the release source.
- Added clearer notes around LLM CI env usage:
  - `ANTHROPIC_API_KEY` still works as the simplest default.
  - `FORGE_LLM_PROVIDER`, `FORGE_LLM_MODEL`, and `FORGE_LLM_API_KEY` are now documented as the generic alternative for other providers.

### Outcome

- The generated CI/CD story now matches the actual public-release distribution path.

## 4. CLI LLM Configuration Was Too Narrow

### What was reviewed

- `src/selqor_forge/cli.py`
- `src/selqor_forge/pipeline/analyze.py`
- scanner CLI behavior

### Bugs found

- CLI flows were too tightly coupled to Anthropic-only assumptions.
- Public release docs needed a cleaner distinction between dashboard-managed LLM config and CLI/CI env-driven config.
- Scanner fallback messaging was not aligned with the new local-only/dashboard story.

### Fixes implemented

- Added env-driven LLM resolution for CLI usage.
- Added support for:
  - `FORGE_LLM_PROVIDER`
  - `FORGE_LLM_MODEL`
  - `FORGE_LLM_BASE_URL`
  - `FORGE_LLM_API_KEY`
  - `FORGE_LLM_BEARER_TOKEN`
  - `MISTRAL_API_KEY`
  - `ANTHROPIC_API_KEY`
- Added default Mistral base URL resolution for provider `mistral`.
- Updated `generate`, `benchmark`, and `scan` to use env-driven runtime LLM config when present.
- Updated fallback warnings so they explain:
  - CLI users should use env configuration
  - dashboard users should use Dashboard > LLM Config

### Outcome

- CLI generation and scan flows now support both Anthropic and OpenAI-compatible providers in a cleaner, more release-safe way.

## 5. Frontend Public Messaging Needed Tightening

### What was reviewed

- `src/dashboard/frontend/src/App.jsx`
- `src/dashboard/frontend/src/components/Topbar.jsx`
- `src/dashboard/frontend/src/pages/Settings.jsx`
- `src/dashboard/frontend/src/pages/Integrations/steps/DeployStep.jsx`

### Bugs found

- The UI did not clearly frame the public dashboard as local-only.
- Users could still infer product maturity or multi-user support that the public build does not actually provide.
- Rust HTTP generation needed stronger public labeling.

### Fixes implemented

- Added auth capability loading into app startup.
- Added a local-only chip/banner in the top bar.
- Added a public-build informational alert in Settings.
- Added a warning in deployment UX when users select Rust HTTP transport, clearly labeling it as experimental.

### Outcome

- The frontend now communicates public-v1 limitations more honestly at the point of use.

## 6. Packaging and Repo Metadata Needed Cleanup

### What was reviewed

- `pyproject.toml`
- branch references in docs and workflows
- repo lockfiles and duplicate files

### Bugs found

- Packaging metadata was too thin for a polished public repository.
- Some docs still referenced an outdated branch name.
- A stray root `package-lock.json` was present without a root package.
- A duplicate legacy frontend file existed outside the active frontend path.

### Fixes implemented

- Added `readme`, authors, maintainers, keywords, classifiers, and project URLs to `pyproject.toml`.
- Replaced stale `forge-mcp` references with `main`.
- Removed the stray root `package-lock.json`.
- Removed the duplicate legacy frontend file:
  - `src/pages/Integrations/components/SpecInputTabs.jsx`

### Outcome

- The repo now looks more intentional and less like an internal snapshot.

## 7. Release Documentation Was Not Honest Enough

### What was reviewed

- `README.md`
- `docs/AUTH_MODULE_INTEGRATION.md`
- newly added release matrix docs

### Bugs found

- The public story did not clearly separate:
  - supported surfaces
  - experimental surfaces
  - intentionally unsupported public-v1 surfaces
- The auth docs did not match the desired public posture.

### Fixes implemented

- Added a public support matrix near the top of `README.md`.
- Added a "Known Limitations" section near the top of `README.md`.
- Added a "Golden Path Demo" section near the top of `README.md`.
- Updated LLM env documentation in `README.md`.
- Updated dashboard/auth wording to clearly describe the local-only public build.
- Rewrote `docs/AUTH_MODULE_INTEGRATION.md` to document the local-only public contract.
- Added `docs/RELEASE_MATRIX.md` as a truth table for the public release surface.

### Outcome

- Public users now have a much more accurate picture of what the project actually supports.

## 8. Real OpenAI Spec Testing Found More Generator Bugs

### What was reviewed

- Official OpenAI OpenAPI specification from the OpenAI-maintained source
- End-to-end `selqor-forge generate` on a large real-world API
- Generated TypeScript server install, build, and runtime behavior
- Scan results against generated output

### Bugs found

- Generation initially failed on the real OpenAI spec because JSON artifact writing did not handle `datetime` values correctly.
- Generated TypeScript runtime initially failed after build because `dist/index.js` expected `dist/plan.json`, while generation only wrote `src/plan.json`.
- Generated text/code artifacts were not consistently written as UTF-8, which created portability and decode issues on Windows.
- Heuristic scanning was producing major false positives by treating generated data artifacts and lockfiles like executable source code.
- The generated `custom_request` tool was too permissive as a default-generated escape hatch for a public-by-default build.

### Fixes implemented

- Updated JSON artifact writing to serialize Pydantic models in JSON mode and safely handle JSON-native values like datetimes.
- Updated the generated TypeScript template to resolve `plan.json` from both built and source layouts.
- Updated generated artifact writing to consistently use UTF-8 encoding.
- Updated heuristic scanning to skip generated artifacts:
  - `analysis-plan.json`
  - `forge.report.json`
  - `plan.json`
  - `tool-plan.json`
  - `uasf.json`
- Updated heuristic scanning to skip lockfiles for regex/code-pattern scanning:
  - `package-lock.json`
  - `npm-shrinkwrap.json`
  - `yarn.lock`
  - `pnpm-lock.yaml`
  - `pnpm-lock.yml`
  - `Cargo.lock`
- Changed `include_custom_request_tool` to default to `False`, making `custom_request` opt-in rather than always-on.
- Added regression tests for:
  - datetime JSON serialization
  - generated TypeScript plan loading behavior
  - heuristic scanner artifact filtering
  - `custom_request` default exclusion and explicit opt-in

### Outcome

- Real OpenAI-spec generation completed successfully.
- The generated TypeScript server installed, built, and booted successfully.
- Generated OpenAI tool plans now omit `custom_request` by default.
- Generated-server scan noise dropped materially after scanner filtering.

## 9. Results From Real OpenAI Spec Validation

### Spec source used

- OpenAI official repository:
  - `https://github.com/openai/openai-openapi`
- Documented spec URL referenced by that repository:
  - `https://app.stainless.com/api/spec/documented/openai/openapi.documented.yml`

### Generation results

- API title: `OpenAI API`
- API version: `2.3.0`
- Endpoint count: `241`
- Generated TypeScript tool count after curation: `31`
- `custom_request` present by default in fresh generation: `False`

### Runtime results

- Generated TypeScript server completed:
  - install
  - TypeScript build
  - stdio startup
- Generated HTTP mode now:
  - refuses startup without `FORGE_HTTP_AUTH_TOKEN`
  - starts successfully when `FORGE_HTTP_AUTH_TOKEN` is configured
  - applies route-level auth and in-memory rate limiting to `/sse` and `/messages`
- Runtime smoke succeeded with:
  - `FORGE_BASE_URL=https://api.openai.com`
  - `FORGE_TRANSPORT=stdio`

### Scan results across the hardening cycle

- Before scanner filtering improvements:
  - `18 findings`
  - `15 high`
  - score `0.0/100`
- After scanner filtering improvements:
  - `6 findings`
  - `3 high`
  - score `31.0/100`
- After generated HTTP/request hardening:
  - `0 findings`
  - score `100.0/100`

### Interpretation

- The original generated-server scan result was overstated by false positives from generated JSON and lockfiles.
- After filtering those files out of heuristic code-pattern analysis, the remaining findings are much closer to the real hardening work still needed.
- The next real work after filtering was generated-server request/HTTP hardening, not basic pipeline correctness.
- That hardening pass is now implemented in the generated TypeScript template:
  - outbound URL validation for `FORGE_BASE_URL`, dynamic token URLs, and OAuth token URLs
  - relative-path enforcement for API requests
  - header sanitization for user-supplied request headers
  - required shared-secret auth for generated HTTP transport
  - in-memory per-client rate limiting on generated HTTP routes

## 10. Generated TypeScript HTTP Hardening Was Completed

### What was reviewed

- `src/selqor_forge/templates.py`
- generated OpenAI TypeScript server output from the real OpenAI spec
- remaining `SEC070` and `SEC071` findings in generated `src/index.ts`

### Bugs found

- Generated TypeScript HTTP mode exposed `/sse` and `/messages` without authentication.
- Generated HTTP routes did not apply rate limiting.
- Generated outbound request handling did not clearly validate configured URLs, relative paths, or dangerous user-supplied headers.
- The remaining scan findings were concentrated in generated request/HTTP behavior rather than the core generator pipeline.

### Fixes implemented

- Added generated env vars for:
  - `FORGE_HTTP_AUTH_TOKEN`
  - `FORGE_HTTP_RATE_LIMIT_WINDOW_MS`
  - `FORGE_HTTP_RATE_LIMIT_MAX`
  - `FORGE_ALLOW_PRIVATE_HOSTS`
- Updated generated README notes to document HTTP auth and rate limiting.
- Added generated URL validation for:
  - `FORGE_BASE_URL`
  - `FORGE_DYNAMIC_TOKEN_URL`
  - `FORGE_OAUTH_TOKEN_URL`
- Added generated relative-path validation so request paths cannot smuggle absolute URLs.
- Added generated header sanitization to drop invalid and hop-by-hop headers.
- Added required shared-secret auth for generated HTTP mode.
- Added basic in-memory rate limiting for generated `/health`, `/sse`, and `/messages` routes.
- Added template regression tests covering the new auth, rate-limiting, and outbound-validation behaviors.

### Outcome

- Fresh real-spec generation still succeeds.
- The generated OpenAI TypeScript server still installs and builds.
- Generated HTTP mode now fails closed when required auth config is missing.
- Generated-server scan findings dropped from `6` to `0`.

## 11. Stretch Bug-Fix Pass Completed

### What was reviewed

- `src/selqor_forge/pipeline/curate.py`
- `src/selqor_forge/templates.py`
- `src/selqor_forge/scanner/scanner.py`
- `src/selqor_forge/scanner/discover.py`
- `src/selqor_forge/scanner/cve_checker.py`
- `src/selqor_forge/dashboard/routes/settings.py`
- `src/dashboard/frontend/src/api/index.js`
- `src/dashboard/frontend/src/pages/Settings.jsx`
- `src/selqor_forge/dashboard/routes/cicd.py`
- `docker-compose.yml`

### Bugs found

- `search_api` still mixed discovery and execution semantics in a way the published schema did not represent cleanly.
- Single-endpoint generated tools still published `operation` behavior inconsistently with what the runtimes actually did.
- Absorbing uncovered endpoints into an existing tool could leave schemas stale.
- Local directory scans still skipped prompt-injection LLM analysis even when LLM config was active.
- Python dependency parsing still corrupted package names for PEP 508 specifiers like `httpx>=0.27`.
- OSV severity parsing could still fail on structured severity payloads.
- `/api/settings/export` could still surface real team/invite rows in a local-only build.
- Backend preference defaults still did not match frontend choices.
- Frontend API error handling still stringified nested local-only error payloads instead of surfacing `detail.message`.
- Generated CI/CD install source was still tied to a version-tag tarball instead of a pinned commit tarball.
- Docker Compose still persisted Postgres but not the actual dashboard state directory used by the container.

### Fixes implemented

- Split overflow handling into two generated tools:
  - `search_api` is now discovery-only with required `query` and optional `limit`
  - `execute_overflow_operation` is now the execution path for overflow operations
- Removed multi-operation fallback behavior from generated runtimes and kept single-endpoint execution implicit without exposing `operation` in single-endpoint schemas.
- Rebuilt tool schemas after endpoint absorption instead of only appending endpoint ids.
- Updated the Rust runtime template to match the TypeScript runtime behavior for discovery-only search and explicit overflow execution.
- Updated local full scans to run both prompt-injection analysis and OWASP agentic analysis when LLM config is active.
- Switched Python dependency parsing to `packaging.requirements.Requirement`.
- Hardened OSV severity parsing so structured severity payloads are accepted instead of dropped.
- Updated local TypeScript dependency discovery to prefer exact installed versions from `package-lock.json`.
- Pinned generated TypeScript scaffold dependencies to known-good exact versions:
  - `@modelcontextprotocol/sdk@1.29.0`
  - `express@4.22.1`
- Made local-only export always return disabled placeholders for team data and an empty invite list.
- Aligned backend preference defaults to `theme="light"` and `default_scan_mode="basic"`, and added frontend coercion for unexpected persisted values.
- Updated frontend API error extraction to prefer nested `detail.message`.
- Switched generated CI/CD installs to pinned GitHub commit tarballs resolved from:
  - `SELQOR_FORGE_GIT_SHA`, or
  - local `git rev-parse HEAD`
- Added explicit CI generation failure when no pinned install ref can be resolved.
- Added a persistent Docker Compose volume for `/home/selqor/dashboard`.

### Outcome

- The generated MCP contract is now materially cleaner and more truthful.
- Scanner behavior is more correct for local LLM-enabled scans and structured OSV responses.
- Local generated-server dependency signoff now reflects the installed Node lockfile instead of broad semver ranges.
- The local-only dashboard contract is now consistent across export, preferences, and frontend messaging.
- CI templates now point to an auditable pinned install source instead of implying release-tag distribution.
- README now includes a real screenshot from the current local-only dashboard.

## 12. Post-Stretch Real-Spec Validation

### OpenAI rerun

- Regenerated against `.tmp-openai-spec/openai-openapi.yml`
- Output: `.tmp-openai-spec/generated-openai-release`
- TypeScript install: passed
- TypeScript build: passed
- stdio boot smoke: passed
- Security scan:
  - `0 findings`
  - score `100.0/100`

### Stripe rerun

- Regenerated against `.tmp-stripe-spec/stripe-openapi.json`
- Output: `.tmp-stripe-spec/generated-stripe-release`
- TypeScript install: passed
- TypeScript build: passed
- stdio boot smoke: passed
- Security scan:
  - `0 findings`
  - score `100.0/100`

### Interpretation

- The generator/runtime contract fixes held up on both large public API specs.
- Generated-server dependency findings are now resolved for the release validation set.
- The remaining generated-server signoff risk moved from runtime/scanner correctness to routine maintenance items like future dependency drift and deprecation cleanup.

## Tests and Verification Performed

The following verification steps were completed during the release pass.

## Automated verification

- `python -m pytest -q`
  - Result: initially `199 passed`, later `204 passed`, then `216 passed`, and finally `217 passed` after the full release-closure pass
- `python -m pytest tests/test_dashboard/test_auth_routes.py tests/test_dashboard/test_org_routes.py tests/test_cli.py -q`
  - Result: passed
- `python -m pytest tests/test_dashboard/test_cicd.py -q`
  - Result: passed
- `python -m ruff check .`
  - Result: passed
- `mypy --follow-imports=skip --ignore-missing-imports --disable-error-code=misc ...`
  - Result: passed on the selected release-scope files
- `npm test`
  - Result: passed
- `npm run build`
  - Result: passed
- `python -m pytest tests/test_templates.py tests/test_heuristic_grouping.py tests/test_scanner_discovery.py tests/test_scanner_runtime.py tests/test_dashboard/test_settings.py tests/test_dashboard/test_cicd.py -q`
  - Result: `43 passed`

## Docker verification

- `docker compose up -d --build`
  - Result: passed after Docker/runtime fixes
- `GET /health/ready`
  - Result: `{"ready":true,"status":"ok"}`
- `GET /`
  - Result: `200`

## Security and release checks

- `npm audit --omit=dev`
  - Result: `0 vulnerabilities`
- `pip-audit` in a fresh disposable virtual environment
  - Result: no known vulnerabilities found in the repo-scoped install; local editable package was skipped as expected because it is not published on PyPI
- `gitleaks` via container
  - Result: no leaks found

## LLM smoke verification

- Verified CLI generation against Mistral-compatible env settings.
- A smoke `generate` run successfully called:
  - `https://api.mistral.ai/v1/chat/completions`
- Verified that scanner behavior is graceful without any LLM env configured.
- Verified that scanner accepts env-driven LLM settings when provided.
- Verified generation against the official OpenAI API spec.
- Verified generated TypeScript server build and stdio runtime startup for the OpenAI-spec output.
- Verified generated HTTP startup fails closed without `FORGE_HTTP_AUTH_TOKEN`.
- Verified generated HTTP startup succeeds with `FORGE_HTTP_AUTH_TOKEN`.
- Verified rescanning the hardened generated OpenAI server returns `0 findings` and `100.0/100`.

## Tests Added or Updated

### Updated tests

- `tests/test_dashboard/test_auth_routes.py`
- `tests/test_dashboard/test_org_routes.py`
- `tests/test_cli.py`
- `tests/test_pipeline.py`
- `tests/test_rules_engine.py`
- `tests/test_heuristic_grouping.py`

### Coverage added by those updates

- Local-only auth config contract
- Explicit `501 LOCAL_ONLY_BUILD` behavior
- CLI env-driven LLM behavior
- Anthropic env fallback coverage in analysis
- datetime-safe JSON artifact writing
- generated TypeScript plan loading after build
- scanner artifact filtering for generated files and lockfiles
- `custom_request` default exclusion and explicit opt-in

## Remaining Follow-Up Items

These are no longer release blockers, but they remain reasonable follow-up maintenance work.

### 1. Optional future cleanup

- There are deprecation warnings from `datetime.utcnow()` in several route modules.
- Those are not release blockers for this pass, but they should be cleaned up in a future maintenance sweep.

### 2. Clean up runtime verification ergonomics

- Generated HTTP hardening is now in place, but the local verification helper flow is still ad hoc.
- A future release-quality step would be to add a checked-in automated smoke test for generated HTTP mode so auth/rate-limiting regressions are caught without manual process orchestration.

## Public Release Position After This Audit

The project is now in a better state to be presented publicly with the following framing:

- Supported:
  - GitHub source checkout
  - Docker demo stack
  - Local single-user dashboard
  - TypeScript targets
  - Rust `stdio`
  - CLI generation
  - CLI scanning
- Experimental:
  - Rust HTTP transport
- Not in public v1:
  - Shared dashboard auth
  - Organizations
  - Team management
  - PyPI distribution
  - File-state to PostgreSQL seeding migration

## Files Most Directly Changed in This Audit

- `README.md`
- `Dockerfile`
- `docker-compose.yml`
- `pyproject.toml`
- `docs/AUTH_MODULE_INTEGRATION.md`
- `docs/RELEASE_MATRIX.md`
- `src/selqor_forge/cli.py`
- `src/selqor_forge/pipeline/analyze.py`
- `src/selqor_forge/pipeline/generate.py`
- `src/selqor_forge/dashboard/middleware.py`
- `src/selqor_forge/dashboard/routes/auth_routes.py`
- `src/selqor_forge/dashboard/routes/org_routes.py`
- `src/selqor_forge/dashboard/routes/settings.py`
- `src/selqor_forge/dashboard/routes/cicd.py`
- `src/dashboard/frontend/src/App.jsx`
- `src/dashboard/frontend/src/components/Topbar.jsx`
- `src/dashboard/frontend/src/pages/Settings.jsx`
- `src/dashboard/frontend/src/pages/Integrations/steps/DeployStep.jsx`
- `src/selqor_forge/scanner/rules_engine.py`
- `src/selqor_forge/templates.py`

## Bottom Line

Before this pass, the repo had multiple public-facing failure modes:

- Docker did not reliably start the intended local demo experience.
- The dashboard implied shared-user features that were not truly supported.
- Generated CI/CD output assumed a distribution path that did not exist.
- Docs overstated maturity in a few important places.

After this pass, the repo tells a more honest story, the local demo path works, public-facing unsupported features fail explicitly instead of pretending to work, and the release surface is much less likely to create immediate credibility damage.

The additional OpenAI-spec validation raised confidence that Selqor Forge works against a large real-world API, and the follow-up hardening pass turned the remaining generated TypeScript HTTP findings into concrete fixes rather than release debt.

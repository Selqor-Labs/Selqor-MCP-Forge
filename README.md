# Selqor Forge

<p align="center">
  <img src="selqorLogos/selqor-labs-dark.svg" alt="Selqor Forge" width="320">
</p>

<p align="center">
  <strong>Turn noisy API surfaces into curated MCP servers agents can actually use.</strong>
</p>

<p align="center">
  Parse OpenAPI specs, preserve coverage, compress tool sprawl, review security, and ship MCP targets with a local dashboard.
</p>

<p align="center">
  <img alt="Public v0.1" src="https://img.shields.io/badge/public-v0.1-0E2235?style=for-the-badge&labelColor=D88A00">
  <img alt="Dashboard" src="https://img.shields.io/badge/dashboard-local--only-163650?style=for-the-badge">
  <img alt="Targets" src="https://img.shields.io/badge/targets-TypeScript%20%7C%20Rust-163650?style=for-the-badge">
</p>

<p align="center">
  <a href="#quick-start-5-minutes">Quick Start</a> &bull;
  <a href="#golden-path-demo">Demo</a> &bull;
  <a href="#why-it-feels-different">Why Forge</a> &bull;
  <a href="#security-scanning--compliance">Security</a> &bull;
  <a href="#more-documentation">Docs</a>
</p>

Selqor Forge turns your application's API specs into smaller, higher-signal MCP servers with smart and intelligently curated tools, then gives you a dashboard to manage integrations, auth, LLM configs, run history, and deployment prep.

## At a Glance

- Start from a full API spec, not a hand-trimmed subset.
- Normalize the surface, score it, and curate it into an agent-usable tool plan.
- Generate hardened MCP servers in TypeScript or Rust.
- Review everything through a local dashboard before shipping.

## Release Confidence

- Full test suite currently passes: `217 passed`
- Real-world validation was rerun against both the OpenAI and Stripe public specs
- Fresh generated TypeScript servers rebuilt, booted over `stdio`, and rescanned at `0 findings / 100.0`

## Why It Feels Different

| Raw API -> MCP | Selqor Forge |
| --- | --- |
| One endpoint becomes one tool | Endpoints are grouped into higher-signal tools |
| Tool count balloons quickly | Tool plans stay compressed and reviewable |
| Agents waste context on definitions | Curated plans aim for agent-usable operating ranges |
| Security and deploy steps are bolted on later | Scanner, dashboard, CI templates, and runtime hardening are built into the flow |
| Hard to inspect what happened | UASF, tool plan, quality report, and generated targets stay visible |

## How It Works

1. **Parse and normalize** your OpenAPI or Swagger spec into a full intermediate surface.
2. **Analyze and curate** the endpoint graph into a tool plan with coverage, compression, and overflow handling.
3. **Generate and review** hardened MCP targets in TypeScript or Rust, then validate them through the local dashboard and scanner.

## Installation

### From npm (Node-first)

```bash
npm install -g selqor-mcp-forge
pipx install selqor-mcp-forge    # or: pip install selqor-mcp-forge
```

Both are required: the npm package provides the `selqor-mcp-forge` CLI shim, and the Python package provides the analysis engine.

### From PyPI (Python-first)

```bash
pip install selqor-mcp-forge
```

Or with development dependencies:

```bash
pip install 'selqor-mcp-forge[dev]'
```

### From Source (Development)

```bash
git clone https://github.com/Selqor-Labs/Selqor-MCP-Forge.git
cd Selqor-MCP-Forge
pip install -e .[dev]
```

## Public v1 Support Matrix

- Supported: GitHub source checkout, Docker demo stack, local single-user dashboard, TypeScript targets, Rust `stdio`, CLI generation, CLI scanning, PyPI distribution, npm wrapper
- Experimental: Rust HTTP transport
- Not in public v1: shared dashboard auth, organizations, team management

## Known Limitations

- The dashboard is intentionally local-only in this public build.
- Shared-user auth, organization management, and team invites are disabled and return explicit `501 LOCAL_ONLY_BUILD` responses.
- PostgreSQL-backed fresh installs are supported, but file-state-to-Postgres seeding is still not implemented.
- Generated CI/CD templates can install Selqor Forge from PyPI or a pinned GitHub commit tarball.

## Golden Path Demo

**Fastest path to value**

1. Install from PyPI: `pip install selqor-mcp-forge[dev]` (or use npm, see above)
2. Build the frontend with `cd src/dashboard/frontend && npm ci && npm run build`
3. Start the dashboard with `selqor-mcp-forge dashboard --state ./dashboard`
4. Create an integration from `https://petstore.swagger.io/v2/swagger.json`
5. Run analysis, inspect the tool plan, then generate a TypeScript target

See [docs/RELEASE_MATRIX.md](docs/RELEASE_MATRIX.md) for the release truth table used for public v1.

## Why This Exists

Raw tool catalogs get expensive and noisy fast:

- Microsoft Research measured the GitHub MCP server at **91 tools**, and cites tool-space growth as a real interference risk for agents at scale. [Source](https://www.microsoft.com/en-us/research/blog/tool-space-interference-in-the-mcp-era-designing-for-agent-compatibility-at-scale/)
- AgentPMT measured a **74-tool MCP setup consuming 46,568 tokens** before the first user message. [Source](https://www.agentpmt.com/articles/mcp-servers-waste-96-of-agent-context-on-tool-definitions)
- OpenAI's function-calling guidance says to **aim for fewer than 20 functions at one time for higher accuracy**. [Source](https://platform.openai.com/docs/guides/function-calling/how-do-i-ensure-the-model-calls-the-correct-function)

Selqor Forge sits in that gap: parse the full API surface, preserve coverage, and curate it into a tool plan that an agent can actually use.

## What You Ship

- Curated MCP servers instead of raw endpoint dumps
- A reviewable tool plan with coverage and compression context
- Local dashboard workflows for integrations, auth profiles, runs, and deployment prep
- Built-in security scanning and generated runtime hardening
- CI/CD scaffolds that match the public GitHub-based install path

## Quick Start (5 Minutes)

If you just want to see the product working, do this:

### Prerequisites

- **Python 3.11+** — Download from [python.org](https://www.python.org/downloads/)
- **Node.js 20+** — Download from [nodejs.org](https://nodejs.org/)
- **Git** — For cloning and version control

### Step 1: Install

From PyPI (recommended):

```bash
pip install selqor-mcp-forge[dev]
```

Or from npm:

```bash
npm install -g selqor-mcp-forge
pipx install selqor-mcp-forge
```

Or from source:

```bash
git clone https://github.com/Selqor-Labs/Selqor-MCP-Forge.git
cd Selqor-MCP-Forge
pip install -e .[dev]
```

### Step 1.5: Initialize the Dashboard Secret Key

```bash
cp .env.example .env                   # first time only
python scripts/init_secret_key.py      # writes FORGE_SECRET_KEY into .env
```

This creates the Fernet key used to encrypt stored credentials at rest. Back up `FORGE_SECRET_KEY` alongside your database and inject it from your secret manager outside local development.

### Step 2: Build the Frontend

```bash
cd src/dashboard/frontend
npm ci           # Clean install (uses package-lock.json)
npm run build    # Creates dist/ folder with optimized assets
cd ../../..      # Back to project root
```

### Step 3: Launch the Dashboard

```bash
selqor-mcp-forge dashboard --state ./dashboard --host 127.0.0.1 --port 8787
```

### Step 4: Open in Your Browser

Open **http://127.0.0.1:8787** in your browser. You should see:

- Dashboard home with example stats
- Sidebar with: Integrations, LLM Config, Monitoring, Settings, etc.
- Welcome message (if first run)

That gets you to a real working local dashboard with integrations, LLM config, scanning, and deployment prep. If something fails, jump to [Troubleshooting](#troubleshooting).

---

## Common Workflows

### 1. Analyze Your First API Spec

1. Go to **Integrations** tab in the dashboard
2. Click **"Create Integration"**
3. Enter:
   - **Name:** "My First API" (any name you want)
   - **Spec URL:** Paste an OpenAPI spec URL (examples below)
4. Click **"Analyze"**
5. Wait for analysis to complete (~30 seconds for small specs, ~2 minutes for 100+ endpoints)
6. View results in **Tool Plan** — shows:
   - **Curated Tools:** The compressed, LLM-optimized tool list
   - **Baseline Tools:** What you'd get without curation
   - **Coverage:** % of endpoints represented in curated plan
   - **Score:** Compression ratio × coverage (higher is better)

**Example OpenAPI Specs to Try:**

- **Petstore (11 endpoints):** https://petstore.swagger.io/v2/swagger.json
- **GitHub API:** https://raw.githubusercontent.com/github/rest-api-description/main/openapi.json
- **Stripe API:** https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json

### 2. Configure Authentication

After analyzing an API, you can set up authentication credentials:

1. Click the integration you created
2. Go to **Auth** tab
3. Select auth mode:
   - **None** — Public API, no credentials
   - **API Key** — Single token, header-based or query param
   - **Bearer Token** — OAuth2 bearer scheme
   - **Basic Auth** — Username + password
   - **OAuth2 Client Credentials** — Full OAuth2 flow
   - **Custom Headers** — Any header-based auth scheme
4. Enter credentials
5. Click **"Test Connection"** to verify

**Security Note:** Credentials are encrypted at rest. Never commit them to git; use environment variables instead (see [Environment Variables](#environment-variables-safe-secrets) below).

### 3. Generate an MCP Server

Once you have a curated tool plan:

1. Go to **Deploy** tab
2. Select:
   - **Language:** TypeScript or Rust
   - **Transport:** stdio (built-in) or HTTP (for APIs)
3. Click **"Generate"**
4. Download the generated server
5. See [Deployment](#deployment--runtime) for how to use it

### 4. View Run History & Reports

1. Go to **Monitoring** tab
2. See all past analyses with timestamps
3. Click a run to view:
   - **UASF:** Raw API surface (all endpoints)
   - **Tool Plan:** Final curated list
   - **Report:** Quality metrics (JSON, CSV, or PDF)

---

## Capabilities

- ✅ OpenAPI 3.x and Swagger 2.0 ingestion from local files or HTTP(S) URLs
- ✅ UASF normalization for endpoint/domain/intent modeling
- ✅ Curated tool plans with endpoint coverage tracking and compression scoring
- ✅ Benchmark mode against a naive one-endpoint-per-tool baseline
- ✅ A local dashboard for integrations, runs, auth profiles, LLM configs, artifacts, and deployment prep
- ✅ TypeScript MCP server generation for `stdio` and HTTP/SSE transports
- ✅ Rust MCP server generation for `stdio`
- ✅ PostgreSQL metadata persistence and optional MinIO/S3 artifact storage
- ✅ Encryption of secrets at rest (Fernet)
- ✅ Local state persistence (JSON files or database)

## Runtime Targets

- **TypeScript:** Ready for `stdio` and HTTP/SSE generation paths
- **Rust:** `stdio` target is production-ready; HTTP transport is experimental

## Dashboard Features

### Core Features

- ✅ **Integration Management** — Add, analyze, and manage OpenAPI specs
- ✅ **Tool Curation** — LLM-powered tool plan creation with manual override
- ✅ **Auth Profiles** — Store and test API credentials securely
- ✅ **LLM Configuration** — Connect to OpenAI, Anthropic, or other LLM providers
- ✅ **Run History** — Browse past analyses with full artifacts
- ✅ **Report Export** — Download tool plans as JSON, CSV, or PDF
- ✅ **MCP Generation** — Auto-generate TypeScript or Rust MCP servers
- ✅ **Deployment Prep** — Generate `.env.generated` and startup commands

### Security & Compliance

- ✅ **Security Scanning** — Heuristic + optional LLM-powered OWASP Agentic Top 10 analysis
- ✅ **CVE Detection** — Always-on dependency vulnerability detection
- ✅ **Prompt Injection Detection** — LLM-powered detection (full mode)
- ✅ **Compliance & Remediation** — Auto-generated fix suggestions for findings
- ✅ **Trivy Integration** — Optional comprehensive vulnerability scanning (full mode)
- ✅ **Secrets Encryption** — Fernet-based encryption for stored credentials

### Advanced Features

- ✅ **MCP Server Discovery** — Auto-discover tools from running MCP servers (local, GitHub, HTTP)
- ✅ **Playground** — Interactive testing environment for MCP tools and debugging
- ✅ **Notifications** — Alerting for scan completion and critical security findings
- ✅ **CI/CD Integration** — Webhook support for automated security scanning pipelines
- ✅ **Compliance Badges** — Generate SVG badges for README integration
- ✅ **Multi-LLM Support** — Anthropic, OpenAI, Mistral, AWS Bedrock, Vertex AI, Gemini, vLLM, and custom endpoints

### 5. Security Scanning & Compliance

Comprehensive security analysis for MCP servers with configurable depth.

1. Go to **Scanner** tab in the dashboard
2. Click **"Create New Scan"**
3. Enter:
   - **Name:** Scan name (e.g., "My MCP Server v1")
   - **Source:** Local path, GitHub repo URL, or HTTP server URL
   - **Scan Mode:** Quick (basic) or Full (all checks)
   - **Options:** Enable Semgrep (advanced pattern matching), disable LLM (for cost savings)
4. Wait for scan to complete
5. Review findings organized by severity with remediation suggestions
6. Apply suggested fixes or export compliance report

**Default Scan (Quick Mode):**
- Heuristic code scanning (pattern-based)
- Dependency CVE checking
- License analysis
- Risk scoring

**Full Scan (adds):**
- OWASP Agentic Top 10 analysis (LLM-powered)
- Prompt injection pattern detection
- Trivy comprehensive vulnerability scanning
- AI Bill of Materials generation

**Optional Enhancements:**
- Semgrep rules engine (`--semgrep` flag)
- Custom LLM provider configuration

---

## Worked Example

The repo includes a checked-in Petstore example with both the curated outputs and a computed baseline comparison:

- [Example summary](examples/petstore/summary.json)
- [Curated-vs-baseline chart](examples/petstore/curated-vs-baseline.svg)
- [UASF output](examples/petstore/uasf.json)
- [Analysis plan](examples/petstore/analysis-plan.json)
- [Curated tool plan](examples/petstore/tool-plan.json)
- [Baseline tool plan](examples/petstore/baseline-tool-plan.json)
- [Curated quality report](examples/petstore/forge.report.json)
- [Baseline quality report](examples/petstore/baseline-quality.json)

## Security And Deployment Notes

- Dashboard secrets are encrypted at rest with Fernet.
- If `FORGE_SECRET_KEY` is missing, Selqor Forge generates a local key in the dashboard state directory on first run and prints a startup warning.
- The dashboard prints a safety banner when it is still in local-dev posture, including wildcard CORS, placeholder auth, or non-loopback binding.
- Binding the CLI to a non-loopback host now requires `--i-know-what-im-doing`.

## Authentication Status

Selqor Forge does **not** ship with a production shared-user auth system in this public build. The dashboard is intentionally positioned as a local-only single-user tool, and shared auth/org/team routes return explicit local-only disabled responses.

Use [docs/AUTH_MODULE_INTEGRATION.md](docs/AUTH_MODULE_INTEGRATION.md) before exposing the dashboard to any shared or untrusted network.

---

## CLI Commands

### Dashboard (Interactive Web UI)

```bash
selqor-mcp-forge dashboard [--state <DIR>] [--host <HOST>] [--port <PORT>]
```

**Options:**

- `--state ./state` — Directory for storing integrations, runs, configs (default: `./dashboard`)
- `--host 127.0.0.1` — Bind address (default: loopback; use `--i-know-what-im-doing` for 0.0.0.0)
- `--port 8787` — Port to listen on (default: 8787)

**Example:**

```bash
selqor-mcp-forge dashboard --state /tmp/forge-state --port 9000
# Then open http://127.0.0.1:9000
```

### Generate (Single Spec Analysis)

```bash
selqor-mcp-forge generate <SPEC> [--out <DIR>] [--config <FILE>] [--target <ts|rust|both>] [--transport <stdio|http>]
```

**Options:**

- `<SPEC>` — Path to OpenAPI spec (JSON/YAML) or URL (required)
- `--out ./output` — Output directory for generated files
- `--config ./forge.json` — Config file with scoring weights, exclusions, etc.
- `--target ts` — Generate TypeScript (default: both)
- `--transport stdio` — MCP transport mode (stdio or http)

**Example:**

```bash
selqor-mcp-forge generate https://petstore.swagger.io/v2/swagger.json --out ./petstore-output --target ts
```

**Outputs:**

- `uasf.json` — Unified API Surface Format (all endpoints)
- `tool-plan.json` — LLM-curated tool list
- `forge.report.json` — Analysis scores and metrics
- `generated/` — MCP server source code

### Benchmark (Compare Curated vs. Baseline)

```bash
selqor-mcp-forge benchmark --manifest <FILE> [--out <DIR>] [--generate-servers] [--fail-fast]
```

**Options:**

- `--manifest ./apis.json` — JSONL file listing APIs to benchmark
- `--out ./results` — Output directory for comparison reports
- `--generate-servers` — Also generate MCP servers for each API
- `--fail-fast` — Stop on first error

**Manifest Format (`apis.json`):**

```json
{
  "apis": [
    {
      "name": "Petstore",
      "slug": "petstore",
      "spec": "https://petstore.swagger.io/v2/swagger.json"
    },
    {
      "name": "Stripe",
      "slug": "stripe",
      "spec": "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json"
    }
  ]
}
```

**Example:**

```bash
selqor-mcp-forge benchmark --manifest ./benchmarks/apis.json --out ./benchmark-results
```

**Outputs:**

- `benchmark-summary.csv` — Side-by-side metrics
- `benchmark-summary.json` — Detailed results
- `benchmark-summary.md` — Markdown summary report

---

## Configuration

### Environment Variables (Safe Secrets)

Create a `.env` file in the project root:

```bash
# Dashboard authentication module (placeholder by default)
DASHBOARD_AUTH_PROVIDER=placeholder  # Options: placeholder, okta, auth0, custom

# Dashboard secret encryption key (Fernet, 32-byte url-safe base64).
# Generate with: python scripts/init_secret_key.py
# WARNING: Losing this value makes previously-stored secrets unreadable.
FORGE_SECRET_KEY=

# PostgreSQL metadata storage (leave blank for embedded SQLite)
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=selqor_forge
POSTGRES_PORT=5432
DATABASE_URL=                        # postgresql://user:pass@localhost/selqor_forge
POSTGRES_SEEDS=

# MinIO / S3-compatible artifact storage (leave blank for local filesystem)
MINIO_ROOT_USER=
MINIO_ROOT_PASSWORD=
MINIO_ENDPOINT=
MINIO_BUCKET=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_REGION=us-east-1
MINIO_PREFIX=selqor-mcp-forge

# CLI and CI can use environment-driven LLM settings directly.
# The dashboard scanner uses Dashboard -> LLM Config instead.
# Minimal Anthropic setup:
ANTHROPIC_API_KEY=
# Generic or Mistral-compatible CLI setup:
FORGE_LLM_PROVIDER=
FORGE_LLM_MODEL=
FORGE_LLM_API_KEY=
FORGE_LLM_BASE_URL=
MISTRAL_API_KEY=

# Optional generated-server auth helpers
FORGE_STATIC_HEADERS_JSON={}
FORGE_TOKEN_HEADER=Authorization
FORGE_TOKEN_PREFIX=Bearer
```

**Important:** Never commit `.env` to git. Use `.env.example` for sharing defaults.

### Config File (`forge.json`)

For advanced customization, create a `forge.json`:

```json
{
  "target_tool_count": {
    "min": 5,
    "max": 15
  },
  "include_custom_request_tool": true,
  "output_targets": ["typescript", "rust"],
  "default_transport": "stdio",
  "anthropic": {
    "enabled": true,
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 3200,
    "temperature": 0.0
  }
}
```

Pass it to commands:

```bash
selqor-mcp-forge generate ./spec.json --config ./forge.json
selqor-mcp-forge dashboard --config ./forge.json
```

---

## Docker (Local Development)

### Using Docker Compose

```bash
docker-compose up --build
```

This starts:

- **Dashboard:** http://localhost:8787
- **PostgreSQL:** localhost:5432

**Note:** The Dockerfile and `docker-compose.yml` are intended for local demo and smoke testing. Review and customize them before any broader deployment.

---

## Deployment & Runtime

### Local Development (What You're Doing Now)

```bash
pip install -e .[dev]
cd src/dashboard/frontend && npm ci && npm run build && cd ../../..
selqor-mcp-forge dashboard --state ./dashboard --host 127.0.0.1 --port 8787
```

**Characteristics:**

- ✅ Single-user, local file storage
- ✅ Wildcard CORS (fine for dev)
- ✅ Placeholder authentication
- ✅ No TLS/HTTPS

### Docker Container (Single-Machine)

```bash
docker build -t selqor-mcp-forge:latest .
docker run -p 8787:8787 \
  -v /data/forge-state:/home/selqor/dashboard \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  selqor-mcp-forge:latest
```

**Characteristics:**

- ✅ Reproducible environment
- ✅ Easy to move between machines
- ⚠️ Still needs real auth module for shared access
- ⚠️ Need reverse proxy (Nginx) for TLS

### Production Deployment

For production deployments:

- Use a reverse proxy (Nginx/Caddy) for TLS termination
- Configure PostgreSQL with proper backups
- Set up proper authentication (see [docs/AUTH_MODULE_INTEGRATION.md](docs/AUTH_MODULE_INTEGRATION.md))
- Use environment variables instead of `.env` files
- Enable security headers and rate limiting
- Monitoring and observability

### Security Checklist for Production

Before exposing Selqor Forge to a shared network:

- [ ] Implement real authentication (don't use placeholder)
- [ ] Enable TLS/HTTPS (use Let's Encrypt + reverse proxy)
- [ ] Rotate `FORGE_SECRET_KEY` from default
- [ ] Use managed database (PostgreSQL on RDS/Cloud SQL)
- [ ] Use S3 or cloud storage for artifacts (not local filesystem)
- [ ] Enable audit logging (see `SECURITY.md`)
- [ ] Set up monitoring (Sentry, DataDog, or Prometheus)
- [ ] Run security scan on dependencies (`pip audit`)

---

## Troubleshooting

### Frontend Build Fails

**Error:** `npm: command not found`

```bash
# Install Node.js from https://nodejs.org/
node --version  # Should be 20+
npm --version   # Should be 9+
```

**Error:** `ERR! code EACCES` (permission denied)

```bash
# On macOS/Linux, fix npm permissions:
sudo chown -R $(whoami) ~/.npm
sudo chown -R $(whoami) /usr/local/lib/node_modules
npm ci --force
```

**Error:** `ERESOLVE unable to resolve dependency tree`

```bash
# Use npm 8+ override flag:
npm ci --legacy-peer-deps
```

### Dashboard Won't Start

**Error:** `Address already in use: 127.0.0.1:8787`

```bash
# Use a different port:
selqor-mcp-forge dashboard --port 9000

# OR kill the existing process:
# macOS/Linux:
lsof -i :8787 | grep LISTEN | awk '{print $2}' | xargs kill -9
# Windows:
netstat -ano | findstr :8787
taskkill /PID <PID> /F
```

**Error:** LLM API key not set

```bash
# Add your LLM provider key to .env (or configure via Dashboard → LLM Config):
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# OR set it temporarily:
export ANTHROPIC_API_KEY=sk-ant-...
selqor-mcp-forge dashboard
```

### Analysis Hangs or Fails

**Issue:** LLM analysis takes >5 minutes for large specs

```bash
# This is normal for 200+ endpoint specs
# You can interrupt (Ctrl+C) and retry with simpler configs:
selqor-mcp-forge generate ./spec.json --no-llm  # Skip LLM analysis
```

**Error:** `Connection refused` when fetching remote specs

```bash
# Check your network/firewall:
curl https://petstore.swagger.io/v2/swagger.json
# If it fails, you may be behind a proxy:
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
```

### Secrets Not Encrypting

**Issue:** Credentials appear in plaintext in dashboard state files

```bash
# Check FORGE_SECRET_KEY is set:
echo $FORGE_SECRET_KEY  # Should not be empty

# Regenerate the key:
rm dashboard/secrets.key  # Deletes the local key
selqor-mcp-forge dashboard    # Generates a new one
```

### Tests Fail

```bash
# Run full test suite:
python -m pytest tests/ -v

# Run specific test:
python -m pytest tests/test_dashboard/test_auth_config.py::test_auth_secrets_are_encrypted_at_rest -v

# Run with coverage:
pip install pytest-cov
python -m pytest tests/ --cov=src/selqor_forge --cov-report=html
```

---

## Examples & Documentation

### Worked Example: Petstore API

The repo includes a complete Petstore example:

- **Spec:** https://petstore.swagger.io/v2/swagger.json
- **Results:** [examples/petstore/](examples/petstore/)
  - `summary.json` — Baseline: 20 tools, Curated: 6 tools (compression 3.3x)
  - `curated-vs-baseline.svg` — Visual comparison
  - `uasf.json` — All 20 endpoints
  - `tool-plan.json` — Final 6 curated tools
  - `forge.report.json` — Full metrics

**Try it yourself:**

```bash
selqor-mcp-forge generate https://petstore.swagger.io/v2/swagger.json --out ./my-petstore
```

Then compare your outputs to `examples/petstore/` to see what the tool does.

### Real-World APIs to Try

1. **GitHub API** (~300 endpoints)

   ```bash
   selqor-mcp-forge generate https://raw.githubusercontent.com/github/rest-api-description/main/openapi.json --out ./github-output
   ```

2. **Stripe API** (~600 endpoints)

   ```bash
   selqor-mcp-forge generate https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json --out ./stripe-output
   ```

3. **Your Own API** (local file)
   ```bash
   selqor-mcp-forge generate ./my-api-spec.yaml --out ./my-api-output
   ```

---

## More Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — How to contribute
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — Community guidelines
- [SECURITY.md](SECURITY.md) — Security policy and how to report vulnerabilities
- [docs/AUTH_MODULE_INTEGRATION.md](docs/AUTH_MODULE_INTEGRATION.md) — How to integrate your own auth system

---

## Known Limitations

- ⚠️ **Placeholder Authentication** — Not for multi-user deployments. See [AUTH_MODULE_INTEGRATION.md](docs/AUTH_MODULE_INTEGRATION.md) to implement real auth.
- ⚠️ **Rust HTTP Transport** — Experimental; `stdio` is production-ready.
- ⚠️ **Large Specs (500+ endpoints)** — Analysis can take 5+ minutes; normal and expected.
- ⚠️ **LLM Costs** — Each analysis costs ~$0.20-$2.00 depending on spec size. Monitor your API usage.

---

## Security Scanning & Compliance

### AI-Powered OWASP Analysis

Selqor Forge uses LLM-powered analysis to evaluate generated MCP tools against the OWASP Agentic Top 10:

- **A01: Unsafe Tool Definition** — Detects overly permissive tool descriptions
- **A02: Unsafe Tool Chaining** — Identifies risky tool combinations
- **A03: Data Handling Risks** — Checks for PII/sensitive data exposure
- **A04: Inadequate Authorization** — Validates authentication patterns
- **A05: Excessive Agency** — Warns about tools with too much autonomy
- **A06: Prompt Injection** — Detects injection patterns in tool descriptions
- **A07: Unsafe Plugin Integration** — Checks third-party tool safety
- **A08: Insecure Output Handling** — Validates response sanitization
- **A09: Overcompliance** — Flags tools that over-filter legitimate requests
- **A10: Insufficient Monitoring** — Recommends observability patterns

### CLI Scanning

Scan MCP servers and dependencies for security vulnerabilities:

```bash
# Quick scan (heuristic + CVE checking)
selqor-mcp-forge scan ./my-mcp-server --out ./scan-results --format json

# Scan from GitHub repository
selqor-mcp-forge scan https://github.com/user/repo --out ./scan-results --format json

# Scan running server
selqor-mcp-forge scan http://localhost:3000 --out ./scan-results --format json

# Full scan with LLM OWASP analysis + Trivy + heuristics
selqor-mcp-forge scan ./server --full --format json,pdf

# Add Semgrep pattern matching rules
selqor-mcp-forge scan ./server --full --semgrep --format json

# Skip LLM analysis (cost savings, faster)
selqor-mcp-forge scan ./server --full --no-llm --format json
```

**Output Formats:** `json`, `markdown`, `spdx`, `pdf`

**Scan Behavior:**
- **Default (Quick):** Heuristic patterns + CVE database checking + license analysis
- **--full:** Adds OWASP Agentic Top 10 (LLM), Trivy deep scanning, AI Bill of Materials
- **--semgrep:** Requires Semgrep CLI installed; adds advanced pattern matching
- **--no-llm:** Disables LLM analysis to reduce costs

---

## Advanced Workflows

### Playground Testing

Test generated tools interactively before deployment:

1. Go to **Playground** tab
2. Connect to an MCP server (stdio or HTTP)
3. Browse available tools
4. Test tools with real API calls
5. Debug authentication and payload issues
6. Review execution results and logs

### CI/CD Integration

Automate security scanning in your deployment pipeline using webhooks:

**1. Register your CI/CD project:**

```bash
curl -X POST http://localhost:8787/api/cicd/webhooks/register \
  -H "Content-Type: application/json" \
  -d '{"project_name": "my-project"}'
```

Response includes `webhook_secret` and `webhook_url`.

**2. Generate CI/CD config files:**

```bash
curl -X POST http://localhost:8787/api/cicd/generate \
  -H "Content-Type: application/json" \
  -d '{
    "source_path": ".",
    "targets": ["github_actions"],
    "output_formats": ["json", "pdf"],
    "scan_threshold": 70
  }'
```

**3. Your CI/CD pipeline posts results back:**

```bash
curl -X POST http://localhost:8787/api/cicd/webhooks/ingest \
  -H "Content-Type: application/json" \
  -H "X-Forge-Signature: sha256=<HMAC-SHA256 of body using webhook_secret>" \
  -d '{"project_name": "my-project", "scan_results": {...}}'
```

**View CI/CD runs and dashboard:**

```bash
curl http://localhost:8787/api/cicd/runs
curl http://localhost:8787/api/cicd/badge/my-project  # Get compliance badge
```

---

## Monitoring & Observability

### Built-in Monitoring Dashboard

- **Run History** — Track all scans and analyses with timestamps
- **Performance Metrics** — Analysis time, LLM token usage, security scores
- **Notifications** — Alerts for scan completion and critical security findings
- **Reports** — Export reports as JSON, CSV, PDF from the dashboard

---

## Getting Help

- **Bug Reports:** [GitHub Issues](https://github.com/Selqor-Labs/Selqor-MCP-Forge/issues)
- **Security Issues:** See [SECURITY.md](SECURITY.md)
- **Questions:** [GitHub Discussions](https://github.com/Selqor-Labs/Selqor-MCP-Forge/discussions)
- **Support:** See [SUPPORT.md](SUPPORT.md)

## License

Selqor Forge is licensed under [Apache-2.0](LICENSE).

If you build on Selqor Forge, attribution such as `Powered by Selqor Labs` is
appreciated but not required.

# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Template strings for generated TypeScript and Rust MCP server scaffolds."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# TypeScript templates
# ---------------------------------------------------------------------------


def ts_package_json() -> str:
    """Return a package.json for the generated TypeScript MCP server."""
    return """\
{
  "name": "forge-generated-server",
  "version": "0.1.0",
  "license": "Apache-2.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "tsx src/index.ts",
    "build": "tsc -p tsconfig.json",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "1.29.0",
    "express": "4.22.1"
  },
  "devDependencies": {
    "@types/express": "4.17.21",
    "@types/node": "24.3.0",
    "tsx": "4.20.5",
    "typescript": "5.9.2"
  }
}
"""


def ts_tsconfig() -> str:
    """Return a tsconfig.json for the generated TypeScript MCP server."""
    return """\
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "types": ["node"]
  },
  "include": ["src/**/*.ts"]
}
"""


def ts_env_example() -> str:
    """Return a .env.example for the generated TypeScript MCP server."""
    return """\
# Required
FORGE_BASE_URL=https://api.example.com

# Optional auth
FORGE_BEARER_TOKEN=
FORGE_API_KEY=
FORGE_API_KEY_HEADER=x-api-key
FORGE_API_KEY_QUERY_NAME=api_key
FORGE_BASIC_USER=
FORGE_BASIC_PASSWORD=
FORGE_TOKEN_HEADER=Authorization
FORGE_TOKEN_VALUE=
FORGE_TOKEN_PREFIX=Bearer
FORGE_DYNAMIC_TOKEN_URL=
FORGE_DYNAMIC_TOKEN_METHOD=POST
FORGE_DYNAMIC_TOKEN_BODY_JSON={}
FORGE_DYNAMIC_TOKEN_HEADERS_JSON={}
FORGE_DYNAMIC_TOKEN_RESPONSE_PATH=access_token
FORGE_DYNAMIC_TOKEN_EXPIRY_SECONDS=3600
FORGE_DYNAMIC_TOKEN_EXPIRY_PATH=
FORGE_DYNAMIC_TOKEN_HEADER_NAME=Authorization
FORGE_DYNAMIC_TOKEN_HEADER_PREFIX=Bearer
FORGE_STATIC_HEADERS_JSON={}
FORGE_OAUTH_TOKEN_URL=
FORGE_OAUTH_CLIENT_ID=
FORGE_OAUTH_CLIENT_SECRET=
FORGE_OAUTH_SCOPE=
FORGE_OAUTH_AUDIENCE=

# Transport: stdio or http
FORGE_TRANSPORT=stdio
FORGE_HTTP_PORT=3333
FORGE_HTTP_AUTH_TOKEN=
FORGE_HTTP_RATE_LIMIT_WINDOW_MS=60000
FORGE_HTTP_RATE_LIMIT_MAX=120
FORGE_ALLOW_PRIVATE_HOSTS=false

# Resilience
FORGE_REQUEST_TIMEOUT_MS=15000
FORGE_MAX_RETRIES=3
FORGE_RETRY_BASE_MS=500
FORGE_CB_FAILURE_THRESHOLD=5
FORGE_CB_RESET_MS=30000
"""


def ts_readme() -> str:
    """Return a README.md for the generated TypeScript MCP server."""
    return """\
# Generated TypeScript MCP Server

Licensed under Apache-2.0. See the root project LICENSE for details.

## Run

```bash
npm install
npm run dev
```

## Notes
- Set `FORGE_BASE_URL` and auth env vars before running.
- `FORGE_TRANSPORT=stdio` runs local stdio transport.
- `FORGE_TRANSPORT=http` runs HTTP/SSE transport at `/sse` and `/messages`.
- HTTP transport requires `FORGE_HTTP_AUTH_TOKEN` and applies basic in-memory rate limiting.
- `FORGE_ALLOW_PRIVATE_HOSTS=true` is available for trusted internal APIs and token endpoints.
- Optional attribution to Selqor Labs is appreciated but not required.
"""


def ts_index(default_transport: str) -> str:
    """Return src/index.ts for the generated TypeScript MCP server."""
    template = """\
/*
 * Copyright (c) Selqor Labs.
 * Licensed under the Apache License, Version 2.0.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import express from "express";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

type JsonObject = Record<string, unknown>;

type ToolDef = {
  name: string;
  description: string;
  covered_endpoints: string[];
  input_schema: JsonObject;
};

type EndpointDef = {
  id: string;
  method: string;
  path: string;
  summary?: string;
  description?: string;
  domain?: string;
  tags?: string[];
  security: string[];
};

type ToolPlan = {
  tools: ToolDef[];
  endpoint_catalog: Record<string, EndpointDef>;
};

const __dirname = dirname(fileURLToPath(import.meta.url));
const planPath = existsSync(join(__dirname, "plan.json"))
  ? join(__dirname, "plan.json")
  : join(__dirname, "..", "src", "plan.json");
const plan = JSON.parse(
  readFileSync(planPath, "utf-8")
) as ToolPlan;

const rawBaseUrl = process.env.FORGE_BASE_URL ?? "";
const defaultTransport = "{{DEFAULT_TRANSPORT}}";
const allowPrivateHosts = (process.env.FORGE_ALLOW_PRIVATE_HOSTS ?? "false").toLowerCase() === "true";
const baseUrl = rawBaseUrl
  ? validateConfiguredUrl(rawBaseUrl, "FORGE_BASE_URL")
  : "";

const server = new Server(
  {
    name: "forge-generated-server",
    version: "0.1.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: plan.tools.map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.input_schema,
    })),
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const tool = plan.tools.find((candidate) => candidate.name === request.params.name);
  if (!tool) {
    return {
      isError: true,
      content: [{ type: "text", text: `Unknown tool: ${request.params.name}` }],
    };
  }

  const args = (request.params.arguments ?? {}) as JsonObject;

  if (tool.name === "search_api") {
    const query = getString(args.query)?.trim();
    if (!query) {
      return {
        isError: true,
        content: [{ type: "text", text: "search_api requires query" }],
      };
    }

    const limit = getInteger(args.limit) ?? 10;
    const matches = findSearchMatches(query, tool.covered_endpoints);
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          query,
          total_matches: matches.length,
          matches: matches.slice(0, Math.max(1, Math.min(limit, 25))),
          next_step: "Call execute_overflow_operation with one of the returned operation ids to execute it.",
        }, null, 2),
      }],
    };
  }

  if (tool.name === "custom_request") {
    const method = getString(args.method)?.toUpperCase();
    const path = getString(args.path);
    if (!method || !path) {
      return {
        isError: true,
        content: [{ type: "text", text: "custom_request requires method and path" }],
      };
    }

    const result = await rawRequest({
      method,
      path,
      query: asRecord(args.query),
      headers: asRecord(args.headers),
      body: args.body,
    });

    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    };
  }

  const operation = tool.covered_endpoints.length === 1
    ? tool.covered_endpoints[0]
    : getString(args.operation);
  if (!operation) {
    return {
      isError: true,
      content: [{ type: "text", text: `Tool ${tool.name} requires an explicit operation` }],
    };
  }

  const result = await executeOperation(operation, args);
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
  };
});

function getString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function getInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

type SearchMatch = {
  operation: string;
  method: string;
  path: string;
  summary: string;
  domain: string;
  score: number;
};

async function executeOperation(operation: string, args: JsonObject): Promise<unknown> {
  const endpoint = plan.endpoint_catalog[operation];
  if (!endpoint) {
    throw new Error(`Unknown operation: ${operation}`);
  }

  return rawRequest({
    method: endpoint.method.toUpperCase(),
    path: endpoint.path,
    pathParams: asRecord(args.path_params),
    query: asRecord(args.query),
    headers: asRecord(args.headers),
    body: args.body,
  });
}

function tokenizeSearchQuery(query: string): string[] {
  return [...new Set(
    query
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .map((part) => part.trim())
      .filter((part) => part.length >= 2)
  )];
}

function findSearchMatches(query: string, operationIds: string[]): SearchMatch[] {
  const normalizedQuery = query.trim().toLowerCase();
  const terms = tokenizeSearchQuery(query);

  const matches = operationIds.flatMap((operation) => {
    const endpoint = plan.endpoint_catalog[operation];
    if (!endpoint) {
      return [];
    }

    const searchableParts = [
      operation,
      endpoint.method,
      endpoint.path,
      endpoint.summary ?? "",
      endpoint.description ?? "",
      endpoint.domain ?? "",
      ...(endpoint.tags ?? []),
    ].map((value) => value.toLowerCase());

    let score = 0;
    for (const part of searchableParts) {
      if (!part) {
        continue;
      }
      if (part.includes(normalizedQuery)) {
        score += 5;
      }
      for (const term of terms) {
        if (part.includes(term)) {
          score += 1;
        }
      }
    }

    if (score === 0) {
      return [];
    }

    return [{
      operation,
      method: endpoint.method.toUpperCase(),
      path: endpoint.path,
      summary: endpoint.summary ?? endpoint.description ?? "",
      domain: endpoint.domain ?? "",
      score,
    }];
  });

  return matches.sort((left, right) => (
    right.score - left.score ||
    left.operation.localeCompare(right.operation)
  ));
}

type RequestArgs = {
  method: string;
  path: string;
  pathParams?: Record<string, unknown>;
  query?: Record<string, unknown>;
  headers?: Record<string, unknown>;
  body?: unknown;
};

type OAuthTokenCache = {
  token: string;
  expiresAt: number;
};

type DynamicTokenCache = {
  token: string;
  expiresAt: number;
  headerName: string;
  headerPrefix: string;
};

let oauthTokenCache: OAuthTokenCache | null = null;
let dynamicTokenCache: DynamicTokenCache | null = null;

// ---------------------------------------------------------------------------
// Resilience: configurable timeout, retries with backoff, circuit breaker
// ---------------------------------------------------------------------------

const REQUEST_TIMEOUT_MS = Number(process.env.FORGE_REQUEST_TIMEOUT_MS ?? "15000");
const MAX_RETRIES = Number(process.env.FORGE_MAX_RETRIES ?? "3");
const RETRY_BASE_MS = Number(process.env.FORGE_RETRY_BASE_MS ?? "500");
const CB_FAILURE_THRESHOLD = Number(process.env.FORGE_CB_FAILURE_THRESHOLD ?? "5");
const CB_RESET_MS = Number(process.env.FORGE_CB_RESET_MS ?? "30000");

type CircuitState = "closed" | "open" | "half_open";
let cbState: CircuitState = "closed";
let cbFailures = 0;
let cbLastFailure = 0;

function circuitCheck(): void {
  if (cbState === "open") {
    if (Date.now() - cbLastFailure >= CB_RESET_MS) {
      cbState = "half_open";
      log("info", "circuit_breaker", "half-open — allowing probe request");
    } else {
      throw new Error("Circuit breaker OPEN — target API unavailable, retry later");
    }
  }
}

function circuitSuccess(): void {
  if (cbState === "half_open") {
    log("info", "circuit_breaker", "closed — target API recovered");
  }
  cbFailures = 0;
  cbState = "closed";
}

function circuitFailure(): void {
  cbFailures++;
  cbLastFailure = Date.now();
  if (cbFailures >= CB_FAILURE_THRESHOLD) {
    cbState = "open";
    log("warn", "circuit_breaker", `open after ${cbFailures} consecutive failures`);
  }
}

function log(level: "info" | "warn" | "error", component: string, msg: string, extra?: Record<string, unknown>): void {
  const entry = { ts: new Date().toISOString(), level, component, msg, ...extra };
  console.error(JSON.stringify(entry));
}

function validateConfiguredUrl(value: string, envName: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${envName} must be a valid absolute URL`);
  }

  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error(`${envName} must use http or https`);
  }

  if (!parsed.hostname) {
    throw new Error(`${envName} must include a hostname`);
  }

  if (!allowPrivateHosts && isBlockedHostname(parsed.hostname)) {
    throw new Error(`${envName} points to a private or loopback host; set FORGE_ALLOW_PRIVATE_HOSTS=true only for trusted internal targets`);
  }

  return parsed.toString();
}

function isBlockedHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  if (normalized === "localhost" || normalized.endsWith(".localhost")) {
    return true;
  }
  if (normalized === "::1") {
    return true;
  }
  if (normalized.startsWith("[") && normalized.endsWith("]")) {
    return isBlockedHostname(normalized.slice(1, -1));
  }

  if (/^\\d+\\.\\d+\\.\\d+\\.\\d+$/.test(normalized)) {
    const octets = normalized.split(".").map((part) => Number(part));
    const [first, second] = octets;
    return (
      first === 0 ||
      first === 10 ||
      first === 127 ||
      (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168)
    );
  }

  return false;
}

function validateRelativePath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) {
    throw new Error("Request path is required");
  }
  if (trimmed.includes("://") || trimmed.startsWith("//")) {
    throw new Error("Request path must be relative to FORGE_BASE_URL");
  }
  if (/[\\r\\n]/.test(trimmed)) {
    throw new Error("Request path contains invalid control characters");
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function buildApiUrl(path: string, query: URLSearchParams): URL {
  const targetApiUrl = new URL(baseUrl);
  targetApiUrl.pathname = `${targetApiUrl.pathname.replace(/\\/+$/, "")}${validateRelativePath(path)}`;
  targetApiUrl.search = query.toString();
  return targetApiUrl;
}

async function rawRequest(args: RequestArgs): Promise<unknown> {
  if (!baseUrl) {
    throw new Error("FORGE_BASE_URL is required");
  }

  circuitCheck();

  const path = validateRelativePath(substitutePathParams(args.path, args.pathParams ?? {}));
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(args.query ?? {})) {
    if (value !== null && value !== undefined) {
      query.set(key, String(value));
    }
  }

  const headers: Record<string, string> = {
    ...(toStringRecord(args.headers ?? {})),
  };

  await applyAuth(headers, query);
  const targetApiUrl = buildApiUrl(path, query);
  if (args.body !== undefined && args.body !== null) {
    headers["content-type"] = headers["content-type"] ?? "application/json";
  }

  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      const delay = RETRY_BASE_MS * Math.pow(2, attempt - 1) + Math.random() * 100;
      log("info", "http", `retry ${attempt}/${MAX_RETRIES} after ${Math.round(delay)}ms`, { url: targetApiUrl.toString(), method: args.method });
      await new Promise((r) => setTimeout(r, delay));
      circuitCheck();
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const started = Date.now();
      const response = await fetch(targetApiUrl.toString(), {
        method: args.method,
        headers,
        body: args.body === undefined || args.body === null ? undefined : JSON.stringify(args.body),
        signal: controller.signal,
      });
      clearTimeout(timer);
      const latency = Date.now() - started;

      const text = await response.text();
      let payload: unknown = text;
      try {
        payload = text ? JSON.parse(text) : {};
      } catch {
        payload = text;
      }

      if (!response.ok) {
        const err = new Error(`HTTP ${response.status}: ${JSON.stringify(payload)}`);
        // Only retry on 429 or 5xx
        if (response.status === 429 || response.status >= 500) {
          lastError = err;
          circuitFailure();
          log("warn", "http", `request failed (retryable)`, { status: response.status, latency, attempt });
          continue;
        }
        circuitSuccess();
        throw err;
      }

      circuitSuccess();
      log("info", "http", "request ok", { status: response.status, latency, method: args.method, path: args.path });
      return payload;
    } catch (err) {
      clearTimeout(timer);
      const error = err instanceof Error ? err : new Error(String(err));
      if (error.name === "AbortError") {
        lastError = new Error(`Request timed out after ${REQUEST_TIMEOUT_MS}ms`);
        circuitFailure();
        log("warn", "http", "request timeout", { timeout: REQUEST_TIMEOUT_MS, attempt });
        continue;
      }
      if (error.message.startsWith("Circuit breaker")) {
        throw error;
      }
      lastError = error;
      circuitFailure();
      log("warn", "http", `request error: ${error.message}`, { attempt });
      if (attempt < MAX_RETRIES) continue;
    }
  }

  throw lastError ?? new Error("Request failed after retries");
}

function substitutePathParams(path: string, params: Record<string, unknown>): string {
  return path.replace(/\\{([^}]+)\\}/g, (_, key: string) => {
    const value = params[key];
    if (value === undefined || value === null) {
      throw new Error(`Missing path parameter: ${key}`);
    }
    return encodeURIComponent(String(value));
  });
}

function toStringRecord(source: Record<string, unknown>): Record<string, string> {
  const result: Record<string, string> = {};
  const blockedHeaders = new Set([
    "connection",
    "content-length",
    "host",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
  ]);
  for (const [key, value] of Object.entries(source)) {
    if (value !== undefined && value !== null) {
      const normalizedKey = key.trim().toLowerCase();
      if (!normalizedKey || !/^[a-z0-9-]+$/.test(normalizedKey)) {
        continue;
      }
      if (blockedHeaders.has(normalizedKey)) {
        continue;
      }
      result[normalizedKey] = String(value);
    }
  }
  return result;
}

async function applyAuth(headers: Record<string, string>, query: URLSearchParams): Promise<void> {
  const staticHeaders = parseStaticHeaders();
  for (const [key, value] of Object.entries(staticHeaders)) {
    headers[key.toLowerCase()] = value;
  }

  const oauthToken = await getOAuthToken();
  if (oauthToken) {
    headers.authorization = `Bearer ${oauthToken}`;
  }

  const dynamicToken = await getDynamicTokenHeader();
  if (dynamicToken) {
    headers[dynamicToken.headerName.toLowerCase()] = dynamicToken.headerValue;
  }

  const bearer = process.env.FORGE_BEARER_TOKEN;
  if (bearer) {
    headers.authorization = `Bearer ${bearer}`;
  }

  const apiKey = process.env.FORGE_API_KEY;
  const apiKeyHeader = process.env.FORGE_API_KEY_HEADER;
  if (apiKey && apiKeyHeader) {
    headers[apiKeyHeader.toLowerCase()] = apiKey;
  }

  const apiQueryName = process.env.FORGE_API_KEY_QUERY_NAME;
  if (apiKey && apiQueryName) {
    query.set(apiQueryName, apiKey);
  }

  const basicUser = process.env.FORGE_BASIC_USER;
  const basicPassword = process.env.FORGE_BASIC_PASSWORD;
  if (basicUser && basicPassword) {
    const token = Buffer.from(`${basicUser}:${basicPassword}`).toString("base64");
    headers.authorization = `Basic ${token}`;
  }

  const tokenHeader = process.env.FORGE_TOKEN_HEADER;
  const tokenValue = process.env.FORGE_TOKEN_VALUE;
  const tokenPrefix = process.env.FORGE_TOKEN_PREFIX;
  if (tokenHeader && tokenValue) {
    headers[tokenHeader.toLowerCase()] = tokenPrefix
      ? `${tokenPrefix} ${tokenValue}`
      : tokenValue;
  }
}

function parseStaticHeaders(): Record<string, string> {
  const raw = process.env.FORGE_STATIC_HEADERS_JSON;
  if (!raw) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw);
    return toStringRecord(parsed && typeof parsed === "object" ? parsed : {});
  } catch {
    return {};
  }
}

function parseJsonEnv(raw: string | undefined): unknown {
  if (!raw || !raw.trim()) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function getPathValue(source: unknown, path: string): unknown {
  if (!source || typeof source !== "object") {
    return undefined;
  }
  const normalized = path.trim().replace(/^\\$\\.?/, "");
  if (!normalized) {
    return undefined;
  }
  const parts = normalized.split(".").filter(Boolean);
  let current: unknown = source;
  for (const part of parts) {
    if (Array.isArray(current)) {
      const index = Number(part);
      if (!Number.isInteger(index)) {
        return undefined;
      }
      current = current[index];
      continue;
    }
    if (!current || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

async function getDynamicTokenHeader(): Promise<{ headerName: string; headerValue: string } | null> {
  const tokenUrl = process.env.FORGE_DYNAMIC_TOKEN_URL;
  if (!tokenUrl) {
    return null;
  }
  const validatedTokenUrl = validateConfiguredUrl(tokenUrl, "FORGE_DYNAMIC_TOKEN_URL");

  const headerName = process.env.FORGE_DYNAMIC_TOKEN_HEADER_NAME || "Authorization";
  const headerPrefix = process.env.FORGE_DYNAMIC_TOKEN_HEADER_PREFIX || "Bearer";
  const now = Date.now();
  if (dynamicTokenCache && dynamicTokenCache.expiresAt > now + 10_000) {
    const headerValue = dynamicTokenCache.headerPrefix
      ? `${dynamicTokenCache.headerPrefix} ${dynamicTokenCache.token}`
      : dynamicTokenCache.token;
    return { headerName: dynamicTokenCache.headerName, headerValue };
  }

  const method = (process.env.FORGE_DYNAMIC_TOKEN_METHOD || "POST").toUpperCase();
  const requestBody = parseJsonEnv(process.env.FORGE_DYNAMIC_TOKEN_BODY_JSON);
  const requestHeaders = toStringRecord(parseJsonEnv(process.env.FORGE_DYNAMIC_TOKEN_HEADERS_JSON) as Record<string, unknown>);
  const responsePath = process.env.FORGE_DYNAMIC_TOKEN_RESPONSE_PATH || "access_token";
  const expiryPath = process.env.FORGE_DYNAMIC_TOKEN_EXPIRY_PATH;
  const defaultExpiry = Number(process.env.FORGE_DYNAMIC_TOKEN_EXPIRY_SECONDS || "3600");

  const options: RequestInit = {
    method,
    headers: {
      "content-type": "application/json",
      ...requestHeaders,
    },
  };

  const tokenEndpoint = new URL(validatedTokenUrl);
  if (method === "GET") {
    const query = new URLSearchParams();
    const data = requestBody && typeof requestBody === "object"
      ? requestBody as Record<string, unknown>
      : {};
    for (const [key, value] of Object.entries(data)) {
      if (value !== null && value !== undefined) {
        query.set(key, String(value));
      }
    }
    tokenEndpoint.search = query.toString();
  } else {
    options.body = JSON.stringify(requestBody || {});
  }

  const response = await fetch(tokenEndpoint.href, options);
  if (!response.ok) {
    throw new Error(`Dynamic token request failed: ${response.status}`);
  }

  const payload = await response.json() as unknown;
  const tokenValue = getPathValue(payload, responsePath);
  if (!tokenValue) {
    throw new Error(`Dynamic token response path not found: ${responsePath}`);
  }

  const token = String(tokenValue);
  let expirySeconds = Number.isFinite(defaultExpiry) && defaultExpiry > 0 ? defaultExpiry : 3600;
  if (expiryPath) {
    const expiryValue = getPathValue(payload, expiryPath);
    const parsedExpiry = Number(expiryValue);
    if (Number.isFinite(parsedExpiry) && parsedExpiry > 0) {
      expirySeconds = parsedExpiry;
    }
  }

  dynamicTokenCache = {
    token,
    expiresAt: now + (expirySeconds * 1000),
    headerName,
    headerPrefix,
  };

  const headerValue = headerPrefix ? `${headerPrefix} ${token}` : token;
  return { headerName, headerValue };
}

async function getOAuthToken(): Promise<string | null> {
  const tokenUrl = process.env.FORGE_OAUTH_TOKEN_URL;
  const clientId = process.env.FORGE_OAUTH_CLIENT_ID;
  const clientSecret = process.env.FORGE_OAUTH_CLIENT_SECRET;
  if (!tokenUrl || !clientId || !clientSecret) {
    return null;
  }
  const oauthEndpoint = new URL(validateConfiguredUrl(tokenUrl, "FORGE_OAUTH_TOKEN_URL"));

  const now = Date.now();
  if (oauthTokenCache && oauthTokenCache.expiresAt > now + 10_000) {
    return oauthTokenCache.token;
  }

  const form = new URLSearchParams();
  form.set("grant_type", "client_credentials");
  form.set("client_id", clientId);
  form.set("client_secret", clientSecret);

  const scope = process.env.FORGE_OAUTH_SCOPE;
  const audience = process.env.FORGE_OAUTH_AUDIENCE;
  if (scope) {
    form.set("scope", scope);
  }
  if (audience) {
    form.set("audience", audience);
  }

  const response = await fetch(oauthEndpoint.href, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
    },
    body: form.toString(),
  });

  if (!response.ok) {
    throw new Error(`OAuth token request failed: ${response.status}`);
  }

  const payload = await response.json() as {
    access_token?: string;
    expires_in?: number;
    token_type?: string;
  };
  if (!payload.access_token) {
    throw new Error("OAuth token response missing access_token");
  }

  const ttl = typeof payload.expires_in === "number" ? payload.expires_in : 3600;
  oauthTokenCache = {
    token: payload.access_token,
    expiresAt: now + (ttl * 1000),
  };

  return payload.access_token;
}

const startedAt = new Date().toISOString();

async function runStdio(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  log("info", "transport", "connected over stdio");
}

async function runHttp(): Promise<void> {
  const app = express();
  app.use(express.json({ limit: "2mb" }));
  const httpAuthToken = process.env.FORGE_HTTP_AUTH_TOKEN;
  if (!httpAuthToken) {
    throw new Error("FORGE_HTTP_AUTH_TOKEN is required when FORGE_TRANSPORT=http");
  }
  const rateLimiter = createRateLimiter();

  let transport: SSEServerTransport | null = null;

  function requireHttpAuth(req: express.Request, res: express.Response, next: express.NextFunction): void {
    const header = req.header("authorization") ?? req.header("x-forge-auth") ?? "";
    const expectedBearer = `Bearer ${httpAuthToken}`;
    if (header !== httpAuthToken && header !== expectedBearer) {
      res.status(401).json({ error: "HTTP transport requires a valid FORGE_HTTP_AUTH_TOKEN" });
      return;
    }
    next();
  }

  // Health endpoint for monitoring
  app.get("/health", rateLimiter, (_req, res) => {
    res.json({
      status: "healthy",
      started_at: startedAt,
      uptime_seconds: Math.round((Date.now() - new Date(startedAt).getTime()) / 1000),
      tools: plan.tools.length,
      circuit_breaker: cbState,
      base_url: baseUrl ? "configured" : "missing",
    });
  });

  app.get("/sse", rateLimiter, requireHttpAuth, async (_req, res) => {
    transport = new SSEServerTransport("/messages", res);
    await server.connect(transport);
  });

  app.post("/messages", rateLimiter, requireHttpAuth, async (req, res) => {
    if (!transport) {
      res.status(400).json({ error: "No active SSE transport. Connect /sse first." });
      return;
    }

    await transport.handlePostMessage(req, res, req.body);
  });

  const port = Number(process.env.FORGE_HTTP_PORT ?? "3333");
  const httpServer = app.listen(port, () => {
    log("info", "transport", `HTTP server listening on port ${port}`);
  });

  // Graceful shutdown
  function shutdown(signal: string) {
    log("info", "lifecycle", `${signal} received — shutting down`);
    httpServer.close(() => {
      log("info", "lifecycle", "HTTP server closed");
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 5000);
  }
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
}

function createRateLimiter(): express.RequestHandler {
  const windowMs = Number(process.env.FORGE_HTTP_RATE_LIMIT_WINDOW_MS ?? "60000");
  const maxRequests = Number(process.env.FORGE_HTTP_RATE_LIMIT_MAX ?? "120");
  const safeWindowMs = Number.isFinite(windowMs) && windowMs > 0 ? windowMs : 60000;
  const safeMaxRequests = Number.isFinite(maxRequests) && maxRequests > 0 ? maxRequests : 120;
  const counters = new Map<string, { count: number; resetAt: number }>();

  return (req, res, next) => {
    const now = Date.now();
    const clientKey = req.ip || req.socket.remoteAddress || "unknown";
    const existing = counters.get(clientKey);

    if (!existing || existing.resetAt <= now) {
      counters.set(clientKey, { count: 1, resetAt: now + safeWindowMs });
      next();
      return;
    }

    existing.count += 1;
    if (existing.count > safeMaxRequests) {
      const retryAfterSeconds = Math.max(1, Math.ceil((existing.resetAt - now) / 1000));
      res.setHeader("retry-after", String(retryAfterSeconds));
      res.status(429).json({ error: "Rate limit exceeded" });
      return;
    }

    next();
  };
}

const transport = (process.env.FORGE_TRANSPORT ?? defaultTransport).toLowerCase();
if (transport === "http") {
  runHttp().catch((error) => {
    log("error", "startup", error.message);
    process.exit(1);
  });
} else {
  runStdio().catch((error) => {
    log("error", "startup", error.message);
    process.exit(1);
  });
}
"""
    return template.replace("{{DEFAULT_TRANSPORT}}", default_transport)


# ---------------------------------------------------------------------------
# Rust templates
# ---------------------------------------------------------------------------


def rust_cargo_toml() -> str:
    """Return a Cargo.toml for the generated Rust MCP server."""
    return """\
[package]
name = "forge_generated_server"
version = "0.1.0"
edition = "2024"

[dependencies]
anyhow = "1.0"
reqwest = { version = "0.12", default-features = false, features = ["blocking", "json", "rustls-tls"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
url = "2.5"
"""


def rust_readme() -> str:
    """Return a README.md for the generated Rust MCP server."""
    return """\
# Generated Rust MCP Server

Licensed under Apache-2.0. See the root project LICENSE for details.

## Run

```bash
cargo run
```

## Notes
- Transport defaults to stdio.
- HTTP transport is scaffold-only in this template.
- Set `FORGE_BASE_URL` and auth env vars before use.
- Optional attribution to Selqor Labs is appreciated but not required.
"""


def rust_main(default_transport: str) -> str:
    """Return src/main.rs for the generated Rust MCP server."""
    template = """\
// Copyright (c) Selqor Labs.
// Licensed under the Apache License, Version 2.0.
use std::{
    collections::BTreeMap,
    io::{self, BufRead, Write},
};

use anyhow::{Context, Result};
use reqwest::blocking::Client;
use serde::Deserialize;
use serde_json::{Value, json};
use url::Url;

#[derive(Debug, Deserialize)]
struct ToolPlan {
    tools: Vec<ToolDefinition>,
    endpoint_catalog: BTreeMap<String, EndpointDefinition>,
}

#[derive(Debug, Deserialize)]
struct ToolDefinition {
    name: String,
    description: String,
    covered_endpoints: Vec<String>,
    input_schema: Value,
}

#[derive(Debug, Deserialize)]
struct EndpointDefinition {
    method: String,
    path: String,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    domain: String,
    #[serde(default)]
    tags: Vec<String>,
    security: Vec<String>,
}

fn main() -> Result<()> {
    let transport = std::env::var("FORGE_TRANSPORT").unwrap_or_else(|_| "{{DEFAULT_TRANSPORT}}".to_string());
    if transport.eq_ignore_ascii_case("http") {
        eprintln!("HTTP transport scaffold is not implemented for the Rust target yet. Use stdio.");
    }

    run_stdio()
}

fn run_stdio() -> Result<()> {
    let plan: ToolPlan = serde_json::from_str(include_str!("plan.json"))
        .context("failed to parse embedded plan.json")?;

    let stdin = io::stdin();
    let mut reader = io::BufReader::new(stdin.lock());
    let mut stdout = io::stdout();

    loop {
        let Some(message) = read_message(&mut reader)? else {
            break;
        };

        if let Some(response) = handle_message(&plan, message)? {
            write_message(&mut stdout, &response)?;
        }
    }

    Ok(())
}

fn handle_message(plan: &ToolPlan, message: Value) -> Result<Option<Value>> {
    let method = message.get("method").and_then(Value::as_str).unwrap_or("");
    let id = message.get("id").cloned();

    match method {
        "initialize" => Ok(id.map(|request_id| {
            json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "tools": {
                            "listChanged": false
                        }
                    },
                    "serverInfo": {
                        "name": "forge-generated-rust-server",
                        "version": "0.1.0"
                    }
                }
            })
        })),
        "tools/list" => Ok(id.map(|request_id| {
            let tools = plan
                .tools
                .iter()
                .map(|tool| {
                    json!({
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema
                    })
                })
                .collect::<Vec<_>>();

            json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            })
        })),
        "tools/call" => Ok(id.map(|request_id| {
            let result = execute_tool_call(plan, message.get("params")).unwrap_or_else(|error| {
                json!({
                    "isError": true,
                    "content": [{"type": "text", "text": format!("{}", error)}]
                })
            });

            json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            })
        })),
        _ => Ok(None),
    }
}

fn execute_tool_call(plan: &ToolPlan, params: Option<&Value>) -> Result<Value> {
    let params = params.and_then(Value::as_object).context("missing tool params")?;
    let tool_name = params
        .get("name")
        .and_then(Value::as_str)
        .context("missing tool name")?;

    let arguments = params
        .get("arguments")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let tool = plan
        .tools
        .iter()
        .find(|tool| tool.name == tool_name);

    if tool_name == "custom_request" {
        let method = arguments
            .get("method")
            .and_then(Value::as_str)
            .context("custom_request requires method")?;
        let path = arguments
            .get("path")
            .and_then(Value::as_str)
            .context("custom_request requires path")?;

        let result = execute_http_request(method, path, &arguments, None)?;
        return Ok(json!({
            "content": [{"type": "text", "text": serde_json::to_string_pretty(&result)?}]
        }));
    }

    if tool_name == "search_api" {
        let tool = tool.context("tool not found")?;
        let query = arguments
            .get("query")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .context("search_api requires query")?;
        let limit = arguments
            .get("limit")
            .and_then(Value::as_i64)
            .unwrap_or(10)
            .clamp(1, 25);

        let matches = find_search_matches(plan, &tool.covered_endpoints, query);
        return Ok(json!({
            "content": [{
                "type": "text",
                "text": serde_json::to_string_pretty(&json!({
                    "query": query,
                    "total_matches": matches.len(),
                    "matches": matches.into_iter().take(limit as usize).collect::<Vec<_>>(),
                    "next_step": "Call execute_overflow_operation with one of the returned operation ids to execute it."
                }))?
            }]
        }));
    }

    let tool = tool.context("tool not found")?;

    let operation = if tool.covered_endpoints.len() == 1 {
        tool.covered_endpoints.first().cloned()
    } else {
        arguments
            .get("operation")
            .and_then(Value::as_str)
            .map(ToString::to_string)
    }
    .with_context(|| format!("tool {tool_name} requires an explicit operation"))?;

    let result = execute_operation(plan, &operation, &arguments)?;

    Ok(json!({
        "content": [{"type": "text", "text": serde_json::to_string_pretty(&result)?}]
    }))
}

fn execute_operation(
    plan: &ToolPlan,
    operation: &str,
    arguments: &serde_json::Map<String, Value>,
) -> Result<Value> {
    let endpoint = plan
        .endpoint_catalog
        .get(operation)
        .context("unknown operation")?;

    execute_http_request(&endpoint.method, &endpoint.path, arguments, Some(endpoint))
}

fn find_search_matches(
    plan: &ToolPlan,
    operation_ids: &[String],
    query: &str,
) -> Vec<Value> {
    let normalized_query = query.trim().to_lowercase();
    let terms = tokenize_search_query(query);
    let mut matches: Vec<(i64, String, Value)> = Vec::new();

    for operation in operation_ids {
        let Some(endpoint) = plan.endpoint_catalog.get(operation) else {
            continue;
        };

        let mut fields = vec![
            operation.to_lowercase(),
            endpoint.method.to_lowercase(),
            endpoint.path.to_lowercase(),
            endpoint.summary.to_lowercase(),
            endpoint.description.to_lowercase(),
            endpoint.domain.to_lowercase(),
        ];
        fields.extend(endpoint.tags.iter().map(|tag| tag.to_lowercase()));

        let mut score = 0_i64;
        for field in fields {
            if field.is_empty() {
                continue;
            }
            if field.contains(&normalized_query) {
                score += 5;
            }
            for term in &terms {
                if field.contains(term) {
                    score += 1;
                }
            }
        }

        if score > 0 {
            matches.push((
                score,
                operation.clone(),
                json!({
                    "operation": operation,
                    "method": endpoint.method.to_uppercase(),
                    "path": endpoint.path,
                    "summary": if endpoint.summary.is_empty() { endpoint.description.clone() } else { endpoint.summary.clone() },
                    "domain": endpoint.domain,
                    "score": score,
                }),
            ));
        }
    }

    matches.sort_by(|left, right| {
        right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1))
    });

    matches.into_iter().map(|(_, _, value)| value).collect()
}

fn tokenize_search_query(query: &str) -> Vec<String> {
    let mut terms: Vec<String> = query
        .to_lowercase()
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter_map(|part| {
            let trimmed = part.trim();
            if trimmed.len() >= 2 {
                Some(trimmed.to_string())
            } else {
                None
            }
        })
        .collect();
    terms.sort();
    terms.dedup();
    terms
}

fn execute_http_request(
    method: &str,
    path_template: &str,
    arguments: &serde_json::Map<String, Value>,
    endpoint: Option<&EndpointDefinition>,
) -> Result<Value> {
    let base_url = std::env::var("FORGE_BASE_URL").context("FORGE_BASE_URL is required")?;

    let path_params = arguments
        .get("path_params")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let query = arguments
        .get("query")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let headers_input = arguments
        .get("headers")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let resolved_path = substitute_path_params(path_template, &path_params)?;
    let mut url = Url::parse(&base_url)?.join(&resolved_path)?;

    for (key, value) in query {
        if !value.is_null() {
            url.query_pairs_mut().append_pair(&key, &value_to_string(&value));
        }
    }

    if let Ok(api_key) = std::env::var("FORGE_API_KEY") {
        if let Ok(query_key) = std::env::var("FORGE_API_KEY_QUERY_NAME") {
            url.query_pairs_mut().append_pair(&query_key, &api_key);
        }
    }

    let client = Client::builder().build().context("failed to build HTTP client")?;
    let mut request = client.request(method.parse()?, url.as_str());

    for (key, value) in headers_input {
        if !value.is_null() {
            request = request.header(key, value_to_string(&value));
        }
    }

    if let Ok(raw_headers) = std::env::var("FORGE_STATIC_HEADERS_JSON") {
        if let Ok(Value::Object(headers)) = serde_json::from_str::<Value>(&raw_headers) {
            for (key, value) in headers {
                if let Some(value) = value.as_str() {
                    request = request.header(key, value);
                }
            }
        }
    }

    if let Some(token) = fetch_oauth_access_token(&client)? {
        request = request.bearer_auth(token);
    }

    if let Some((header_name, header_value)) = fetch_dynamic_token_header(&client)? {
        request = request.header(header_name, header_value);
    }

    if let Ok(token) = std::env::var("FORGE_BEARER_TOKEN") {
        request = request.bearer_auth(token);
    }

    if let Ok(api_key) = std::env::var("FORGE_API_KEY") {
        if let Ok(header_name) = std::env::var("FORGE_API_KEY_HEADER") {
            request = request.header(header_name, api_key);
        }
    }

    if let (Ok(user), Ok(password)) = (
        std::env::var("FORGE_BASIC_USER"),
        std::env::var("FORGE_BASIC_PASSWORD"),
    ) {
        request = request.basic_auth(user, Some(password));
    }

    if let Ok(value) = std::env::var("FORGE_TOKEN_VALUE") {
        let header = std::env::var("FORGE_TOKEN_HEADER")
            .unwrap_or_else(|_| "Authorization".to_string());
        let prefix = std::env::var("FORGE_TOKEN_PREFIX").unwrap_or_default();
        let header_value = if prefix.is_empty() {
            value
        } else {
            format!("{prefix} {value}")
        };
        request = request.header(header, header_value);
    }

    if let Some(endpoint) = endpoint {
        if !endpoint.security.is_empty() {
            request = request.header("x-forge-security", endpoint.security.join(","));
        }
    }

    if let Some(body) = arguments.get("body") {
        request = request.json(body);
    }

    let response = request.send()?;
    let status = response.status();
    let text = response.text()?;

    let parsed = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| json!({ "raw": text }));

    if !status.is_success() {
        return Ok(json!({
            "http_status": status.as_u16(),
            "error": parsed
        }));
    }

    Ok(parsed)
}

fn substitute_path_params(path_template: &str, params: &serde_json::Map<String, Value>) -> Result<String> {
    let mut result = path_template.to_string();

    while let Some(start) = result.find('{') {
        let Some(end_relative) = result[start..].find('}') else {
            break;
        };
        let end = start + end_relative;
        let key = &result[start + 1..end];
        let value = params
            .get(key)
            .map(value_to_string)
            .context(format!("missing path param: {key}"))?;
        result.replace_range(start..=end, &value);
    }

    Ok(result)
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(v) => v.to_string(),
        Value::Number(v) => v.to_string(),
        Value::String(v) => v.clone(),
        other => other.to_string(),
    }
}

fn fetch_oauth_access_token(client: &Client) -> Result<Option<String>> {
    let token_url = match std::env::var("FORGE_OAUTH_TOKEN_URL") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => return Ok(None),
    };

    let client_id = match std::env::var("FORGE_OAUTH_CLIENT_ID") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => return Ok(None),
    };

    let client_secret = match std::env::var("FORGE_OAUTH_CLIENT_SECRET") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => return Ok(None),
    };

    let mut form = vec![
        ("grant_type".to_string(), "client_credentials".to_string()),
        ("client_id".to_string(), client_id),
        ("client_secret".to_string(), client_secret),
    ];

    if let Ok(scope) = std::env::var("FORGE_OAUTH_SCOPE") {
        if !scope.trim().is_empty() {
            form.push(("scope".to_string(), scope));
        }
    }

    if let Ok(audience) = std::env::var("FORGE_OAUTH_AUDIENCE") {
        if !audience.trim().is_empty() {
            form.push(("audience".to_string(), audience));
        }
    }

    let response = client
        .post(token_url)
        .form(&form)
        .send()
        .context("oauth token request failed")?;
    if !response.status().is_success() {
        anyhow::bail!("oauth token endpoint returned {}", response.status());
    }

    let payload = response
        .json::<Value>()
        .context("failed parsing oauth token response")?;
    let token = payload
        .get("access_token")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .filter(|value| !value.is_empty());

    Ok(token)
}

fn fetch_dynamic_token_header(client: &Client) -> Result<Option<(String, String)>> {
    let token_url = match std::env::var("FORGE_DYNAMIC_TOKEN_URL") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => return Ok(None),
    };

    let method = std::env::var("FORGE_DYNAMIC_TOKEN_METHOD")
        .unwrap_or_else(|_| "POST".to_string())
        .to_uppercase();
    let token_response_path = std::env::var("FORGE_DYNAMIC_TOKEN_RESPONSE_PATH")
        .unwrap_or_else(|_| "access_token".to_string());
    let header_name = std::env::var("FORGE_DYNAMIC_TOKEN_HEADER_NAME")
        .unwrap_or_else(|_| "Authorization".to_string());
    let header_prefix = std::env::var("FORGE_DYNAMIC_TOKEN_HEADER_PREFIX")
        .unwrap_or_else(|_| "Bearer".to_string());

    let token_body = std::env::var("FORGE_DYNAMIC_TOKEN_BODY_JSON")
        .ok()
        .and_then(|value| serde_json::from_str::<Value>(&value).ok())
        .unwrap_or_else(|| json!({}));
    let token_headers = std::env::var("FORGE_DYNAMIC_TOKEN_HEADERS_JSON")
        .ok()
        .and_then(|value| serde_json::from_str::<Value>(&value).ok())
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_default();

    let mut request = if method == "GET" {
        let mut url = Url::parse(&token_url)?;
        if let Some(body) = token_body.as_object() {
            for (key, value) in body {
                if !value.is_null() {
                    url.query_pairs_mut().append_pair(key, &value_to_string(value));
                }
            }
        }
        client.get(url.as_str())
    } else {
        client
            .request(method.parse()?, token_url.as_str())
            .json(&token_body)
    };

    for (key, value) in token_headers {
        if let Some(value) = value.as_str() {
            request = request.header(key, value);
        }
    }

    let response = request.send().context("dynamic token request failed")?;
    if !response.status().is_success() {
        anyhow::bail!("dynamic token endpoint returned {}", response.status());
    }

    let payload = response
        .json::<Value>()
        .context("failed parsing dynamic token response")?;
    let token = extract_json_path_as_string(&payload, &token_response_path)
        .ok_or_else(|| anyhow::anyhow!("dynamic token missing at path {}", token_response_path))?;

    let header_value = if header_prefix.trim().is_empty() {
        token
    } else {
        format!("{} {}", header_prefix, token)
    };
    Ok(Some((header_name, header_value)))
}

fn extract_json_path_as_string(value: &Value, raw_path: &str) -> Option<String> {
    let normalized = raw_path.trim().trim_start_matches("$.").trim_start_matches('.');
    if normalized.is_empty() {
        return None;
    }

    let mut current = value;
    for segment in normalized.split('.') {
        let segment = segment.trim();
        if segment.is_empty() {
            continue;
        }
        if let Ok(index) = segment.parse::<usize>() {
            current = current.get(index)?;
        } else {
            current = current.get(segment)?;
        }
    }

    match current {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(flag) => Some(flag.to_string()),
        _ => None,
    }
}

fn read_message<R: BufRead>(reader: &mut R) -> Result<Option<Value>> {
    let mut content_length: Option<usize> = None;

    loop {
        let mut line = String::new();
        let bytes_read = reader.read_line(&mut line)?;
        if bytes_read == 0 {
            return Ok(None);
        }

        let line = line.trim_end_matches(['\\r', '\\n']);
        if line.is_empty() {
            break;
        }

        if let Some(value) = line.strip_prefix("Content-Length:") {
            content_length = Some(value.trim().parse()?);
        }
    }

    let length = content_length.context("missing Content-Length header")?;
    let mut payload = vec![0_u8; length];
    reader.read_exact(&mut payload)?;

    let parsed = serde_json::from_slice::<Value>(&payload)?;
    Ok(Some(parsed))
}

fn write_message<W: Write>(writer: &mut W, payload: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(payload)?;
    write!(writer, "Content-Length: {}\\r\\n\\r\\n", bytes.len())?;
    writer.write_all(&bytes)?;
    writer.flush()?;
    Ok(())
}
"""
    return template.replace("{{DEFAULT_TRANSPORT}}", default_transport)

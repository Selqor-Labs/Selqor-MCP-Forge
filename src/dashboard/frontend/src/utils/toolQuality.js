// Feature 5 — Multi-factor tool quality scoring.
//
// The existing `tool.confidence` field represents *how confident the
// analyzer is that this grouping is correct*. It's a single number between
// 0 and 1 produced by the analysis pipeline and says nothing about whether
// the tool will be *pleasant to use* by an LLM agent.
//
// This module adds a separate, complementary 4-factor quality score that
// inspects the curated tool + its endpoints and answers four different
// questions:
//
//   • Importance — how much value does this tool deliver?
//   • Usability  — how easy is it for an agent to pick and invoke?
//   • Security   — is it safe to expose to an agent?
//   • Complexity — how simple is its surface area? (inverse metric — lower
//                   param count = higher score)
//
// The four factors compose with fixed weights from the MVP plan:
//
//   final = 0.30 * importance + 0.25 * usability + 0.25 * security + 0.20 * complexity
//
// All factors and the final score are returned in a 0–100 range so UI
// can render them as progress bars interchangeably.
//
// This is a **client-side heuristic** for the MVP. When the backend ships
// server-side scoring, `ToolQualityBreakdown` will prefer the server's
// numbers (via `tool.quality_score` / `tool.quality_factors`) and only
// fall back to this module when they are missing.

const WEIGHTS = { importance: 0.3, usability: 0.25, security: 0.25, complexity: 0.2 };

// Keywords that strongly suggest a mutating / high-value endpoint. Presence
// boosts importance but also slightly hurts security (needs more review).
const MUTATION_VERBS = ['create', 'delete', 'update', 'modify', 'patch', 'remove', 'add'];
const READ_VERBS = ['list', 'get', 'fetch', 'read', 'show', 'view', 'search', 'find'];

// Paths that are red-flags for security: admin surfaces, raw SQL, file IO.
const SENSITIVE_PATH_MARKERS = ['admin', 'internal', 'debug', 'sudo', 'root', 'password', 'secret', 'credential'];

// Clamp helper — all factors are reported in 0..100.
const clamp = (n, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, n));

function describeList(tool, endpointMap) {
  const ids = tool.covered_endpoints || [];
  const endpoints = ids.map((id) => endpointMap[id]).filter(Boolean);
  return endpoints;
}

// ─────────────────────────────────────────────────────────────
// Factor 1: Importance
// ─────────────────────────────────────────────────────────────
//
// Criteria (each contributes up to 25 points):
//   • Endpoint count — more endpoints = broader capability (logarithmic)
//   • Presence of mutation verbs (create/delete/update) — high-leverage ops
//   • Presence of multiple HTTP methods — indicates a full CRUD surface
//   • Description length — a well-documented tool is worth documenting
//
function scoreImportance(tool, endpoints) {
  let score = 0;
  const n = endpoints.length;
  // Logarithmic ramp: 1 endpoint → 8, 4 → 16, 16 → 24, saturates at 25.
  score += n > 0 ? clamp(8 * Math.log2(n + 1), 0, 25) : 0;

  const methods = new Set(endpoints.map((e) => (e.method || '').toUpperCase()));
  // Diversity of methods: 1 method = 5, 2 = 15, 3+ = 25.
  score += methods.size >= 3 ? 25 : methods.size === 2 ? 15 : methods.size === 1 ? 5 : 0;

  const textBlob = `${tool.name || ''} ${tool.description || ''}`.toLowerCase();
  const hasMutation = MUTATION_VERBS.some((v) => textBlob.includes(v));
  const hasRead = READ_VERBS.some((v) => textBlob.includes(v));
  // Mutating tools are more valuable than pure read tools.
  score += hasMutation ? 25 : hasRead ? 12 : 0;

  // Documentation signal — a tool with a real description is more
  // intentional than one with a placeholder.
  const descLen = (tool.description || '').trim().length;
  score += descLen >= 120 ? 25 : descLen >= 40 ? 15 : descLen >= 10 ? 6 : 0;

  return clamp(score);
}

// ─────────────────────────────────────────────────────────────
// Factor 2: Usability
// ─────────────────────────────────────────────────────────────
//
// Criteria:
//   • Snake_case name (LLM-friendly)
//   • Reasonable name length (6–40 chars)
//   • Description length signals intent clarity
//   • Endpoint count below 15 (gigantic tools are hard to use)
//
function scoreUsability(tool, endpoints) {
  let score = 0;
  const name = (tool.name || '').trim();

  // Naming: MCP convention is snake_case, lowercase, meaningful length.
  if (/^[a-z][a-z0-9_]+$/.test(name)) score += 25;
  else if (name) score += 8;

  const len = name.length;
  if (len >= 6 && len <= 40) score += 15;
  else if (len >= 3) score += 5;

  // Description clarity
  const desc = (tool.description || '').trim();
  if (desc.length >= 60) score += 25;
  else if (desc.length >= 20) score += 12;
  else if (desc.length > 0) score += 4;

  // Endpoint count: ideal band is 3–8. Above 15 hurts because the agent
  // can't predict which sub-operation will run. Below 2 hurts because
  // the tool is too trivial to be worth listing.
  const n = endpoints.length;
  if (n >= 3 && n <= 8) score += 25;
  else if (n >= 2 && n <= 15) score += 15;
  else if (n === 1) score += 8;
  else if (n > 15) score += 2;

  // Schema-presence bonus: a well-formed input_schema means the agent
  // has concrete parameter types to fill.
  if (tool.input_schema && Object.keys(tool.input_schema).length > 0) {
    score += 10;
  }

  return clamp(score);
}

// ─────────────────────────────────────────────────────────────
// Factor 3: Security
// ─────────────────────────────────────────────────────────────
//
// Starts at 100 and subtracts penalties for risky signals. This is a
// heuristic — it does not replace a real scanner run, but it catches the
// obvious foot-guns before deployment.
//
function scoreSecurity(tool, endpoints) {
  let score = 100;

  const sensitivePaths = endpoints.filter((e) => {
    const p = (e.path || '').toLowerCase();
    return SENSITIVE_PATH_MARKERS.some((marker) => p.includes(marker));
  });
  score -= sensitivePaths.length * 15;

  // DELETE endpoints are inherently more dangerous than reads.
  const deletes = endpoints.filter((e) => (e.method || '').toUpperCase() === 'DELETE');
  score -= deletes.length * 5;

  // Unbounded wildcards / path params with no validation suggest broad
  // attack surface. We can only detect the `/*` / `{any}` pattern here.
  const wildcards = endpoints.filter((e) => /\*|\{any\}/.test(e.path || ''));
  score -= wildcards.length * 8;

  // An empty input_schema on a mutating tool is a red flag — it means
  // the agent can pass arbitrary data.
  const textBlob = `${tool.name || ''} ${tool.description || ''}`.toLowerCase();
  const isMutating = MUTATION_VERBS.some((v) => textBlob.includes(v));
  if (isMutating && (!tool.input_schema || Object.keys(tool.input_schema).length === 0)) {
    score -= 10;
  }

  return clamp(score);
}

// ─────────────────────────────────────────────────────────────
// Factor 4: Complexity (inverse)
// ─────────────────────────────────────────────────────────────
//
// Fewer parameters = higher score. Fewer distinct HTTP methods in one
// tool = higher score (pure-read or pure-write tools are easier to
// reason about than mixed CRUD piles).
//
function scoreComplexity(tool, endpoints) {
  let score = 100;

  // Average parameter count across endpoints.
  const paramCounts = endpoints.map((e) => {
    const params = e.parameters || e.params || [];
    return Array.isArray(params) ? params.length : 0;
  });
  const avgParams = paramCounts.length > 0
    ? paramCounts.reduce((a, b) => a + b, 0) / paramCounts.length
    : 0;

  // 0 params = no penalty, 5 params = -25, 10+ = -50.
  score -= Math.min(50, Math.round(avgParams * 5));

  // Wide method spread inside one tool means it does multiple conceptual
  // things (e.g. list + create + delete) which is harder to reason about.
  const methods = new Set(endpoints.map((e) => (e.method || '').toUpperCase()));
  if (methods.size >= 4) score -= 20;
  else if (methods.size === 3) score -= 10;

  // Endpoint count penalty — big tools are cognitively complex.
  if (endpoints.length > 20) score -= 25;
  else if (endpoints.length > 12) score -= 12;
  else if (endpoints.length > 8) score -= 5;

  return clamp(score);
}

/**
 * Compute the full 4-factor breakdown for a tool.
 *
 * @param {object} tool         Tool definition from the curated tooling payload
 * @param {object} endpointMap  Map of endpoint id → endpoint record (method, path, parameters)
 * @returns {{
 *   overall: number,
 *   importance: number,
 *   usability: number,
 *   security: number,
 *   complexity: number,
 *   endpointCount: number,
 * }}
 */
export function computeToolQuality(tool, endpointMap = {}) {
  if (!tool) {
    return { overall: 0, importance: 0, usability: 0, security: 0, complexity: 0, endpointCount: 0 };
  }

  // Prefer backend-computed values if present — matches the same pattern
  // used by `owaspMapping.js`, so lifting this to the server later costs
  // zero UI changes.
  if (tool.quality_factors && typeof tool.quality_factors === 'object') {
    const qf = tool.quality_factors;
    const overall = tool.quality_score ?? Math.round(
      WEIGHTS.importance * (qf.importance || 0)
      + WEIGHTS.usability * (qf.usability || 0)
      + WEIGHTS.security * (qf.security || 0)
      + WEIGHTS.complexity * (qf.complexity || 0),
    );
    return {
      overall,
      importance: qf.importance || 0,
      usability: qf.usability || 0,
      security: qf.security || 0,
      complexity: qf.complexity || 0,
      endpointCount: (tool.covered_endpoints || []).length,
    };
  }

  const endpoints = describeList(tool, endpointMap);
  const importance = scoreImportance(tool, endpoints);
  const usability = scoreUsability(tool, endpoints);
  const security = scoreSecurity(tool, endpoints);
  const complexity = scoreComplexity(tool, endpoints);

  const overall = Math.round(
    WEIGHTS.importance * importance
    + WEIGHTS.usability * usability
    + WEIGHTS.security * security
    + WEIGHTS.complexity * complexity,
  );

  return { overall, importance, usability, security, complexity, endpointCount: endpoints.length };
}

/** Human-readable label for a score — matches the Scanner tier language. */
export function qualityTier(score) {
  if (score >= 85) return { label: 'Excellent', color: '#10b981' };
  if (score >= 70) return { label: 'Good', color: '#3b82f6' };
  if (score >= 55) return { label: 'Fair', color: '#f59e0b' };
  return { label: 'Needs work', color: '#dc2626' };
}

export { WEIGHTS as QUALITY_WEIGHTS };

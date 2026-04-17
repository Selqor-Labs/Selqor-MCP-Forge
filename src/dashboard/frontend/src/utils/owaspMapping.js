// OWASP Agentic Top 10 (2024) → Selqor Forge security findings mapping.
//
// The Selqor Forge backend does not yet tag findings with OWASP categories,
// so this module provides a **client-side heuristic** that inspects a
// finding's `tags`, `title`, `description`, and `source` to place it in
// one of the 10 categories. When the backend eventually ships a server-
// side mapping (e.g. a `finding.owasp_category` field), the report view
// will prefer that and only fall back to this heuristic.
//
// Design notes:
//   • Pure functions only — trivially unit-testable.
//   • "Unknown" is a legitimate result; we don't force-fit findings.
//   • Ordering matters inside `categorize`: the first matching rule wins.
//     More specific rules should come first.
//
// Reference: https://owasp.org/www-project-top-10-for-large-language-model-applications/

/**
 * OWASP Agentic Top 10 category definitions. `key` is the short ID used in
 * URLs / UI; `code` matches OWASP's published numbering.
 */
export const OWASP_AGENTIC_TOP_10 = [
  {
    key: 'ag01',
    code: 'AG01',
    title: 'Prompt Injection',
    description: 'Manipulation of LLM behavior through crafted inputs that override system instructions.',
    mcpRelevance: 'high',
  },
  {
    key: 'ag02',
    code: 'AG02',
    title: 'Insecure Output Handling',
    description: 'Downstream systems trusting LLM-generated content without validation (XSS, SQLi, SSRF).',
    mcpRelevance: 'high',
  },
  {
    key: 'ag03',
    code: 'AG03',
    title: 'Training Data Poisoning',
    description: 'Tampered training data creating biased or backdoored behavior.',
    mcpRelevance: 'low',
  },
  {
    key: 'ag04',
    code: 'AG04',
    title: 'Model Denial of Service',
    description: 'Resource-exhaustion attacks via unbounded context, recursion, or expensive tool calls.',
    mcpRelevance: 'medium',
  },
  {
    key: 'ag05',
    code: 'AG05',
    title: 'Supply Chain Vulnerabilities',
    description: 'Compromised dependencies, pretrained models, plugins, or data sources.',
    mcpRelevance: 'high',
  },
  {
    key: 'ag06',
    code: 'AG06',
    title: 'Sensitive Information Disclosure',
    description: 'Leakage of secrets, PII, or proprietary data through tool outputs or logs.',
    mcpRelevance: 'high',
  },
  {
    key: 'ag07',
    code: 'AG07',
    title: 'Insecure Plugin / Tool Design',
    description: 'MCP tools with over-broad schemas, missing validation, or unsafe parameter handling.',
    mcpRelevance: 'high',
  },
  {
    key: 'ag08',
    code: 'AG08',
    title: 'Excessive Agency',
    description: 'Tools with permissions beyond what the task requires — write access, admin scopes, unrestricted actions.',
    mcpRelevance: 'high',
  },
  {
    key: 'ag09',
    code: 'AG09',
    title: 'Overreliance',
    description: 'Blind trust in LLM outputs without human review for consequential actions.',
    mcpRelevance: 'medium',
  },
  {
    key: 'ag10',
    code: 'AG10',
    title: 'Model Theft',
    description: 'Exfiltration of proprietary model weights, prompts, or IP.',
    mcpRelevance: 'low',
  },
];

/**
 * Normalize a string for keyword matching (lowercase, collapse whitespace).
 */
function norm(s) {
  return (s || '').toString().toLowerCase();
}

/**
 * Check whether any of the provided haystacks contains any of the needles.
 */
function matches(haystacks, needles) {
  const joined = haystacks.map(norm).join(' | ');
  return needles.some((n) => joined.includes(n));
}

/**
 * Categorize a SecurityFinding into one of the OWASP Agentic Top 10.
 * Returns the category `key` (e.g. 'ag06') or `null` if no rule matched.
 *
 * Rules are ordered from most specific to most generic. The first match wins.
 */
export function categorize(finding) {
  if (!finding) return null;

  // Prefer server-provided mapping if present. When the backend ships this,
  // the client heuristic becomes dead code without any UI change.
  if (finding.owasp_category) {
    const key = String(finding.owasp_category).toLowerCase().replace(/[_\s-]/g, '');
    const found = OWASP_AGENTIC_TOP_10.find((c) => c.key === key || c.code.toLowerCase() === key);
    if (found) return found.key;
  }

  const tags = Array.isArray(finding.tags) ? finding.tags : [];
  const haystacks = [finding.title, finding.description, ...tags];
  const source = norm(finding.source);

  // AG05 — Supply Chain: CVE database hits are unambiguous.
  if (source === 'cve_database' || finding.cve_id || matches(haystacks, [
    'cve-', 'dependency', 'outdated package', 'vulnerable library', 'supply chain',
  ])) {
    return 'ag05';
  }

  // AG01 — Prompt Injection
  if (matches(haystacks, [
    'prompt injection', 'prompt_injection', 'jailbreak', 'system prompt',
    'instruction injection', 'indirect injection',
  ])) {
    return 'ag01';
  }

  // AG06 — Sensitive Information Disclosure (secrets, PII, leaks)
  if (matches(haystacks, [
    'secret', 'hardcoded', 'api key', 'api_key', 'password', 'credential',
    'token leak', 'pii', 'personal information', 'sensitive data', 'disclosure',
    'information leak', 'data leak',
  ])) {
    return 'ag06';
  }

  // AG02 — Insecure Output Handling (XSS, SQLi, SSRF, unsafe deserialization)
  if (matches(haystacks, [
    'xss', 'cross-site scripting', 'sql injection', 'sqli', 'ssrf', 'xxe',
    'command injection', 'code injection', 'deserialization', 'unsafe output',
    'html injection', 'template injection', 'unvalidated output',
  ])) {
    return 'ag02';
  }

  // AG08 — Excessive Agency (over-broad permissions, admin scopes, missing auth)
  if (matches(haystacks, [
    'excessive', 'missing authentication', 'missing authorization', 'broken access',
    'privilege escalation', 'admin', 'unrestricted', 'broad scope', 'over-permissive',
    'auth bypass', 'insecure direct object', 'idor',
  ])) {
    return 'ag08';
  }

  // AG07 — Insecure Plugin / Tool Design (parameter handling, schema flaws)
  if (matches(haystacks, [
    'tool', 'plugin', 'schema', 'parameter', 'input validation', 'missing validation',
    'unsafe parameter', 'path traversal', 'mass assignment', 'open redirect',
  ])) {
    return 'ag07';
  }

  // AG04 — Model Denial of Service (rate limits, timeouts, recursion)
  if (matches(haystacks, [
    'denial of service', 'dos', 'rate limit', 'rate-limit', 'resource exhaustion',
    'infinite loop', 'recursion', 'timeout', 'unbounded',
  ])) {
    return 'ag04';
  }

  // AG09 — Overreliance
  if (matches(haystacks, [
    'overreliance', 'human review', 'human-in-the-loop', 'confirmation required',
    'auto-apply', 'unreviewed',
  ])) {
    return 'ag09';
  }

  // AG10 — Model Theft
  if (matches(haystacks, [
    'model theft', 'weight extraction', 'model extraction', 'ip leak',
  ])) {
    return 'ag10';
  }

  // AG03 — Training Data Poisoning (rare in MCP server scanning)
  if (matches(haystacks, ['training data', 'data poisoning', 'backdoor'])) {
    return 'ag03';
  }

  return null;
}

/**
 * Group an array of findings into a `{ categoryKey: finding[] }` map, plus
 * an `uncategorized` bucket for everything that didn't match a rule. Stable
 * ordering: findings keep their original order within each bucket.
 */
export function groupByOwasp(findings = []) {
  const groups = {};
  for (const cat of OWASP_AGENTIC_TOP_10) groups[cat.key] = [];
  const uncategorized = [];
  for (const f of findings) {
    const key = categorize(f);
    if (key && groups[key]) groups[key].push(f);
    else uncategorized.push(f);
  }
  return { groups, uncategorized };
}

/**
 * Numeric weight assigned to each risk level for score calculations. Values
 * are tuned so a single critical finding dominates a handful of lows.
 */
const RISK_WEIGHTS = {
  critical: 25,
  high: 10,
  medium: 4,
  low: 1,
  info: 0,
};

function riskKey(f) {
  return norm(f.risk_level || f.severity || 'info');
}

/**
 * Compute an OWASP-coverage compliance score in [0, 100].
 *
 * The score starts at 100 and subtracts weighted penalties for each
 * finding, clamped at 0. A scan with zero findings scores 100; a scan
 * with a single critical finding drops to ~75; multiple criticals push
 * it towards 0.
 *
 * We also report per-category counts so the UI can show a matrix of
 * "clean" vs "has findings" categories.
 */
export function computeComplianceReport(findings = []) {
  const { groups, uncategorized } = groupByOwasp(findings);

  let score = 100;
  for (const f of findings) {
    score -= RISK_WEIGHTS[riskKey(f)] || 0;
  }
  score = Math.max(0, Math.min(100, Math.round(score)));

  const perCategory = OWASP_AGENTIC_TOP_10.map((cat) => {
    const items = groups[cat.key] || [];
    const severityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    for (const f of items) {
      const k = riskKey(f);
      if (severityCounts[k] != null) severityCounts[k] += 1;
    }
    const worst = ['critical', 'high', 'medium', 'low', 'info'].find((s) => severityCounts[s] > 0) || null;
    return {
      ...cat,
      count: items.length,
      findings: items,
      severityCounts,
      worstSeverity: worst,
      clean: items.length === 0,
    };
  });

  const categoriesCovered = perCategory.filter((c) => !c.clean).length;
  const coveragePct = Math.round(((OWASP_AGENTIC_TOP_10.length - categoriesCovered) / OWASP_AGENTIC_TOP_10.length) * 100);

  return {
    score,
    coveragePct,
    categoriesCovered,
    categoriesClean: OWASP_AGENTIC_TOP_10.length - categoriesCovered,
    perCategory,
    uncategorized,
    totalFindings: findings.length,
  };
}

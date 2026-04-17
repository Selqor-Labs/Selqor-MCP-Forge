// Central helper for turning any thrown API error into something the UI
// can render. It covers three cases we see in practice:
//
//   1. A plain `Error` with a message string — the common case when
//      `api/index.js` wraps a non-OK response.
//   2. A rich Error that already has `.fieldErrors` / `.status` attached
//      (set by the enhanced `api/index.js` — see that file).
//   3. A raw string (legacy — some older code throws plain strings).
//
// Return shape is always the same:
//
//   {
//     message:     'Human-readable summary string',
//     fieldErrors: { fieldName: 'error message', ... },   // empty if none
//     status:      503,                                   // if known
//   }
//
// Callers typically pass the extracted `message` to `toast(msg, 'error')`
// and the `fieldErrors` map to `setFieldErrors(...)` so the form can
// highlight the offending inputs inline.

export function extractError(err) {
  if (err == null) {
    return { message: 'Unknown error', fieldErrors: {}, status: null };
  }
  if (typeof err === 'string') {
    return { message: err, fieldErrors: {}, status: null };
  }
  const message = err.message || err.error || 'Something went wrong';
  const fieldErrors = err.fieldErrors && typeof err.fieldErrors === 'object' ? err.fieldErrors : {};
  const status = err.status ?? err.statusCode ?? null;
  return { message, fieldErrors, status };
}

/**
 * Build a user-facing error message with actionable context. Mirrors the
 * Feature 6 standard "what / why / how / example" error shape so the same
 * phrasing can live in both validators and API error handlers.
 */
export function formatUserError({ what, why, how, example }) {
  const parts = [what];
  if (why) parts.push(why);
  if (how) parts.push(how);
  if (example) parts.push(`Example: ${example}`);
  return parts.filter(Boolean).join(' ');
}

/**
 * Map a FastAPI 422 validation detail array into a `{ field: message }`
 * object. FastAPI emits entries like:
 *
 *   { loc: ['body', 'base_url'], msg: 'field required', type: 'value_error.missing' }
 *
 * We drop the first `loc` segment (usually 'body') and use the next one as
 * the field name. Nested fields are joined with dots.
 */
export function mapFastApiDetail(detail) {
  const out = {};
  if (!Array.isArray(detail)) return out;
  for (const entry of detail) {
    if (!entry || !Array.isArray(entry.loc)) continue;
    const path = entry.loc.slice(1); // drop 'body' / 'query' / etc.
    if (path.length === 0) continue;
    const field = path.join('.');
    if (!out[field]) out[field] = entry.msg || 'Invalid value';
  }
  return out;
}

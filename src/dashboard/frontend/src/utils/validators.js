// Reusable form validation helpers for Selqor MCP Forge.
//
// Design goals:
//   • Every validator returns either `null` (valid) or a structured error
//     `{ message, hint?, example? }`. Keeping the shape consistent means
//     forms can render field-level helperText, Alert banners, or tooltips
//     from the same source of truth.
//   • Validators are pure functions — no React, no DOM — so they can be
//     tested directly and composed into larger validation runs.
//   • Error messages follow the Feature 6 standard: say *what* is wrong,
//     *why* it matters, and *how* to fix it (with an example when useful).
//
// Typical usage inside a component:
//
//   import { required, httpUrl, jsonObject, runValidators } from '@/utils/validators';
//
//   const errors = runValidators({
//     base_url: [required('Base URL'), httpUrl('Base URL')],
//     headers:  [jsonObject('Headers')],
//   }, form);
//
//   if (Object.keys(errors).length) { setFieldErrors(errors); return; }

/**
 * Build a validator error from a standard shape.
 * Not exported — validators call this internally.
 */
function makeError(message, hint, example) {
  const err = { message };
  if (hint) err.hint = hint;
  if (example) err.example = example;
  return err;
}

/** Flatten a structured validator error into a single helperText string. */
export function formatError(err) {
  if (!err) return '';
  if (typeof err === 'string') return err;
  const parts = [err.message];
  if (err.hint) parts.push(err.hint);
  if (err.example) parts.push(`Example: ${err.example}`);
  return parts.filter(Boolean).join(' — ');
}

// ─────────────────────────────────────────────────────────────
// Core validators
// ─────────────────────────────────────────────────────────────

/** Field must be non-empty after trimming. */
export const required = (label = 'This field') => (value) => {
  if (value == null) return makeError(`${label} is required.`);
  if (typeof value === 'string' && value.trim() === '') {
    return makeError(`${label} is required.`);
  }
  if (Array.isArray(value) && value.length === 0) {
    return makeError(`${label} must have at least one entry.`);
  }
  return null;
};

/** Value must be a valid http(s) URL. Empty values pass — pair with `required` if mandatory. */
export const httpUrl = (label = 'URL') => (value) => {
  if (!value) return null;
  const trimmed = String(value).trim();
  if (!/^https?:\/\//i.test(trimmed)) {
    return makeError(
      `${label} must start with http:// or https://.`,
      'We use it to reach your API over the network, so a scheme is required.',
      'https://api.example.com',
    );
  }
  try {
    // URL constructor catches most malformed inputs (bad host, invalid port, etc.)
    // eslint-disable-next-line no-new
    new URL(trimmed);
  } catch {
    return makeError(
      `${label} is not a valid URL.`,
      'Check for typos, spaces, or missing host.',
      'https://api.example.com',
    );
  }
  return null;
};

/** Value must look like an email address. */
export const email = (label = 'Email') => (value) => {
  if (!value) return null;
  const trimmed = String(value).trim();
  // Deliberately simple — full RFC 5322 validation isn't useful in the UI.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
    return makeError(
      `${label} must be a valid email address.`,
      null,
      'name@example.com',
    );
  }
  return null;
};

/** Value must parse as JSON. Pass `kind: 'object'` to also require `{}`-style output. */
export const jsonValue = (label = 'Value', { kind = 'any' } = {}) => (value) => {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    if (kind === 'object') {
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return makeError(
          `${label} must be a JSON object.`,
          'Keys are header/parameter names, values are strings.',
          '{ "X-API-Key": "abc123" }',
        );
      }
    }
    return null;
  } catch (e) {
    return makeError(
      `${label} is not valid JSON.`,
      e?.message ? `Parser says: ${e.message}` : null,
      '{ "key": "value" }',
    );
  }
};

/** Shortcut: JSON that must be an object literal. */
export const jsonObject = (label) => jsonValue(label, { kind: 'object' });

/** String length bounds. Either min or max can be null to skip that side. */
export const length = (label = 'Value', { min = null, max = null } = {}) => (value) => {
  if (value == null || value === '') return null;
  const len = String(value).length;
  if (min != null && len < min) {
    return makeError(`${label} must be at least ${min} characters.`);
  }
  if (max != null && len > max) {
    return makeError(`${label} must be at most ${max} characters.`);
  }
  return null;
};

/** Numeric range. Accepts strings and coerces. */
export const numberInRange = (label = 'Value', { min = null, max = null, integer = false } = {}) => (value) => {
  if (value == null || value === '') return null;
  const n = Number(value);
  if (Number.isNaN(n)) {
    return makeError(`${label} must be a number.`);
  }
  if (integer && !Number.isInteger(n)) {
    return makeError(`${label} must be a whole number.`);
  }
  if (min != null && n < min) {
    return makeError(`${label} must be at least ${min}.`);
  }
  if (max != null && n > max) {
    return makeError(`${label} must be at most ${max}.`);
  }
  return null;
};

/** Value must match a regex. */
export const pattern = (label, re, { example = null, hint = null } = {}) => (value) => {
  if (!value) return null;
  if (!re.test(String(value))) {
    return makeError(`${label} has an invalid format.`, hint, example);
  }
  return null;
};

/** Value must be one of a fixed set. */
export const oneOf = (label, choices) => (value) => {
  if (value == null || value === '') return null;
  if (!choices.includes(value)) {
    return makeError(
      `${label} must be one of: ${choices.join(', ')}.`,
    );
  }
  return null;
};

// ─────────────────────────────────────────────────────────────
// Composition
// ─────────────────────────────────────────────────────────────

/**
 * Run a list of validators against a single value. Returns the first error
 * found, or null if all pass. Order matters — put `required` first.
 */
export function runFieldValidators(validators, value) {
  for (const v of validators) {
    const result = v(value);
    if (result) return result;
  }
  return null;
}

/**
 * Run a validator spec against a form object. Returns a `{ field: error }`
 * map containing only the fields that failed, so callers can simply check
 * `Object.keys(errors).length`.
 *
 * Spec shape:
 *   { fieldName: [validatorFn, validatorFn, ...], ... }
 */
export function runValidators(spec, form) {
  const errors = {};
  for (const [field, validators] of Object.entries(spec)) {
    const err = runFieldValidators(validators, form[field]);
    if (err) errors[field] = err;
  }
  return errors;
}

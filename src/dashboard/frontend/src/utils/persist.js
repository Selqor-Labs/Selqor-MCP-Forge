// Feature 7 — centralized localStorage helpers.
//
// A dozen places in the app were repeating the same
// `try { localStorage.getItem(...) } catch { /* ignore */ }` dance. This
// module wraps the browser API in two small primitives so new persistence
// sites don't have to copy/paste the boilerplate, and so we get a single
// place to swap out storage backends (e.g. IndexedDB, sessionStorage) if
// we ever need it.
//
// Storage keys used across the app live in `STORAGE_KEYS` below so they
// are discoverable and typo-safe.

import { useCallback, useEffect, useState } from 'react';

/** All persisted keys in one place so we can audit/clear them in bulk. */
export const STORAGE_KEYS = {
  theme: 'selqor-theme',
  recentSpecs: 'selqor.recent_specs',
  lastScanId: 'selqor.last_scan_id',
  lastIntegrationId: 'selqor.last_integration_id',
  scannerResultsTab: 'selqor.scanner_results_tab',
  toolBuilderSelected: 'selqor.toolbuilder_selected',
  sidebarCollapsed: 'selqor.sidebar_collapsed',
};

/**
 * Safe JSON read. Returns `fallback` on any failure (missing key,
 * quota error, private-mode throw, invalid JSON).
 */
export function loadJson(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

/** Safe JSON write. Silently no-ops if storage is unavailable. */
export function saveJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Safe string read. Returns `fallback` if key is missing or storage fails. */
export function loadString(key, fallback = '') {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : raw;
  } catch {
    return fallback;
  }
}

/** Safe string write. */
export function saveString(key, value) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Safe delete. */
export function removeKey(key) {
  try {
    localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

/** Wipe every key this app owns (used by Settings "reset UI" action). */
export function clearAppStorage() {
  Object.values(STORAGE_KEYS).forEach(removeKey);
}

/**
 * React hook: `useLocalStorage(key, initial)` — like useState but the
 * value is persisted to localStorage on every change. Serialises with
 * JSON so non-string values (booleans, numbers, objects) round-trip
 * cleanly.
 *
 * The setter supports both a new value and an updater function, matching
 * the shape of `useState`.
 */
export function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    const loaded = loadJson(key, undefined);
    return loaded === undefined ? initial : loaded;
  });

  const update = useCallback((next) => {
    setValue((prev) => {
      const resolved = typeof next === 'function' ? next(prev) : next;
      saveJson(key, resolved);
      return resolved;
    });
  }, [key]);

  // Keep tabs in sync when the same key changes in another window.
  useEffect(() => {
    function onStorage(e) {
      if (e.key !== key) return;
      if (e.newValue == null) {
        setValue(initial);
        return;
      }
      try { setValue(JSON.parse(e.newValue)); } catch { /* ignore */ }
    }
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key, initial]);

  return [value, update];
}

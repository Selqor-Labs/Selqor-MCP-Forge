// Feature 7 — keyboard shortcut hook.
//
// A micro-hook for wiring global or modal-scoped keyboard shortcuts
// without pulling in a dependency like `react-hotkeys-hook`. It attaches
// a `keydown` listener to the window (or a specific element) and fires
// the handler when the chord matches.
//
// Usage:
//   useHotkey('Escape', onClose, { enabled: open });
//   useHotkey('mod+Enter', handleSubmit);  // Ctrl on win/linux, ⌘ on mac
//
// Chord syntax: lowercase modifiers joined with '+' followed by the key.
//   Modifiers: mod | ctrl | meta | alt | shift
//   Key: any KeyboardEvent.key value (case-insensitive)

import { useEffect } from 'react';

function matches(event, chord) {
  const parts = chord.toLowerCase().split('+').map((s) => s.trim());
  const key = parts.pop();
  const mods = new Set(parts);

  const wantCtrl = mods.has('ctrl');
  const wantMeta = mods.has('meta');
  const wantMod = mods.has('mod');
  const wantAlt = mods.has('alt');
  const wantShift = mods.has('shift');

  // `mod` maps to ⌘ on mac, Ctrl elsewhere.
  const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);
  const modPressed = isMac ? event.metaKey : event.ctrlKey;

  if (wantMod && !modPressed) return false;
  if (wantCtrl && !event.ctrlKey) return false;
  if (wantMeta && !event.metaKey) return false;
  if (wantAlt && !event.altKey) return false;
  if (wantShift && !event.shiftKey) return false;

  // Reject stray modifiers that weren't requested. This prevents
  // `Enter` from firing when the user hits `Ctrl+Enter`.
  if (!wantMod && !wantCtrl && !isMac && event.ctrlKey) return false;
  if (!wantMod && !wantMeta && isMac && event.metaKey) return false;
  if (!wantAlt && event.altKey) return false;

  return event.key.toLowerCase() === key;
}

/**
 * Bind a keyboard chord to a handler while the component is mounted.
 *
 * @param {string|string[]} chord    A single chord or array of chords
 * @param {function} handler         Called with the KeyboardEvent
 * @param {object} [options]
 * @param {boolean} [options.enabled=true]  Gate the listener (useful for modals)
 * @param {boolean} [options.preventDefault=true]  Call preventDefault on match
 * @param {boolean} [options.allowInInputs=false]  Fire even when an input is focused
 */
export default function useHotkey(chord, handler, options = {}) {
  const { enabled = true, preventDefault = true, allowInInputs = false } = options;

  useEffect(() => {
    if (!enabled || !handler) return undefined;
    const chords = Array.isArray(chord) ? chord : [chord];

    function onKey(event) {
      if (!allowInInputs) {
        const tag = (event.target && event.target.tagName) || '';
        const editable = event.target && event.target.isContentEditable;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || editable) {
          // Still allow Escape — modal close-on-escape should work
          // even when the user is typing in the search box.
          if (event.key !== 'Escape') return;
        }
      }
      if (chords.some((c) => matches(event, c))) {
        if (preventDefault) event.preventDefault();
        handler(event);
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chord, handler, enabled, preventDefault, allowInInputs]);
}

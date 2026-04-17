import React from 'react';
import Box from '@mui/material/Box';
import useStore from '../store/useStore';

/**
 * Inline animated-logo loader. Drop-in replacement for `<CircularProgress />`.
 *
 * Sizing: pass `size` in pixels (the loader is square). The default 120px
 * matches the modal-overlay variant. For inline-with-text use 14–18, for
 * panels 48–80, for full-page splashes 96–160.
 *
 * The loader uses the same CSS classes as the global `LoadingOverlay`, so
 * any tweaks to the keyframes / SVG assets are picked up automatically.
 * Respects ``prefers-reduced-motion`` via the existing media query.
 */
export default function LogoLoader({
  size = 64,
  message,
  centered = false,
  sx,
}) {
  const theme = useStore((s) => s.theme);
  const dark = theme === 'dark';

  const wrapper = (
    <Box
      sx={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: message ? 1.25 : 0,
        ...(sx || {}),
      }}
    >
      <div
        className="loading-logo-motion"
        aria-label="Loading"
        role="status"
        style={{ '--loader-size': `${size}px` }}
      >
        <img
          className="loading-mark-part loading-part-one"
          src={dark ? '/assets/selqor-symbol-one-dark.svg' : '/assets/selqor-symbol-one-light.svg'}
          alt=""
        />
        <img
          className="loading-mark-part loading-part-two"
          src={dark ? '/assets/selqor-symbol-two-dark.svg' : '/assets/selqor-symbol-two-light.svg'}
          alt=""
        />
        <img
          className="loading-mark-part loading-part-three"
          src={dark ? '/assets/selqor-symbol-three-dark.svg' : '/assets/selqor-symbol-three-light.svg'}
          alt=""
        />
        <img
          className="loading-mark-part loading-part-four"
          src={dark ? '/assets/selqor-symbol-four-dark.svg' : '/assets/selqor-symbol-four-light.svg'}
          alt=""
        />
        <img
          className="loading-logo-mark"
          src={dark ? '/assets/selqor-mark-dark.svg' : '/assets/selqor-mark-light.svg'}
          alt=""
        />
      </div>
      {message && (
        <Box
          component="span"
          sx={{
            fontSize: '0.78rem',
            color: 'text.secondary',
            fontFamily: 'inherit',
          }}
        >
          {message}
        </Box>
      )}
    </Box>
  );

  if (!centered) return wrapper;

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        width: '100%',
        minHeight: size * 1.6,
      }}
    >
      {wrapper}
    </Box>
  );
}

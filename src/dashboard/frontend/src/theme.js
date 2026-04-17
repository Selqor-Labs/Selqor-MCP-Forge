import { createTheme } from '@mui/material/styles';

export const METHOD_COLORS = {
  get: { bg: '#dbeafe', fg: '#1d4ed8', darkBg: 'rgba(59,130,246,.15)', darkFg: '#93c5fd' },
  post: { bg: '#dcfce7', fg: '#15803d', darkBg: 'rgba(34,197,94,.15)', darkFg: '#86efac' },
  put: { bg: '#fef3c7', fg: '#a16207', darkBg: 'rgba(234,179,8,.15)', darkFg: '#fde68a' },
  patch: { bg: '#fef3c7', fg: '#a16207', darkBg: 'rgba(234,179,8,.15)', darkFg: '#fde68a' },
  delete: { bg: '#fee2e2', fg: '#b91c1c', darkBg: 'rgba(239,68,68,.15)', darkFg: '#fca5a5' },
  head: { bg: '#e5e5e5', fg: '#525252', darkBg: 'rgba(100,100,100,.15)', darkFg: '#a3a3a3' },
  options: { bg: '#e5e5e5', fg: '#525252', darkBg: 'rgba(100,100,100,.15)', darkFg: '#a3a3a3' },
};

export function getTheme(mode) {
  const isLight = mode === 'light';
  return createTheme({
    palette: {
      mode,
      primary: { main: isLight ? '#0a0a0a' : '#fafafa', contrastText: isLight ? '#ffffff' : '#0a0a0a' },
      error: { main: isLight ? '#dc2626' : '#ef4444' },
      success: { main: isLight ? '#16a34a' : '#22c55e' },
      warning: { main: isLight ? '#ca8a04' : '#eab308' },
      background: { default: isLight ? '#ffffff' : '#0a0a0a', paper: isLight ? '#ffffff' : '#141414' },
      text: { primary: isLight ? '#0a0a0a' : '#fafafa', secondary: isLight ? '#737373' : '#a3a3a3' },
      divider: isLight ? '#e5e5e5' : '#262626',
      action: { hover: isLight ? '#f5f5f5' : '#1a1a1a', selected: isLight ? '#f0f0f0' : '#1a1a1a' },
      custom: {
        sidebarBg: isLight ? '#fafafa' : '#0a0a0a',
        sidebarFg: isLight ? '#737373' : '#a3a3a3',
        sidebarActiveBg: isLight ? '#f0f0f0' : '#1a1a1a',
        sidebarActiveFg: isLight ? '#0a0a0a' : '#fafafa',
        sidebarHover: isLight ? '#f0f0f0' : '#1a1a1a',
        headerBg: isLight ? '#ffffff' : '#0a0a0a',
        headerBorder: isLight ? '#ebebeb' : '#1f1f1f',
        codeBg: '#0a0a0a',
        codeFg: '#d4d4d4',
        successSoft: isLight ? '#f0fdf4' : 'rgba(34,197,94,.1)',
        warningSoft: isLight ? '#fefce8' : 'rgba(234,179,8,.1)',
      },
    },
    typography: {
      fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
      h4: { fontSize: '1.5rem', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.2 },
      h5: { fontSize: '1.125rem', fontWeight: 700, letterSpacing: '-0.01em', lineHeight: 1.3 },
      h6: { fontSize: '0.875rem', fontWeight: 600, lineHeight: 1.4, letterSpacing: 0 },
      subtitle1: { fontSize: '0.875rem', fontWeight: 500, lineHeight: 1.5 },
      subtitle2: { fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.5 },
      body1: { fontSize: '0.875rem', lineHeight: 1.6 },
      body2: { fontSize: '0.8125rem', lineHeight: 1.6 },
      caption: { fontSize: '0.6875rem', fontWeight: 500, lineHeight: 1.5 },
      overline: { fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.06em', lineHeight: 1.6 },
      button: { textTransform: 'none', fontWeight: 600, fontSize: '0.8125rem' },
    },
    shape: { borderRadius: 8 },
    shadows: [
      'none', '0 1px 2px rgba(0,0,0,.04)', '0 2px 8px rgba(0,0,0,.06)',
      '0 4px 12px rgba(0,0,0,.07)', '0 6px 16px rgba(0,0,0,.07)', '0 8px 24px rgba(0,0,0,.08)',
      ...Array(19).fill('0 8px 24px rgba(0,0,0,.08)'),
    ],
    components: {
      MuiCssBaseline: { styleOverrides: { body: { WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale' } } },
      MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 999 }, sizeSmall: { padding: '5px 12px', fontSize: '0.75rem' } } },
      MuiCard: { defaultProps: { variant: 'outlined' } },
      MuiTextField: { defaultProps: { size: 'small', fullWidth: true, variant: 'outlined' } },
      MuiChip: { styleOverrides: { sizeSmall: { height: 22, fontSize: '0.6875rem' } } },
      MuiDialog: { styleOverrides: { paper: { borderRadius: 12 } } },
      MuiAppBar: { defaultProps: { elevation: 0, color: 'default' }, styleOverrides: { root: { borderBottom: '1px solid', borderColor: isLight ? '#ebebeb' : '#1f1f1f', backgroundColor: isLight ? '#ffffff' : '#0a0a0a' } } },
    },
  });
}

import React, { useMemo, useEffect } from 'react';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { SnackbarProvider } from 'notistack';
import useStore from '../store/useStore';
import { getTheme } from '../theme';

export default function ThemeWrapper({ children }) {
  const mode = useStore((s) => s.theme);
  const theme = useMemo(() => getTheme(mode), [mode]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
  }, [mode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <SnackbarProvider maxSnack={5} anchorOrigin={{ vertical: 'top', horizontal: 'right' }} autoHideDuration={4000}>
        {children}
      </SnackbarProvider>
    </ThemeProvider>
  );
}

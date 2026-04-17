import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import Toast from './Toast';
import useStore from '../store/useStore';
import { DRAWER_WIDTH, DRAWER_COLLAPSED } from '../constants';

export default function Layout({ children }) {
  const theme = useStore((s) => s.theme);

  return (
    // Column-first: Topbar spans full width at top, Sidebar+Content below
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <Topbar />
      <Box sx={{ display: 'flex', flexGrow: 1, overflow: 'hidden' }}>
        <Sidebar drawerWidth={DRAWER_WIDTH} collapsedWidth={DRAWER_COLLAPSED} />
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          <Box sx={{ flexGrow: 1, overflow: 'auto', p: { xs: 1.5, sm: 2.5, md: 3 } }}>
            {children}
          </Box>
          <Divider />
          <Box
            component="footer"
            sx={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              px: { xs: 1.5, sm: 2.5, md: 3 }, py: 1, flexShrink: 0,
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <img
                src={theme === 'dark' ? '/assets/selqor-symbol-dark.svg' : '/assets/selqor-symbol-light.svg'}
                alt="Selqor"
                style={{ width: 16, height: 16 }}
              />
              <Typography variant="caption" color="text.secondary" fontWeight={600}>selqor</Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">
              &copy; {new Date().getFullYear()} Selqor Labs &middot; Selqor Forge is open sourced by Selqor Labs.
            </Typography>
          </Box>
        </Box>
      </Box>
      <Toast />
    </Box>
  );
}

export { DRAWER_WIDTH, DRAWER_COLLAPSED };

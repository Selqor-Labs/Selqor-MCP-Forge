import React from 'react';
import { useLocation } from 'react-router-dom';
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';
import RefreshIcon from '@mui/icons-material/Refresh';
import LightModeIcon from '@mui/icons-material/LightMode';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import useStore from '../store/useStore';
import useHotkey from '../utils/useHotkey';
import { DRAWER_WIDTH, DRAWER_COLLAPSED } from '../constants';

const titleMap = {
  '/': 'Dashboard',
  '/dashboard': 'Dashboard',
  '/integrations': 'App Integrations',
  '/llm-config': 'LLM Config',
  '/llm-logs': 'LLM Logs',
  '/playground': 'Forge Playground',
  '/scanner': 'Security Scanner',
  '/cicd': 'CI/CD',
  '/monitoring': 'Monitoring',
  '/settings': 'Settings',
};

function getTitle(pathname) {
  if (titleMap[pathname]) return titleMap[pathname];
  if (pathname.startsWith('/integrations')) return 'App Integrations';
  return '';
}

export default function Topbar() {
  const location = useLocation();
  const authConfig = useStore((s) => s.authConfig);
  const { theme, toggleTheme, toggleSidebar, setSidebarHovered, sidebarHovered } = useStore();
  const muiTheme = useTheme();
  const isMobile = useMediaQuery(muiTheme.breakpoints.down('md'));

  useHotkey('mod+shift+l', toggleTheme);
  useHotkey('mod+shift+r', () => window.location.reload());

  const brandWidth = isMobile ? 56 : (sidebarHovered ? DRAWER_WIDTH : DRAWER_COLLAPSED);

  return (
    <AppBar position="sticky" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
      <Toolbar variant="dense" disableGutters sx={{ minHeight: 48 }}>
        <Box
          onMouseEnter={() => !isMobile && setSidebarHovered(true)}
          onMouseLeave={() => !isMobile && setSidebarHovered(false)}
          sx={{
            width: brandWidth,
            minWidth: brandWidth,
            transition: 'width 200ms ease, min-width 200ms ease',
            display: 'flex',
            alignItems: 'center',
            gap: 1.25,
            px: 1.5,
            height: 48,
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          {isMobile ? (
            <IconButton edge="start" onClick={toggleSidebar} size="small">
              <MenuIcon fontSize="small" />
            </IconButton>
          ) : (
            <>
              <Box sx={{ width: 24, height: 24, flexShrink: 0 }}>
                <img
                  src={theme === 'dark' ? '/assets/selqor-symbol-dark.svg' : '/assets/selqor-symbol-light.svg'}
                  alt="Selqor"
                  style={{ width: '100%', height: '100%' }}
                />
              </Box>
              <Typography
                variant="body1"
                fontWeight={700}
                noWrap
                sx={{
                  letterSpacing: '-0.02em',
                  opacity: sidebarHovered ? 1 : 0,
                  transition: 'opacity 200ms ease',
                  whiteSpace: 'nowrap',
                }}
              >
                Selqor Forge
              </Typography>
            </>
          )}
        </Box>

        <Divider orientation="vertical" flexItem sx={{ my: 0 }} />

        <Typography
          variant="h6"
          fontWeight={600}
          noWrap
          sx={{ flexGrow: 1, px: 2 }}
        >
          {getTitle(location.pathname)}
        </Typography>

        {authConfig?.local_only && (
          <Tooltip title={authConfig.message}>
            <Chip
              label="Local-only"
              size="small"
              color="warning"
              variant="outlined"
              sx={{ mr: 1, display: { xs: 'none', sm: 'inline-flex' } }}
            />
          </Tooltip>
        )}

        <Box sx={{ display: 'flex', gap: 0.5, pr: 1 }}>
          <Tooltip title="Refresh page (Ctrl + Shift + R)">
            <IconButton size="small" onClick={() => window.location.reload()}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={`${theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} (Ctrl + Shift + L)`}>
            <IconButton size="small" onClick={toggleTheme}>
              {theme === 'dark' ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
      </Toolbar>
    </AppBar>
  );
}

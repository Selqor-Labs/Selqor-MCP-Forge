import React, { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Tooltip from '@mui/material/Tooltip';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import ExtensionOutlinedIcon from '@mui/icons-material/ExtensionOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import TerminalOutlinedIcon from '@mui/icons-material/TerminalOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import SecurityOutlinedIcon from '@mui/icons-material/SecurityOutlined';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import useStore from '../store/useStore';

const TOPBAR_HEIGHT = 48;

const NAV = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    path: '/',
    icon: DashboardOutlinedIcon,
    tooltip: 'Home dashboard with activity overview',
    requiresIntegration: false,
  },
  {
    id: 'integrations',
    label: 'App Integrations',
    path: '/integrations',
    icon: ExtensionOutlinedIcon,
    tooltip: 'Create integrations from OpenAPI specs',
    requiresIntegration: false,
  },
  {
    id: 'llm',
    label: 'LLM Config',
    path: '/llm-config',
    icon: SmartToyOutlinedIcon,
    tooltip: 'Configure LLM providers for analysis',
    requiresIntegration: false,
  },
  {
    id: 'llm-logs',
    label: 'LLM Logs',
    path: '/llm-logs',
    icon: TerminalOutlinedIcon,
    tooltip: 'View LLM analysis logs',
    requiresIntegration: false,
  },
  {
    id: 'playground',
    label: 'Forge Playground',
    path: '/playground',
    icon: PlayArrowOutlinedIcon,
    tooltip: 'Test MCP servers and tools interactively',
    requiresIntegration: false,
  },
  {
    id: 'scanner',
    label: 'Security Scanner',
    path: '/scanner',
    icon: SecurityOutlinedIcon,
    tooltip: 'Analyze APIs for security issues',
    requiresIntegration: false,
  },
  {
    id: 'cicd',
    label: 'CI/CD',
    path: '/cicd',
    icon: AccountTreeOutlinedIcon,
    tooltip: 'Set up CI/CD pipeline for MCP servers',
    requiresIntegration: false,
  },
  {
    id: 'monitoring',
    label: 'Monitoring',
    path: '/monitoring',
    icon: MonitorHeartOutlinedIcon,
    tooltip: 'Monitor deployed MCP servers',
    requiresIntegration: false,
  },
  {
    id: 'settings',
    label: 'Settings',
    path: '/settings',
    icon: SettingsOutlinedIcon,
    tooltip: 'Application settings and preferences',
    requiresIntegration: false,
  },
];

export default function Sidebar({ drawerWidth = 200, collapsedWidth = 56 }) {
  const location = useLocation();
  const navigate = useNavigate();
  const muiTheme = useTheme();
  const isMobile = useMediaQuery(muiTheme.breakpoints.down('md'));

  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const closeSidebar = useStore((s) => s.closeSidebar);
  const setSidebarHovered = useStore((s) => s.setSidebarHovered);
  const hovered = useStore((s) => s.sidebarHovered);
  const integrations = useStore((s) => s.integrations);

  const hasIntegrations = useMemo(() => (integrations && integrations.length > 0), [integrations]);
  const expanded = isMobile ? true : hovered;
  const currentWidth = isMobile ? drawerWidth : (hovered ? drawerWidth : collapsedWidth);

  function isActive(item) {
    if (item.id === 'dashboard') return location.pathname === '/' || location.pathname === '/dashboard';
    return location.pathname.startsWith(item.path);
  }

  function handleNav(path) {
    navigate(path);
    if (isMobile) closeSidebar();
  }

  /**
   * Build tooltip text for a nav item:
   * - If disabled, show reason why
   * - Otherwise show the item's description
   */
  function buildTooltip(item) {
    if (item.requiresIntegration && !hasIntegrations) {
      return 'Create an integration first';
    }
    return item.tooltip || item.label;
  }

  const navList = (
    <List sx={{ flex: 1, py: 0.75, px: 0.75, overflow: 'hidden' }}>
      {NAV.map((item) => {
        const active = isActive(item);
        const isDisabled = item.requiresIntegration && !hasIntegrations;
        const Icon = item.icon;
        const btn = (
          <ListItemButton
            key={item.id}
            selected={active}
            disabled={isDisabled}
            onClick={() => !isDisabled && handleNav(item.path)}
            sx={{
              borderRadius: 1,
              mb: 0.25,
              minHeight: 36,
              px: 1.25,
              cursor: isDisabled ? 'not-allowed' : 'pointer',
              opacity: isDisabled ? 0.5 : 1,
              transition: 'opacity 200ms',
              '&.Mui-selected': {
                bgcolor: 'action.selected',
                '&:hover': { bgcolor: 'action.selected' },
              },
              '&.Mui-disabled': {
                opacity: 0.5,
              },
            }}
          >
            <ListItemIcon
              sx={{
                minWidth: 32,
                color: active ? 'text.primary' : 'text.secondary',
              }}
            >
              {isDisabled && item.requiresIntegration ? (
                <LockOutlinedIcon fontSize="small" />
              ) : (
                <Icon fontSize="small" />
              )}
            </ListItemIcon>
            <ListItemText
              primary={item.label}
              primaryTypographyProps={{
                variant: 'body2',
                fontWeight: active ? 600 : 500,
                noWrap: true,
                sx: {
                  opacity: expanded ? 1 : 0,
                  transition: 'opacity 200ms',
                },
              }}
            />
          </ListItemButton>
        );

        const tooltip = buildTooltip(item);
        return expanded ? (
          <Tooltip
            key={item.id}
            title={tooltip}
            placement="right"
            arrow
            disableInteractive
          >
            <Box>{btn}</Box>
          </Tooltip>
        ) : (
          <Tooltip key={item.id} title={tooltip} placement="right" arrow>
            {btn}
          </Tooltip>
        );
      })}
    </List>
  );

  // ── Mobile: temporary Drawer (full height, slides over topbar) ──
  if (isMobile) {
    return (
      <Drawer
        variant="temporary"
        open={sidebarOpen}
        onClose={closeSidebar}
        ModalProps={{ keepMounted: true }}
        sx={{
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            bgcolor: (t) => t.palette.custom.sidebarBg,
          },
        }}
      >
        {navList}
      </Drawer>
    );
  }

  // ── Desktop: permanent Drawer — starts BELOW topbar ──
  return (
    <Drawer
      variant="permanent"
      open
      onMouseEnter={() => setSidebarHovered(true)}
      onMouseLeave={() => setSidebarHovered(false)}
      sx={{
        width: currentWidth,
        flexShrink: 0,
        transition: 'width 200ms ease',
        '& .MuiDrawer-paper': {
          width: currentWidth,
          top: TOPBAR_HEIGHT,
          height: `calc(100vh - ${TOPBAR_HEIGHT}px)`,
          transition: 'width 200ms ease',
          overflow: 'hidden',
          bgcolor: (t) => t.palette.custom.sidebarBg,
          borderRight: '1px solid',
          borderColor: 'divider',
          boxSizing: 'border-box',
        },
      }}
    >
      {navList}
    </Drawer>
  );
}

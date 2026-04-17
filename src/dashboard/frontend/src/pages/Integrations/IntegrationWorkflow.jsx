import React from 'react';
import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Tooltip from '@mui/material/Tooltip';
import Paper from '@mui/material/Paper';
import Stepper from '@mui/material/Stepper';
import Step from '@mui/material/Step';
import StepButton from '@mui/material/StepButton';
import StepLabel from '@mui/material/StepLabel';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import CheckIcon from '@mui/icons-material/Check';
import IconButton from '@mui/material/IconButton';
import TextField from '@mui/material/TextField';
import useStore from '../../store/useStore';
import OverviewStep from './steps/OverviewStep';
import ToolBuilderStep from './steps/ToolBuilderStep';
import AuthStep from './steps/AuthStep';
import ScanStep from './steps/ScanStep';
import DeployStep from './steps/DeployStep';
import { fetchRuns, fetchTooling, fetchAuth, fetchDeployments, fetchVersions, updateIntegration } from '../../api';

const STEPS = [
  { label: 'Overview', desc: 'Run analysis & review results' },
  { label: 'Auth Config', desc: 'Set up authentication' },
  { label: 'Tool Builder', desc: 'Configure tool groupings' },
  { label: 'Scan & Secure', desc: 'Security vulnerability scan' },
  { label: 'Deploy', desc: 'Deploy MCP server' },
];

export default function IntegrationWorkflow({ integration, step = 1, onBack }) {
  const toast = useStore((s) => s.toast);
  const runs = useStore((s) => s.runs);
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState(integration.name);
  const [savingName, setSavingName] = useState(false);

  async function handleSaveName() {
    const trimmed = (nameValue || '').trim();
    if (!trimmed || trimmed === integration.name) { setEditingName(false); return; }
    setSavingName(true);
    try {
      await updateIntegration(integration.id, { name: trimmed });
      integration.name = trimmed;
      toast('Name updated', 'success');
      setEditingName(false);
    } catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Update failed'), 'error'); }
    finally { setSavingName(false); }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [runsRes, toolRes, authRes, deplRes, verRes] = await Promise.all([
        fetchRuns(integration.id), fetchTooling(integration.id).catch(() => null),
        fetchAuth(integration.id).catch(() => null), fetchDeployments(integration.id).catch(() => null),
        fetchVersions(integration.id).catch(() => null),
      ]);
      useStore.setState({ runs: runsRes.runs || [], tooling: toolRes, auth: authRes, deployments: deplRes?.deployments || [], versions: verRes?.versions || [] });
    } catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Load failed'), 'error'); }
    finally { setLoading(false); }
  }, [integration.id, toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const onReload = () => load();
    window.addEventListener('integration:reload', onReload);
    return () => window.removeEventListener('integration:reload', onReload);
  }, [load]);

  const completedSteps = [];
  if (runs.length > 0) completedSteps.push(0);
  const auth = useStore.getState().auth;
  if (auth?.auth_mode) completedSteps.push(1);
  const tooling = useStore.getState().tooling;
  if (tooling?.tools?.length > 0) completedSteps.push(2);
  if (auth?.base_url && /^https?:\/\//i.test(auth.base_url)) completedSteps.push(3);
  const deployments = useStore.getState().deployments;
  if (deployments?.length > 0) completedSteps.push(4);

  const stepContent = [
    <OverviewStep integration={integration} onReload={load} />,
    <AuthStep integration={integration} onReload={load} />,
    <ToolBuilderStep integration={integration} onReload={load} />,
    <ScanStep integration={integration} onReload={load} />,
    <DeployStep integration={integration} onReload={load} />,
  ];

  const activeStep = step - 1;

  function handleStepClick(idx) {
    const paths = ['', '/auth', '/tools', '/scan', '/deploy'];
    navigate(`/integrations/${integration.id}${paths[idx]}`);
  }

  return (
    <Box sx={{
      display: 'flex',
      // Fill the Layout's flex-constrained content box exactly, so the only
      // scroll container on this screen is the right pane below. Using a
      // viewport calc() here was fragile and produced a second (outer) scroll.
      height: '100%',
      minHeight: 0,
      borderRadius: 1,
      border: 1,
      borderColor: 'divider',
      overflow: 'hidden',
    }}>
      <Paper elevation={0} sx={{ width: { xs: '100%', md: 220 }, display: { xs: activeStep != null ? 'none' : 'flex', md: 'flex' }, flexDirection: 'column', gap: 2, p: 2, borderRight: 1, borderColor: 'divider', bgcolor: (t) => t.palette.custom?.sidebarBg || t.palette.background.default, flexShrink: 0 }}>
        <Tooltip title="Back to all integrations" placement="right">
          <Button size="small" variant="outlined" startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ justifyContent: 'flex-start' }}>All Integrations</Button>
        </Tooltip>
        <Box sx={{ pb: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          {editingName ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <TextField size="small" value={nameValue} onChange={(e) => setNameValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSaveName(); if (e.key === 'Escape') { setEditingName(false); setNameValue(integration.name); } }}
                autoFocus sx={{ flex: 1, '& input': { fontSize: '0.875rem', fontWeight: 600, py: 0.5 } }} />
              <IconButton size="small" onClick={handleSaveName} disabled={savingName} color="primary"><CheckIcon fontSize="small" /></IconButton>
            </Box>
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Tooltip title={integration.name} placement="right"><Typography variant="body1" fontWeight={600} noWrap sx={{ flex: 1 }}>{integration.name}</Typography></Tooltip>
              <Tooltip title="Edit name"><IconButton size="small" onClick={() => { setNameValue(integration.name); setEditingName(true); }} sx={{ opacity: 0.5, '&:hover': { opacity: 1 } }}><EditIcon sx={{ fontSize: 14 }} /></IconButton></Tooltip>
            </Box>
          )}
          <Tooltip title={integration.spec || ''} placement="right"><Typography variant="caption" color="text.secondary" noWrap sx={{ fontFamily: 'monospace', display: 'block' }}>{integration.spec || '—'}</Typography></Tooltip>
        </Box>
        <Stepper orientation="vertical" nonLinear activeStep={activeStep} sx={{ '& .MuiStepConnector-line': { minHeight: 16 } }}>
          {STEPS.map((s, i) => (
            <Step key={i} completed={completedSteps.includes(i)}>
              <StepButton onClick={() => handleStepClick(i)}><StepLabel>{s.label}</StepLabel></StepButton>
            </Step>
          ))}
        </Stepper>
      </Paper>
      <Box sx={{ flex: 1, p: { xs: 2, sm: 3 }, overflow: 'auto' }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
            <Typography variant="body2" color="text.secondary">Loading...</Typography>
          </Box>
        ) : stepContent[activeStep] || stepContent[0]}
      </Box>
    </Box>
  );
}

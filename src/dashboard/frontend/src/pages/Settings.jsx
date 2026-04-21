import React from 'react';
import { useEffect, useState } from 'react';
import useStore from '../store/useStore';
import ConfirmDialog from '../components/ConfirmDialog';
import LogoLoader from '../components/LogoLoader';
import {
  fetchPreferences, savePreferences,
  fetchScanPolicy, saveScanPolicy,
  fetchNotificationChannels, createNotificationChannel, updateNotificationChannel,
  deleteNotificationChannel, testNotificationChannel, fetchNotificationLogs,
} from '../api';
import {
  Box,
  Tabs,
  Tab,
  Typography,
  Paper,
  Button,
  TextField,
  MenuItem,
  Stack,
  Chip,
  Divider,
  FormControlLabel,
  Switch,
  CircularProgress,
  Alert,
  IconButton,
  Slider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Collapse,
  Select,
  InputLabel,
  FormControl,
} from '@mui/material';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import NotificationsOutlinedIcon from '@mui/icons-material/NotificationsOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import SendOutlinedIcon from '@mui/icons-material/SendOutlined';
import AddIcon from '@mui/icons-material/Add';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';

const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low'];

const DEFAULT_POLICY = {
  min_score_threshold: 70,
  blocked_severities: [],
  require_llm_analysis: false,
  require_code_pattern_analysis: false,
  require_dependency_scan: false,
  max_critical_findings: 0,
  max_high_findings: 5,
  auto_fail_on_critical: true,
};

function normalizePreferences(prefs) {
  const next = { ...(prefs || {}) };
  next.theme = next.theme === 'dark' ? 'dark' : 'light';
  next.default_scan_mode = next.default_scan_mode === 'full' ? 'full' : 'basic';
  if (typeof next.notifications_enabled !== 'boolean') next.notifications_enabled = true;
  if (typeof next.auto_remediate !== 'boolean') next.auto_remediate = false;
  if (!next.dashboard_layout) next.dashboard_layout = 'default';
  return next;
}

export default function Settings() {
  const toast = useStore((s) => s.toast);
  const authConfig = useStore((s) => s.authConfig);
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);

  // Preferences state
  const [prefs, setPrefs] = useState(null);
  const [savingPrefs, setSavingPrefs] = useState(false);

  // Scan Policy state
  const [policy, setPolicy] = useState(null);
  const [savingPolicy, setSavingPolicy] = useState(false);

  // Notifications state
  const [channels, setChannels] = useState([]);
  const [notifLogs, setNotifLogs] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [channelDialogOpen, setChannelDialogOpen] = useState(false);
  const [channelForm, setChannelForm] = useState({ name: '', channel_type: 'webhook', config: {}, enabled: true });
  const [savingChannel, setSavingChannel] = useState(false);
  const [testingChannel, setTestingChannel] = useState(null);
  const [deleteChannelTarget, setDeleteChannelTarget] = useState(null);

  async function loadPrefs() {
    try {
      const p = await fetchPreferences();
      setPrefs(normalizePreferences(p));
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function loadPolicy() {
    try {
      const p = await fetchScanPolicy();
      setPolicy({ ...DEFAULT_POLICY, ...p });
    } catch (err) {
      // If endpoint not found or empty, use defaults
      setPolicy({ ...DEFAULT_POLICY });
    }
  }

  async function loadChannels() {
    try {
      const res = await fetchNotificationChannels();
      setChannels(res.channels || []);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function loadNotifLogs() {
    try {
      const res = await fetchNotificationLogs();
      setNotifLogs((res.logs || []).slice(0, 20));
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  useEffect(() => {
    Promise.all([loadPrefs(), loadPolicy(), loadChannels()]).finally(() => setLoading(false));
  }, []);

  async function handleSavePrefs() {
    if (!prefs) return;
    setSavingPrefs(true);
    try {
      const saved = await savePreferences(normalizePreferences(prefs));
      setPrefs(normalizePreferences(saved));
      toast('Preferences saved');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSavingPrefs(false);
    }
  }

  async function handleSavePolicy() {
    if (!policy) return;
    setSavingPolicy(true);
    try {
      await saveScanPolicy(policy);
      toast('Scan policy saved');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSavingPolicy(false);
    }
  }

  async function handleCreateChannel() {
    setSavingChannel(true);
    try {
      await createNotificationChannel(channelForm);
      toast('Channel created');
      setChannelDialogOpen(false);
      setChannelForm({ name: '', channel_type: 'webhook', config: {}, enabled: true });
      loadChannels();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSavingChannel(false);
    }
  }

  async function handleToggleChannel(ch) {
    try {
      await updateNotificationChannel(ch.id, { enabled: !ch.enabled });
      loadChannels();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function handleTestChannel(id) {
    setTestingChannel(id);
    try {
      await testNotificationChannel(id);
      toast('Test notification sent');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setTestingChannel(null);
    }
  }

  async function handleDeleteChannel() {
    if (!deleteChannelTarget) return;
    try {
      await deleteNotificationChannel(deleteChannelTarget);
      toast('Channel deleted');
      loadChannels();
    } catch (err) {
      toast(err.message, 'error');
    }
    setDeleteChannelTarget(null);
  }

  function handleToggleSeverity(sev) {
    if (!policy) return;
    const current = policy.blocked_severities || [];
    const next = current.includes(sev)
      ? current.filter((s) => s !== sev)
      : [...current, sev];
    setPolicy({ ...policy, blocked_severities: next });
  }

  function handleExport() {
    window.open('/api/settings/export', '_blank');
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
        <LogoLoader size={96} message="Loading..." />
      </Box>
    );
  }

  return (
    <Box>
      {/* Page header */}
      <Box sx={{ mb: 3, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>
            Settings
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Configure scan policies, preferences, and notifications
          </Typography>
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={<DownloadOutlinedIcon />}
          onClick={handleExport}
          sx={{ height: 36, textTransform: 'none' }}
        >
          Export All Data
        </Button>
      </Box>

      {authConfig?.local_only && (
        <Alert severity="info" sx={{ mb: 3, maxWidth: 760 }}>
          {authConfig.message} API auth for integrations is supported, but shared dashboard auth,
          organizations, and team management are intentionally disabled in this public build.
        </Alert>
      )}

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          textColor="primary"
          indicatorColor="primary"
        >
          <Tab
            icon={<ShieldOutlinedIcon fontSize="small" />}
            iconPosition="start"
            label="Scan Policy"
            sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }}
          />
          <Tab
            icon={<TuneOutlinedIcon fontSize="small" />}
            iconPosition="start"
            label="Preferences"
            sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }}
          />
          <Tab
            icon={<NotificationsOutlinedIcon fontSize="small" />}
            iconPosition="start"
            label="Notifications"
            sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }}
          />
        </Tabs>
      </Box>

      {/* ───── Scan Policy Tab ───── */}
      {tab === 0 && policy && (
        <Stack spacing={3.5} sx={{ maxWidth: 560 }}>
          <Box>
            <Typography variant="subtitle1" fontWeight={700}>
              Scan Policy
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Enforce organisation-wide security rules for all scans and CI runs
            </Typography>
          </Box>

          {/* Minimum Score Threshold */}
          <Box>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.25 }}>
              Minimum Score Threshold
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
              Scans and CI runs that score below this will be marked as failing
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <Slider
                value={policy.min_score_threshold}
                onChange={(_, v) => setPolicy({ ...policy, min_score_threshold: v })}
                min={0}
                max={100}
                step={1}
                valueLabelDisplay="auto"
                sx={{ flex: 1 }}
              />
              <TextField
                size="small"
                type="number"
                value={policy.min_score_threshold}
                onChange={(e) => {
                  const v = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                  setPolicy({ ...policy, min_score_threshold: v });
                }}
                inputProps={{ min: 0, max: 100, style: { width: 48, textAlign: 'center' } }}
                sx={{ width: 80 }}
              />
            </Stack>
          </Box>

          <Divider />

          {/* Auto-fail & Finding Limits */}
          <Box>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1.5 }}>
              Finding Limits
            </Typography>

            <Stack spacing={1.5}>
              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Auto-fail on Critical</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Automatically fail any scan that has critical findings
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={policy.auto_fail_on_critical}
                    onChange={(e) => setPolicy({ ...policy, auto_fail_on_critical: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />

              <Stack direction="row" spacing={2}>
                <TextField
                  size="small"
                  label="Max Critical Findings"
                  type="number"
                  value={policy.max_critical_findings}
                  onChange={(e) => setPolicy({ ...policy, max_critical_findings: Math.max(0, Number(e.target.value) || 0) })}
                  inputProps={{ min: 0 }}
                  helperText="Maximum allowed critical findings before auto-fail (0 = zero tolerance)"
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Max High Findings"
                  type="number"
                  value={policy.max_high_findings}
                  onChange={(e) => setPolicy({ ...policy, max_high_findings: Math.max(0, Number(e.target.value) || 0) })}
                  inputProps={{ min: 0 }}
                  helperText="Maximum allowed high severity findings"
                  fullWidth
                />
              </Stack>
            </Stack>
          </Box>

          <Divider />

          {/* Blocked Severities */}
          <Box>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.25 }}>
              Blocked Severities
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
              Scans with these severity findings are blocked from passing
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap">
              {SEVERITY_OPTIONS.map((sev) => {
                const active = (policy.blocked_severities || []).includes(sev);
                return (
                  <Chip
                    key={sev}
                    label={sev}
                    size="small"
                    color={active ? 'error' : 'default'}
                    variant={active ? 'filled' : 'outlined'}
                    onClick={() => handleToggleSeverity(sev)}
                    sx={{ textTransform: 'capitalize', cursor: 'pointer' }}
                  />
                );
              })}
            </Stack>
          </Box>

          <Divider />

          {/* Required Scan Options */}
          <Box>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.25 }}>
              Required Scan Options
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
              Enforce which analysis steps must run on every scan
            </Typography>
            <Stack spacing={1}>
              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Require LLM Analysis</Typography>
                    <Typography variant="caption" color="text.secondary">
                      All scans must include AI-powered analysis
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={policy.require_llm_analysis}
                    onChange={(e) => setPolicy({ ...policy, require_llm_analysis: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />
              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Require Code Pattern Analysis</Typography>
                    <Typography variant="caption" color="text.secondary">
                      All scans must include static code pattern checks
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={policy.require_code_pattern_analysis}
                    onChange={(e) => setPolicy({ ...policy, require_code_pattern_analysis: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />
              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Require Dependency Scan</Typography>
                    <Typography variant="caption" color="text.secondary">
                      All scans must include deep dependency scanning
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={policy.require_dependency_scan}
                    onChange={(e) => setPolicy({ ...policy, require_dependency_scan: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />
            </Stack>
          </Box>

          <Box>
            <Button
              variant="contained"
              size="small"
              onClick={handleSavePolicy}
              disabled={savingPolicy}
              startIcon={savingPolicy ? <CircularProgress size={14} color="inherit" /> : null}
            >
              {savingPolicy ? 'Saving...' : 'Save Policy'}
            </Button>
          </Box>
        </Stack>
      )}

      {tab === 0 && !policy && (
        <Alert severity="warning" sx={{ maxWidth: 560 }}>
          Scan policy could not be loaded.
        </Alert>
      )}

      {/* ───── Preferences Tab ───── */}
      {tab === 1 && prefs && (
        <Stack spacing={3.5} sx={{ maxWidth: 480 }}>
          {/* Appearance */}
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.25 }}>
              Appearance
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
              Control how the dashboard looks and feels
            </Typography>
            <TextField
              size="small"
              label="Theme"
              select
              value={prefs.theme || 'light'}
              onChange={(e) => setPrefs({ ...prefs, theme: e.target.value })}
              fullWidth
            >
              <MenuItem value="light">Light</MenuItem>
              <MenuItem value="dark">Dark</MenuItem>
            </TextField>
          </Box>

          <Divider />

          {/* Defaults */}
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.25 }}>
              Defaults
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
              Set default behaviour for new scans and integrations
            </Typography>
            <TextField
              size="small"
              label="Default Scan Mode"
              select
              value={prefs.default_scan_mode || 'basic'}
              onChange={(e) => setPrefs({ ...prefs, default_scan_mode: e.target.value })}
              fullWidth
            >
              <MenuItem value="basic">Basic</MenuItem>
              <MenuItem value="full">Full</MenuItem>
            </TextField>
          </Box>

          <Divider />

          {/* Automation */}
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.25 }}>
              Automation
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
              Configure automated alerts and remediation behaviour
            </Typography>
            <Stack spacing={1}>
              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Enable Notifications</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Receive alerts when scans complete or servers go down
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={prefs.notifications_enabled ?? true}
                    onChange={(e) => setPrefs({ ...prefs, notifications_enabled: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />

              <FormControlLabel
                label={
                  <Box>
                    <Typography variant="body2">Auto-remediate</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Automatically apply safe remediation fixes after scans complete
                    </Typography>
                  </Box>
                }
                control={
                  <Switch
                    checked={prefs.auto_remediate ?? false}
                    onChange={(e) => setPrefs({ ...prefs, auto_remediate: e.target.checked })}
                    size="small"
                  />
                }
                sx={{ alignItems: 'flex-start', ml: 0, '.MuiSwitch-root': { mt: 0.5 } }}
              />
            </Stack>
          </Box>

          <Box>
            <Button
              variant="contained"
              size="small"
              onClick={handleSavePrefs}
              disabled={savingPrefs}
              startIcon={savingPrefs ? <CircularProgress size={14} color="inherit" /> : null}
            >
              {savingPrefs ? 'Saving...' : 'Save Preferences'}
            </Button>
          </Box>
        </Stack>
      )}

      {tab === 1 && !prefs && (
        <Alert severity="warning" sx={{ maxWidth: 480 }}>
          Preferences could not be loaded.
        </Alert>
      )}

      {/* ───── Notifications Tab ───── */}
      {tab === 2 && (
        <Stack spacing={3} sx={{ maxWidth: 720 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={700}>
                Notification Channels
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Configure where alerts and notifications are delivered
              </Typography>
            </Box>
            <Button
              variant="contained"
              size="small"
              startIcon={<AddIcon />}
              onClick={() => {
                setChannelForm({ name: '', channel_type: 'webhook', config: {}, enabled: true });
                setChannelDialogOpen(true);
              }}
              sx={{ textTransform: 'none' }}
            >
              Add Channel
            </Button>
          </Box>

          {/* Channel table */}
          {channels.length === 0 ? (
            <Alert severity="info">No notification channels configured yet.</Alert>
          ) : (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell align="center">Enabled</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {channels.map((ch) => (
                    <TableRow key={ch.id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight={500}>{ch.name}</Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={ch.channel_type}
                          size="small"
                          color={
                            ch.channel_type === 'slack' ? 'primary' :
                            ch.channel_type === 'email' ? 'secondary' : 'default'
                          }
                          variant="outlined"
                          sx={{ textTransform: 'capitalize', fontSize: 12 }}
                        />
                      </TableCell>
                      <TableCell align="center">
                        <Switch
                          checked={ch.enabled}
                          onChange={() => handleToggleChannel(ch)}
                          size="small"
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          <IconButton
                            size="small"
                            onClick={() => handleTestChannel(ch.id)}
                            disabled={testingChannel === ch.id}
                            title="Send test notification"
                          >
                            {testingChannel === ch.id ? (
                              <CircularProgress size={16} />
                            ) : (
                              <SendOutlinedIcon fontSize="small" />
                            )}
                          </IconButton>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => setDeleteChannelTarget(ch.id)}
                            title="Delete channel"
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {/* Recent Logs (collapsible) */}
          <Box>
            <Button
              size="small"
              onClick={() => {
                if (!logsOpen) loadNotifLogs();
                setLogsOpen((v) => !v);
              }}
              startIcon={logsOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              sx={{ textTransform: 'none', mb: 1 }}
            >
              Recent Notification Logs
            </Button>
            <Collapse in={logsOpen}>
              {notifLogs.length === 0 ? (
                <Alert severity="info" sx={{ mt: 1 }}>No notification logs yet.</Alert>
              ) : (
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Timestamp</TableCell>
                        <TableCell>Event</TableCell>
                        <TableCell align="right">Status</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {notifLogs.map((log, i) => (
                        <TableRow key={log.id || i}>
                          <TableCell>
                            <Typography variant="caption">
                              {log.created_at ? new Date(log.created_at).toLocaleString() : '\u2014'}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">{log.event || log.message || '\u2014'}</Typography>
                          </TableCell>
                          <TableCell align="right">
                            <Chip
                              label={log.status || 'unknown'}
                              size="small"
                              color={log.status === 'sent' ? 'success' : log.status === 'failed' ? 'error' : 'default'}
                              sx={{ fontSize: 11, height: 20 }}
                            />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Collapse>
          </Box>
        </Stack>
      )}

      {/* Add Channel Dialog */}
      <Dialog
        open={channelDialogOpen}
        onClose={() => setChannelDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Add Notification Channel</DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} sx={{ mt: 1 }}>
            <TextField
              size="small"
              label="Name"
              value={channelForm.name}
              onChange={(e) => setChannelForm({ ...channelForm, name: e.target.value })}
              fullWidth
              required
            />
            <FormControl size="small" fullWidth>
              <InputLabel>Type</InputLabel>
              <Select
                value={channelForm.channel_type}
                label="Type"
                onChange={(e) =>
                  setChannelForm({ ...channelForm, channel_type: e.target.value, config: {} })
                }
              >
                <MenuItem value="webhook">Webhook</MenuItem>
                <MenuItem value="slack">Slack</MenuItem>
                <MenuItem value="email">Email</MenuItem>
              </Select>
            </FormControl>

            {/* Dynamic config fields */}
            {channelForm.channel_type === 'webhook' && (
              <>
                <TextField
                  size="small"
                  label="Webhook URL"
                  value={channelForm.config.url || ''}
                  onChange={(e) =>
                    setChannelForm({ ...channelForm, config: { ...channelForm.config, url: e.target.value } })
                  }
                  fullWidth
                  required
                  placeholder="https://example.com/webhook"
                />
                <TextField
                  size="small"
                  label="Headers (JSON, optional)"
                  value={channelForm.config.headers || ''}
                  onChange={(e) =>
                    setChannelForm({ ...channelForm, config: { ...channelForm.config, headers: e.target.value } })
                  }
                  fullWidth
                  multiline
                  minRows={2}
                  placeholder='{"Authorization": "Bearer ..."}'
                />
              </>
            )}

            {channelForm.channel_type === 'slack' && (
              <TextField
                size="small"
                label="Slack Webhook URL"
                value={channelForm.config.webhook_url || ''}
                onChange={(e) =>
                  setChannelForm({ ...channelForm, config: { ...channelForm.config, webhook_url: e.target.value } })
                }
                fullWidth
                required
                placeholder="https://hooks.slack.com/services/..."
              />
            )}

            {channelForm.channel_type === 'email' && (
              <>
                <TextField
                  size="small"
                  label="Recipients (comma-separated)"
                  value={channelForm.config.recipients || ''}
                  onChange={(e) =>
                    setChannelForm({ ...channelForm, config: { ...channelForm.config, recipients: e.target.value } })
                  }
                  fullWidth
                  required
                  placeholder="alice@example.com, bob@example.com"
                />
                <Alert severity="info" sx={{ fontSize: 13 }}>
                  Email delivery requires SMTP to be configured on the server.
                </Alert>
              </>
            )}

            <FormControlLabel
              label="Enabled"
              control={
                <Switch
                  checked={channelForm.enabled}
                  onChange={(e) => setChannelForm({ ...channelForm, enabled: e.target.checked })}
                  size="small"
                />
              }
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChannelDialogOpen(false)} sx={{ textTransform: 'none' }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleCreateChannel}
            disabled={savingChannel || !channelForm.name.trim()}
            startIcon={savingChannel ? <CircularProgress size={14} color="inherit" /> : null}
            sx={{ textTransform: 'none' }}
          >
            {savingChannel ? 'Creating...' : 'Create Channel'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Confirm dialogs */}
      <ConfirmDialog
        open={!!deleteChannelTarget}
        onClose={() => setDeleteChannelTarget(null)}
        onConfirm={handleDeleteChannel}
        title="Delete Channel"
        message="Are you sure you want to delete this notification channel?"
        confirmLabel="Delete"
        confirmClass="btn-danger"
      />
    </Box>
  );
}

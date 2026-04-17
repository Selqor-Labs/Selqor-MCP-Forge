import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import useStore from '../store/useStore';
import ConfirmDialog from '../components/ConfirmDialog';
import LogoLoader from '../components/LogoLoader';
import {
  fetchMonitoringServers,
  addMonitoringServer,
  updateMonitoringServer,
  deleteMonitoringServer,
  checkMonitoringServer,
  checkAllMonitoringServers,
  fetchMonitoringHistory,
  fetchMonitoringStats,
  fetchAlertRules,
  createAlertRule,
  deleteAlertRule,
  fetchFiredAlerts,
  acknowledgeAlert,
  startMonitoringScheduler,
  stopMonitoringScheduler,
  fetchSchedulerStatus,
} from '../api';
import {
  Box,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  Typography,
  Button,
  Chip,
  Stack,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress,
  IconButton,
  Tooltip,
  Divider,
  LinearProgress,
  Alert,
  InputAdornment,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import AddIcon from '@mui/icons-material/Add';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import NotificationsActiveOutlinedIcon from '@mui/icons-material/NotificationsActiveOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';

// ── helpers ────────────────────────────────────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function statusColor(status) {
  if (status === 'healthy') return 'success';
  if (status === 'unhealthy' || status === 'unreachable' || status === 'error' || status === 'timeout') return 'error';
  return 'default';
}

function StatusChip({ status }) {
  return (
    <Chip
      label={status || 'unknown'}
      size="small"
      color={statusColor(status)}
      variant={status === 'unknown' || !status ? 'outlined' : 'filled'}
      sx={{ height: 20, fontSize: 11, textTransform: 'capitalize', fontWeight: 600 }}
    />
  );
}

function fmtLatency(ms) {
  if (ms == null || ms === 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

const MIN_INTERVAL = 30;
const HTTP_URL_RE = /^https?:\/\/[^\s]+$/;

const EMPTY_FORM = {
  name: '',
  url: '',
  check_interval_seconds: 300,
};

// Build a friendly error message out of a FastAPI 422 payload or any
// generic JS error.
function formatApiError(err) {
  if (!err) return 'Request failed';
  if (typeof err === 'string') return err;
  const msg = err.message || '';
  // FastAPI 422 detail can be a JSON-encoded array. Try to parse it.
  try {
    if (msg.startsWith('{') || msg.startsWith('[')) {
      const parsed = JSON.parse(msg);
      if (parsed?.detail && Array.isArray(parsed.detail)) {
        return parsed.detail
          .map((d) => `${(d.loc || []).slice(1).join('.') || 'field'}: ${d.msg}`)
          .join(' · ');
      }
      if (parsed?.detail && typeof parsed.detail === 'string') return parsed.detail;
    }
  } catch { /* ignore */ }
  return msg || 'Request failed';
}

// ── component ────────────────────────────────────────────────────────────────
// Mini sparkline component — renders an inline SVG line chart
function Sparkline({ data, width = 80, height = 24, color = '#4caf50' }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

export default function Monitoring() {
  const toast = useStore((s) => s.toast);
  const theme = useTheme();

  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [checking, setChecking] = useState(null);
  const [checkingAll, setCheckingAll] = useState(false);
  const [selectedServer, setSelectedServer] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Stats & alerts state
  const [serverStats, setServerStats] = useState(null);
  const [alertRules, setAlertRules] = useState([]);
  const [alertDialogOpen, setAlertDialogOpen] = useState(false);
  const [alertForm, setAlertForm] = useState({ name: '', condition: 'latency_above', threshold: 2000 });
  const [firedAlerts, setFiredAlerts] = useState([]);

  // Scheduler state
  const [schedulerRunning, setSchedulerRunning] = useState(false);
  const [schedulerToggling, setSchedulerToggling] = useState(false);

  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  // ── scheduler ─────────────────────────────────────────────────────────────
  async function loadSchedulerStatus() {
    try {
      const res = await fetchSchedulerStatus();
      setSchedulerRunning(res.running || false);
    } catch { /* ignore */ }
  }

  async function toggleScheduler() {
    setSchedulerToggling(true);
    try {
      if (schedulerRunning) {
        await stopMonitoringScheduler();
        toast('Auto-monitoring stopped', 'info');
      } else {
        await startMonitoringScheduler();
        toast('Auto-monitoring started — checks every 5 minutes', 'success');
      }
      setSchedulerRunning(!schedulerRunning);
    } catch (err) {
      toast(err.message || 'Failed to toggle scheduler', 'error');
    } finally {
      setSchedulerToggling(false);
    }
  }

  // ── data loading ──────────────────────────────────────────────────────────
  async function loadServers() {
    try {
      const res = await fetchMonitoringServers();
      setServers(res.servers || []);
    } catch (err) {
      toast(formatApiError(err), 'error');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadServers(); loadSchedulerStatus(); }, []);

  async function loadHistory(id) {
    setHistoryLoading(true);
    try {
      const res = await fetchMonitoringHistory(id);
      setHistory(res.checks || []);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadStats(id) {
    try {
      const res = await fetchMonitoringStats(id);
      setServerStats(res);
    } catch { setServerStats(null); }
  }

  async function loadAlertRules(id) {
    try {
      const res = await fetchAlertRules(id);
      setAlertRules(res.rules || []);
    } catch { setAlertRules([]); }
  }

  async function loadFiredAlerts() {
    try {
      const res = await fetchFiredAlerts();
      setFiredAlerts(res.alerts || []);
    } catch { /* ignore */ }
  }

  useEffect(() => { loadFiredAlerts(); }, []);

  async function handleCreateAlert(e) {
    e?.preventDefault?.();
    if (!selectedServer || !alertForm.name.trim()) return;
    try {
      await createAlertRule(selectedServer, alertForm);
      toast('Alert rule created');
      setAlertDialogOpen(false);
      setAlertForm({ name: '', condition: 'latency_above', threshold: 2000 });
      loadAlertRules(selectedServer);
    } catch (err) {
      toast(formatApiError(err), 'error');
    }
  }

  async function handleDeleteAlert(ruleId) {
    if (!selectedServer) return;
    try {
      await deleteAlertRule(selectedServer, ruleId);
      toast('Alert rule removed');
      loadAlertRules(selectedServer);
    } catch (err) {
      toast(formatApiError(err), 'error');
    }
  }

  // ── form handling ─────────────────────────────────────────────────────────
  function openCreate() {
    setForm(EMPTY_FORM);
    setErrors({});
    setEditId(null);
    setDialogOpen(true);
  }

  function openEdit(server) {
    setForm({
      name: server.name || '',
      url: server.url || '',
      check_interval_seconds: server.check_interval_seconds || 300,
    });
    setErrors({});
    setEditId(server.id);
    setDialogOpen(true);
  }

  function closeDialog() {
    setDialogOpen(false);
    setEditId(null);
    setForm(EMPTY_FORM);
    setErrors({});
  }

  function setField(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    if (errors[field]) setErrors((e) => ({ ...e, [field]: '' }));
  }

  function validate() {
    const next = {};
    if (!form.name.trim()) {
      next.name = 'Name is required';
    } else if (form.name.length > 120) {
      next.name = 'Name must be at most 120 characters';
    }

    const url = form.url.trim();
    if (!url) {
      next.url = 'URL is required';
    } else if (!HTTP_URL_RE.test(url)) {
      next.url = 'URL must start with http:// or https://';
    }

    const interval = Number(form.check_interval_seconds);
    if (!Number.isFinite(interval)) {
      next.check_interval_seconds = 'Interval must be a number';
    } else if (interval < MIN_INTERVAL) {
      next.check_interval_seconds = `Interval must be at least ${MIN_INTERVAL} seconds`;
    } else if (interval > 86400) {
      next.check_interval_seconds = 'Interval must be at most 24 hours (86 400 s)';
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e) {
    e?.preventDefault?.();
    if (!validate()) return;
    setSubmitting(true);
    try {
      const payload = {
        name: form.name.trim(),
        url: form.url.trim(),
        check_interval_seconds: Number(form.check_interval_seconds),
      };
      if (editId) {
        await updateMonitoringServer(editId, payload);
        toast('Server updated');
      } else {
        await addMonitoringServer(payload);
        toast('Server added');
      }
      closeDialog();
      loadServers();
    } catch (err) {
      const friendly = formatApiError(err);
      toast(friendly, 'error');
      // If the server complained about a specific field, surface it inline.
      if (/url/i.test(friendly)) setErrors((e) => ({ ...e, url: friendly }));
      else if (/name/i.test(friendly)) setErrors((e) => ({ ...e, name: friendly }));
      else if (/interval/i.test(friendly)) setErrors((e) => ({ ...e, check_interval_seconds: friendly }));
    } finally {
      setSubmitting(false);
    }
  }

  // ── actions ───────────────────────────────────────────────────────────────
  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteMonitoringServer(deleteTarget);
      toast('Server removed');
      if (selectedServer === deleteTarget) {
        setSelectedServer(null);
        setHistory([]);
      }
      loadServers();
    } catch (err) {
      toast(formatApiError(err), 'error');
    }
    setDeleteTarget(null);
  }

  async function handleCheck(id) {
    setChecking(id);
    try {
      const res = await checkMonitoringServer(id);
      if (res.status === 'healthy') {
        toast(`Healthy · ${fmtLatency(res.latency_ms)} · ${res.tool_count} tool${res.tool_count === 1 ? '' : 's'}`);
      } else {
        toast(`${res.status}: ${res.error || 'check failed'}`, 'error');
      }
      loadServers();
      if (selectedServer === id) loadHistory(id);
    } catch (err) {
      toast(formatApiError(err), 'error');
    } finally {
      setChecking(null);
    }
  }

  async function handleCheckAll() {
    if (servers.length === 0) return;
    setCheckingAll(true);
    try {
      const res = await checkAllMonitoringServers();
      const healthy = (res.results || []).filter((r) => r.status === 'healthy').length;
      const total = res.total || 0;
      toast(`${healthy}/${total} healthy`);
      loadServers();
      if (selectedServer) loadHistory(selectedServer);
    } catch (err) {
      toast(formatApiError(err), 'error');
    } finally {
      setCheckingAll(false);
    }
  }

  function handleSelectServer(id) {
    setSelectedServer(id);
    loadHistory(id);
    loadStats(id);
    loadAlertRules(id);
  }

  // ── derived ──────────────────────────────────────────────────────────────
  const summary = useMemo(() => {
    const out = { total: servers.length, healthy: 0, unhealthy: 0, unknown: 0 };
    servers.forEach((s) => {
      if (s.status === 'healthy') out.healthy += 1;
      else if (s.status && s.status !== 'unknown') out.unhealthy += 1;
      else out.unknown += 1;
    });
    return out;
  }, [servers]);

  const selectedServerObj = useMemo(
    () => servers.find((s) => s.id === selectedServer),
    [servers, selectedServer],
  );

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
        <LogoLoader size={96} message="Loading…" />
      </Box>
    );
  }

  return (
    <Box>
      {/* Page header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3, gap: 2, flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="h6" fontWeight={700}>Server Monitoring</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            Monitor uptime and availability of your deployed MCP servers. Get alerted when servers go down or respond slowly.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexShrink={0} alignItems="center">
          {/* Auto-monitoring toggle */}
          <Chip
            label={schedulerRunning ? 'Auto-monitoring ON' : 'Auto-monitoring OFF'}
            color={schedulerRunning ? 'success' : 'default'}
            variant={schedulerRunning ? 'filled' : 'outlined'}
            size="small"
            onClick={toggleScheduler}
            disabled={schedulerToggling}
            sx={{ cursor: 'pointer', fontWeight: 600 }}
          />
          {servers.length > 0 && (
            <Button
              variant="outlined"
              size="small"
              startIcon={checkingAll ? <CircularProgress size={14} color="inherit" /> : <RefreshOutlinedIcon />}
              onClick={handleCheckAll}
              disabled={checkingAll}
            >
              {checkingAll ? 'Checking…' : 'Check All'}
            </Button>
          )}
          <Button
            variant="contained"
            size="small"
            startIcon={<AddIcon />}
            onClick={openCreate}
          >
            Add Server
          </Button>
        </Stack>
      </Box>

      {/* Summary strip */}
      {servers.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2.5 }} flexWrap="wrap" useFlexGap>
          <Chip label={`${summary.total} total`} size="small" />
          <Chip label={`${summary.healthy} healthy`} size="small" color="success" variant={summary.healthy ? 'filled' : 'outlined'} />
          <Chip label={`${summary.unhealthy} unhealthy`} size="small" color="error" variant={summary.unhealthy ? 'filled' : 'outlined'} />
          {summary.unknown > 0 && (
            <Chip label={`${summary.unknown} not yet checked`} size="small" variant="outlined" />
          )}
        </Stack>
      )}

      {/* Server grid or empty state */}
      {servers.length === 0 ? (
        <Paper
          variant="outlined"
          sx={{
            p: 6,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 1.5,
            color: 'text.secondary',
            borderStyle: 'dashed',
          }}
        >
          <MonitorHeartOutlinedIcon sx={{ fontSize: 40, opacity: 0.45 }} />
          <Typography variant="subtitle2" fontWeight={600}>No servers being monitored</Typography>
          <Box sx={{ maxWidth: 420, textAlign: 'left', mt: 0.5 }}>
            <Typography variant="caption" component="ul" sx={{ pl: 2, mb: 0, '& li': { mb: 0.5 } }}>
              <li><strong>Track uptime</strong> — know instantly when a server goes down</li>
              <li><strong>Measure response times</strong> — spot performance degradation early</li>
              <li><strong>Verify tool availability</strong> — ensure all expected tools are registered</li>
            </Typography>
          </Box>
          <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openCreate} sx={{ mt: 1 }}>
            Add Server
          </Button>
        </Paper>
      ) : (
        <Grid container spacing={2}>
          {servers.map((s) => {
            const isSelected = selectedServer === s.id;
            const isChecking = checking === s.id;
            return (
              <Grid item xs={12} sm={6} md={4} key={s.id}>
                <Card
                  variant="outlined"
                  sx={{
                    border: 2,
                    borderColor: isSelected ? 'primary.main' : 'divider',
                    transition: 'border-color 0.15s',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  {isChecking && (
                    <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3 }} />
                  )}
                  <CardActionArea onClick={() => handleSelectServer(s.id)} sx={{ pt: isChecking ? 0.375 : 0 }}>
                    <CardContent sx={{ pb: '8px !important' }}>
                      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.75, gap: 1 }}>
                        <Typography variant="body2" fontWeight={700} noWrap sx={{ flex: 1, minWidth: 0 }}>
                          {s.name}
                        </Typography>
                        <StatusChip status={s.status} />
                      </Stack>
                      <Tooltip title={s.url} placement="top">
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ fontFamily: 'monospace', display: 'block', mb: 0.5 }}
                          noWrap
                        >
                          {s.url}
                        </Typography>
                      </Tooltip>
                      <Typography variant="caption" color="text.secondary" display="block">
                        Every {s.check_interval_seconds}s · Last check {fmtDate(s.last_check)}
                      </Typography>
                    </CardContent>
                  </CardActionArea>

                  <Divider />

                  <Stack
                    direction="row"
                    spacing={0.5}
                    sx={{ px: 1.5, py: 0.75, justifyContent: 'space-between' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Stack direction="row" spacing={0.5}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={isChecking ? <CircularProgress size={12} color="inherit" /> : <PlayArrowOutlinedIcon />}
                        onClick={() => handleCheck(s.id)}
                        disabled={isChecking || checkingAll}
                      >
                        {isChecking ? 'Checking…' : 'Check'}
                      </Button>
                      <Tooltip title="Edit server">
                        <span>
                          <IconButton size="small" onClick={() => openEdit(s)} disabled={isChecking}>
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </Stack>
                    <Tooltip title="Remove from monitoring">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setDeleteTarget(s.id)}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      {/* History */}
      {selectedServer && (
        <Box sx={{ mt: 4 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Check History {selectedServerObj && `· ${selectedServerObj.name}`}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {history.length} {history.length === 1 ? 'check' : 'checks'} (last 50)
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: 'block' }}>
            Response time and availability history for this server
          </Typography>
          <Paper variant="outlined">
            {historyLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
                <LogoLoader size={56} />
              </Box>
            ) : history.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>No checks yet</Typography>
                <Typography variant="caption">
                  Click <strong>Check</strong> on the card above to record the first health check.
                </Typography>
              </Box>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Time</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Latency</TableCell>
                    <TableCell>Tools</TableCell>
                    <TableCell>Error</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {history.slice().reverse().map((h, i) => (
                    <TableRow key={i} hover>
                      <TableCell><Typography variant="caption">{fmtDate(h.timestamp)}</Typography></TableCell>
                      <TableCell><StatusChip status={h.status} /></TableCell>
                      <TableCell><Typography variant="caption">{fmtLatency(h.latency_ms)}</Typography></TableCell>
                      <TableCell><Typography variant="caption">{h.tool_count ?? '—'}</Typography></TableCell>
                      <TableCell sx={{ maxWidth: 320 }}>
                        <Typography
                          variant="caption"
                          color={h.error ? 'error.main' : 'text.disabled'}
                          sx={{
                            display: 'block',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            fontFamily: h.error ? 'monospace' : 'inherit',
                          }}
                          title={h.error || ''}
                        >
                          {h.error || '—'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Paper>
        </Box>
      )}

      {/* Uptime Stats Panel */}
      {selectedServer && serverStats && serverStats.total_checks > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
            Server Stats {selectedServerObj && `· ${selectedServerObj.name}`}
          </Typography>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={6} sm={3}>
              <Card variant="outlined">
                <CardContent sx={{ textAlign: 'center', py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Typography variant="h5" fontWeight={700} color={serverStats.uptime_percent >= 99 ? 'success.main' : serverStats.uptime_percent >= 90 ? 'warning.main' : 'error.main'}>
                    {serverStats.uptime_percent}%
                  </Typography>
                  <Typography variant="caption" color="text.secondary">Uptime</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Card variant="outlined">
                <CardContent sx={{ textAlign: 'center', py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Typography variant="h5" fontWeight={700}>{fmtLatency(serverStats.avg_latency_ms)}</Typography>
                  <Typography variant="caption" color="text.secondary">Avg Latency</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Card variant="outlined">
                <CardContent sx={{ textAlign: 'center', py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Typography variant="h5" fontWeight={700}>{fmtLatency(serverStats.p95_latency_ms)}</Typography>
                  <Typography variant="caption" color="text.secondary">P95 Latency</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Card variant="outlined">
                <CardContent sx={{ textAlign: 'center', py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Typography variant="h5" fontWeight={700} color={serverStats.consecutive_failures > 0 ? 'error.main' : 'success.main'}>
                    {serverStats.consecutive_failures}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">Consecutive Failures</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
          {/* Latency sparkline */}
          {serverStats.latency_sparkline?.length >= 2 && (
            <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Response Time Trend (last {serverStats.latency_sparkline.length} checks)
              </Typography>
              <Sparkline
                data={serverStats.latency_sparkline}
                width={480}
                height={40}
                color={theme.palette.primary.main}
              />
              <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
                <Typography variant="caption" color="text.secondary">
                  Min: {fmtLatency(Math.min(...serverStats.latency_sparkline))}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Max: {fmtLatency(Math.max(...serverStats.latency_sparkline))}
                </Typography>
              </Stack>
            </Paper>
          )}
        </Box>
      )}

      {/* Alert Rules */}
      {selectedServer && (
        <Box sx={{ mt: 3 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Alert Rules {selectedServerObj && `· ${selectedServerObj.name}`}
            </Typography>
            <Button size="small" variant="outlined" startIcon={<NotificationsActiveOutlinedIcon />} onClick={() => setAlertDialogOpen(true)}>
              Add Rule
            </Button>
          </Stack>
          {alertRules.length === 0 ? (
            <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderStyle: 'dashed' }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>No alert rules configured</Typography>
              <Typography variant="caption" color="text.secondary">
                Set up rules to get notified when latency spikes, servers go down, or consecutive failures exceed a threshold.
              </Typography>
            </Paper>
          ) : (
            <Paper variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Condition</TableCell>
                    <TableCell>Threshold</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {alertRules.map((rule) => (
                    <TableRow key={rule.id} hover>
                      <TableCell><Typography variant="body2" fontWeight={500}>{rule.name}</Typography></TableCell>
                      <TableCell>
                        <Chip
                          label={rule.condition.replace(/_/g, ' ')}
                          size="small"
                          variant="outlined"
                          sx={{ height: 20, fontSize: 11, textTransform: 'capitalize' }}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption">
                          {rule.condition === 'latency_above' ? `${rule.threshold} ms` : rule.threshold}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <IconButton size="small" color="error" onClick={() => handleDeleteAlert(rule.id)}>
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Paper>
          )}
        </Box>
      )}

      {/* Fired Alerts Banner */}
      {firedAlerts.filter(a => !a.acknowledged).length > 0 && (
        <Alert severity="warning" sx={{ mt: 3 }}>
          <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
            {firedAlerts.filter(a => !a.acknowledged).length} active alert(s)
          </Typography>
          {firedAlerts.filter(a => !a.acknowledged).slice(0, 5).map((a) => (
            <Typography key={a.id} variant="caption" sx={{ display: 'block' }}>
              {a.rule_name}: {a.detail} ({fmtDate(a.timestamp)})
            </Typography>
          ))}
        </Alert>
      )}

      {/* Alert Rule Dialog */}
      <Dialog
        open={alertDialogOpen}
        onClose={() => setAlertDialogOpen(false)}
        fullWidth
        maxWidth="xs"
        PaperProps={{ component: 'form', onSubmit: handleCreateAlert, noValidate: true }}
      >
        <DialogTitle>Add Alert Rule</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <TextField
              size="small"
              label="Rule Name"
              required
              autoFocus
              value={alertForm.name}
              onChange={(e) => setAlertForm(f => ({ ...f, name: e.target.value }))}
              placeholder="High latency alert"
              fullWidth
            />
            <FormControl size="small" fullWidth>
              <InputLabel>Condition</InputLabel>
              <Select
                value={alertForm.condition}
                label="Condition"
                onChange={(e) => setAlertForm(f => ({ ...f, condition: e.target.value }))}
              >
                <MenuItem value="latency_above">Latency exceeds threshold (ms)</MenuItem>
                <MenuItem value="consecutive_failures">Consecutive failures exceed count</MenuItem>
                <MenuItem value="status_unhealthy">Server becomes unhealthy</MenuItem>
              </Select>
            </FormControl>
            {alertForm.condition !== 'status_unhealthy' && (
              <TextField
                size="small"
                label={alertForm.condition === 'latency_above' ? 'Latency Threshold (ms)' : 'Failure Count'}
                type="number"
                value={alertForm.threshold}
                onChange={(e) => setAlertForm(f => ({ ...f, threshold: Number(e.target.value) }))}
                fullWidth
              />
            )}
            <Alert severity="info" variant="outlined" sx={{ fontSize: '0.78rem' }}>
              Alert rules are evaluated after each health check.
              {alertForm.condition === 'latency_above' && ' The rule fires when response time exceeds the threshold.'}
              {alertForm.condition === 'consecutive_failures' && ' The rule fires when failures in a row reach the count.'}
              {alertForm.condition === 'status_unhealthy' && ' The rule fires whenever the server is not healthy.'}
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button size="small" onClick={() => setAlertDialogOpen(false)}>Cancel</Button>
          <Button size="small" variant="contained" type="submit" disabled={!alertForm.name.trim()}>
            Create Rule
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add / Edit Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => !submitting && closeDialog()}
        fullWidth
        maxWidth="xs"
        PaperProps={{ component: 'form', onSubmit: handleSubmit, noValidate: true }}
      >
        <DialogTitle>{editId ? 'Edit Server' : 'Add Server'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 0.5 }}>
            <TextField
              size="small"
              label="Name"
              required
              autoFocus
              value={form.name}
              onChange={(e) => setField('name', e.target.value)}
              error={!!errors.name}
              helperText={errors.name || 'A human-friendly label'}
              placeholder="My MCP Server"
              fullWidth
              inputProps={{ maxLength: 120 }}
            />
            <TextField
              size="small"
              label="URL"
              required
              value={form.url}
              onChange={(e) => setField('url', e.target.value)}
              error={!!errors.url}
              helperText={errors.url || 'Base URL or /sse endpoint — http:// or https:// only'}
              placeholder="http://localhost:3336"
              fullWidth
            />
            <TextField
              size="small"
              label="Check Interval"
              type="number"
              required
              value={form.check_interval_seconds}
              onChange={(e) => {
                const v = e.target.value;
                setField('check_interval_seconds', v === '' ? '' : Math.max(0, Number(v)));
              }}
              error={!!errors.check_interval_seconds}
              helperText={errors.check_interval_seconds || `How often to re-check (min ${MIN_INTERVAL}s, max 24 h)`}
              inputProps={{ min: MIN_INTERVAL, max: 86400 }}
              InputProps={{ endAdornment: <InputAdornment position="end">seconds</InputAdornment> }}
              fullWidth
            />
            <Alert severity="info" variant="outlined" sx={{ fontSize: '0.78rem' }}>
              Health checks verify your server is running, responding within acceptable time, and has all its
              tools registered. Only HTTP/HTTPS servers are supported — local stdio servers cannot be monitored
              remotely.
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button size="small" onClick={closeDialog} disabled={submitting}>Cancel</Button>
          <Button
            size="small"
            variant="contained"
            type="submit"
            disabled={submitting}
            startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : null}
          >
            {submitting ? 'Saving…' : (editId ? 'Save Changes' : 'Add Server')}
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Remove Server"
        message="Remove this server from monitoring? Its check history will be deleted."
        confirmLabel="Remove"
        confirmClass="btn-danger"
      />
    </Box>
  );
}

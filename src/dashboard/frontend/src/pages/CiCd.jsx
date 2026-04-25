import React from 'react';
import { useEffect, useState, useMemo } from 'react';
import useStore from '../store/useStore';
import {
  fetchCicdTemplates, generateCicdConfig,
  registerWebhook, fetchWebhooks, deleteWebhook,
  fetchCiRuns, fetchCiRunStats,
} from '../api';
import LogoLoader from '../components/LogoLoader';
import {
  Box,
  Typography,
  Paper,
  Button,
  TextField,
  FormControlLabel,
  Checkbox,
  Chip,
  Stack,
  Grid,
  CircularProgress,
  Divider,
  IconButton,
  Tooltip,
  Alert,
  InputAdornment,
  Tabs,
  Tab,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Card,
  CardContent,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import KeyOutlinedIcon from '@mui/icons-material/KeyOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import WebhookOutlinedIcon from '@mui/icons-material/WebhookOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import AddIcon from '@mui/icons-material/Add';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';

// ── constants ────────────────────────────────────────────────────────────────
const TARGET_OPTIONS = [
  {
    id: 'github_actions',
    label: 'GitHub Actions',
    filename: '.github/workflows/selqor-mcp-forge-scan.yml',
    description: 'Runs automatically on every push and pull request in GitHub',
  },
  {
    id: 'gitlab_ci',
    label: 'GitLab CI',
    filename: '.gitlab-ci.yml',
    description: 'Adds a security stage to your GitLab merge request pipeline',
  },
  {
    id: 'pre_commit',
    label: 'Pre-commit Framework',
    filename: '.pre-commit-config.yaml',
    description: 'Runs scans locally before each commit \u2014 catches issues before they reach CI',
  },
];

const OUTPUT_FORMAT_OPTIONS = [
  { id: 'json', label: 'JSON' },
  { id: 'markdown', label: 'Markdown' },
  { id: 'spdx', label: 'SPDX SBOM' },
  { id: 'pdf', label: 'PDF' },
];

const DEFAULT_FORM = {
  source_path: '.',
  branches_text: 'main',
  output_dir: 'scan-results',
  scan_threshold: 70,
  targets: ['github_actions'],
  output_formats: ['json'],
  fail_on_threshold: true,
  use_semgrep: false,
  use_llm: true,
};

// ── component ────────────────────────────────────────────────────────────────
export default function CiCd() {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const toast = useStore((s) => s.toast);

  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState({});
  const [form, setForm] = useState(DEFAULT_FORM);
  const [errors, setErrors] = useState({});

  // Webhook state
  const [webhooks, setWebhooks] = useState([]);
  const [webhookName, setWebhookName] = useState('');
  const [registering, setRegistering] = useState(false);
  const [newWebhook, setNewWebhook] = useState(null);

  // CI Runs state
  const [ciRuns, setCiRuns] = useState([]);
  const [ciStats, setCiStats] = useState(null);
  const [runsLoading, setRunsLoading] = useState(false);

  useEffect(() => {
    fetchCicdTemplates()
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  async function loadWebhooks() {
    try {
      const res = await fetchWebhooks();
      setWebhooks(res.projects || []);
    } catch { /* ignore */ }
  }

  async function loadCiRuns() {
    setRunsLoading(true);
    try {
      const [runsRes, statsRes] = await Promise.all([fetchCiRuns(), fetchCiRunStats()]);
      setCiRuns(runsRes.runs || []);
      setCiStats(statsRes);
    } catch { /* ignore */ }
    setRunsLoading(false);
  }

  useEffect(() => {
    if (activeTab === 1) loadWebhooks();
    if (activeTab === 2) loadCiRuns();
  }, [activeTab]);

  async function handleRegisterWebhook(e) {
    e?.preventDefault?.();
    if (!webhookName.trim()) return;
    setRegistering(true);
    try {
      const res = await registerWebhook({ project_name: webhookName.trim() });
      setNewWebhook(res);
      setWebhookName('');
      loadWebhooks();
      toast('Webhook registered');
    } catch (err) {
      toast(err.message || 'Failed to register webhook', 'error');
    }
    setRegistering(false);
  }

  async function handleDeleteWebhook(name) {
    try {
      await deleteWebhook(name);
      toast('Webhook removed');
      loadWebhooks();
      if (newWebhook?.project_name === name) setNewWebhook(null);
    } catch (err) {
      toast(err.message || 'Failed', 'error');
    }
  }

  const branches = useMemo(
    () =>
      (form.branches_text || '')
        .split(',')
        .map((b) => b.trim())
        .filter(Boolean),
    [form.branches_text],
  );

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    if (errors[field]) setErrors((e) => ({ ...e, [field]: '' }));
  }

  function toggleArray(field, value) {
    setForm((f) => {
      const current = f[field] || [];
      const next = current.includes(value)
        ? current.filter((x) => x !== value)
        : [...current, value];
      return { ...f, [field]: next };
    });
    if (errors[field]) setErrors((e) => ({ ...e, [field]: '' }));
  }

  function validate() {
    const next = {};
    if (!form.source_path.trim()) next.source_path = 'Source path is required';
    if (branches.length === 0) next.branches_text = 'Add at least one branch';
    if (!form.output_dir.trim()) next.output_dir = 'Output directory is required';
    const thr = Number(form.scan_threshold);
    if (!Number.isFinite(thr) || thr < 0 || thr > 100) {
      next.scan_threshold = 'Threshold must be between 0 and 100';
    }
    if (!form.targets || form.targets.length === 0) {
      next.targets = 'Select at least one CI target';
    }
    if (!form.output_formats || form.output_formats.length === 0) {
      next.output_formats = 'Select at least one output format';
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleGenerate() {
    if (!validate()) return;
    setGenerating(true);
    setResult(null);
    try {
      const payload = {
        source_path: form.source_path.trim(),
        branches,
        output_dir: form.output_dir.trim(),
        scan_threshold: Number(form.scan_threshold),
        targets: form.targets,
        output_formats: form.output_formats,
        fail_on_threshold: form.fail_on_threshold,
        use_semgrep: form.use_semgrep,
        use_llm: form.use_llm,
      };
      const res = await generateCicdConfig(payload);
      setResult(res);
      toast(`Generated ${form.targets.length} CI config${form.targets.length === 1 ? '' : 's'}`);
    } catch (err) {
      toast(err.message || 'Generation failed', 'error');
    } finally {
      setGenerating(false);
    }
  }

  function copyConfig(targetId, text) {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        toast('Copied to clipboard');
        setCopied((prev) => ({ ...prev, [targetId]: true }));
        setTimeout(() => setCopied((prev) => ({ ...prev, [targetId]: false })), 1500);
      })
      .catch(() => toast('Copy failed', 'error'));
  }

  function downloadConfig(filename, text) {
    try {
      const blob = new Blob([text], { type: 'text/yaml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      // Strip directory from the filename so the browser saves a flat file
      a.download = filename.split('/').pop() || filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast(`Downloaded ${a.download}`);
    } catch {
      toast('Download failed', 'error');
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
        <LogoLoader size={96} message="Loading…" />
      </Box>
    );
  }

  // Files object from new API; falls back to legacy top-level keys.
  const files = result?.files || (result
    ? Object.fromEntries(
        TARGET_OPTIONS
          .filter((t) => typeof result[t.id] === 'string')
          .map((t) => [t.id, { filename: t.filename, content: result[t.id] }])
      )
    : {});
  const generatedKeys = Object.keys(files);

  function fmtDate(iso) {
    if (!iso) return '\u2014';
    return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  return (
    <Box>
      {/* Page header */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="h6" fontWeight={700}>CI/CD Integration</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
          Automate security scans in your deployment pipeline
        </Typography>
      </Box>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)} textColor="primary" indicatorColor="primary">
          <Tab icon={<SettingsOutlinedIcon fontSize="small" />} iconPosition="start" label="Config Generator" sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }} />
          <Tab icon={<WebhookOutlinedIcon fontSize="small" />} iconPosition="start" label="Webhooks" sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }} />
          <Tab icon={<HistoryOutlinedIcon fontSize="small" />} iconPosition="start" label="CI Run History" sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }} />
          <Tab icon={<BadgeOutlinedIcon fontSize="small" />} iconPosition="start" label="Status Badge" sx={{ minHeight: 48, textTransform: 'none', fontSize: 14 }} />
        </Tabs>
      </Box>

      {/* ── Tab 0: Config Generator (existing) ── */}
      {activeTab === 0 && (
      <Grid container spacing={3}>
        {/* Form */}
        <Grid item xs={12} md={6}>
          <Stack spacing={2.25}>
            {/* Scan inputs */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
                Scan Inputs
              </Typography>
              <Stack spacing={2}>
                <TextField
                  size="small"
                  label="Source Path"
                  value={form.source_path}
                  onChange={(e) => update('source_path', e.target.value)}
                  error={!!errors.source_path}
                  helperText={errors.source_path || 'Local directory the scanner runs against (e.g. ".", "./mcp-server")'}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Branches"
                  value={form.branches_text}
                  onChange={(e) => update('branches_text', e.target.value)}
                  error={!!errors.branches_text}
                  helperText={errors.branches_text || 'Comma-separated branches the workflow triggers on (e.g. "main, develop")'}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Output Directory"
                  value={form.output_dir}
                  onChange={(e) => update('output_dir', e.target.value)}
                  error={!!errors.output_dir}
                  helperText={errors.output_dir || 'Where the scanner writes reports — passed to --out'}
                  fullWidth
                />
                <TextField
                  size="small"
                  label="Security Score Threshold"
                  type="number"
                  value={form.scan_threshold}
                  onChange={(e) => {
                    const v = e.target.value;
                    update('scan_threshold', v === '' ? '' : Math.max(0, Math.min(100, Number(v))));
                  }}
                  inputProps={{ min: 0, max: 100 }}
                  error={!!errors.scan_threshold}
                  helperText={errors.scan_threshold || 'Pipeline fails when overall score drops below this value (0–100)'}
                  fullWidth
                />
              </Stack>
            </Paper>

            {/* Targets */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                CI Targets
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Pick the providers you want files for. You'll get exactly those files in the response.
              </Typography>
              <Stack>
                {TARGET_OPTIONS.map((t) => (
                  <FormControlLabel
                    key={t.id}
                    sx={{ alignItems: 'flex-start', m: 0, py: 0.25 }}
                    control={
                      <Checkbox
                        size="small"
                        checked={form.targets.includes(t.id)}
                        onChange={() => toggleArray('targets', t.id)}
                        sx={{ mt: 0.25 }}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2" fontWeight={500}>
                          {t.label}
                          {' '}
                          <Box component="code" sx={{ fontSize: '0.7rem', color: 'text.secondary', fontFamily: 'monospace' }}>
                            {t.filename}
                          </Box>
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                          {t.description}
                        </Typography>
                      </Box>
                    }
                  />
                ))}
              </Stack>
              {errors.targets && (
                <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
                  {errors.targets}
                </Typography>
              )}
            </Paper>

            {/* Output formats + flags */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                Scanner Options
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Output formats are passed to <code>selqor-mcp-forge scan --format</code>.
              </Typography>
              <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mb: 1.5 }}>
                {OUTPUT_FORMAT_OPTIONS.map((fmt) => (
                  <FormControlLabel
                    key={fmt.id}
                    label={<Typography variant="body2">{fmt.label}</Typography>}
                    control={
                      <Checkbox
                        size="small"
                        checked={form.output_formats.includes(fmt.id)}
                        onChange={() => toggleArray('output_formats', fmt.id)}
                      />
                    }
                  />
                ))}
              </Stack>
              {errors.output_formats && (
                <Typography variant="caption" color="error" sx={{ display: 'block', mb: 1 }}>
                  {errors.output_formats}
                </Typography>
              )}
              <Divider sx={{ my: 1 }} />
              <Stack direction="row" flexWrap="wrap" gap={0.5}>
                <FormControlLabel
                  label={<Typography variant="body2">Fail on threshold</Typography>}
                  control={
                    <Checkbox
                      size="small"
                      checked={form.fail_on_threshold}
                      onChange={(e) => update('fail_on_threshold', e.target.checked)}
                    />
                  }
                />
                <Tooltip title="Static analysis to detect common vulnerability patterns in source code" arrow>
                  <FormControlLabel
                    label={<Typography variant="body2">Code Pattern Analysis</Typography>}
                    control={
                      <Checkbox
                        size="small"
                        checked={form.use_semgrep}
                        onChange={(e) => update('use_semgrep', e.target.checked)}
                      />
                    }
                  />
                </Tooltip>
                <FormControlLabel
                  label={<Typography variant="body2">LLM Analysis</Typography>}
                  control={
                    <Checkbox
                      size="small"
                      checked={form.use_llm}
                      onChange={(e) => update('use_llm', e.target.checked)}
                    />
                  }
                />
              </Stack>
              {form.use_llm && (
                <Alert
                  severity="info"
                  variant="outlined"
                  icon={<KeyOutlinedIcon fontSize="small" />}
                  sx={{ mt: 1.5, fontSize: '0.78rem' }}
                >
                  LLM analysis requires an <code>ANTHROPIC_API_KEY</code> secret in your CI provider.
                  The generated files reference it but do not create it for you.
                </Alert>
              )}
            </Paper>

            <Box>
              <Button
                variant="contained"
                onClick={handleGenerate}
                disabled={generating}
                startIcon={generating ? <CircularProgress size={14} color="inherit" /> : null}
              >
                {generating ? 'Generating…' : 'Generate Configs'}
              </Button>
            </Box>
          </Stack>
        </Grid>

        {/* Generated configs */}
        <Grid item xs={12} md={6}>
          {generatedKeys.length === 0 ? (
            <Paper
              variant="outlined"
              sx={{
                p: 4,
                textAlign: 'center',
                borderStyle: 'dashed',
                color: 'text.secondary',
              }}
            >
              <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1.5 }}>
                Your generated configs will appear here
              </Typography>
              <Stack
                direction="row"
                alignItems="center"
                justifyContent="center"
                flexWrap="wrap"
                gap={1}
                sx={{ mb: 2 }}
              >
                {['Configure', 'Generate', 'Copy to repo', 'Scans run automatically'].map((step, i) => (
                  <React.Fragment key={step}>
                    <Chip
                      label={step}
                      size="small"
                      variant="outlined"
                      sx={{ fontWeight: 500, fontSize: '0.72rem' }}
                    />
                    {i < 3 && <ArrowForwardIcon sx={{ fontSize: 14, color: 'text.disabled' }} />}
                  </React.Fragment>
                ))}
              </Stack>
              <Typography variant="caption">
                Pick at least one CI target on the left, then click <strong>Generate Configs</strong>.
                The files will be ready to copy straight into your repo.
              </Typography>
            </Paper>
          ) : (
            <Stack spacing={2}>
              {generatedKeys.map((key) => {
                const file = files[key];
                if (!file) return null;
                const meta = TARGET_OPTIONS.find((t) => t.id === key);
                const text = typeof file.content === 'string'
                  ? file.content
                  : JSON.stringify(file.content, null, 2);
                return (
                  <Paper variant="outlined" key={key}>
                    <Stack
                      direction="row"
                      alignItems="center"
                      justifyContent="space-between"
                      sx={{ px: 1.5, py: 0.75, borderBottom: 1, borderColor: 'divider', flexWrap: 'wrap', gap: 0.5 }}
                    >
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="caption" fontWeight={600}>
                          {meta?.label || key}
                        </Typography>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block', fontFamily: 'monospace', fontSize: '0.68rem' }}
                          noWrap
                        >
                          {file.filename}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={0.5}>
                        <Tooltip title={copied[key] ? 'Copied' : 'Copy to clipboard'}>
                          <IconButton size="small" onClick={() => copyConfig(key, text)}>
                            {copied[key]
                              ? <CheckIcon sx={{ fontSize: 16, color: 'success.main' }} />
                              : <ContentCopyIcon sx={{ fontSize: 16 }} />}
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Download file">
                          <IconButton size="small" onClick={() => downloadConfig(file.filename, text)}>
                            <DownloadOutlinedIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </Tooltip>
                      </Stack>
                    </Stack>
                    <Box
                      component="pre"
                      sx={{
                        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                        p: 1.5,
                        borderRadius: '0 0 4px 4px',
                        bgcolor: isDark ? '#0d0d0d' : '#f7f7f7',
                        border: 0,
                        overflowX: 'auto',
                        m: 0,
                        fontSize: 12,
                        lineHeight: 1.55,
                        whiteSpace: 'pre',
                        maxHeight: 420,
                      }}
                    >
                      {text}
                    </Box>
                  </Paper>
                );
              })}
            </Stack>
          )}
        </Grid>
      </Grid>
      )}

      {/* ── Tab 1: Webhooks ── */}
      {activeTab === 1 && (
        <Stack spacing={3}>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
              Webhook Endpoints
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Register your projects so CI pipelines can POST scan results back to the dashboard.
              After each scan, your pipeline sends the JSON report to the webhook URL with an HMAC signature.
            </Typography>

            <Stack direction="row" spacing={1} component="form" onSubmit={handleRegisterWebhook} sx={{ mb: 2 }}>
              <TextField
                size="small"
                label="Project Name"
                value={webhookName}
                onChange={(e) => setWebhookName(e.target.value)}
                placeholder="my-mcp-server"
                sx={{ flex: 1, maxWidth: 320 }}
              />
              <Button
                type="submit"
                variant="contained"
                size="small"
                disabled={registering || !webhookName.trim()}
                startIcon={registering ? <CircularProgress size={14} color="inherit" /> : <AddIcon />}
                sx={{ height: 40 }}
              >
                Register
              </Button>
            </Stack>

            {newWebhook && (
              <Alert severity="success" variant="outlined" sx={{ mb: 2 }} onClose={() => setNewWebhook(null)}>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
                  Webhook registered for "{newWebhook.project_name}"
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', fontFamily: 'monospace', mb: 0.5 }}>
                  Secret: <strong>{newWebhook.webhook_secret}</strong>
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', fontFamily: 'monospace', mb: 0.5 }}>
                  URL: <strong>POST {newWebhook.webhook_url}</strong>
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', fontFamily: 'monospace' }}>
                  Header: <strong>{newWebhook.header_name}: sha256=&lt;HMAC&gt;</strong>
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                  Add these as CI secrets. This secret won't be shown again in full.
                </Typography>
              </Alert>
            )}

            {webhooks.length > 0 ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Project</TableCell>
                    <TableCell>Secret (masked)</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {webhooks.map((w) => (
                    <TableRow key={w.project_name} hover>
                      <TableCell>
                        <Typography variant="body2" fontWeight={500}>{w.project_name}</Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{w.webhook_secret}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip title="Remove webhook">
                          <IconButton size="small" color="error" onClick={() => handleDeleteWebhook(w.project_name)}>
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Typography variant="caption" color="text.secondary">
                No webhooks registered yet. Register a project above to get started.
              </Typography>
            )}
          </Paper>

          <Alert severity="info" variant="outlined" sx={{ fontSize: '0.78rem' }}>
            <strong>How it works:</strong> After your CI pipeline runs <code>selqor-mcp-forge scan</code>,
            add a step that POSTs the scan results JSON to <code>/api/cicd/webhooks/ingest</code>.
            Include the HMAC signature header for verification. Results appear in the CI Run History tab.
          </Alert>
        </Stack>
      )}

      {/* ── Tab 2: CI Run History ── */}
      {activeTab === 2 && (
        <Stack spacing={3}>
          {/* Stats cards */}
          {ciStats && ciStats.total_runs > 0 && (
            <Grid container spacing={2}>
              {[
                { label: 'Total Runs', value: ciStats.total_runs, color: 'text.primary' },
                { label: 'Pass Rate', value: `${ciStats.pass_rate}%`, color: ciStats.pass_rate >= 80 ? 'success.main' : ciStats.pass_rate >= 50 ? 'warning.main' : 'error.main' },
                { label: 'Avg Score', value: `${ciStats.avg_score}/100`, color: ciStats.avg_score >= 70 ? 'success.main' : 'warning.main' },
                { label: 'Failed', value: ciStats.fail_count, color: ciStats.fail_count > 0 ? 'error.main' : 'success.main' },
              ].map((stat) => (
                <Grid item xs={6} sm={3} key={stat.label}>
                  <Card variant="outlined">
                    <CardContent sx={{ textAlign: 'center', py: 1.5, '&:last-child': { pb: 1.5 } }}>
                      <Typography variant="h5" fontWeight={700} sx={{ color: stat.color }}>{stat.value}</Typography>
                      <Typography variant="caption" color="text.secondary">{stat.label}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          )}

          <Paper variant="outlined">
            <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: 'divider', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <Typography variant="subtitle2" fontWeight={700}>
                Pipeline Scan Results
              </Typography>
              <Button size="small" onClick={loadCiRuns} disabled={runsLoading}>
                {runsLoading ? 'Loading...' : 'Refresh'}
              </Button>
            </Box>
            {ciRuns.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
                <HistoryOutlinedIcon sx={{ fontSize: 40, opacity: 0.3, mb: 1, display: 'block', mx: 'auto' }} />
                <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.5 }}>No CI runs recorded yet</Typography>
                <Typography variant="caption">
                  Set up a webhook in the Webhooks tab, then configure your CI pipeline to POST scan results.
                  Each run will appear here with its score, status, and branch.
                </Typography>
              </Box>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Project</TableCell>
                    <TableCell>Branch</TableCell>
                    <TableCell>Score</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Findings</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell>Time</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {ciRuns.map((run) => (
                    <TableRow key={run.id} hover>
                      <TableCell>
                        <Typography variant="body2" fontWeight={500}>{run.project_name}</Typography>
                      </TableCell>
                      <TableCell>
                        <Chip label={run.branch || 'unknown'} size="small" variant="outlined" sx={{ height: 20, fontSize: 11 }} />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontWeight={600} color={run.score >= 70 ? 'success.main' : run.score >= 50 ? 'warning.main' : 'error.main'}>
                          {run.score}/100
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={run.status}
                          size="small"
                          color={run.status === 'pass' ? 'success' : 'error'}
                          sx={{ height: 20, fontSize: 11, fontWeight: 600 }}
                        />
                      </TableCell>
                      <TableCell>{run.findings_count}</TableCell>
                      <TableCell>
                        <Typography variant="caption">{run.duration_seconds ? `${run.duration_seconds}s` : '\u2014'}</Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption">{fmtDate(run.timestamp)}</Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Paper>
        </Stack>
      )}

      {/* ── Tab 3: Status Badge ── */}
      {activeTab === 3 && (
        <Stack spacing={3} sx={{ maxWidth: 640 }}>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
              Embeddable Status Badge
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Add a live security score badge to your README or documentation.
              The badge updates automatically after each CI scan.
            </Typography>

            {webhooks.length === 0 ? (
              <Alert severity="info" variant="outlined">
                Register a project in the Webhooks tab first. Each project gets its own badge URL.
              </Alert>
            ) : (
              <Stack spacing={2}>
                {webhooks.map((w) => (
                  <Paper key={w.project_name} variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>{w.project_name}</Typography>
                    {/* Badge preview */}
                    <Box sx={{ mb: 1.5 }}>
                      <img
                        src={`/api/cicd/badge/${encodeURIComponent(w.project_name)}`}
                        alt={`Security badge for ${w.project_name}`}
                        style={{ height: 20 }}
                      />
                    </Box>
                    {/* Markdown embed */}
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                      Markdown:
                    </Typography>
                    <Box
                      component="code"
                      sx={{
                        display: 'block',
                        p: 1,
                        borderRadius: 1,
                        bgcolor: isDark ? '#111' : '#f5f5f5',
                        fontFamily: 'monospace',
                        fontSize: 11,
                        wordBreak: 'break-all',
                        mb: 1,
                      }}
                    >
                      {`![Security](${window.location.origin}/api/cicd/badge/${encodeURIComponent(w.project_name)})`}
                    </Box>
                    {/* HTML embed */}
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                      HTML:
                    </Typography>
                    <Box
                      component="code"
                      sx={{
                        display: 'block',
                        p: 1,
                        borderRadius: 1,
                        bgcolor: isDark ? '#111' : '#f5f5f5',
                        fontFamily: 'monospace',
                        fontSize: 11,
                        wordBreak: 'break-all',
                      }}
                    >
                      {`<img src="${window.location.origin}/api/cicd/badge/${encodeURIComponent(w.project_name)}" alt="Security Score" />`}
                    </Box>
                  </Paper>
                ))}
              </Stack>
            )}
          </Paper>
        </Stack>
      )}
    </Box>
  );
}

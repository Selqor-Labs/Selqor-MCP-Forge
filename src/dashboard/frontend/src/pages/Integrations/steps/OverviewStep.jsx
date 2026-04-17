import React from 'react';
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import LinearProgress from '@mui/material/LinearProgress';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import CircularProgress from '@mui/material/CircularProgress';
import LogoLoader from '../../../components/LogoLoader';
import Alert from '@mui/material/Alert';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardActionArea from '@mui/material/CardActionArea';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Divider from '@mui/material/Divider';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import TextField from '@mui/material/TextField';
import Radio from '@mui/material/Radio';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import { useTheme } from '@mui/material/styles';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DownloadIcon from '@mui/icons-material/Download';
import CloseIcon from '@mui/icons-material/Close';
import CheckIcon from '@mui/icons-material/Check';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined';
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined';
import BuildOutlinedIcon from '@mui/icons-material/BuildOutlined';
import HandymanOutlinedIcon from '@mui/icons-material/HandymanOutlined';
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import useStore from '../../../store/useStore';
import ConfirmDialog from '../../../components/ConfirmDialog';
import RunProgressStepper from '../../../components/RunProgressStepper';
import {
  startRun, fetchRunJobStatus, fetchActiveRunJob, deleteRun,
  fetchArtifacts, fetchArtifactContent, fetchRunReport,
  fetchLlmConfigs,
} from '../../../api';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function fmtRunId(id) {
  if (!id) return '—';
  try { return fmtDate(new Date(parseInt(id)).toISOString()); } catch { return id; }
}

const ARTIFACT_LABELS = {
  'quality-report.json': 'Quality Report',
  'analysis-plan.json': 'Analysis Plan',
  'tool-plan.json': 'Tool Definitions',
  'tool-definitions.json': 'Tool Definitions',
  'api-surface.json': 'API Surface',
  'run-meta.json': 'Run Metadata',
  'uasf.json': 'UASF',
  'forge.report.json': 'Forge Report',
  'run.json': 'Run Data',
};

const ARTIFACT_DESCRIPTIONS = {
  'quality-report.json': 'AI-generated quality analysis with scores and recommendations',
  'analysis-plan.json': 'Step-by-step plan used during the analysis run',
  'tool-plan.json': 'Tool groupings and definitions generated from the spec',
  'tool-definitions.json': 'MCP-compatible tool definitions ready for deployment',
  'api-surface.json': 'Full API endpoint surface extracted from the spec',
  'run-meta.json': 'Metadata and timing information for this run',
  'uasf.json': 'Unified API Surface Format — structured endpoint catalog',
  'forge.report.json': 'Complete Forge analysis report',
  'run.json': 'Raw run data and results',
};

function getStatusColor(status) {
  if (status === 'completed' || status === 'ok') return 'success';
  if (status === 'failed') return 'error';
  return 'default';
}

// ── Run error interpretation ───────────────────────────────────────────────────
// Maps known backend error messages to user-friendly guidance.
function getRunErrorHelp(errorMsg) {
  if (!errorMsg) return null;
  const msg = errorMsg.toLowerCase();

  if (msg.includes('yaml document is not a mapping') || msg.includes('yaml document')) {
    return {
      title: 'Invalid spec format',
      body: 'Your spec URL may be pointing to an HTML page (e.g. the Swagger UI browser) instead of the raw YAML or JSON spec.',
      suggestions: ['/v3/api-docs', '/v2/api-docs', '/openapi.json', '/swagger.json', '/api-docs'],
    };
  }
  if (msg.includes('not valid json') || msg.includes('json decode') || msg.includes('jsondecodeerror')) {
    return {
      title: 'Spec is not valid JSON',
      body: 'The spec URL returned content that could not be parsed as JSON. Check that it points to a raw OpenAPI spec file.',
      suggestions: ['/openapi.json', '/swagger.json', '/v3/api-docs'],
    };
  }
  if (msg.includes('html') || msg.includes('<!doctype') || msg.includes('<html')) {
    return {
      title: 'HTML page returned instead of spec',
      body: 'The spec URL returned an HTML page. Use the raw JSON or YAML spec endpoint.',
      suggestions: ['/v3/api-docs', '/openapi.json', '/swagger.json'],
    };
  }
  if (msg.includes('connection refused') || msg.includes('could not connect') || msg.includes('timeout')) {
    return {
      title: 'Could not reach the spec URL',
      body: 'The server at the spec URL was unreachable. Check that the URL is accessible from this environment.',
      suggestions: null,
    };
  }
  return null;
}

// Detail label-value row component
function DetailCell({ label, value, mono }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, fontSize: '0.6rem', display: 'block' }}>
        {label}
      </Typography>
      <Typography
        variant="body2"
        fontWeight={500}
        sx={mono
          ? { fontFamily: 'monospace', fontSize: '0.8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }
          : {}
        }
        title={mono ? (value ?? '') : undefined}
      >
        {value ?? '—'}
      </Typography>
    </Box>
  );
}

export default function OverviewStep({ integration, onReload }) {
  const runs = useStore((s) => s.runs);
  const toast = useStore((s) => s.toast);
  const muiTheme = useTheme();
  const isDark = muiTheme.palette.mode === 'dark';
  const navigate = useNavigate();
  const hasCompletedRun = runs.some((r) => r.status === 'ok' || r.status === 'completed');

  // Run analysis modal
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [analysisMode, setAnalysisMode] = useState('llm');
  const [agentIntent, setAgentIntent] = useState('');
  const [llmConfigs, setLlmConfigs] = useState([]);
  const [selectedLlmConfigId, setSelectedLlmConfigId] = useState('');
  const [llmConfigsLoading, setLlmConfigsLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [runError, setRunError] = useState(null);   // { message, help? }
  const [deleteTarget, setDeleteTarget] = useState(null);

  // Run detail modal
  const [detailRun, setDetailRun] = useState(null);
  const [detailTab, setDetailTab] = useState(0);

  // Artifacts
  const [artifacts, setArtifacts] = useState([]);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);

  // Artifact content modal
  const [artifactModal, setArtifactModal] = useState(null);
  const [loadingArtifactContent, setLoadingArtifactContent] = useState(false);
  const [artifactCopied, setArtifactCopied] = useState(false);

  const pollRef = useRef(null);

  // Load LLM configs whenever the run modal opens so the user can pick which
  // model to use (and we can warn/redirect when none are configured).
  useEffect(() => {
    if (!runModalOpen) return;
    let cancelled = false;
    setLlmConfigsLoading(true);
    fetchLlmConfigs()
      .then((res) => {
        if (cancelled) return;
        const configs = (res?.configs || []).filter((c) => c.enabled !== false && (c.model || '').trim());
        setLlmConfigs(configs);
        const def = configs.find((c) => c.is_default) || configs[0];
        setSelectedLlmConfigId((prev) => {
          if (prev && configs.some((c) => c.id === prev)) return prev;
          return def?.id || '';
        });
      })
      .catch(() => { if (!cancelled) setLlmConfigs([]); })
      .finally(() => { if (!cancelled) setLlmConfigsLoading(false); });
    return () => { cancelled = true; };
  }, [runModalOpen]);

  const selectedLlmConfig = llmConfigs.find((c) => c.id === selectedLlmConfigId) || null;
  const hasLlmConfigs = llmConfigs.length > 0;

  // Load artifacts when detail modal opens
  useEffect(() => {
    if (!detailRun) { setArtifacts([]); return; }
    setLoadingArtifacts(true);
    fetchArtifacts(integration.id, detailRun.run_id)
      .then((res) => setArtifacts(res.artifacts || []))
      .catch(() => setArtifacts([]))
      .finally(() => setLoadingArtifacts(false));
  }, [integration.id, detailRun]);

  function openRunDetail(run) {
    setDetailRun(run);
    setDetailTab(0);
  }

  async function openArtifact(name) {
    setArtifactModal({ name, content: null });
    setLoadingArtifactContent(true);
    try {
      const content = await fetchArtifactContent(integration.id, detailRun.run_id, name);
      setArtifactModal({ name, content: typeof content === 'string' ? content : JSON.stringify(content, null, 2) });
    } catch (err) {
      setArtifactModal({ name, content: `Error: ${err.message}` });
    } finally {
      setLoadingArtifactContent(false);
    }
  }

  function copyArtifactContent() {
    if (!artifactModal?.content) return;
    navigator.clipboard.writeText(artifactModal.content).then(() => {
      setArtifactCopied(true);
      toast('Copied to clipboard');
      setTimeout(() => setArtifactCopied(false), 1500);
    });
  }

  async function handleStartRun() {
    setRunModalOpen(false);
    setRunning(true);
    setRunError(null);
    setProgress({ message: 'Starting analysis…', steps: [], currentStep: null });
    const payload = { mode: analysisMode };
    if (agentIntent.trim()) payload.agent_prompt = agentIntent.trim();
    if (analysisMode === 'llm' && selectedLlmConfigId) {
      payload.llm_config_id = selectedLlmConfigId;
    }
    try {
      const res = await startRun(integration.id, payload);
      const jobId = res.job?.job_id;
      if (!jobId) throw new Error('No job ID returned');
      startPolling(jobId);
    } catch (err) {
      setRunning(false);
      setProgress(null);
      const errMsg = err?.message || 'Failed to start run';
      toast(errMsg, 'error');
      setRunError({ message: errMsg, help: getRunErrorHelp(errMsg) });
    }
  }

  // Start polling a known job id. Extracted so both handleStartRun and the
  // on-mount resume logic can share the same implementation.
  function startPolling(jobId) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetchRunJobStatus(integration.id, jobId);
        const job = res?.job ?? res;
        const jobStatus = job?.status;
        const jobProgress = job?.progress || {};
        const progressMsg = jobProgress.message || job?.message || jobStatus;
        setProgress({
          message: progressMsg,
          steps: Array.isArray(jobProgress.steps) ? jobProgress.steps : [],
          currentStep: jobProgress.current_step || null,
        });
        if (jobStatus === 'completed' || jobStatus === 'failed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setRunning(false);
          setProgress(null);
          if (jobStatus === 'completed') {
            toast('Analysis completed');
          } else {
            const errMsg = job?.error || 'Analysis failed';
            toast(errMsg, 'error');
            setRunError({ message: errMsg, help: getRunErrorHelp(errMsg) });
          }
          onReload();
        }
      } catch {
        clearInterval(pollRef.current);
        pollRef.current = null;
        setRunning(false);
        setProgress(null);
        toast('Lost connection to job', 'error');
      }
    }, 2000);
  }

  // On mount: check if there's an active run job for this integration
  // so the progress stepper survives page reloads.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchActiveRunJob(integration.id);
        const job = res?.job;
        if (!job || cancelled) return;
        const jobStatus = job.status;
        if (jobStatus === 'queued' || jobStatus === 'running') {
          const jobProgress = job.progress || {};
          setRunning(true);
          setProgress({
            message: jobProgress.message || jobStatus,
            steps: Array.isArray(jobProgress.steps) ? jobProgress.steps : [],
            currentStep: jobProgress.current_step || null,
          });
          startPolling(job.job_id);
        }
      } catch {
        // silent — no active job or backend unreachable
      }
    })();
    return () => { cancelled = true; };
  }, [integration.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []);

  async function handleDeleteRun() {
    if (!deleteTarget) return;
    try {
      await deleteRun(integration.id, deleteTarget);
      toast('Run deleted');
      if (detailRun?.run_id === deleteTarget) setDetailRun(null);
      onReload();
    } catch (err) {
      toast(err.message, 'error');
    }
    setDeleteTarget(null);
  }

  return (
    <Box>
      {/* Integration Details */}
      <Paper variant="outlined" sx={{ mb: 2 }}>
        <Box sx={{ px: 2.5, py: 1.75, borderBottom: 1, borderColor: 'divider' }}>
          <Typography variant="subtitle2" fontWeight={600}>Integration Details</Typography>
        </Box>
        <Box sx={{ px: 2.5, py: 2 }}>
          <Grid container spacing={3}>
            <Grid item xs={12} sm={4}>
              <DetailCell label="Name" value={integration.name} />
            </Grid>
            <Grid item xs={12} sm={4}>
              <DetailCell label="Spec" value={integration.spec || '—'} mono />
            </Grid>
            <Grid item xs={12} sm={4}>
              <DetailCell label="Created" value={fmtDate(integration.created_at)} />
            </Grid>
            {integration.agent_prompt && (
              <Grid item xs={12}>
                <DetailCell label="Agent Prompt" value={integration.agent_prompt} />
              </Grid>
            )}
          </Grid>
        </Box>
      </Paper>

      {/* Analysis Runs */}
      <Paper variant="outlined">
        <Box sx={{ px: 2.5, py: 1.75, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: runs.length > 0 || progress || runError ? 1 : 0, borderColor: 'divider' }}>
          <Typography variant="subtitle2" fontWeight={600}>Analysis Runs</Typography>
          <Button
            variant="contained"
            size="small"
            startIcon={running ? <CircularProgress size={12} color="inherit" /> : <PlayCircleOutlineIcon />}
            disabled={running}
            onClick={() => setRunModalOpen(true)}
            sx={{ borderRadius: 5 }}
          >
            {running ? 'Running…' : 'Run Analysis'}
          </Button>
        </Box>

        {/* Live "deep research" progress stepper */}
        {progress && (
          <Box sx={{ px: 2.5, py: 1.75, borderBottom: 1, borderColor: 'divider' }}>
            <RunProgressStepper
              steps={progress.steps}
              currentStep={progress.currentStep}
              message={progress.message}
            />
          </Box>
        )}

        {/* Run error with contextual help */}
        {runError && !running && (
          <Box sx={{ px: 2.5, py: 1.5, borderBottom: runs.length > 0 ? 1 : 0, borderColor: 'divider' }}>
            <Alert
              severity="error"
              onClose={() => setRunError(null)}
              sx={{ mb: runError.help ? 1 : 0 }}
            >
              {runError.message}
            </Alert>
            {runError.help && (
              <Alert severity="info" icon={false} sx={{ mt: 0.5 }}>
                <Typography variant="caption" fontWeight={600} display="block" sx={{ mb: 0.5 }}>
                  {runError.help.title}
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: runError.help.suggestions ? 0.75 : 0 }}>
                  {runError.help.body}
                </Typography>
                {runError.help.suggestions && (
                  <Box sx={{ mt: 0.5 }}>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                      Try one of these endpoints instead of <code style={{ fontFamily: 'monospace' }}>{integration.spec}</code>:
                    </Typography>
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                      {runError.help.suggestions.map((path) => {
                        let base = '';
                        try { base = new URL(integration.spec).origin; } catch { base = ''; }
                        const suggestion = base ? `${base}${path}` : path;
                        return (
                          <Chip
                            key={path}
                            size="small"
                            label={suggestion}
                            variant="outlined"
                            sx={{ fontFamily: 'monospace', fontSize: '0.65rem', cursor: 'default' }}
                          />
                        );
                      })}
                    </Stack>
                  </Box>
                )}
              </Alert>
            )}
          </Box>
        )}

        {/* Empty state */}
        {runs.length === 0 && !progress && !runError && (
          <Box sx={{ px: 2.5, py: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">No analysis runs yet.</Typography>
            <Typography variant="caption" color="text.secondary">Click "Run Analysis" to analyze your API spec.</Typography>
          </Box>
        )}

        {/* Run rows */}
        {runs.map((run, i) => (
          <Box
            key={run.run_id}
            sx={{
              px: 2.5, py: 1.5,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1,
              borderBottom: i < runs.length - 1 ? 1 : 0, borderColor: 'divider',
              '&:hover': { bgcolor: 'action.hover' },
              transition: 'background-color 0.15s',
            }}
          >
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="body2" fontWeight={500}>{fmtRunId(run.run_id)}</Typography>
              <Typography variant="caption" color="text.secondary">
                {[run.analysis_source, run.tool_count != null && `${run.tool_count} tools`, run.endpoint_count != null && `${run.endpoint_count} endpoints`, run.score != null && `Score: ${run.score}`].filter(Boolean).join(' · ')}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexShrink: 0 }}>
              <Chip label={run.status === 'ok' || run.status === 'completed' ? 'ok' : run.status || 'unknown'} color={getStatusColor(run.status)} size="small" sx={{ fontWeight: 600 }} />
              <Tooltip title="View details">
                <IconButton size="small" onClick={() => openRunDetail(run)}>
                  <VisibilityOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Delete run">
                <IconButton size="small" color="error" onClick={() => setDeleteTarget(run.run_id)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        ))}
      </Paper>

      {/* Sticky footer CTA — always visible at the bottom of the scroll container
          once the user has at least one successful run. Content above scrolls
          underneath it. */}
      {hasCompletedRun && (
        <Box
          sx={{
            position: 'sticky',
            // Cancel out the parent scroll container's padding so the footer
            // hugs the viewport edges. Parent is { p: { xs: 2, sm: 3 } } in
            // IntegrationWorkflow.jsx.
            bottom: { xs: -16, sm: -24 },
            mx: { xs: -2, sm: -3 },
            mt: 2,
            px: { xs: 2, sm: 3 },
            py: 1.5,
            display: 'flex',
            justifyContent: 'flex-end',
            bgcolor: 'background.paper',
            borderTop: 1,
            borderColor: 'divider',
            zIndex: 2,
          }}
        >
          <Tooltip title="Analysis doesn't need credentials, but the next step does — configure auth so you can test the connection and deploy later.">
            <Button
              variant="contained"
              color="primary"
              size="small"
              endIcon={<ArrowForwardIcon />}
              onClick={() => navigate(`/integrations/${integration.id}/auth`)}
            >
              Next: Configure Auth
            </Button>
          </Tooltip>
        </Box>
      )}

      {/* ── Run Analysis Modal ── */}
      <Dialog open={runModalOpen} onClose={() => setRunModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle component="div" sx={{ px: 2.5, py: 2 }}>
          <Typography variant="h6" component="div" fontWeight={600}>Choose Analysis Mode</Typography>
          <Typography variant="caption" component="div" color="text.secondary">Select how this integration should be analyzed.</Typography>
        </DialogTitle>
        <Divider />
        <DialogContent sx={{ px: 2.5, py: 2 }}>
          {/* Mode cards */}
          <Grid container spacing={1.5} sx={{ mb: 2.5 }}>
            {/* LLM Analysis */}
            <Grid item xs={12} sm={6}>
              <Card
                variant="outlined"
                onClick={() => setAnalysisMode('llm')}
                sx={{
                  cursor: 'pointer', height: '100%', position: 'relative',
                  borderColor: analysisMode === 'llm' ? 'primary.main' : 'divider',
                  borderWidth: analysisMode === 'llm' ? 2 : 1,
                  transition: 'border-color 0.15s',
                  '&:hover': { borderColor: 'primary.main' },
                }}
              >
                <CardContent sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                    <Box sx={{ width: 36, height: 36, borderRadius: 1.5, bgcolor: '#3b82f620', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <AutoAwesomeOutlinedIcon sx={{ fontSize: 18, color: '#3b82f6' }} />
                    </Box>
                    <Radio size="small" checked={analysisMode === 'llm'} onChange={() => setAnalysisMode('llm')} sx={{ p: 0 }} />
                  </Box>
                  <Typography variant="body2" fontWeight={700} sx={{ mb: 0.5 }}>LLM Analysis</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    Uses Claude to intelligently group API endpoints into semantic MCP tools. Fast and automatic.
                  </Typography>
                  <Chip label="Recommended" size="small" color="success" sx={{ fontSize: '0.6rem', height: 18 }} />
                </CardContent>
              </Card>
            </Grid>

            {/* Manual Analysis */}
            <Grid item xs={12} sm={6}>
              <Card
                variant="outlined"
                onClick={() => setAnalysisMode('manual')}
                sx={{
                  cursor: 'pointer', height: '100%',
                  borderColor: analysisMode === 'manual' ? 'primary.main' : 'divider',
                  borderWidth: analysisMode === 'manual' ? 2 : 1,
                  transition: 'border-color 0.15s',
                  '&:hover': { borderColor: 'primary.main' },
                }}
              >
                <CardContent sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                    <Box sx={{ width: 36, height: 36, borderRadius: 1.5, bgcolor: '#6366f120', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <HandymanOutlinedIcon sx={{ fontSize: 18, color: '#6366f1' }} />
                    </Box>
                    <Radio size="small" checked={analysisMode === 'manual'} onChange={() => setAnalysisMode('manual')} sx={{ p: 0 }} />
                  </Box>
                  <Typography variant="body2" fontWeight={700} sx={{ mb: 0.5 }}>Manual Analysis</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                    Skip LLM and use tools you've manually defined in Step 2. Auto-generates if needed.
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* LLM picker (LLM only) */}
          {analysisMode === 'llm' && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                LLM Model
              </Typography>
              {llmConfigsLoading ? (
                <Typography variant="caption" color="text.secondary">Loading configured LLMs…</Typography>
              ) : !hasLlmConfigs ? (
                <Alert severity="warning" sx={{ py: 0.5 }}>
                  <Typography variant="caption" fontWeight={600} display="block">No LLM configured</Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
                    Configure one under Settings → LLM Config, or run a heuristic (manual) analysis instead.
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => setAnalysisMode('manual')}
                    sx={{ borderRadius: 5 }}
                  >
                    Use Manual Analysis
                  </Button>
                </Alert>
              ) : (
                <TextField
                  select
                  fullWidth
                  size="small"
                  value={selectedLlmConfigId}
                  onChange={(e) => setSelectedLlmConfigId(e.target.value)}
                  helperText={
                    selectedLlmConfig
                      ? `Will use ${selectedLlmConfig.provider} · ${selectedLlmConfig.model}${selectedLlmConfig.is_default ? ' (default)' : ''}`
                      : 'Select a configured LLM'
                  }
                >
                  {llmConfigs.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name || c.id} — {c.provider} · {c.model}
                      {c.is_default ? ' · default' : ''}
                    </MenuItem>
                  ))}
                </TextField>
              )}
            </Box>
          )}

          {/* Agent Intent Override — applies to both LLM and manual runs */}
          {(analysisMode === 'manual' || (analysisMode === 'llm' && hasLlmConfigs)) && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                Agent Intent Override <Typography component="span" variant="caption" color="text.disabled">(optional)</Typography>
              </Typography>
              <TextField
                fullWidth multiline rows={3} size="small"
                placeholder="Override agent intent for this run only…"
                value={agentIntent}
                onChange={(e) => setAgentIntent(e.target.value)}
                helperText={
                  analysisMode === 'llm'
                    ? 'Customize the LLM analysis instructions for this specific run'
                    : 'Used to bias heuristic grouping toward the agent\'s intent'
                }
              />
            </Box>
          )}

          {/* Auto-generate tools info */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
            <InfoOutlinedIcon sx={{ fontSize: 15, color: 'text.secondary', flexShrink: 0 }} />
            <Typography variant="caption" color="text.secondary">
              <strong>Auto-generating tools</strong> — Will create tool groupings this run
            </Typography>
          </Box>
        </DialogContent>
        <Divider />
        <DialogActions sx={{ px: 2.5, py: 1.5, gap: 1 }}>
          <Button variant="outlined" size="small" onClick={() => setRunModalOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            size="small"
            startIcon={<PlayCircleOutlineIcon />}
            onClick={handleStartRun}
            disabled={analysisMode === 'llm' && !hasLlmConfigs}
            sx={{ borderRadius: 5 }}
          >
            Start Analysis
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Run Detail Modal ── */}
      <Dialog open={!!detailRun} onClose={() => setDetailRun(null)} maxWidth="sm" fullWidth>
        <DialogTitle component="div" sx={{ px: 2.5, py: 1.75, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Box>
            <Typography variant="subtitle1" fontWeight={600}>
              Run Details — {fmtRunId(detailRun?.run_id)}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
              {detailRun && <Chip label={detailRun.status === 'ok' || detailRun.status === 'completed' ? 'ok' : detailRun.status || 'unknown'} color={getStatusColor(detailRun.status)} size="small" fontWeight={600} />}
              {detailRun && (
                <Typography variant="caption" color="text.secondary">
                  {[detailRun.score != null && `Score: ${detailRun.score}`, detailRun.tool_count != null && `${detailRun.tool_count} tools`, detailRun.endpoint_count != null && `${detailRun.endpoint_count} endpoints`].filter(Boolean).join(' · ')}
                </Typography>
              )}
            </Box>
          </Box>
          <IconButton size="small" onClick={() => setDetailRun(null)} sx={{ mt: -0.5 }}><CloseIcon fontSize="small" /></IconButton>
        </DialogTitle>

        <Tabs value={detailTab} onChange={(_, v) => setDetailTab(v)} sx={{ px: 2.5, borderBottom: 1, borderColor: 'divider' }}>
          <Tab icon={<AssessmentOutlinedIcon fontSize="small" />} iconPosition="start" label="Summary" sx={{ textTransform: 'none', minHeight: 42, fontSize: '0.82rem' }} />
          <Tab
            icon={<ArticleOutlinedIcon fontSize="small" />} iconPosition="start"
            label={loadingArtifacts ? 'Artifacts' : `Artifacts (${artifacts.length})`}
            sx={{ textTransform: 'none', minHeight: 42, fontSize: '0.82rem' }}
          />
        </Tabs>

        <DialogContent sx={{ px: 2.5, py: 2, minHeight: 200 }}>
          {/* Summary tab */}
          {detailTab === 0 && detailRun && (
            <Grid container spacing={2}>
              <Grid item xs={6} sm={3}><DetailCell label="Quality Score" value={detailRun.score ?? '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Tools Generated" value={detailRun.tool_count ?? '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Endpoints Covered" value={detailRun.endpoint_count ?? '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Coverage" value={detailRun.coverage != null ? `${Math.round(detailRun.coverage * 100)}%` : '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Compression" value={detailRun.compression_ratio != null ? `${detailRun.compression_ratio.toFixed(2)}x` : '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Analysis Source" value={detailRun.analysis_source || '—'} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Model" value={detailRun.model ? detailRun.model : `N/A (${detailRun.analysis_source || 'heuristic'})`} /></Grid>
              <Grid item xs={6} sm={3}><DetailCell label="Created" value={fmtRunId(detailRun.run_id)} /></Grid>

              {detailRun.warnings?.length > 0 && (
                <Grid item xs={12}>
                  <Stack spacing={0.75}>
                    {detailRun.warnings.map((w, i) => <Alert severity="warning" key={i}>{w}</Alert>)}
                  </Stack>
                </Grid>
              )}
            </Grid>
          )}

          {/* Artifacts tab */}
          {detailTab === 1 && (
            loadingArtifacts ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
            ) : artifacts.length === 0 ? (
              <Alert severity="info">No artifacts for this run.</Alert>
            ) : (
              <Grid container spacing={1.25}>
                {artifacts.map((name) => (
                  <Grid item xs={12} sm={6} key={name}>
                    <Card variant="outlined" sx={{ '&:hover': { borderColor: 'primary.main' }, transition: 'border-color 0.15s' }}>
                      <CardActionArea onClick={() => openArtifact(name)} sx={{ p: 1.5, display: 'flex', alignItems: 'flex-start', gap: 1.25 }}>
                        <ArticleOutlinedIcon sx={{ fontSize: 22, color: 'primary.main', flexShrink: 0, mt: 0.2 }} />
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600} noWrap>{ARTIFACT_LABELS[name] || name}</Typography>
                          <Typography variant="caption" color="text.disabled" sx={{ fontFamily: 'monospace', fontSize: '0.62rem' }}>{name}</Typography>
                        </Box>
                      </CardActionArea>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            )
          )}
        </DialogContent>
      </Dialog>

      {/* ── Artifact Content Modal ── */}
      <Dialog open={!!artifactModal} onClose={() => setArtifactModal(null)} maxWidth="lg" fullWidth PaperProps={{ sx: { height: '85vh', display: 'flex', flexDirection: 'column' } }}>
        <DialogTitle component="div" sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 1.5, px: 2.5, flexShrink: 0 }}>
          <Box>
            <Typography variant="subtitle1" fontWeight={600}>{artifactModal ? (ARTIFACT_LABELS[artifactModal.name] || artifactModal.name) : ''}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>{artifactModal?.name}</Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Tooltip title={artifactCopied ? 'Copied!' : 'Copy'}>
              <IconButton size="small" onClick={copyArtifactContent} disabled={!artifactModal?.content}>
                {artifactCopied ? <CheckIcon fontSize="small" sx={{ color: 'success.main' }} /> : <ContentCopyIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            {detailRun && (
              <Tooltip title="Download">
                <IconButton size="small" component="a" href={fetchRunReport(integration.id, detailRun.run_id, 'json')} download>
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <IconButton size="small" onClick={() => setArtifactModal(null)}><CloseIcon fontSize="small" /></IconButton>
          </Box>
        </DialogTitle>
        <Divider />
        <DialogContent sx={{ flex: 1, overflow: 'hidden', p: 0 }}>
          {loadingArtifactContent ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
              <LogoLoader size={72} message="Loading artifact…" />
            </Box>
          ) : (
            <Box component="pre" sx={{
              m: 0, p: 2.5, height: '100%', overflowY: 'auto', overflowX: 'auto',
              fontSize: '0.73rem', fontFamily: '"JetBrains Mono", "Fira Code", monospace', lineHeight: 1.65,
              bgcolor: isDark ? '#0a0a0a' : '#f8f8f8',
              color: isDark ? '#e5e5e5' : '#1a1a1a',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', boxSizing: 'border-box',
            }}>
              {artifactModal?.content || ''}
            </Box>
          )}
        </DialogContent>
      </Dialog>

      {/* ── Delete Confirm ── */}
      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteRun}
        title="Delete Run"
        message="Delete this analysis run and all its artifacts? This cannot be undone."
        confirmLabel="Delete"
        confirmClass="btn-danger"
      />
    </Box>
  );
}

import React from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import LinearProgress from '@mui/material/LinearProgress';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import CloseIcon from '@mui/icons-material/Close';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import LinkOutlinedIcon from '@mui/icons-material/LinkOutlined';
import ExtensionOutlinedIcon from '@mui/icons-material/ExtensionOutlined';
import Divider from '@mui/material/Divider';
import HistoryIcon from '@mui/icons-material/History';
import useStore from '../../store/useStore';
import ConfirmDialog from '../../components/ConfirmDialog';
import LogoLoader from '../../components/LogoLoader';
import SpecInputTabs from './components/SpecInputTabs';
import { createIntegration, deleteIntegration, testConnection } from '../../api';
import { loadString, STORAGE_KEYS } from '../../utils/persist';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── Spec URL content validation ────────────────────────────────────────────────
// Attempts to fetch the URL and determine if it returns a valid JSON/YAML spec.
// Returns { valid, error, suggestions } — CORS failures are treated as "pass" since
// the backend will do the authoritative validation on creation.
async function validateSpecUrl(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch { return { valid: false, error: 'Invalid URL format.' }; }

  // Derive candidate spec endpoints from the base origin for suggestions
  const base = url.origin;
  const KNOWN_SPEC_PATHS = ['/v3/api-docs', '/v2/api-docs', '/openapi.json', '/swagger.json', '/api-docs'];
  const suggestions = KNOWN_SPEC_PATHS
    .map((p) => `${base}${p}`)
    .filter((s) => s.toLowerCase() !== rawUrl.toLowerCase());

  try {
    const resp = await fetch(rawUrl, {
      method: 'GET',
      headers: { Accept: 'application/json, application/yaml, text/yaml, text/plain' },
    });

    const contentType = (resp.headers.get('content-type') || '').toLowerCase();
    const text = await resp.text();
    const trimmed = text.trimStart();

    // Detect HTML response → Swagger UI browser page
    const isHtml = contentType.includes('text/html')
      || trimmed.startsWith('<!doctype')
      || trimmed.startsWith('<html')
      || trimmed.startsWith('<!DOCTYPE');

    if (isHtml) {
      return {
        valid: false,
        error: 'This URL returns an HTML page (the Swagger UI browser), not the raw spec. Use the JSON or YAML spec endpoint instead.',
        suggestions,
      };
    }

    // Try JSON
    try { JSON.parse(text); return { valid: true }; } catch { /* not JSON */ }

    // Accept YAML indicators
    if (
      trimmed.startsWith('openapi:') ||
      trimmed.startsWith('swagger:') ||
      trimmed.startsWith('---') ||
      trimmed.includes('\nopenapi:') ||
      trimmed.includes('\nswagger:')
    ) {
      return { valid: true };
    }

    // Non-empty but unrecognised format
    if (text.trim().length > 0) {
      return {
        valid: false,
        error: 'URL did not return a recognisable OpenAPI spec (expected JSON or YAML).',
        suggestions,
      };
    }

    return { valid: false, error: 'The URL returned an empty response.', suggestions };
  } catch (err) {
    // Network / CORS error — block and ask user to verify URL accessibility
    return {
      valid: false,
      error: 'Could not reach this URL (network, CORS, or connection error). Verify the URL is accessible and public.',
    };
  }
}

export default function IntegrationGrid({ loading = false }) {
  const integrations = useStore((s) => s.integrations);
  const toast = useStore((s) => s.toast);
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [testing, setTesting] = useState(null);
  const [creating, setCreating] = useState(false);
  const [validatingSpecs, setValidatingSpecs] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [name, setName] = useState('');
  const [specs, setSpecs] = useState([]);
  const [agentPrompt, setAgentPrompt] = useState('');
  const [tags, setTags] = useState('');
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState({});
  // Per-spec fetch validation results: array of { valid, error, suggestions, warning }
  const [specFetchResults, setSpecFetchResults] = useState([]);
  const [duplicateUrlConfirm, setDuplicateUrlConfirm] = useState(null);

  const filtered = integrations.filter((i) => {
    const q = search.toLowerCase();
    return i.name.toLowerCase().includes(q) || (i.spec || '').toLowerCase().includes(q) || (i.tags || []).some((t) => t.toLowerCase().includes(q));
  });

  function resetForm() {
    setName(''); setSpecs([]); setAgentPrompt(''); setTags(''); setNotes('');
    setErrors({}); setSpecFetchResults([]);
  }

  // File-upload and pasted-content specs are stored as JSON blobs starting
  // with "{". Plain URLs are everything else. Helper keeps that contract.
  const isInlineSpec = (s) => typeof s === 'string' && s.trim().startsWith('{');

  function validateForm() {
    const errs = {};
    const trimName = name.trim();
    if (!trimName) errs.name = 'Integration name is required';
    else if (trimName.length < 2) errs.name = 'Name must be at least 2 characters';
    else if (trimName.length > 100) errs.name = 'Name must be under 100 characters';
    else if (integrations.some((i) => i.name.toLowerCase() === trimName.toLowerCase())) errs.name = `"${trimName}" already exists`;
    const validSpecs = specs.map((s) => s.trim()).filter(Boolean);
    if (validSpecs.length === 0) errs.specs = 'Add at least one spec (URL, file, or pasted content)';
    else {
      const specErrors = []; const seen = new Set();
      validSpecs.forEach((u, i) => {
        if (isInlineSpec(u)) {
          // File uploads and pasted content are validated inside SpecInputTabs.
          const key = `inline:${u.length}:${u.slice(0, 48)}`;
          if (seen.has(key)) specErrors[i] = 'Duplicate entry';
          seen.add(key);
          return;
        }
        try {
          const url = new URL(u);
          if (!['http:', 'https:'].includes(url.protocol)) specErrors[i] = 'Must be http:// or https://';
          else if (seen.has(u.toLowerCase())) specErrors[i] = 'Duplicate URL';
          seen.add(u.toLowerCase());
        } catch { specErrors[i] = 'Invalid URL format'; }
      });
      if (specErrors.some(Boolean)) errs.specErrors = specErrors;
    }
    const tagList = tags.split(',').map((t) => t.trim()).filter(Boolean);
    if (tagList.length > 10) errs.tags = 'Maximum 10 tags allowed';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function findDuplicateUrls(validSpecs) {
    // Only URL specs can be matched against previously persisted integrations.
    // Inline file/paste specs are per-submission and have no authoritative key.
    const matches = [];
    validSpecs.forEach((url) => {
      if (isInlineSpec(url)) return;
      const lower = url.toLowerCase();
      integrations.forEach((integ) => {
        const existingSpecs = [integ.spec, ...(integ.specs || [])].filter(Boolean);
        if (existingSpecs.some((s) => s.toLowerCase() === lower)) {
          matches.push({ url, integrationName: integ.name });
        }
      });
    });
    return matches;
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!validateForm()) return;

    // ── Spec URL content validation ──
    // Only URL-backed specs need a remote fetch check. Inline specs
    // (file-upload / pasted-content) are already validated by SpecInputTabs.
    const validSpecs = specs.map((s) => s.trim()).filter(Boolean);
    setValidatingSpecs(true);
    setSpecFetchResults([]);
    const results = await Promise.all(
      validSpecs.map((s) => (isInlineSpec(s) ? Promise.resolve({ valid: true }) : validateSpecUrl(s))),
    );
    setSpecFetchResults(results);
    setValidatingSpecs(false);

    // Block if any spec returned an invalid result
    if (results.some((r) => !r.valid)) {
      setErrors((prev) => ({
        ...prev,
        specs: 'One or more spec URLs are invalid. Fix the errors below and try again.',
      }));
      return;
    }

    if (!duplicateUrlConfirm) {
      const matches = findDuplicateUrls(validSpecs);
      if (matches.length > 0) { setDuplicateUrlConfirm(matches); return; }
    }
    await submitCreate();
  }

  async function submitCreate() {
    const trimName = name.trim();
    const validSpecs = specs.map((s) => s.trim()).filter(Boolean);
    const tagList = tags.split(',').map((t) => t.trim()).filter(Boolean);
    setCreating(true); setDuplicateUrlConfirm(null);
    try {
      await createIntegration({
        name: trimName,
        specs: validSpecs,
        agent_prompt: agentPrompt.trim() || undefined,
        tags: tagList.length > 0 ? tagList : undefined,
        notes: notes.trim() || undefined,
      });
      toast('Integration created');
      setCreateOpen(false);
      resetForm();
      window.dispatchEvent(new CustomEvent('integrations:reload'));
    } catch (err) {
      toast(typeof err === 'string' ? err : (err?.message || 'Create failed'), 'error');
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    const targetId = deleteTarget.id;
    setDeletingId(targetId);
    setDeleteTarget(null);
    try {
      await deleteIntegration(targetId);
      toast('Integration deleted');
      window.dispatchEvent(new CustomEvent('integrations:reload'));
    } catch (err) {
      toast(typeof err === 'string' ? err : (err?.message || 'Delete failed'), 'error');
    } finally {
      setDeletingId(null);
    }
  }

  async function handleTestConnection(id) {
    setTesting(id);
    try {
      const result = await testConnection(id);
      toast(result.success ? `Connected (${result.latency_ms}ms)` : (result.message || 'Connection failed'), result.success ? '' : 'error');
      window.dispatchEvent(new CustomEvent('integrations:reload'));
    } catch (err) {
      toast(typeof err === 'string' ? err : (err?.message || 'Test failed'), 'error');
    } finally {
      setTesting(null);
    }
  }

  const isBusy = creating || validatingSpecs;

  return (
    <Box>
      {/* Toolbar */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2.5, alignItems: 'center' }}>
        <TextField placeholder="Search integrations..." value={search} onChange={(e) => setSearch(e.target.value)} sx={{ flex: 1 }} />
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)} sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
          New Integration
        </Button>
      </Box>

      {/* Resume last integration banner */}
      {!loading && (() => {
        const lastId = loadString(STORAGE_KEYS.lastIntegrationId);
        if (!lastId) return null;
        const lastInteg = integrations.find((i) => i.id === lastId);
        if (!lastInteg) return null;
        return (
          <Paper
            variant="outlined"
            sx={{
              mb: 2,
              px: 2.5,
              py: 1.5,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 2,
              borderStyle: 'dashed',
            }}
          >
            <Stack direction="row" spacing={1.25} alignItems="center" sx={{ minWidth: 0 }}>
              <HistoryIcon sx={{ color: 'text.secondary', fontSize: 20 }} />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>
                  Resume: {lastInteg.name}
                </Typography>
                <Typography variant="caption" color="text.secondary" noWrap>
                  Pick up where you left off
                </Typography>
              </Box>
            </Stack>
            <Button
              variant="outlined"
              size="small"
              endIcon={<ArrowForwardIcon />}
              onClick={() => navigate(`/integrations/${lastInteg.id}`)}
              sx={{ flexShrink: 0 }}
            >
              Continue
            </Button>
          </Paper>
        );
      })()}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '45vh' }}>
          <LogoLoader size={88} message="Loading integrations..." />
        </Box>
      ) : filtered.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          {integrations.length === 0 ? (
            <Box sx={{ py: 3 }}>
              <ExtensionOutlinedIcon
                sx={{
                  fontSize: 56,
                  color: 'action.disabled',
                  mb: 2,
                  display: 'block',
                  mx: 'auto',
                }}
              />
              <Typography variant="h6" sx={{ mb: 1, fontWeight: 600 }}>
                Create Your First Integration
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3, maxWidth: 400, mx: 'auto' }}>
                Upload an OpenAPI spec to get started. We'll analyze it and help you build an MCP server.
              </Typography>

              <Stack gap={2} sx={{ maxWidth: 350, mx: 'auto' }}>
                <Button
                  variant="contained"
                  size="large"
                  onClick={() => setCreateOpen(true)}
                  sx={{ textTransform: 'none', fontWeight: 600 }}
                >
                  Add OpenAPI Spec
                </Button>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                  <Divider sx={{ flex: 1 }} />
                  <Typography variant="caption" color="text.secondary">or</Typography>
                  <Divider sx={{ flex: 1 }} />
                </Box>

                <Alert severity="info" sx={{ textAlign: 'left' }}>
                  <Typography variant="caption" sx={{ fontWeight: 500, display: 'block', mb: 0.5 }}>
                    New to Forge?
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                    Check the documentation to see an example integration workflow.
                  </Typography>
                </Alert>
              </Stack>
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No integrations match your search. Try a different query.
            </Typography>
          )}
        </Paper>
      ) : (
        <Grid container spacing={1.5}>
          {filtered.map((integ) => {
            const conn = integ.last_connection_test;
            const latency = conn?.latency_ms;
            const latencyLabel = latency != null ? (latency >= 1000 ? `${(latency / 1000).toFixed(1)}s` : `${latency}ms`) : null;
            const cardTags = integ.tags || [];
            const primaryTag = cardTags[0];
            const remainingTagCount = Math.max(0, cardTags.length - 1);
            return (
              <Grid item xs={12} sm={6} lg={4} key={integ.id}>
                <Card
                  sx={{
                    height: '100%',
                    '&:hover': { boxShadow: 3 },
                    transition: 'box-shadow 150ms',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  {testing === integ.id && <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3 }} />}
                  {(primaryTag || remainingTagCount > 0) && (
                    <Box
                      sx={{
                        position: 'absolute',
                        top: conn ? 36 : 12,
                        right: 14,
                        zIndex: 1,
                        display: 'flex',
                        gap: 0.5,
                      }}
                    >
                      {primaryTag && <Chip size="small" label={primaryTag} variant="outlined" />}
                      {remainingTagCount > 0 && <Chip size="small" label={`+${remainingTagCount}`} variant="outlined" />}
                    </Box>
                  )}
                  <CardContent sx={{ display: 'flex', flexDirection: 'column', minHeight: 174, pt: 2, pb: 1, '&:last-child': { pb: 1.25 } }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 1.5, mb: 0.5, minHeight: 30 }}>
                      <Typography variant="body1" fontWeight={600} noWrap sx={{ flex: 1, minWidth: 0 }}>{integ.name}</Typography>
                      {conn && (
                        <Chip
                          size="small"
                          label={conn.success ? `Connected · ${latencyLabel}` : 'Failed'}
                          color={conn.success ? 'success' : 'error'}
                          variant={conn.success ? 'filled' : 'outlined'}
                          sx={conn.success ? { bgcolor: (t) => t.palette.mode === 'dark' ? 'rgba(34,197,94,.15)' : '#f0fdf4', color: 'success.main' } : undefined}
                        />
                      )}
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                      <Typography variant="caption" color="text.secondary" noWrap sx={{ fontFamily: 'monospace', flex: 1 }}>{integ.spec || '—'}</Typography>
                      {integ.spec && (
                        <Tooltip title={copiedId === integ.id ? 'Copied!' : 'Copy spec URL'}>
                          <IconButton size="small" color={copiedId === integ.id ? 'success' : 'default'}
                            onClick={() => { navigator.clipboard.writeText(integ.spec); setCopiedId(integ.id); setTimeout(() => setCopiedId((p) => p === integ.id ? null : p), 2000); }}>
                            {copiedId === integ.id ? <CheckIcon sx={{ fontSize: 14 }} /> : <ContentCopyIcon sx={{ fontSize: 14 }} />}
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>
                    {false && integ.tags?.length > 0 && (
                      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
                        {integ.tags.map((t) => <Chip key={t} size="small" label={t} variant="outlined" />)}
                      </Box>
                    )}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, minHeight: 24 }}>
                      {integ.run_count > 0
                        ? <Chip size="small" label="Scored" variant="outlined" />
                        : <Chip size="small" label="No score" variant="outlined" sx={{ color: 'text.secondary' }} />}
                      <Typography variant="caption" color="text.secondary">{integ.run_count || 0} runs</Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mt: 'auto' }}>
                      <Button variant="contained" size="small" endIcon={<ArrowForwardIcon />} onClick={() => navigate(`/integrations/${integ.id}`)}>Manage</Button>
                      <Box sx={{ display: 'flex', gap: 0.5 }}>
                        <Tooltip title="Test connection">
                          <span>
                            <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleTestConnection(integ.id); }} disabled={testing === integ.id}>
                              <CheckCircleOutlineIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                        <Tooltip title="Delete integration">
                          <span>
                            <IconButton size="small" color="error" disabled={deletingId === integ.id} onClick={(e) => { e.stopPropagation(); setDeleteTarget(integ); }}>
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Box>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      {/* ── Create Dialog ── */}
      <Dialog open={createOpen} onClose={() => { setCreateOpen(false); resetForm(); }} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ pb: 0 }}>Create Integration</DialogTitle>
        <Box sx={{ px: 3, pb: 1 }}>
          <Typography variant="body2" color="text.secondary">Connect an API by providing its OpenAPI/Swagger spec URL.</Typography>
        </Box>

        {/* Spec validation progress */}
        {validatingSpecs && (
          <Box sx={{ px: 3, py: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
              <CircularProgress size={14} />
              <Typography variant="caption" color="text.secondary">Validating spec URL(s)…</Typography>
            </Box>
            <LinearProgress sx={{ mt: 0.75, borderRadius: 1 }} />
          </Box>
        )}

        <DialogContent>
          <form id="create-integ" onSubmit={handleCreate}>
            <Stack spacing={2.5} sx={{ mt: 0.5 }}>
              {/* Name */}
              <Box>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>
                  Name <Typography component="span" color="error.main">*</Typography>
                </Typography>
                <TextField
                  value={name}
                  onChange={(e) => { setName(e.target.value); setErrors((p) => ({ ...p, name: undefined })); }}
                  placeholder="e.g. Jira Cloud API"
                  error={!!errors.name}
                  helperText={errors.name}
                  autoFocus
                  inputProps={{ maxLength: 100 }}
                />
              </Box>

              {/* Spec Input - Multi-method (URL, File, Paste, Recent) */}
              <Box>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>
                  API Spec <Typography component="span" color="error.main">*</Typography>
                </Typography>
                {errors.specs && (
                  <Alert severity="error" sx={{ mb: 1 }}>
                    {errors.specs}
                  </Alert>
                )}
                <SpecInputTabs
                  specs={specs}
                  onChange={(updated) => {
                    setSpecs(updated);
                    setErrors((p) => ({ ...p, specs: undefined, specErrors: undefined }));
                    setSpecFetchResults([]);
                  }}
                />
                {specFetchResults.some((r) => !r.valid) && (
                  <Stack spacing={1} sx={{ mt: 1 }}>
                    {specFetchResults.map((result, idx) => (
                      !result.valid ? (
                        <Alert key={idx} severity="error" sx={{ whiteSpace: 'pre-wrap' }}>
                          <strong>Spec {idx + 1} validation failed:</strong> {result.error}
                          {result.suggestions?.length ? (
                            <Box component="div" sx={{ mt: 1 }}>
                              Suggested spec URLs:
                              <ul style={{ margin: '0.25rem 0 0 1rem', padding: 0 }}>
                                {result.suggestions.map((suggestion) => (
                                  <li key={suggestion} style={{ listStyle: 'disc' }}>{suggestion}</li>
                                ))}
                              </ul>
                            </Box>
                          ) : null}
                        </Alert>
                      ) : null
                    ))}
                  </Stack>
                )}
              </Box>

              {/* Agent Intent */}
              <Box>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>
                  Agent Intent <Typography component="span" color="text.secondary" fontWeight={400}>(optional)</Typography>
                </Typography>
                <TextField
                  multiline rows={3}
                  value={agentPrompt}
                  onChange={(e) => setAgentPrompt(e.target.value)}
                  placeholder="e.g. A support agent that looks up orders, checks status, and handles refunds"
                  helperText="Describe what the agent using this API should do. This helps the LLM create better tool groupings."
                />
              </Box>

              {/* Tags + Notes */}
              <Box sx={{ display: 'flex', gap: 2 }}>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>Tags</Typography>
                  <TextField
                    value={tags}
                    onChange={(e) => { setTags(e.target.value); setErrors((p) => ({ ...p, tags: undefined })); }}
                    placeholder="support, prod"
                    error={!!errors.tags}
                    helperText={errors.tags || 'Comma-separated, max 10'}
                  />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>Notes</Typography>
                  <TextField
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Optional notes"
                    helperText="Internal notes about this integration"
                  />
                </Box>
              </Box>
            </Stack>
          </form>
        </DialogContent>

        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button variant="outlined" onClick={() => { setCreateOpen(false); resetForm(); }}>Cancel</Button>
          <Button
            variant="contained"
            type="submit"
            form="create-integ"
            disabled={isBusy}
            startIcon={validatingSpecs ? <CircularProgress size={13} color="inherit" /> : undefined}
          >
            {validatingSpecs ? 'Validating…' : creating ? 'Creating…' : 'Create Integration'}
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Delete Integration"
        message={`Delete "${deleteTarget?.name}"? This will remove all runs, artifacts, and configurations.`}
        confirmLabel="Delete"
        confirmClass="btn-danger"
        loading={!!deleteTarget && deletingId === deleteTarget.id}
      />

      {/* Duplicate URL Confirmation */}
      <Dialog open={!!duplicateUrlConfirm} onClose={() => setDuplicateUrlConfirm(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Duplicate Spec URL Detected</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>The following spec URL(s) are already used:</Typography>
          <Stack spacing={1}>
            {duplicateUrlConfirm?.map((m, i) => (
              <Paper key={i} variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="caption" sx={{ fontFamily: 'monospace', display: 'block', wordBreak: 'break-all' }}>{m.url}</Typography>
                <Typography variant="caption" color="text.secondary">Already in: <strong>{m.integrationName}</strong></Typography>
              </Paper>
            ))}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>Would you still like to create this integration?</Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDuplicateUrlConfirm(null)}>Cancel</Button>
          <Button variant="contained" onClick={submitCreate} disabled={creating}>
            {creating ? 'Creating…' : 'Create Anyway'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

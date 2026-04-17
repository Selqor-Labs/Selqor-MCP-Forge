import React from 'react';
import { useEffect, useState, useCallback } from 'react';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardActionArea from '@mui/material/CardActionArea';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Autocomplete from '@mui/material/Autocomplete';
import Stack from '@mui/material/Stack';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import Table from '@mui/material/Table';
import TableHead from '@mui/material/TableHead';
import TableBody from '@mui/material/TableBody';
import TableRow from '@mui/material/TableRow';
import TableCell from '@mui/material/TableCell';
import Paper from '@mui/material/Paper';
import CircularProgress from '@mui/material/CircularProgress';
import LogoLoader from '../components/LogoLoader';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Divider from '@mui/material/Divider';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import AddIcon from '@mui/icons-material/Add';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import StarIcon from '@mui/icons-material/Star';
import CloseIcon from '@mui/icons-material/Close';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import useStore from '../store/useStore';
import ConfirmDialog from '../components/ConfirmDialog';
import {
  fetchLlmProviders, fetchLlmConfigs, saveLlmConfig, deleteLlmConfig,
  testLlmConnection,
} from '../api';
import { required, httpUrl, jsonObject, runValidators, formatError } from '../utils/validators';
import { extractError } from '../utils/apiError';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function StatusChip({ cfg }) {
  if (cfg.last_test_success === true) return <Chip size="small" label="Active" color="success" icon={<CheckCircleOutlineIcon />} />;
  if (cfg.last_test_success === false) return <Chip size="small" label="Error" color="error" icon={<ErrorOutlineIcon />} />;
  return <Chip size="small" label="Untested" icon={<HelpOutlineIcon />} />;
}

function emptyForm() {
  return {
    name: '', provider: '', model: '', api_key: '', base_url: '',
    enabled: true, is_default: false,
    embedding_model: '', embedding_api_key: '', embedding_dimensions: '',
    is_default_embedding: false,
    vllm_auth_type: 'none',
    vllm_auth_headers: {},
    custom_headers: '{}',
  };
}

export default function LlmConfig() {
  const toast = useStore((s) => s.toast);
  const [providers, setProviders] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [testing, setTesting] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formErrors, setFormErrors] = useState({});
  const [form, setForm] = useState(emptyForm());

  const load = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([fetchLlmProviders(), fetchLlmConfigs()]);
      setProviders(p.providers || p || []);
      setConfigs(c.configs || c || []);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const llmConfigs = configs.filter((c) => c.model || c.provider);
  const selectedProvider = providers.find((p) => (p.id || p.name || p) === form.provider);
  const providerModels = selectedProvider?.models || [];

  function update(field, value) { setForm((f) => ({ ...f, [field]: value })); setFormErrors((e) => ({ ...e, [field]: '' })); }

  function openCreate(providerId) {
    const f = emptyForm();
    if (providerId) f.provider = providerId;
    setForm(f);
    setFormErrors({});
    setEditId(null);
    setModalOpen(true);
  }

  function openEdit(cfg) {
    setForm({
      name: cfg.name || '',
      provider: cfg.provider || '',
      model: cfg.model || '',
      api_key: cfg.api_key || '',
      base_url: cfg.base_url || '',
      enabled: cfg.enabled !== false,
      is_default: cfg.is_default || false,
      embedding_model: cfg.embedding_model || '',
      embedding_api_key: cfg.embedding_api_key || '',
      embedding_dimensions: cfg.embedding_dimensions || '',
      is_default_embedding: cfg.is_default_embedding || false,
      vllm_auth_type: cfg.vllm_auth_type || 'none',
      vllm_auth_headers: cfg.vllm_auth_headers || {},
      custom_headers: cfg.custom_headers ? JSON.stringify(cfg.custom_headers, null, 2) : '{}',
    });
    setFormErrors({});
    setEditId(cfg.id || cfg.config_id);
    setModalOpen(true);
  }

  // Centralized validator spec (Feature 6). The visible fields differ by
  // provider, so we only add validators for what's actually shown.
  function validate() {
    const spec = {
      provider: [required('Provider')],
      name: [required('Config name')],
      model: [required('Model')],
      custom_headers: [jsonObject('Custom headers')],
    };
    if (showApiKey()) {
      spec.api_key = [required('API Key')];
    }
    if (showBaseUrl()) {
      // Base URL is only required for providers that explicitly need one
      // (vLLM, self-hosted). Everywhere else it's optional and we just
      // validate the format if the user typed something.
      const baseValidators = [httpUrl('Base URL')];
      if (selectedProvider?.requires_base_url || form.provider === 'vllm') {
        baseValidators.unshift(required('Base URL'));
      }
      spec.base_url = baseValidators;
    }
    const errors = runValidators(spec, form);
    // Flatten to a `{ field: message }` map for compatibility with the
    // existing render code which reads `formErrors[field]` as a string.
    const flat = Object.fromEntries(
      Object.entries(errors).map(([k, v]) => [k, formatError(v)]),
    );
    setFormErrors(flat);
    return Object.keys(errors).length === 0;
  }

  async function handleSave() {
    if (!validate()) return;
    setSaving(true);
    try {
      const wasFirstConfig = llmConfigs.length === 0;
      const payload = { ...form };
      // Already validated above — safe to parse directly.
      payload.custom_headers = form.custom_headers ? JSON.parse(form.custom_headers) : {};
      // Coerce numeric-or-empty string fields to int | null so Pydantic accepts them
      if (payload.embedding_dimensions === '' || payload.embedding_dimensions == null) {
        payload.embedding_dimensions = null;
      } else {
        const n = Number(payload.embedding_dimensions);
        payload.embedding_dimensions = Number.isFinite(n) ? Math.trunc(n) : null;
      }
      if (editId) payload.id = editId;
      await saveLlmConfig(payload);

      // Show appropriate toast message
      if (editId) {
        toast('Configuration updated', 'success');
      } else if (wasFirstConfig) {
        toast('✨ First LLM configured and automatically set as default for analysis', 'success');
      } else {
        toast('Configuration created', 'success');
      }

      setModalOpen(false);
      load();
    } catch (err) {
      const { message, fieldErrors: serverFieldErrors } = extractError(err);
      if (Object.keys(serverFieldErrors).length > 0) {
        setFormErrors((prev) => ({ ...prev, ...serverFieldErrors }));
      }
      toast(message, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await deleteLlmConfig(deleteTarget);
      toast('Configuration deleted', 'success');
      load();
    } catch (err) {
      toast(extractError(err).message, 'error');
    }
    setDeleteTarget(null);
  }

  async function handleTest(id) {
    setTesting(id);
    try {
      const res = await testLlmConnection(id);
      if (res.success || res.status === 'ok') {
        toast(`Connection successful${res.latency_ms ? ` (${res.latency_ms}ms)` : ''}`, 'success');
      } else {
        toast(res.error || 'Connection failed', 'error');
      }
      load();
    } catch (err) {
      toast(extractError(err).message, 'error');
    } finally {
      setTesting(null);
    }
  }

  function providerLabel(id) {
    const p = providers.find((pr) => (pr.id || pr.name || pr) === id);
    return p?.label || p?.name || id || '—';
  }

  const showApiKey = () => {
    if (form.provider === 'vllm') return false;
    return selectedProvider?.requires_api_key || ['anthropic', 'openai', 'mistral', 'gemini', 'sarvam'].includes(form.provider) || !!form.api_key;
  };

  const showBaseUrl = () => selectedProvider?.requires_base_url || ['vllm', 'sarvam', 'aws_bedrock', 'vertex_ai'].includes(form.provider) || !!form.base_url;

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
        <LogoLoader size={96} message="Loading LLM configurations…" />
      </Box>
    );
  }

  return (
    <Box>
      {/* Security Banner */}
      <Alert severity="info" icon={<LockOutlinedIcon fontSize="small" />} sx={{ mb: 3 }}>
        <Typography variant="body2">
          <strong>Security:</strong> API keys are encrypted at rest. Keys are never exposed in logs or responses.
        </Typography>
      </Alert>

      {/* Current Default LLM Status */}
      {llmConfigs.length > 0 && (
        <Box sx={{ mb: 3 }}>
          {llmConfigs.find((c) => c.is_default) ? (
            <Alert severity="success" icon={<CheckCircleOutlineIcon />}>
              <Typography variant="body2">
                <strong>Default LLM:</strong> {llmConfigs.find((c) => c.is_default).name} ({llmConfigs.find((c) => c.is_default).provider} / {llmConfigs.find((c) => c.is_default).model}) will be used for all analysis operations.
              </Typography>
            </Alert>
          ) : (
            <Alert severity="info">
              <Typography variant="body2">
                <strong>No default LLM set.</strong> Select one below to use it for analysis.
              </Typography>
            </Alert>
          )}
        </Box>
      )}

      {/* LLM Configurations Table */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Typography variant="body2" color="text.secondary">Manage your AI model connections for analysis and generation</Typography>
          <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={() => openCreate()} sx={{ flexShrink: 0, ml: 2 }}>
            Add Configuration
          </Button>
        </Box>

        <Paper variant="outlined">
          {llmConfigs.length === 0 ? (
            <Box sx={{ p: 4 }}>
              <Box sx={{ textAlign: 'center', mb: 3 }}>
                <SmartToyOutlinedIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1, display: 'block' }} />
                <Typography variant="h6" sx={{ mb: 1, fontWeight: 600 }}>
                  LLM Configuration (Optional)
                </Typography>
              </Box>
              <Alert severity="info" sx={{ mb: 2 }}>
                <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
                  LLM integration is optional. When configured, Forge can:
                </Typography>
                <ul style={{ margin: '0.5rem 0', paddingLeft: '1.2rem' }}>
                  <li><Typography variant="caption" component="span">Generate tool arguments from natural language</Typography></li>
                  <li><Typography variant="caption" component="span">Suggest optimal endpoint compression strategies</Typography></li>
                  <li><Typography variant="caption" component="span">Score integration quality and coverage</Typography></li>
                </ul>
              </Alert>
              <Alert severity="success" icon={<CheckCircleOutlineIcon />} sx={{ mb: 2 }}>
                <Typography variant="body2">
                  <strong>✨ First LLM automatically becomes default:</strong> When you add your first LLM configuration, it will automatically be set as the default for all analysis operations.
                </Typography>
              </Alert>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
                Click <strong>Add Configuration</strong> to connect an LLM provider, or skip and continue creating integrations.
              </Typography>
            </Box>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Provider</TableCell>
                  <TableCell>Model</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Last Tested</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {llmConfigs.map((cfg) => {
                  const id = cfg.id || cfg.config_id;
                  return (
                    <TableRow key={id} hover>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          {cfg.is_default && (
                            <Tooltip title="Default LLM">
                              <StarIcon sx={{ fontSize: 14, color: '#eab308' }} />
                            </Tooltip>
                          )}
                          <Typography variant="body2" fontWeight={500}>{cfg.name || id}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip size="small" label={providerLabel(cfg.provider)} variant="outlined" />
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{cfg.model || '—'}</Typography>
                      </TableCell>
                      <TableCell><StatusChip cfg={cfg} /></TableCell>
                      <TableCell>
                        <Typography variant="caption" color="text.secondary">{fmtDate(cfg.last_tested_at)}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                          <Tooltip title={testing === id ? 'Testing…' : 'Test Connection'}>
                            <span>
                              <IconButton size="small" onClick={() => handleTest(id)} disabled={!!testing}>
                                {testing === id ? <CircularProgress size={14} /> : <RefreshOutlinedIcon fontSize="small" />}
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title="Edit">
                            <IconButton size="small" onClick={() => openEdit(cfg)}>
                              <EditOutlinedIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Delete">
                            <IconButton size="small" color="error" onClick={() => setDeleteTarget(id)}>
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </Box>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </Paper>
      </Box>

      {/* Supported Providers */}
      <Box>
        <Box sx={{ mb: 1.5 }}>
          <Typography variant="subtitle2">Supported Providers</Typography>
          <Typography variant="caption" color="text.secondary">Click a provider card to quickly add a new configuration</Typography>
        </Box>
        <Grid container spacing={1.5}>
          {providers.map((p, i) => {
            const id = p.id || p.name || p;
            const label = p.label || p.name || p;
            const desc = p.description || '';
            return (
              <Grid item xs={12} sm={6} md={4} lg={3} key={i}>
                <Card variant="outlined" sx={{ height: '100%' }}>
                  <CardActionArea onClick={() => openCreate(id)} sx={{ p: 1.5, height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                    <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>{label}</Typography>
                    {desc && <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>{desc}</Typography>}
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 'auto' }}>
                      {p.requires_api_key && <Chip size="small" label="API Key" variant="outlined" sx={{ fontSize: '0.6rem' }} />}
                      {p.requires_base_url && <Chip size="small" label="Base URL" variant="outlined" sx={{ fontSize: '0.6rem' }} />}
                    </Box>
                  </CardActionArea>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      </Box>

      {/* Add / Edit Dialog */}
      <Dialog open={modalOpen} onClose={() => setModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 1.5, px: 2.5 }}>
          {editId ? 'Edit Configuration' : 'Add LLM Configuration'}
          <IconButton size="small" onClick={() => setModalOpen(false)}><CloseIcon fontSize="small" /></IconButton>
        </DialogTitle>
        <Divider />
        <DialogContent sx={{ px: 3, pt: 2.5, pb: 1 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2.5 }}>
            {editId ? 'Update your LLM provider settings.' : 'Connect a new LLM provider — API keys are encrypted and stored securely.'}
          </Typography>
          <Grid container spacing={2} alignItems="flex-start">
            <Grid item xs={12} sm={6}>
              <TextField
                select fullWidth size="small" label="Provider" required
                value={form.provider}
                onChange={(e) => update('provider', e.target.value)}
                disabled={!!editId}
                error={!!formErrors.provider}
                helperText={formErrors.provider || 'The LLM service you want to connect'}
              >
                <MenuItem value=""><em>Select provider</em></MenuItem>
                {providers.map((p, i) => (
                  <MenuItem key={i} value={p.id || p.name || p}>{p.label || p.name || p}</MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth size="small" label="Config Name" required
                placeholder="e.g. Production Claude"
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                error={!!formErrors.name}
                helperText={formErrors.name || 'A friendly label for this configuration'}
              />
            </Grid>
            <Grid item xs={12}>
              <Autocomplete
                freeSolo
                size="small"
                options={providerModels.map((m) => (typeof m === 'string' ? m : (m.id || m.name || '')))}
                value={form.model || ''}
                onChange={(_, newValue) => update('model', newValue || '')}
                onInputChange={(_, newValue, reason) => {
                  if (reason === 'input' || reason === 'clear') update('model', newValue || '');
                }}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    fullWidth
                    label="Model"
                    required
                    placeholder={providerModels.length === 0 ? 'e.g. claude-sonnet-4-20250514' : 'Select a preset or type a custom model'}
                    error={!!formErrors.model}
                    helperText={formErrors.model || 'Pick from suggestions or type any custom model name'}
                  />
                )}
              />
            </Grid>

            {showApiKey() && (
              <Grid item xs={12}>
                <TextField
                  fullWidth size="small" label="API Key" type="password"
                  placeholder="sk-…"
                  value={form.api_key}
                  onChange={(e) => update('api_key', e.target.value)}
                  helperText="Your provider API key — stored encrypted, never logged"
                />
              </Grid>
            )}

            {showBaseUrl() && (
              <Grid item xs={12}>
                <TextField
                  fullWidth size="small" label="Base URL" type="url"
                  placeholder="https://api.example.com/v1"
                  value={form.base_url}
                  onChange={(e) => update('base_url', e.target.value)}
                  helperText="Custom endpoint URL (required for vLLM, Sarvam, Bedrock)"
                />
              </Grid>
            )}

            <Grid item xs={12}>
              <Stack direction="row" spacing={3} sx={{ mt: 0.5 }}>
                <FormControlLabel
                  control={<Checkbox size="small" checked={form.enabled} onChange={(e) => update('enabled', e.target.checked)} />}
                  label={<Typography variant="body2">Enabled</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Checkbox size="small" checked={form.is_default} onChange={(e) => update('is_default', e.target.checked)} />}
                  label={<Typography variant="body2">Set as Default LLM</Typography>}
                  sx={{ m: 0 }}
                />
              </Stack>
            </Grid>
          </Grid>
        </DialogContent>
        <Divider />
        <DialogActions sx={{ px: 2.5, py: 1.5, justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {editId && (
              <>
                <Button
                  size="small" variant="outlined"
                  startIcon={testing === editId ? <CircularProgress size={12} /> : <RefreshOutlinedIcon />}
                  onClick={() => handleTest(editId)}
                  disabled={!!testing}
                >
                  Test
                </Button>
                <Button size="small" color="error" startIcon={<DeleteOutlineIcon />}
                  onClick={() => { setModalOpen(false); setDeleteTarget(editId); }}>
                  Delete
                </Button>
              </>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button variant="outlined" size="small" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button variant="contained" size="small" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : editId ? 'Save Changes' : 'Create'}
            </Button>
          </Box>
        </DialogActions>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Delete Configuration"
        message="Delete this LLM configuration? All associated settings will be permanently removed."
        confirmLabel="Delete"
        confirmClass="btn-danger"
      />
    </Box>
  );
}

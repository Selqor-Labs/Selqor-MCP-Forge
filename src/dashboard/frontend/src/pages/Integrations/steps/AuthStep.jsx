import React from 'react';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogActions from '@mui/material/DialogActions';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import useStore from '../../../store/useStore';
import { saveAuth, testConnection } from '../../../api';
import { required, httpUrl, jsonObject, runValidators, formatError } from '../../../utils/validators';
import { extractError } from '../../../utils/apiError';

function formatRelativeTime(iso) {
  if (!iso) return '';
  try {
    const then = new Date(iso).getTime();
    const diff = Date.now() - then;
    const mins = Math.round(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    return `${days}d ago`;
  } catch {
    return '';
  }
}

const AUTH_MODES = [
  { value: 'none', label: 'None' }, { value: 'api_key', label: 'API Key' }, { value: 'bearer', label: 'Bearer Token' },
  { value: 'basic', label: 'Basic Auth' }, { value: 'token_based', label: 'Token-Based' },
  { value: 'oauth2_client_credentials', label: 'OAuth2 Client Credentials' }, { value: 'custom_headers', label: 'Custom Headers' },
];

export default function AuthStep({ integration, onReload }) {
  const auth = useStore((s) => s.auth);
  const toast = useStore((s) => s.toast);
  const navigate = useNavigate();
  const [form, setForm] = useState({ base_url: '', auth_mode: 'none', api_key: '', api_key_header: 'X-API-Key', bearer_token: '', basic_username: '', basic_password: '', token_value: '', token_header: 'Authorization', token_prefix: 'Bearer', oauth_token_url: '', oauth_client_id: '', oauth_client_secret: '', oauth_scope: '', custom_headers: '{}' });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  // Seed from persisted last_connection_test so the banner survives navigation/reload.
  const [testResult, setTestResult] = useState(() => integration?.last_connection_test || null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Field-level errors populated by the centralized validator run (Feature 6).
  // Keys match `form` keys; values are `{ message, hint?, example? }`.
  const [fieldErrors, setFieldErrors] = useState({});

  // Build a validator spec keyed off the currently selected auth mode so we
  // only validate the fields that are actually visible. `httpUrl` passes
  // empty values — pair with `required` to gate the Save.
  function buildValidationSpec(mode) {
    const spec = {
      base_url: [required('Base URL'), httpUrl('Base URL')],
    };
    switch (mode) {
      case 'api_key':
        spec.api_key = [required('API Key')];
        spec.api_key_header = [required('Header Name')];
        break;
      case 'bearer':
        spec.bearer_token = [required('Bearer Token')];
        break;
      case 'basic':
        spec.basic_username = [required('Username')];
        spec.basic_password = [required('Password')];
        break;
      case 'token_based':
        spec.token_value = [required('Token Value')];
        spec.token_header = [required('Header Name')];
        break;
      case 'oauth2_client_credentials':
        spec.oauth_token_url = [required('Token URL'), httpUrl('Token URL')];
        spec.oauth_client_id = [required('Client ID')];
        spec.oauth_client_secret = [required('Client Secret')];
        break;
      case 'custom_headers':
        spec.custom_headers = [required('Headers'), jsonObject('Headers')];
        break;
      default:
        break;
    }
    return spec;
  }

  // Only auto-fill Base URL when the spec is a real http(s) URL. For uploaded
  // files / paste / file paths the user must enter the API's real host — the
  // spec path is not a network target.
  function deriveBaseUrl(spec) {
    if (!spec) return '';
    if (!/^https?:\/\//i.test(spec)) return '';
    try { return new URL(spec).origin; }
    catch { return ''; }
  }

  const specIsHttp = Boolean(integration?.spec && /^https?:\/\//i.test(integration.spec));

  useEffect(() => {
    const defaultBaseUrl = deriveBaseUrl(integration.spec);
    // Reject any stored base_url that isn't a real http(s) URL — old records
    // may contain a file path written by an earlier version of this form.
    const storedBase = auth?.base_url && /^https?:\/\//i.test(auth.base_url)
      ? auth.base_url
      : '';
    if (auth) setForm({ base_url: storedBase || defaultBaseUrl, auth_mode: auth.auth_mode || 'none', api_key: auth.api_key || '', api_key_header: auth.api_key_header || 'X-API-Key', bearer_token: auth.bearer_token || '', basic_username: auth.basic_username || '', basic_password: auth.basic_password || '', token_value: auth.token_value || '', token_header: auth.token_header || 'Authorization', token_prefix: auth.token_prefix || 'Bearer', oauth_token_url: auth.oauth_token_url || '', oauth_client_id: auth.oauth_client_id || '', oauth_client_secret: auth.oauth_client_secret || '', oauth_scope: auth.oauth_scope || '', custom_headers: auth.custom_headers ? JSON.stringify(auth.custom_headers, null, 2) : '{}' });
    else setForm((f) => ({ ...f, base_url: f.base_url || defaultBaseUrl }));
  }, [auth, integration.spec]);

  // Keep the banner in sync if the parent reloads the integration record.
  useEffect(() => {
    if (integration?.last_connection_test && !testResult) {
      setTestResult(integration.last_connection_test);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [integration?.last_connection_test]);

  // Soft gate: if auth_mode requires credentials and no successful test exists,
  // warn the user but still allow them to proceed.
  const needsCredentials = form.auth_mode && form.auth_mode !== 'none';
  const hasSuccessfulTest = Boolean(testResult?.success);
  const shouldWarnOnContinue = needsCredentials && !hasSuccessfulTest;

  function goToToolBuilder() {
    navigate(`/integrations/${integration.id}/tools`);
  }

  function handleContinueClick() {
    if (shouldWarnOnContinue) {
      setConfirmOpen(true);
    } else {
      goToToolBuilder();
    }
  }

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    // Clear the field-level error as soon as the user edits the field,
    // so they don't see stale red text while still typing.
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  }

  async function handleSave() {
    // Validate everything relevant to the current auth mode before hitting
    // the server. Client-side failures never reach the API.
    const spec = buildValidationSpec(form.auth_mode);
    const errors = runValidators(spec, form);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      toast('Please fix the highlighted fields before saving.', 'error');
      return;
    }
    setFieldErrors({});
    setSaving(true);
    try {
      const payload = { base_url: form.base_url || null, auth_mode: form.auth_mode };
      switch (form.auth_mode) {
        case 'api_key': payload.api_key = form.api_key || null; payload.api_key_header = form.api_key_header || 'X-API-Key'; break;
        case 'bearer': payload.bearer_token = form.bearer_token || null; break;
        case 'basic': payload.basic_username = form.basic_username || null; payload.basic_password = form.basic_password || null; break;
        case 'token_based': payload.token_value = form.token_value || null; payload.token_header = form.token_header || 'Authorization'; payload.token_prefix = form.token_prefix || 'Bearer'; break;
        case 'oauth2_client_credentials': payload.oauth_token_url = form.oauth_token_url || null; payload.oauth_client_id = form.oauth_client_id || null; payload.oauth_client_secret = form.oauth_client_secret || null; payload.oauth_scope = form.oauth_scope || null; break;
        case 'custom_headers':
          // Already validated above — this parse is guaranteed to succeed.
          payload.custom_headers = JSON.parse(form.custom_headers || '{}');
          break;
      }
      await saveAuth(integration.id, payload);
      toast('Auth config saved', 'success');
      onReload();
    } catch (err) {
      const { message, fieldErrors: serverFieldErrors } = extractError(err);
      if (Object.keys(serverFieldErrors).length > 0) {
        // FastAPI 422 — highlight the specific inputs the server rejected.
        setFieldErrors((prev) => ({
          ...prev,
          ...Object.fromEntries(
            Object.entries(serverFieldErrors).map(([k, v]) => [k, { message: v }]),
          ),
        }));
      }
      toast(message, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    // Only Base URL matters for the test call — we don't require credentials
    // because some public APIs are reachable without auth and the user may
    // legitimately want to verify network reachability first.
    const errors = runValidators({ base_url: [required('Base URL'), httpUrl('Base URL')] }, form);
    if (Object.keys(errors).length > 0) {
      setFieldErrors((prev) => ({ ...prev, ...errors }));
      toast('Enter a valid Base URL before testing.', 'error');
      return;
    }
    setTesting(true); setTestResult(null);
    try {
      const result = await testConnection(integration.id);
      setTestResult(result);
      toast(
        result.success ? `Connected (${result.latency_ms}ms)` : (result.message || 'Failed'),
        result.success ? 'success' : 'error',
      );
    } catch (err) {
      const { message } = extractError(err);
      toast(message, 'error');
    } finally {
      setTesting(false);
    }
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 0.5 }}>Authentication Configuration</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>Configure how Selqor Forge authenticates with your API when testing connections and deploying servers.</Typography>
      <Stack spacing={2} sx={{ maxWidth: 520 }}>
        {!specIsHttp && !form.base_url && (
          <Alert severity="info" variant="outlined">
            <Typography variant="body2" fontWeight={600} sx={{ mb: 0.25 }}>
              Enter your API&apos;s base URL
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              This integration was created from an uploaded spec file, so Selqor Forge
              can&apos;t auto-detect the API&apos;s host. Enter the root URL where this
              API is actually served (e.g. <code>https://api.digitalocean.com</code>) so
              connectivity tests and deployed servers know where to send requests.
            </Typography>
          </Alert>
        )}
        <TextField
          label="Base URL"
          type="url"
          placeholder="https://api.example.com"
          value={form.base_url}
          onChange={(e) => update('base_url', e.target.value)}
          error={Boolean(fieldErrors.base_url)}
          helperText={
            fieldErrors.base_url
              ? formatError(fieldErrors.base_url)
              : 'The root URL of your API (used for connection testing)'
          }
        />
        <TextField select label="Auth Mode" value={form.auth_mode} onChange={(e) => update('auth_mode', e.target.value)} helperText="Select the authentication method your API requires">
          {AUTH_MODES.map((m) => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
        </TextField>
        {form.auth_mode === 'api_key' && (
          <>
            <TextField label="API Key" type="password" value={form.api_key} onChange={(e) => update('api_key', e.target.value)} placeholder="sk-..."
              error={Boolean(fieldErrors.api_key)} helperText={fieldErrors.api_key ? formatError(fieldErrors.api_key) : ''} />
            <TextField label="Header Name" value={form.api_key_header} onChange={(e) => update('api_key_header', e.target.value)}
              error={Boolean(fieldErrors.api_key_header)} helperText={fieldErrors.api_key_header ? formatError(fieldErrors.api_key_header) : ''} />
          </>
        )}
        {form.auth_mode === 'bearer' && (
          <TextField label="Bearer Token" type="password" value={form.bearer_token} onChange={(e) => update('bearer_token', e.target.value)}
            error={Boolean(fieldErrors.bearer_token)} helperText={fieldErrors.bearer_token ? formatError(fieldErrors.bearer_token) : ''} />
        )}
        {form.auth_mode === 'basic' && (
          <>
            <TextField label="Username" value={form.basic_username} onChange={(e) => update('basic_username', e.target.value)}
              error={Boolean(fieldErrors.basic_username)} helperText={fieldErrors.basic_username ? formatError(fieldErrors.basic_username) : ''} />
            <TextField label="Password" type="password" value={form.basic_password} onChange={(e) => update('basic_password', e.target.value)}
              error={Boolean(fieldErrors.basic_password)} helperText={fieldErrors.basic_password ? formatError(fieldErrors.basic_password) : ''} />
          </>
        )}
        {form.auth_mode === 'token_based' && (
          <>
            <TextField label="Token Value" type="password" value={form.token_value} onChange={(e) => update('token_value', e.target.value)}
              error={Boolean(fieldErrors.token_value)} helperText={fieldErrors.token_value ? formatError(fieldErrors.token_value) : ''} />
            <TextField label="Header Name" value={form.token_header} onChange={(e) => update('token_header', e.target.value)}
              error={Boolean(fieldErrors.token_header)} helperText={fieldErrors.token_header ? formatError(fieldErrors.token_header) : ''} />
            <TextField label="Prefix" value={form.token_prefix} onChange={(e) => update('token_prefix', e.target.value)} />
          </>
        )}
        {form.auth_mode === 'oauth2_client_credentials' && (
          <>
            <TextField label="Token URL" type="url" value={form.oauth_token_url} onChange={(e) => update('oauth_token_url', e.target.value)}
              error={Boolean(fieldErrors.oauth_token_url)} helperText={fieldErrors.oauth_token_url ? formatError(fieldErrors.oauth_token_url) : ''} />
            <TextField label="Client ID" value={form.oauth_client_id} onChange={(e) => update('oauth_client_id', e.target.value)}
              error={Boolean(fieldErrors.oauth_client_id)} helperText={fieldErrors.oauth_client_id ? formatError(fieldErrors.oauth_client_id) : ''} />
            <TextField label="Client Secret" type="password" value={form.oauth_client_secret} onChange={(e) => update('oauth_client_secret', e.target.value)}
              error={Boolean(fieldErrors.oauth_client_secret)} helperText={fieldErrors.oauth_client_secret ? formatError(fieldErrors.oauth_client_secret) : ''} />
            <TextField label="Scope" value={form.oauth_scope} onChange={(e) => update('oauth_scope', e.target.value)} />
          </>
        )}
        {form.auth_mode === 'custom_headers' && (
          <TextField label="Headers (JSON)" multiline rows={4} value={form.custom_headers} onChange={(e) => update('custom_headers', e.target.value)}
            sx={{ '& textarea': { fontFamily: 'monospace' } }}
            error={Boolean(fieldErrors.custom_headers)}
            helperText={fieldErrors.custom_headers ? formatError(fieldErrors.custom_headers) : 'JSON object of header name → value pairs'} />
        )}
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Button variant="contained" size="small" onClick={handleSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
          <Button variant="outlined" size="small" onClick={handleTest} disabled={testing}>{testing ? 'Testing...' : 'Test Connection'}</Button>
          <Box sx={{ flex: 1 }} />
          <Button
            variant="contained"
            color="primary"
            size="small"
            endIcon={<ArrowForwardIcon />}
            onClick={handleContinueClick}
          >
            Continue to Tool Builder
          </Button>
        </Box>
        {testResult && (
          <Alert severity={testResult.success ? 'success' : 'error'}>
            <Typography variant="body2" fontWeight={600}>
              {testResult.success ? 'Connected' : 'Failed'}
              {testResult.status_code ? ` — ${testResult.status_code}` : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {testResult.message}
              {testResult.latency_ms != null ? ` (${testResult.latency_ms}ms)` : ''}
            </Typography>
            {testResult.tested_at && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                Last tested {formatRelativeTime(testResult.tested_at)}
              </Typography>
            )}
          </Alert>
        )}
        {shouldWarnOnContinue && (
          <Alert severity="info" variant="outlined">
            You haven&apos;t verified this connection yet. You can run a Test Connection check
            before moving on, or continue anyway and fix it later.
          </Alert>
        )}
      </Stack>
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>Continue without a successful connection test?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Running analysis and tool curation works fine without a verified connection,
            but you&apos;ll need one before deploying or testing tools in the playground.
            Do you want to continue to Tool Builder now?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Stay Here</Button>
          <Button
            variant="contained"
            onClick={() => {
              setConfirmOpen(false);
              goToToolBuilder();
            }}
          >
            Continue Anyway
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

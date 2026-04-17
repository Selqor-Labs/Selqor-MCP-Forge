import React, { useEffect, useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import ContentPasteOutlinedIcon from '@mui/icons-material/ContentPasteOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import LinkOutlinedIcon from '@mui/icons-material/LinkOutlined';
import useStore from '../../../store/useStore';
import { loadJson, saveJson } from '../../../utils/persist';

// ── Constants ────────────────────────────────────────────────────────────────
const RECENT_SPECS_KEY = 'forge.recentSpecs.v1';
const MAX_RECENT = 5;
const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5MB
const FILE_UPLOAD = 'file-upload';
const PASTED_CONTENT = 'pasted-content';

// ── Helpers ──────────────────────────────────────────────────────────────────
// Specs stored as a JSON object with `__type` carry file or pasted content.
// Plain strings are URLs. These helpers keep that contract in one place.
function parseSpecMeta(spec) {
  if (typeof spec !== 'string' || !spec.startsWith('{')) return null;
  try {
    const parsed = JSON.parse(spec);
    if (parsed && typeof parsed === 'object' && parsed.__type) return parsed;
  } catch { /* not json */ }
  return null;
}

function describeSpec(spec) {
  const meta = parseSpecMeta(spec);
  if (meta?.__type === FILE_UPLOAD) {
    return { kind: 'file', label: meta.filename || 'Uploaded file' };
  }
  if (meta?.__type === PASTED_CONTENT) {
    return { kind: 'paste', label: 'Pasted content' };
  }
  try {
    const u = new URL(spec);
    return { kind: 'url', label: `${u.host}${u.pathname}`.replace(/\/$/, '') || u.host };
  } catch {
    return { kind: 'url', label: spec.length > 48 ? `${spec.slice(0, 45)}…` : spec };
  }
}

function looksLikeYaml(text) {
  const t = text.trimStart();
  return /^(openapi|swagger)\s*:/i.test(t) || t.startsWith('---');
}

function validateSpecDocument(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) return 'Content cannot be empty.';
  try {
    const doc = JSON.parse(trimmed);
    if (doc && typeof doc === 'object' && (doc.openapi || doc.swagger || doc.paths)) return null;
    return 'JSON parsed but does not look like an OpenAPI document (missing `openapi`, `swagger`, or `paths`).';
  } catch { /* not JSON, try YAML */ }
  if (looksLikeYaml(trimmed)) return null;
  return 'Content does not look like OpenAPI JSON or YAML.';
}

function validateUrl(value) {
  const trimmed = (value || '').trim();
  if (!trimmed) return 'URL cannot be empty.';
  try {
    const u = new URL(trimmed);
    if (!['http:', 'https:'].includes(u.protocol)) {
      return 'URL must start with http:// or https://';
    }
  } catch {
    return 'Invalid URL format.';
  }
  return null;
}

// ── Component ────────────────────────────────────────────────────────────────
export default function SpecInputTabs({ specs, onChange }) {
  const toast = useStore((s) => s.toast);

  // Strip legacy empty strings before rendering.
  const activeSpecs = useMemo(
    () => (specs || []).filter((s) => typeof s === 'string' && s.trim()),
    [specs],
  );

  const [tab, setTab] = useState(0);
  const [recent, setRecent] = useState([]);
  const [urlValue, setUrlValue] = useState('');
  const [urlError, setUrlError] = useState('');
  const [pasteValue, setPasteValue] = useState('');
  const [pasteError, setPasteError] = useState('');
  const [dragActive, setDragActive] = useState(false);

  // Load persisted recent URLs once on mount.
  useEffect(() => {
    const parsed = loadJson(RECENT_SPECS_KEY, []);
    if (Array.isArray(parsed)) setRecent(parsed.slice(0, MAX_RECENT));
  }, []);

  const persistRecent = (url) => {
    setRecent((prev) => {
      const next = [url, ...prev.filter((u) => u !== url)].slice(0, MAX_RECENT);
      saveJson(RECENT_SPECS_KEY, next);
      return next;
    });
  };

  const tryAddSpec = (spec, label) => {
    if (activeSpecs.includes(spec)) {
      toast(`${label} is already added`, 'error');
      return false;
    }
    onChange([...activeSpecs, spec]);
    return true;
  };

  const removeSpec = (spec) => {
    onChange(activeSpecs.filter((s) => s !== spec));
  };

  // ── URL tab ────────────────────────────────────────────────────────────────
  const handleAddUrl = () => {
    const err = validateUrl(urlValue);
    if (err) { setUrlError(err); return; }
    const trimmed = urlValue.trim();
    if (!tryAddSpec(trimmed, 'This URL')) return;
    persistRecent(trimmed);
    toast('Spec URL added', 'success');
    setUrlValue('');
    setUrlError('');
  };

  // ── File tab ───────────────────────────────────────────────────────────────
  const handleFile = async (file) => {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      toast(`File too large (${(file.size / 1024 / 1024).toFixed(1)}MB · max 5MB)`, 'error');
      return;
    }
    const lower = file.name.toLowerCase();
    if (!['.json', '.yaml', '.yml'].some((ext) => lower.endsWith(ext))) {
      toast('Only .json, .yaml and .yml files are supported', 'error');
      return;
    }
    let content;
    try { content = await file.text(); }
    catch { toast('Could not read file', 'error'); return; }

    const err = validateSpecDocument(content);
    if (err) { toast(err, 'error'); return; }

    const spec = JSON.stringify({
      __type: FILE_UPLOAD,
      filename: file.name,
      content,
      uploadedAt: new Date().toISOString(),
    });
    if (tryAddSpec(spec, `"${file.name}"`)) toast(`Added "${file.name}"`, 'success');
  };

  const handleDragOver = (e) => { e.preventDefault(); setDragActive(true); };
  const handleDragLeave = (e) => { e.preventDefault(); setDragActive(false); };
  const handleDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  };

  // ── Paste tab ──────────────────────────────────────────────────────────────
  const handleAddPaste = () => {
    const err = validateSpecDocument(pasteValue);
    if (err) { setPasteError(err); return; }
    const spec = JSON.stringify({
      __type: PASTED_CONTENT,
      content: pasteValue.trim(),
      pastedAt: new Date().toISOString(),
    });
    if (tryAddSpec(spec, 'This content')) {
      toast('Spec content added', 'success');
      setPasteValue('');
      setPasteError('');
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <Box>
      {activeSpecs.length > 0 && (
        <Box sx={{ mb: 1.25 }}>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: 'block', mb: 0.5, fontWeight: 600 }}
          >
            Added Specs ({activeSpecs.length})
          </Typography>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.625 }}>
            {activeSpecs.map((spec) => {
              const { kind, label } = describeSpec(spec);
              const Icon =
                kind === 'file' ? CloudUploadOutlinedIcon
                  : kind === 'paste' ? ContentPasteOutlinedIcon
                    : LinkOutlinedIcon;
              return (
                <Chip
                  key={spec}
                  size="small"
                  variant="outlined"
                  icon={<Icon sx={{ fontSize: 14 }} />}
                  label={label}
                  onDelete={() => removeSpec(spec)}
                  sx={{ maxWidth: '100%', '& .MuiChip-label': { px: 0.75 } }}
                />
              );
            })}
          </Stack>
        </Box>
      )}

      <Paper
        variant="outlined"
        sx={{
          overflow: 'hidden',
          // Inherit the surrounding surface tone so the section doesn't look
          // darker than the dialog's elevation-tinted background in dark mode.
          bgcolor: 'transparent',
          backgroundImage: 'none',
        }}
      >
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
          sx={{
            minHeight: 40,
            borderBottom: 1,
            borderColor: 'divider',
            '& .MuiTab-root': {
              minHeight: 40,
              textTransform: 'none',
              fontSize: '0.8125rem',
              fontWeight: 600,
              gap: 0.5,
            },
          }}
        >
          <Tab
            icon={<LinkOutlinedIcon sx={{ fontSize: 16 }} />}
            iconPosition="start"
            label="From URL"
          />
          <Tab
            icon={<CloudUploadOutlinedIcon sx={{ fontSize: 16 }} />}
            iconPosition="start"
            label="Upload File"
          />
          <Tab
            icon={<ContentPasteOutlinedIcon sx={{ fontSize: 16 }} />}
            iconPosition="start"
            label="Paste"
          />
          <Tab
            icon={<HistoryOutlinedIcon sx={{ fontSize: 16 }} />}
            iconPosition="start"
            label={recent.length ? `Recent (${recent.length})` : 'Recent'}
            disabled={recent.length === 0}
          />
        </Tabs>

        <Box sx={{ p: { xs: 1.5, sm: 2 } }}>
          {/* URL tab */}
          {tab === 0 && (
            <Stack spacing={1.25}>
              <TextField
                placeholder="https://api.example.com/openapi.json"
                value={urlValue}
                onChange={(e) => { setUrlValue(e.target.value); setUrlError(''); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); handleAddUrl(); }
                }}
                error={!!urlError}
                helperText={urlError || 'Public URL returning an OpenAPI JSON or YAML document.'}
              />
              <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                  variant="contained"
                  onClick={handleAddUrl}
                  disabled={!urlValue.trim()}
                >
                  Add URL
                </Button>
              </Box>
            </Stack>
          )}

          {/* File tab */}
          {tab === 1 && (
            <Stack spacing={1}>
              <Box
                component="label"
                htmlFor="spec-file-input"
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  textAlign: 'center',
                  px: 2,
                  py: { xs: 2.5, sm: 3.5 },
                  borderRadius: 1.5,
                  border: '1.5px dashed',
                  borderColor: dragActive ? 'text.primary' : 'divider',
                  bgcolor: dragActive ? 'action.hover' : 'transparent',
                  cursor: 'pointer',
                  transition: 'border-color 150ms ease, background-color 150ms ease',
                  '&:hover': {
                    borderColor: 'text.primary',
                    bgcolor: 'action.hover',
                  },
                }}
              >
                <CloudUploadOutlinedIcon sx={{ fontSize: 32, color: 'text.secondary', mb: 1 }} />
                <Typography variant="body2" fontWeight={600}>
                  Drag & drop file here
                </Typography>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mb: 1.25 }}
                >
                  or click to browse
                </Typography>
                <Button variant="outlined" size="small" component="span">
                  Select File
                </Button>
                <input
                  id="spec-file-input"
                  type="file"
                  accept=".json,.yaml,.yml,application/json,text/yaml"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFile(f);
                    e.target.value = '';
                  }}
                />
              </Box>
              <Typography variant="caption" color="text.secondary">
                JSON or YAML, up to 5MB.
              </Typography>
            </Stack>
          )}

          {/* Paste tab */}
          {tab === 2 && (
            <Stack spacing={1.25}>
              <TextField
                multiline
                minRows={6}
                maxRows={12}
                placeholder={'openapi: 3.0.0\ninfo:\n  title: My API\n  version: 1.0.0\npaths:\n  ...'}
                value={pasteValue}
                onChange={(e) => { setPasteValue(e.target.value); setPasteError(''); }}
                error={!!pasteError}
                helperText={pasteError || 'Paste a complete OpenAPI JSON or YAML document.'}
                sx={{
                  '& textarea': {
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                    fontSize: '0.75rem',
                    lineHeight: 1.5,
                  },
                }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                  variant="contained"
                  onClick={handleAddPaste}
                  disabled={!pasteValue.trim()}
                >
                  Add Content
                </Button>
              </Box>
            </Stack>
          )}

          {/* Recent tab */}
          {tab === 3 && (
            <Stack spacing={0.75}>
              {recent.length === 0 ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ py: 1.5, textAlign: 'center' }}
                >
                  No recent specs yet.
                </Typography>
              ) : recent.map((url) => {
                let host = url;
                try { host = new URL(url).host; } catch { /* ignore */ }
                const alreadyAdded = activeSpecs.includes(url);
                return (
                  <Paper
                    key={url}
                    variant="outlined"
                    onClick={() => {
                      if (alreadyAdded) return;
                      if (tryAddSpec(url, 'This URL')) {
                        toast('Recent spec added', 'success');
                      }
                    }}
                    sx={{
                      px: 1.25,
                      py: 0.875,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      cursor: alreadyAdded ? 'default' : 'pointer',
                      opacity: alreadyAdded ? 0.55 : 1,
                      bgcolor: 'transparent',
                      backgroundImage: 'none',
                      transition: 'background-color 150ms',
                      '&:hover': {
                        bgcolor: alreadyAdded ? undefined : 'action.hover',
                      },
                    }}
                  >
                    <LinkOutlinedIcon sx={{ fontSize: 16, color: 'text.secondary', flexShrink: 0 }} />
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography variant="body2" noWrap fontWeight={600}>{host}</Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        noWrap
                        sx={{ display: 'block', fontFamily: 'ui-monospace, monospace' }}
                      >
                        {url}
                      </Typography>
                    </Box>
                    {alreadyAdded && (
                      <Typography variant="caption" color="text.secondary">Added</Typography>
                    )}
                  </Paper>
                );
              })}
            </Stack>
          )}
        </Box>
      </Paper>
    </Box>
  );
}

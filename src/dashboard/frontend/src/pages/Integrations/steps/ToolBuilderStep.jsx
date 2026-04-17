import React from 'react';
import { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import Paper from '@mui/material/Paper';
import Alert from '@mui/material/Alert';
import Stack from '@mui/material/Stack';
import LinearProgress from '@mui/material/LinearProgress';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Checkbox from '@mui/material/Checkbox';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import FormControl from '@mui/material/FormControl';
import AddIcon from '@mui/icons-material/Add';
import SaveIcon from '@mui/icons-material/Save';
import ClearIcon from '@mui/icons-material/Clear';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import CloseIcon from '@mui/icons-material/Close';
import SearchIcon from '@mui/icons-material/Search';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import useStore from '../../../store/useStore';
import { saveTooling, deleteTooling, fetchArtifacts, fetchArtifactContent } from '../../../api';
import { METHOD_COLORS } from '../../../theme';
import { useTheme } from '@mui/material/styles';
import ToolQualityBreakdown from '../../../components/ToolQualityBreakdown';

function MethodChip({ method, isDark }) {
  const m = (method || 'GET').toLowerCase();
  const c = METHOD_COLORS[m] || METHOD_COLORS.get;
  return (
    <Chip size="small" label={m.toUpperCase()}
      sx={{ height: 18, fontSize: '0.6rem', fontWeight: 700, fontFamily: 'monospace',
        bgcolor: isDark ? c.darkBg : c.bg, color: isDark ? c.darkFg : c.fg,
        '& .MuiChip-label': { px: 0.5 }, borderRadius: 0.5 }} />
  );
}

export default function ToolBuilderStep({ integration, onReload }) {
  const tooling = useStore((s) => s.tooling);
  const runs = useStore((s) => s.runs);
  const toast = useStore((s) => s.toast);
  const muiTheme = useTheme();
  const isDark = muiTheme.palette.mode === 'dark';

  const tools = tooling?.tools || [];
  const source = tooling?.source || 'default';

  const [selectedIndex, setSelectedIndex] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toolSearch, setToolSearch] = useState('');
  const [endpointCatalog, setEndpointCatalog] = useState([]);
  const [endpointMap, setEndpointMap] = useState({});
  const [loadingEndpoints, setLoadingEndpoints] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [loadingRun, setLoadingRun] = useState(false);

  // Detail-panel search (edits now live-update the store directly — no edit buffer).
  const [epSearch, setEpSearch] = useState('');

  const selectedTool = selectedIndex !== null ? tools[selectedIndex] : null;

  // Build endpoint catalog from tools' covered_endpoints. For large specs
  // (1000+ endpoints) the uasf.json artifact can be 400MB+ and cannot be
  // parsed in the browser. Instead, we synthesize the catalog from the
  // tools themselves which already contain all endpoint IDs.
  useEffect(() => {
    const currentTools = useStore.getState().tooling?.tools || [];
    if (currentTools.length === 0) return;

    const seen = new Set();
    const eps = [];
    for (const tool of currentTools) {
      for (const epId of (tool.covered_endpoints || [])) {
        if (!seen.has(epId)) {
          seen.add(epId);
          // Derive method from endpoint ID prefix if possible
          const parts = epId.split('_');
          const method = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options'].includes(parts[0])
            ? parts[0].toUpperCase() : 'GET';
          eps.push({ id: epId, method, path: epId, summary: epId.replace(/_/g, ' ') });
        }
      }
    }
    setEndpointCatalog(eps);
    const map = {};
    eps.forEach((ep) => { map[ep.id] = ep; });
    setEndpointMap(map);
  }, [tooling]);

  // Load tools from a specific run when user selects one
  async function loadRunTools(runId) {
    setLoadingRun(true);
    try {
      const res = await fetchArtifacts(integration.id, runId);
      const names = res.artifacts || [];
      const planName = names.find((n) => n === 'analysis-plan.json');
      if (planName) {
        const content = await fetchArtifactContent(integration.id, runId, planName);
        const parsed = typeof content === 'string' ? JSON.parse(content) : content;
        const runTools = parsed.tools || [];
        if (runTools.length > 0) {
          useStore.setState({ tooling: { tools: runTools, source: 'generated', warnings: parsed.warnings || [] } });
          setSelectedRunId(runId);
          setSelectedIndex(null);
          toast(`Loaded ${runTools.length} tools from run ${runId}`, 'success');
        } else {
          toast('No tools found in this run', 'warning');
        }
      } else {
        toast('No analysis plan found for this run', 'warning');
      }
    } catch (err) {
      toast(typeof err === 'string' ? err : (err?.message || 'Failed to load run tools'), 'error');
    } finally { setLoadingRun(false); }
  }

  // Clear the endpoint-search field when switching tools.
  useEffect(() => { setEpSearch(''); }, [selectedIndex]);

  // Stats
  const allAssigned = new Set(tools.flatMap((t) => t.covered_endpoints || []));
  const unassigned = endpointCatalog.filter((ep) => !allAssigned.has(ep.id));
  const totalEp = endpointCatalog.length;
  const coveragePct = totalEp > 0 ? Math.round((allAssigned.size / totalEp) * 100) : 0;

  const filteredTools = tools.filter((t) => {
    if (!toolSearch) return true;
    const q = toolSearch.toLowerCase();
    return (t.name || '').toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
  });

  function updateSelectedTool(patch) {
    if (selectedIndex === null) return;
    const updated = tools.map((t, i) => (i === selectedIndex ? { ...t, ...patch } : t));
    useStore.setState({ tooling: { ...tooling, tools: updated, source: 'manual' } });
  }

  function handleAddTool() {
    const updated = [...tools, { name: `New Tool ${tools.length + 1}`, description: '', covered_endpoints: [] }];
    useStore.setState({ tooling: { ...tooling, tools: updated, source: 'manual' } });
    setSelectedIndex(updated.length - 1);
  }

  async function handleDeleteTool() {
    if (selectedIndex === null) return;
    const nextTools = tools.filter((_, i) => i !== selectedIndex);
    useStore.setState({ tooling: { ...tooling, tools: nextTools, source: 'manual' } });
    setSelectedIndex(null);
    // Persist immediately — the detail panel closes after delete so the user
    // has no Save button to click.
    setSaving(true);
    try { await saveTooling(integration.id, nextTools); toast('Tool deleted', 'success'); onReload(); }
    catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Save failed'), 'error'); }
    finally { setSaving(false); }
  }

  async function handleSave() {
    setSaving(true);
    try { await saveTooling(integration.id, tools); toast('Tools saved', 'success'); onReload(); }
    catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Save failed'), 'error'); }
    finally { setSaving(false); }
  }

  async function handleClear() {
    try { await deleteTooling(integration.id); toast('Manual overrides cleared'); setSelectedIndex(null); onReload(); }
    catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Failed'), 'error'); }
  }

  function toggleEndpoint(epId) {
    if (!selectedTool) return;
    const covered = selectedTool.covered_endpoints || [];
    const next = covered.includes(epId)
      ? covered.filter((id) => id !== epId)
      : [...covered, epId];
    updateSelectedTool({ covered_endpoints: next });
  }

  const filteredEps = endpointCatalog.filter((ep) => {
    if (!epSearch) return true;
    const q = epSearch.toLowerCase();
    return (ep.path || '').toLowerCase().includes(q) || (ep.method || '').toLowerCase().includes(q) || (ep.summary || '').toLowerCase().includes(q);
  });

  if (tools.length === 0) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 1.5 }}>
        <Typography variant="body1" fontWeight={600}>No tools available</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', maxWidth: 400 }}>
          Run an analysis first (Step 1) to auto-generate tools from your API spec, or add tools manually.
        </Typography>
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={handleAddTool}>Add Tool Manually</Button>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)' }}>
      {/* Top bar */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Tooltip title="Tools shown in this builder (from analysis). The pipeline curates these into a smaller final set during generation.">
            <Typography variant="body2"><strong>{tools.length}</strong> analysis tools</Typography>
          </Tooltip>
          <Divider orientation="vertical" flexItem />
          <Tooltip title="Endpoints covered by these tools / total unique endpoints">
            <Typography variant="body2"><strong>{allAssigned.size}</strong>/{totalEp} endpoints</Typography>
          </Tooltip>
          <Divider orientation="vertical" flexItem />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 100 }}>
            <LinearProgress variant="determinate" value={coveragePct} sx={{ flex: 1, height: 6, borderRadius: 3 }} color={coveragePct === 100 ? 'success' : 'primary'} />
            <Typography variant="caption" fontWeight={600}>{coveragePct}%</Typography>
          </Box>
          {(loadingEndpoints || loadingRun) && <CircularProgress size={14} />}
          <Chip size="small" label={source === 'manual' ? 'Manual' : source === 'generated' ? 'Auto-generated' : 'Default'} color={source === 'manual' ? 'primary' : 'default'} variant="outlined" />
        </Box>
        <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center' }}>
          {runs.length > 1 && (
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <Select
                value={selectedRunId || (runs[0]?.run_id || '')}
                onChange={(e) => loadRunTools(e.target.value)}
                displayEmpty
                sx={{ fontSize: '0.75rem', height: 30 }}
              >
                {runs.map((r) => (
                  <MenuItem key={r.run_id} value={r.run_id} sx={{ fontSize: '0.75rem' }}>
                    {r.analysis_source || 'run'} &middot; {r.tool_count || '?'} curated &middot; score {r.score ?? '?'} &middot; {(r.created_at || '').slice(0, 16).replace('T', ' ')}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <Button variant="outlined" size="small" startIcon={<AddIcon />} onClick={handleAddTool}>Add Tool</Button>
          {source === 'manual' && <Button variant="text" size="small" startIcon={<ClearIcon />} onClick={handleClear}>Reset</Button>}
        </Box>
      </Box>

      {unassigned.length > 0 && (
        <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mb: 1, py: 0 }}>
          <Typography variant="caption"><strong>{unassigned.length}</strong> endpoint{unassigned.length !== 1 ? 's' : ''} not assigned to any tool.</Typography>
        </Alert>
      )}


      {/* Master-Detail */}
      <Box sx={{ display: 'flex', flex: 1, gap: 2, overflow: 'hidden' }}>
        {/* Left: Tool List */}
        <Box sx={{ width: { xs: selectedTool ? 0 : '100%', md: selectedTool ? 300 : '100%' }, display: { xs: selectedTool ? 'none' : 'flex', md: 'flex' }, flexDirection: 'column', flexShrink: 0, transition: 'width 200ms' }}>
          <TextField placeholder="Search tools..." value={toolSearch} onChange={(e) => setToolSearch(e.target.value)} size="small" sx={{ mb: 1 }}
            InputProps={{ startAdornment: <SearchIcon sx={{ mr: 0.5, color: 'text.disabled', fontSize: 18 }} /> }} />
          <Box sx={{ flex: 1, overflow: 'auto' }}>
            <Stack spacing={0.75}>
              {filteredTools.map((tool) => {
                const realIdx = tools.indexOf(tool);
                const covered = tool.covered_endpoints || [];
                const isSelected = selectedIndex === realIdx;
                // Method distribution
                const methods = {};
                covered.forEach((id) => { const ep = endpointMap[id]; if (ep) { const m = (ep.method || 'GET').toUpperCase(); methods[m] = (methods[m] || 0) + 1; } });
                return (
                  <Card key={realIdx} onClick={() => setSelectedIndex(realIdx)}
                    sx={{ cursor: 'pointer', borderColor: isSelected ? 'primary.main' : 'divider', borderWidth: isSelected ? 2 : 1, '&:hover': { borderColor: 'primary.main' } }}>
                    <CardContent sx={{ py: 1.25, px: 1.5, '&:last-child': { pb: 1.25 } }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 0.5 }}>
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600} noWrap>{tool.name}</Typography>
                          {tool.description && <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>{tool.description}</Typography>}
                        </Box>
                        {tool.name === 'custom_request' ? (
                          <Chip size="small" label="Built-in" sx={{ height: 18, fontSize: '0.6rem', ml: 0.5 }}
                            color="default" variant="outlined" />
                        ) : (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 0.5 }}>
                            {/* Feature 5: compact 4-factor quality score badge.
                                The existing confidence chip stays put — the two
                                numbers answer different questions (Q = is this
                                tool good?, % = is the grouping correct?). */}
                            <ToolQualityBreakdown tool={tool} endpointMap={endpointMap} compact />
                            {tool.confidence != null && tool.confidence > 0 && (
                              <Chip size="small" label={`${Math.round(tool.confidence * 100)}%`} sx={{ height: 18, fontSize: '0.6rem' }}
                                color={tool.confidence >= 0.8 ? 'success' : tool.confidence >= 0.5 ? 'warning' : 'error'} variant="outlined" />
                            )}
                          </Box>
                        )}
                      </Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
                        {Object.keys(methods).map((m) => <MethodChip key={m} method={m} isDark={isDark} />)}
                        <Typography variant="caption" color="text.secondary">{covered.length} endpoint{covered.length !== 1 ? 's' : ''}</Typography>
                      </Box>
                    </CardContent>
                  </Card>
                );
              })}
            </Stack>

            {/* Unassigned */}
            {unassigned.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="caption" color="warning.main" fontWeight={600} sx={{ mb: 0.5, display: 'block' }}>Unassigned ({unassigned.length})</Typography>
                <Stack spacing={0.25}>
                  {unassigned.slice(0, 10).map((ep, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, py: 0.25 }}>
                      <MethodChip method={ep.method} isDark={isDark} />
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }} noWrap>{ep.path}</Typography>
                    </Box>
                  ))}
                  {unassigned.length > 10 && <Typography variant="caption" color="text.secondary">+{unassigned.length - 10} more</Typography>}
                </Stack>
              </Box>
            )}
          </Box>
        </Box>

        {/* Right: Detail Panel */}
        {selectedTool && (
          <Paper variant="outlined" sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', px: 2, py: 1.5, borderBottom: 1, borderColor: 'divider' }}>
              <Typography variant="body1" fontWeight={600}>{selectedTool.name || 'Untitled Tool'}</Typography>
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Tooltip title="Delete tool"><IconButton size="small" color="error" onClick={handleDeleteTool}><DeleteOutlineIcon fontSize="small" /></IconButton></Tooltip>
                <Tooltip title="Close"><IconButton size="small" onClick={() => setSelectedIndex(null)}><CloseIcon fontSize="small" /></IconButton></Tooltip>
              </Box>
            </Box>

            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              <TextField label="Tool Name" value={selectedTool.name || ''} onChange={(e) => updateSelectedTool({ name: e.target.value })} sx={{ mb: 1.5 }} helperText="Shown to LLM clients when listing available tools" />
              <TextField label="Description" multiline rows={2} value={selectedTool.description || ''} onChange={(e) => updateSelectedTool({ description: e.target.value })} sx={{ mb: 1.5 }} helperText="Helps the LLM decide when to use this tool" />

              {/* Feature 5: 4-factor quality breakdown. Sits above the
                  legacy confidence chip so users can see *both* the
                  grouping confidence (from the analyzer) and the
                  usability/security posture of the tool itself. */}
              {selectedTool.name !== 'custom_request' && (
                <Box sx={{ mb: 1.5 }}>
                  <ToolQualityBreakdown tool={selectedTool} endpointMap={endpointMap} />
                </Box>
              )}

              {/* Confidence + Schema */}
              <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                {selectedTool.name === 'custom_request' ? (
                  <Box>
                    <Typography variant="overline" color="text.secondary">Type</Typography>
                    <Box>
                      <Tooltip title="Built-in escape-hatch tool. Lets agents call arbitrary endpoints on this API by specifying method + path at call time — not tied to any specific operation.">
                        <Chip label="Built-in" color="default" variant="outlined" />
                      </Tooltip>
                    </Box>
                  </Box>
                ) : selectedTool.confidence != null && selectedTool.confidence > 0 ? (
                  <Box>
                    <Typography variant="overline" color="text.secondary">Confidence</Typography>
                    <Box><Chip label={`${Math.round(selectedTool.confidence * 100)}%`} color={selectedTool.confidence >= 0.8 ? 'success' : 'warning'} /></Box>
                  </Box>
                ) : null}
                {selectedTool.input_schema && Object.keys(selectedTool.input_schema).length > 0 && (
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="overline" color="text.secondary">Input Schema</Typography>
                    <Paper variant="outlined" sx={{ p: 1, maxHeight: 80, overflow: 'auto', bgcolor: 'grey.900' }}>
                      <Typography component="pre" sx={{ m: 0, fontFamily: 'monospace', fontSize: '0.625rem', color: '#d4d4d4', whiteSpace: 'pre-wrap' }}>
                        {JSON.stringify(selectedTool.input_schema, null, 2)}
                      </Typography>
                    </Paper>
                  </Box>
                )}
              </Box>

              <Divider sx={{ mb: 1.5 }} />

              {/* Assigned Endpoints */}
              <Typography variant="body2" fontWeight={600} sx={{ mb: 0.75 }}>Assigned Endpoints ({(selectedTool.covered_endpoints || []).length})</Typography>
              {(selectedTool.covered_endpoints || []).length > 0 ? (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1.5 }}>
                  {(selectedTool.covered_endpoints || []).map((id, i) => {
                    const ep = endpointMap[id];
                    return (
                      <Chip key={i} size="small" label={ep ? `${ep.method?.toUpperCase()} ${ep.path}` : id} onDelete={() => toggleEndpoint(id)}
                        sx={{ fontFamily: 'monospace', fontSize: '0.65rem', maxWidth: 260 }} />
                    );
                  })}
                </Box>
              ) : (
                <Alert severity="info" sx={{ mb: 1.5, py: 0 }}><Typography variant="caption">No endpoints assigned. Select from the catalog below.</Typography></Alert>
              )}

              {/* Endpoint Catalog */}
              <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>Endpoint Catalog ({endpointCatalog.length})</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.75, display: 'block' }}>Check endpoints to assign them to this tool</Typography>

              {endpointCatalog.length > 0 ? (
                <>
                  <TextField placeholder="Search endpoints..." value={epSearch} onChange={(e) => setEpSearch(e.target.value)} size="small" sx={{ mb: 1 }}
                    InputProps={{ startAdornment: <SearchIcon sx={{ mr: 0.5, color: 'text.disabled', fontSize: 18 }} /> }} />
                  <Paper variant="outlined" sx={{ maxHeight: 300, overflow: 'auto' }}>
                    <List dense disablePadding>
                      {filteredEps.map((ep, i) => {
                        const epId = ep.id || `${ep.method} ${ep.path}`;
                        const assigned = (selectedTool.covered_endpoints || []).includes(epId);
                        return (
                          <ListItemButton key={i} dense onClick={() => toggleEndpoint(epId)}
                            sx={{ py: 0.5, borderBottom: 1, borderColor: 'divider',
                              bgcolor: assigned ? (isDark ? 'rgba(34,197,94,.06)' : '#f0fdf4') : 'transparent' }}>
                            <ListItemIcon sx={{ minWidth: 28 }}>
                              <Checkbox size="small" edge="start" checked={assigned} tabIndex={-1} disableRipple sx={{ p: 0 }} />
                            </ListItemIcon>
                            <MethodChip method={ep.method} isDark={isDark} />
                            <ListItemText sx={{ ml: 0.75 }}
                              primary={<Typography variant="caption" sx={{ fontFamily: 'monospace' }} noWrap>{ep.path}</Typography>}
                              secondary={ep.summary ? <Typography variant="caption" color="text.secondary" noWrap sx={{ fontSize: '0.6rem' }}>{ep.summary}</Typography> : null} />
                          </ListItemButton>
                        );
                      })}
                    </List>
                  </Paper>
                </>
              ) : (
                <Alert severity="info" icon={<InfoOutlinedIcon />}><Typography variant="caption">Run analysis (Step 1) to load the endpoint catalog.</Typography></Alert>
              )}
            </Box>

            <Box sx={{ display: 'flex', justifyContent: 'space-between', px: 2, py: 1.25, borderTop: 1, borderColor: 'divider' }}>
              <Button size="small" onClick={() => setSelectedIndex(null)}>Close</Button>
              <Button variant="contained" size="small" startIcon={<SaveIcon />} onClick={handleSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
            </Box>
          </Paper>
        )}
      </Box>
    </Box>
  );
}

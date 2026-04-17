import React from 'react';
import { useState, useEffect, useRef, useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import ButtonGroup from '@mui/material/ButtonGroup';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Grid from '@mui/material/Grid';
import LinearProgress from '@mui/material/LinearProgress';
import CircularProgress from '@mui/material/CircularProgress';
import LogoLoader from '../../../components/LogoLoader';
import Alert from '@mui/material/Alert';
import Divider from '@mui/material/Divider';
import TextField from '@mui/material/TextField';
import FormControlLabel from '@mui/material/FormControlLabel';
import Switch from '@mui/material/Switch';
import Collapse from '@mui/material/Collapse';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Tooltip from '@mui/material/Tooltip';
import Accordion from '@mui/material/Accordion';
import AccordionSummary from '@mui/material/AccordionSummary';
import AccordionDetails from '@mui/material/AccordionDetails';
import InputAdornment from '@mui/material/InputAdornment';
import { useTheme, alpha } from '@mui/material/styles';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import BugReportOutlinedIcon from '@mui/icons-material/BugReportOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import BuildOutlinedIcon from '@mui/icons-material/BuildOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import SearchIcon from '@mui/icons-material/Search';
import ScoreOutlinedIcon from '@mui/icons-material/ScoreOutlined';
import SecurityOutlinedIcon from '@mui/icons-material/SecurityOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SecurityReport from '../../../components/SecurityReport';
import useStore from '../../../store/useStore';
import {
  fetchScans, createScan, fetchScan, fetchScanReport,
  applyRemediationFixes, applyAllRemediationFixes,
  checkScanPolicy,
} from '../../../api';

// ── helpers ────────────────────────────────────────────────────────────────────
function getSeverityColor(s) {
  const level = (s || 'info').toLowerCase();
  if (level === 'critical' || level === 'high') return 'error';
  if (level === 'medium') return 'warning';
  if (level === 'low') return 'info';
  return 'default';
}

function getStatusColor(status) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'running' || status === 'pending') return 'warning';
  return 'default';
}

function findingSeverity(f) {
  return ((f.severity || f.risk_level || 'info') + '').toLowerCase();
}

// ── sub-components ────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, sub, color, valueColor }) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent sx={{ textAlign: 'center', py: 2.25, px: 1.5, '&:last-child': { pb: 2.25 } }}>
        {Icon && <Icon sx={{ fontSize: 22, color: color || 'text.secondary', mb: 1, display: 'block', mx: 'auto' }} />}
        <Typography
          variant="h4"
          fontWeight={700}
          sx={{ lineHeight: 1, mb: 0.5, letterSpacing: '-0.02em', color: valueColor || 'text.primary' }}
        >
          {value}
        </Typography>
        <Typography
          variant="overline"
          color="text.secondary"
          sx={{ fontSize: '0.6rem', letterSpacing: '0.08em', lineHeight: 1.6, display: 'block' }}
        >
          {label}
        </Typography>
        {sub && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
            {sub}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

// ── main component ────────────────────────────────────────────────────────────
export default function ScanStep({ integration, onReload }) {
  const toast = useStore((s) => s.toast);
  const theme = useTheme();

  const [scan, setScan] = useState(null);
  const [loadingInit, setLoadingInit] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [remediating, setRemediating] = useState(false);

  // Scan options form
  const [showOptions, setShowOptions] = useState(false);
  const [scanName, setScanName] = useState(`${integration.name} Security Scan`);
  const [scanSource, setScanSource] = useState(integration.spec || '');
  const [fullMode, setFullMode] = useState(false);
  const [useSemgrep, setUseSemgrep] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const [nameError, setNameError] = useState('');
  const [sourceError, setSourceError] = useState('');

  // Policy compliance
  const [policyResult, setPolicyResult] = useState(null);

  // Results tabs + findings filter
  const [resultsTab, setResultsTab] = useState(0);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [findingSearch, setFindingSearch] = useState('');

  const pollRef = useRef(null);
  const completedRef = useRef(false);

  // Memoised severity counts
  const severityCounts = useMemo(() => {
    const list = scan?.findings || scan?.vulnerabilities || [];
    const out = { all: list.length, critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    list.forEach((f) => {
      const sev = findingSeverity(f);
      if (out[sev] !== undefined) out[sev] += 1;
    });
    return out;
  }, [scan]);

  // Memoised filtered findings
  const filteredFindings = useMemo(() => {
    const list = scan?.findings || scan?.vulnerabilities || [];
    const q = findingSearch.trim().toLowerCase();
    return list.filter((f) => {
      if (severityFilter !== 'all' && findingSeverity(f) !== severityFilter) return false;
      if (!q) return true;
      const haystack = `${f.title || ''} ${f.description || ''} ${f.endpoint || ''}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [scan, severityFilter, findingSearch]);

  // ── on mount: find the most recent scan for this integration ─
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchScans();
        const all = res.scans || res || [];
        const match = all.find((s) =>
          s.name?.toLowerCase().includes(integration.name.toLowerCase())
        );
        if (match) {
          const detail = await fetchScan(match.scan_id || match.id);
          setScan(detail);
          // Load policy check
          if (detail.status === 'completed' || detail.status === 'policy_violation') {
            checkScanPolicy(match.scan_id || match.id).then(setPolicyResult).catch(() => {});
          }
        }
      } catch { /* no scans yet */ }
      finally { setLoadingInit(false); }
    })();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [integration.id, integration.name]);

  // ── validation ─────────────────────────────────────────────────────────────
  function validate() {
    let ok = true;
    if (!scanName.trim()) { setNameError('Scan name is required'); ok = false; }
    else setNameError('');
    if (!scanSource.trim()) { setSourceError('Source URL or path is required'); ok = false; }
    else setSourceError('');
    return ok;
  }

  // ── start scan ─────────────────────────────────────────────────────────────
  async function handleStartScan(overrides) {
    const name = overrides?.name ?? scanName;
    const source = overrides?.source ?? scanSource;
    if (!overrides && !validate()) return;
    setShowOptions(false);
    setScanning(true);
    setProgress('Initialising security scan...');
    completedRef.current = false;
    try {
      const res = await createScan({
        name: name.trim(),
        source: source.trim(),
        description: `Security scan for ${integration.name} integration`,
        full_mode: fullMode,
        use_semgrep: useSemgrep,
        use_llm: useLlm,
      });
      const scanId = res.scan_id || res.id;
      toast('Security scan started');

      pollRef.current = setInterval(async () => {
        if (completedRef.current) return;
        try {
          const detail = await fetchScan(scanId);
          if (completedRef.current) return;
          const pct = detail.progress_percent;
          setProgress(
            detail.current_step
              ? `${detail.current_step}${pct != null ? ` (${pct}%)` : ''}...`
              : (detail.status === 'running' ? 'Scanning...' : detail.status)
          );
          if (detail.status === 'completed' || detail.status === 'failed' || detail.status === 'policy_violation') {
            completedRef.current = true;
            clearInterval(pollRef.current);
            pollRef.current = null;
            setScanning(false);
            setProgress(null);
            setScan(detail);
            setSeverityFilter('all');
            setFindingSearch('');
            toast(
              detail.status === 'completed' ? 'Scan completed' : detail.status === 'policy_violation' ? 'Scan completed — policy violations found' : 'Scan failed',
              detail.status === 'completed' ? '' : 'error',
            );
            // Check policy compliance
            if (detail.status === 'completed' || detail.status === 'policy_violation') {
              checkScanPolicy(scanId).then(setPolicyResult).catch(() => {});
            }
          }
        } catch {
          if (completedRef.current) return;
          completedRef.current = true;
          clearInterval(pollRef.current);
          pollRef.current = null;
          setScanning(false);
          setProgress(null);
        }
      }, 3000);
    } catch (err) {
      setScanning(false);
      setProgress(null);
      toast(typeof err === 'string' ? err : err?.message || 'Scan failed to start', 'error');
    }
  }

  function handleRescan() {
    const name = scan?.name || `${integration.name} Security Scan`;
    const source = scan?.source || integration.spec || '';
    setScanName(name);
    setScanSource(source);
    handleStartScan({ name, source });
  }

  async function handleApplyAll() {
    if (!scan) return;
    setRemediating(true);
    try {
      const id = scan.scan_id || scan.id;
      await applyAllRemediationFixes(id);
      toast('All fixes applied');
      const detail = await fetchScan(id);
      setScan(detail);
    } catch (err) {
      toast(typeof err === 'string' ? err : err?.message || 'Apply failed', 'error');
    } finally {
      setRemediating(false);
    }
  }

  async function handleApplyFix(fixId) {
    if (!scan) return;
    const id = scan.scan_id || scan.id;
    try {
      await applyRemediationFixes(id, [fixId]);
      toast('Fix applied');
      const detail = await fetchScan(id);
      setScan(detail);
    } catch (err) {
      toast(typeof err === 'string' ? err : err?.message || 'Apply failed', 'error');
    }
  }

  const findings = scan?.findings || scan?.vulnerabilities || [];
  const fixes = scan?.fixes || scan?.suggested_fixes || scan?.remediation || [];
  const criticalHigh = (severityCounts?.critical || 0) + (severityCounts?.high || 0);
  const isClean = scan?.status === 'completed' && findings.length === 0;
  const selectedScanId = scan?.scan_id || scan?.id;

  // ── loading ────────────────────────────────────────────────────────────────
  if (loadingInit) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 220 }}>
        <LogoLoader size={72} message="Loading scan..." />
      </Box>
    );
  }

  return (
    <Box>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 2.5, gap: 2 }}>
        <Box>
          <Typography variant="h6" fontWeight={700}>Security Scanning</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            Scan your integration for security vulnerabilities and get automated fix suggestions.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, flexShrink: 0 }}>
          <Button
            variant="outlined"
            size="small"
            startIcon={<TuneOutlinedIcon />}
            onClick={() => setShowOptions((v) => !v)}
            sx={{ borderRadius: 5 }}
          >
            Options
          </Button>
          <Button
            variant="contained"
            size="small"
            startIcon={scanning ? <CircularProgress size={12} color="inherit" /> : <ShieldOutlinedIcon />}
            onClick={scan ? handleRescan : handleStartScan}
            disabled={scanning}
            sx={{ borderRadius: 5, fontWeight: 600 }}
          >
            {scanning ? 'Scanning...' : (scan ? 'Re-scan' : 'Run Scan')}
          </Button>
        </Box>
      </Box>

      {/* ── Collapsible scan options ───────────────────────────────────────── */}
      <Collapse in={showOptions}>
        <Paper variant="outlined" sx={{ p: 2, mb: 2.5, bgcolor: alpha(theme.palette.primary.main, 0.03) }}>
          <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1.5 }}>Scan Configuration</Typography>
          <Stack spacing={1.5}>
            <TextField
              fullWidth size="small" label="Scan Name *"
              value={scanName}
              onChange={(e) => { setScanName(e.target.value); setNameError(''); }}
              error={!!nameError}
              helperText={nameError || 'A label to identify this scan run'}
            />
            <TextField
              fullWidth size="small" label="Source *"
              value={scanSource}
              onChange={(e) => { setScanSource(e.target.value); setSourceError(''); }}
              error={!!sourceError}
              helperText={sourceError || 'OpenAPI spec URL, local path, or GitHub URL to scan'}
              placeholder="https://api.example.com/openapi.json"
            />
            <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
              <FormControlLabel
                control={<Switch size="small" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />}
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <AutoAwesomeOutlinedIcon sx={{ fontSize: 14, color: useLlm ? 'primary.main' : 'text.disabled' }} />
                    <Typography variant="body2">LLM Analysis</Typography>
                    <Chip label="Recommended" size="small" color="success" sx={{ height: 16, fontSize: '0.58rem' }} />
                  </Box>
                }
              />
              <Tooltip title="Run static code pattern analysis to detect common vulnerability patterns in source code" arrow placement="top">
                <FormControlLabel
                  control={<Switch size="small" checked={useSemgrep} onChange={(e) => setUseSemgrep(e.target.checked)} />}
                  label={<Typography variant="body2">Code Pattern Analysis</Typography>}
                />
              </Tooltip>
              <Tooltip title="Deep dependency & container scan — checks for known CVEs in packages, Docker images, and infrastructure configs" arrow placement="top">
                <FormControlLabel
                  control={<Switch size="small" checked={fullMode} onChange={(e) => setFullMode(e.target.checked)} />}
                  label={<Typography variant="body2">Deep Dependency Scan</Typography>}
                />
              </Tooltip>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button size="small" onClick={() => setShowOptions(false)}>Cancel</Button>
              <Button
                size="small"
                variant="contained"
                startIcon={<ShieldOutlinedIcon />}
                onClick={handleStartScan}
                disabled={scanning}
                sx={{ borderRadius: 5 }}
              >
                Start Scan
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Collapse>

      {/* ── Progress ───────────────────────────────────────────────────────── */}
      {progress && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2.5, bgcolor: alpha(theme.palette.primary.main, 0.04) }}>
          <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />
          <Typography variant="body2" color="text.secondary">{progress}</Typography>
        </Paper>
      )}

      {/* ── Empty state — no scan yet ──────────────────────────────────────── */}
      {!scan && !scanning && (
        <Paper variant="outlined" sx={{
          p: 5, textAlign: 'center',
          borderStyle: 'dashed',
          borderColor: alpha(theme.palette.text.secondary, 0.2),
        }}>
          <Box sx={{
            width: 60, height: 60, borderRadius: '50%',
            bgcolor: alpha(theme.palette.warning.main, 0.1),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            mx: 'auto', mb: 2,
          }}>
            <ShieldOutlinedIcon sx={{ fontSize: 30, color: 'warning.main' }} />
          </Box>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.75 }}>No scan run yet</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5, maxWidth: 380, mx: 'auto' }}>
            Run a security scan to detect vulnerabilities, misconfigurations, and compliance issues in your API integration.
          </Typography>
          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1, flexWrap: 'wrap', mb: 3 }}>
            {['Vulnerability Detection', 'Risk Scoring', 'Auto-Remediation', 'Compliance Check'].map((cap) => (
              <Chip key={cap} label={cap} size="small" variant="outlined" sx={{ fontSize: '0.7rem' }} />
            ))}
          </Box>
          <Button
            variant="contained"
            startIcon={<ShieldOutlinedIcon />}
            onClick={() => { setShowOptions(true); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            sx={{ borderRadius: 5, fontWeight: 600 }}
          >
            Configure &amp; Run Scan
          </Button>
        </Paper>
      )}

      {/* ── Scan results ──────────────────────────────────────────────────── */}
      {scan && (
        <Stack spacing={2}>

          {/* ── Stat cards (Dashboard aesthetic) ── */}
          <Grid container spacing={1.5}>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                icon={ScoreOutlinedIcon}
                label="Score"
                value={scan.overall_score ?? '—'}
                sub="overall quality"
                color="#3b82f6"
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                icon={SecurityOutlinedIcon}
                label="Risk Level"
                value={(scan.risk_level || 'info').replace(/^./, (c) => c.toUpperCase())}
                sub="assessed severity"
                color={
                  scan.risk_level === 'critical' || scan.risk_level === 'high'
                    ? theme.palette.error.main
                    : scan.risk_level === 'medium'
                      ? theme.palette.warning.main
                      : theme.palette.success.main
                }
                valueColor={
                  scan.risk_level === 'critical' || scan.risk_level === 'high'
                    ? theme.palette.error.main
                    : scan.risk_level === 'medium'
                      ? theme.palette.warning.main
                      : undefined
                }
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                icon={BugReportOutlinedIcon}
                label="Findings"
                value={findings.length}
                sub="issues detected"
                color="#8b5cf6"
                valueColor={findings.length > 0 ? theme.palette.error.main : undefined}
              />
            </Grid>
            <Grid item xs={6} sm={4} md={2.4}>
              <StatCard
                icon={WarningAmberOutlinedIcon}
                label="Critical / High"
                value={criticalHigh}
                sub="urgent issues"
                color="#ef4444"
                valueColor={criticalHigh > 0 ? theme.palette.error.main : undefined}
              />
            </Grid>
            <Grid item xs={12} sm={4} md={2.4}>
              <StatCard
                icon={BuildOutlinedIcon}
                label="Fixes"
                value={fixes.length}
                sub="suggested remediations"
                color="#16a34a"
                valueColor={fixes.length > 0 ? theme.palette.success.main : undefined}
              />
            </Grid>
          </Grid>

          {/* ── Policy compliance ── */}
          {policyResult && policyResult.passed !== null && (
            <Alert
              severity={policyResult.passed ? 'success' : 'error'}
              sx={{ borderRadius: 2 }}
            >
              <Typography variant="body2" fontWeight={600}>
                {policyResult.passed ? 'Policy Check Passed' : 'Policy Check Failed'}
              </Typography>
              {policyResult.violations && policyResult.violations.length > 0 && (
                <Box component="ul" sx={{ m: 0, pl: 2, mt: 0.5 }}>
                  {policyResult.violations.map((v, i) => (
                    <li key={i}><Typography variant="caption">{v}</Typography></li>
                  ))}
                </Box>
              )}
            </Alert>
          )}

          {/* ── Source + download row ── */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0, flex: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{
                textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, flexShrink: 0,
              }}>
                Source
              </Typography>
              <Tooltip title={scan.source || ''} placement="top">
                <Typography
                  variant="caption"
                  noWrap
                  sx={{ fontFamily: 'monospace', fontSize: '0.72rem', color: 'text.secondary', minWidth: 0 }}
                >
                  {scan.source || '—'}
                </Typography>
              </Tooltip>
            </Box>
            {selectedScanId && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
                <DownloadOutlinedIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                <Typography variant="caption" color="text.secondary" sx={{
                  textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700,
                }}>
                  Report
                </Typography>
                <ButtonGroup size="small" variant="outlined">
                  {['json', 'markdown', 'spdx', 'pdf'].map((fmt) => (
                    <Button
                      key={fmt}
                      component="a"
                      href={fetchScanReport(selectedScanId, fmt)}
                      download
                    >
                      {fmt === 'spdx' ? 'SPDX' : fmt.toUpperCase()}
                    </Button>
                  ))}
                </ButtonGroup>
              </Box>
            )}
          </Box>

          {/* ── Tab switcher: Security Report vs Findings ── */}
          <Paper variant="outlined" sx={{ px: 1 }}>
            <Tabs
              value={resultsTab}
              onChange={(_, v) => setResultsTab(v)}
              sx={{ minHeight: 40, '& .MuiTab-root': { minHeight: 40, textTransform: 'none', fontSize: '0.82rem', fontWeight: 600 } }}
            >
              <Tab
                icon={<ShieldOutlinedIcon fontSize="small" />}
                iconPosition="start"
                label="Security Report"
              />
              <Tab
                icon={<BugReportOutlinedIcon fontSize="small" />}
                iconPosition="start"
                label={`Findings (${findings.length})`}
              />
            </Tabs>
          </Paper>

          {/* ── Tab 0: OWASP Security Report ── */}
          {resultsTab === 0 && (
            <SecurityReport scan={scan} />
          )}

          {/* ── Tab 1: All clear ── */}
          {resultsTab === 1 && isClean && (
            <Alert severity="success" icon={<CheckCircleOutlineIcon />}>
              <Typography variant="body2" fontWeight={600}>No security vulnerabilities found.</Typography>
              <Typography variant="caption">Your integration passed the security scan successfully.</Typography>
            </Alert>
          )}

          {/* ── Tab 1: Findings — accordion list with severity filter + search ── */}
          {resultsTab === 1 && findings.length > 0 && (
            <Paper variant="outlined">
              {/* Header */}
              <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', gap: 1, borderBottom: 1, borderColor: 'divider', flexWrap: 'wrap' }}>
                <BugReportOutlinedIcon sx={{ fontSize: 16, color: 'error.main' }} />
                <Typography variant="subtitle2" fontWeight={700}>Findings</Typography>
                <Chip
                  label={`${filteredFindings.length} of ${findings.length}`}
                  size="small"
                  color="error"
                  sx={{ fontWeight: 700, height: 18, fontSize: '0.68rem' }}
                />
              </Box>

              {/* Filter bar */}
              <Box sx={{
                px: 2, py: 1.25,
                borderBottom: 1, borderColor: 'divider',
                bgcolor: 'background.paper',
                display: 'flex', flexDirection: 'column', gap: 1,
              }}>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  {[
                    { id: 'all',      label: 'All',      color: 'default' },
                    { id: 'critical', label: 'Critical', color: 'error' },
                    { id: 'high',     label: 'High',     color: 'error' },
                    { id: 'medium',   label: 'Medium',   color: 'warning' },
                    { id: 'low',      label: 'Low',      color: 'info' },
                    { id: 'info',     label: 'Info',     color: 'default' },
                  ].map((bucket) => {
                    const count = severityCounts[bucket.id] ?? 0;
                    if (bucket.id !== 'all' && count === 0) return null;
                    const active = severityFilter === bucket.id;
                    return (
                      <Chip
                        key={bucket.id}
                        size="small"
                        clickable
                        label={`${bucket.label} ${count}`}
                        color={active ? (bucket.color === 'default' ? 'primary' : bucket.color) : 'default'}
                        variant={active ? 'filled' : 'outlined'}
                        onClick={() => setSeverityFilter(bucket.id)}
                        sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600 }}
                      />
                    );
                  })}
                </Stack>
                <TextField
                  size="small"
                  fullWidth
                  placeholder="Filter findings by title, description, or endpoint..."
                  value={findingSearch}
                  onChange={(e) => setFindingSearch(e.target.value)}
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <SearchIcon fontSize="small" />
                      </InputAdornment>
                    ),
                  }}
                  sx={{ '& input': { fontSize: '0.8rem', py: 0.75 } }}
                />
              </Box>

              {/* Scrollable findings list — collapsible accordions */}
              <Box sx={{ maxHeight: 520, overflow: 'auto' }}>
                {filteredFindings.length === 0 ? (
                  <Box sx={{ p: 4, textAlign: 'center' }}>
                    <Typography variant="body2" color="text.secondary" fontWeight={600}>
                      No findings match the current filter
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                      Try clearing the search or selecting a different severity.
                    </Typography>
                  </Box>
                ) : (
                  filteredFindings.map((f, i) => {
                    const sev = findingSeverity(f);
                    const sevColor = getSeverityColor(sev);
                    const borderColor = sevColor === 'error'
                      ? theme.palette.error.main
                      : sevColor === 'warning'
                        ? theme.palette.warning.main
                        : sevColor === 'info'
                          ? theme.palette.info.main
                          : theme.palette.divider;
                    return (
                      <Accordion
                        key={f.id || i}
                        disableGutters
                        square
                        elevation={0}
                        sx={{
                          borderLeft: `3px solid ${borderColor}`,
                          borderBottom: 1,
                          borderColor: 'divider',
                          '&:last-of-type': { borderBottom: 0 },
                          '&:before': { display: 'none' },
                          bgcolor: 'transparent',
                        }}
                      >
                        <AccordionSummary
                          expandIcon={<ExpandMoreIcon fontSize="small" />}
                          sx={{ px: 2, '& .MuiAccordionSummary-content': { my: 1, alignItems: 'center', gap: 1 } }}
                        >
                          <Chip
                            label={sev}
                            size="small"
                            color={sevColor === 'default' ? undefined : sevColor}
                            sx={{ textTransform: 'capitalize', fontWeight: 600, height: 18, fontSize: '0.65rem', flexShrink: 0 }}
                          />
                          <Typography
                            variant="body2"
                            fontWeight={600}
                            sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          >
                            {f.title || f.rule || f.id}
                          </Typography>
                          {f.endpoint && (
                            <Typography
                              variant="caption"
                              color="text.disabled"
                              sx={{ fontFamily: 'monospace', fontSize: '0.68rem', flexShrink: 0, display: { xs: 'none', sm: 'block' } }}
                            >
                              {f.endpoint}
                            </Typography>
                          )}
                        </AccordionSummary>
                        <AccordionDetails sx={{ px: 2, pt: 0, pb: 1.5 }}>
                          {f.description && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', whiteSpace: 'pre-wrap', mb: f.endpoint ? 0.75 : 0 }}>
                              {f.description}
                            </Typography>
                          )}
                          {f.endpoint && (
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.7rem', color: 'text.disabled', display: 'block' }}>
                              {f.endpoint}
                            </Typography>
                          )}
                          {Array.isArray(f.tags) && f.tags.length > 0 && (
                            <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                              {f.tags.map((t) => (
                                <Chip key={t} label={t} size="small" variant="outlined" sx={{ height: 16, fontSize: '0.62rem' }} />
                              ))}
                            </Stack>
                          )}
                        </AccordionDetails>
                      </Accordion>
                    );
                  })
                )}
              </Box>
            </Paper>
          )}

          {/* ── Tab 1: Remediation ── */}
          {resultsTab === 1 && fixes.length > 0 && (() => {
            const isPatchable = (f) => Boolean(f.patch || f.diff_patch);
            const patchableFixes = fixes.filter(isPatchable);
            const showBulkApply = patchableFixes.some((f) => !f.applied);

            return (
              <Paper variant="outlined">
                <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: 1, borderColor: 'divider', flexWrap: 'wrap', gap: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <BuildOutlinedIcon sx={{ fontSize: 16, color: 'success.main' }} />
                    <Typography variant="subtitle2" fontWeight={700}>Suggested Remediations</Typography>
                    <Chip
                      label={`${fixes.length} ${fixes.length === 1 ? 'item' : 'items'}`}
                      size="small"
                      sx={{ height: 18, fontSize: '0.68rem' }}
                    />
                    {patchableFixes.length === 0 && (
                      <Tooltip title="These are guidance-only — auto-apply requires a local code source where the LLM judge can generate a unified diff.">
                        <Chip
                          label="guidance"
                          size="small"
                          variant="outlined"
                          sx={{ height: 18, fontSize: '0.6rem' }}
                        />
                      </Tooltip>
                    )}
                  </Box>
                  {showBulkApply && (
                    <Button
                      variant="contained" size="small" color="success"
                      startIcon={remediating ? <CircularProgress size={12} color="inherit" /> : <CheckCircleOutlineIcon />}
                      onClick={handleApplyAll}
                      disabled={remediating}
                      sx={{ borderRadius: 4 }}
                    >
                      {remediating ? 'Applying...' : 'Apply All Patches'}
                    </Button>
                  )}
                </Box>
                <Stack divider={<Divider />}>
                  {fixes.map((fix, i) => {
                    const patchable = isPatchable(fix);
                    return (
                      <Box key={i} sx={{ px: 2, py: 1.5 }}>
                        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 1, mb: fix.instructions ? 0.75 : 0 }}>
                          <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Typography variant="body2" fontWeight={600}>
                              {fix.title || fix.description || `Fix ${i + 1}`}
                            </Typography>
                            {fix.description && fix.description !== fix.title && (
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                {fix.description}
                              </Typography>
                            )}
                          </Box>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
                            <Chip
                              label={fix.applied ? 'Applied' : (patchable ? 'Pending' : 'Manual')}
                              color={fix.applied ? 'success' : 'default'}
                              size="small"
                              icon={fix.applied ? <CheckCircleOutlineIcon /> : <WarningAmberOutlinedIcon />}
                              sx={{ height: 20, fontSize: '0.68rem' }}
                            />
                            {patchable && !fix.applied && (
                              <Button
                                variant="outlined" size="small" color="success"
                                onClick={() => handleApplyFix(fix.id || fix.fix_id || fix.finding_id || i)}
                                sx={{ borderRadius: 4 }}
                              >
                                Apply
                              </Button>
                            )}
                          </Box>
                        </Box>
                        {fix.instructions && (
                          <Box
                            component="pre"
                            sx={{
                              m: 0,
                              mt: 0.5,
                              p: 1.25,
                              bgcolor: 'action.hover',
                              borderRadius: 1,
                              fontFamily: 'inherit',
                              fontSize: '0.75rem',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              color: 'text.secondary',
                            }}
                          >
                            {fix.instructions}
                          </Box>
                        )}
                      </Box>
                    );
                  })}
                </Stack>
              </Paper>
            );
          })()}
        </Stack>
      )}
    </Box>
  );
}

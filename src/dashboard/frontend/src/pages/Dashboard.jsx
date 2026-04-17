import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Divider from '@mui/material/Divider';
import Tooltip from '@mui/material/Tooltip';
import Avatar from '@mui/material/Avatar';
import Button from '@mui/material/Button';
import LogoLoader from '../components/LogoLoader';
import GetStartedGuide from '../components/GetStartedGuide';
import { alpha, useTheme } from '@mui/material/styles';
import AutoGraphOutlinedIcon from '@mui/icons-material/AutoGraphOutlined';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import RuleFolderOutlinedIcon from '@mui/icons-material/RuleFolderOutlined';
import CheckCircleOutlineRoundedIcon from '@mui/icons-material/CheckCircleOutlineRounded';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import useStore from '../store/useStore';
import { fetchDashboard, fetchScans, fetchLlmConfigs } from '../api';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';

function formatDateTime(iso) {
  if (!iso) return '--';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatRelative(iso) {
  if (!iso) return 'No runs yet';
  const deltaMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.max(1, Math.round(deltaMs / 60000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function formatPercent(value) {
  if (value == null) return '--';
  return `${Math.round(value * 100)}%`;
}

function isHealthyStatus(status) {
  return status === 'ok' || status === 'completed';
}

function numericAverage(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function scoreTone(score) {
  if (score == null) return { label: 'No score yet', color: 'default' };
  if (score >= 85) return { label: 'Excellent', color: 'success' };
  if (score >= 70) return { label: 'Strong', color: 'primary' };
  if (score >= 55) return { label: 'Needs tuning', color: 'warning' };
  return { label: 'At risk', color: 'error' };
}

function statusTone(status) {
  if (isHealthyStatus(status)) {
    return { label: 'Healthy', color: 'success', icon: CheckCircleOutlineRoundedIcon };
  }
  if (status === 'failed') {
    return { label: 'Failed', color: 'error', icon: ErrorOutlineRoundedIcon };
  }
  return { label: status || 'Pending', color: 'default', icon: ScheduleRoundedIcon };
}

function buildFallbackIntegrations(recentRuns) {
  const byIntegration = new Map();

  recentRuns.forEach((run) => {
    const key = run.integration_id || run.integration_name || run.spec || run.run_id;
    if (!key) return;

    const current = byIntegration.get(key);
    const currentRunId = current?.last_run_id || '';
    const nextRunId = run.run_id || '';
    const isNewer = !current || nextRunId > currentRunId;

    const nextWarnings = run.warnings || [];
    const summary = current || {
      id: run.integration_id || key,
      name: run.integration_name || run.integration_id || 'Unnamed integration',
      spec: run.spec || null,
      run_count: 0,
      successful_runs: 0,
      failed_runs: 0,
      warning_runs: 0,
      warning_count: 0,
      last_run_id: null,
      last_run_at: null,
      last_run_status: null,
      latest_score: null,
      latest_tool_count: null,
      latest_endpoint_count: null,
      latest_coverage: null,
      latest_compression_ratio: null,
      latest_warnings: [],
    };

    summary.run_count += 1;
    if (isHealthyStatus(run.status)) summary.successful_runs += 1;
    if (run.status === 'failed') summary.failed_runs += 1;
    if (nextWarnings.length > 0) summary.warning_runs += 1;
    summary.warning_count += nextWarnings.length;

    if (isNewer) {
      summary.last_run_id = run.run_id || null;
      summary.last_run_at = run.created_at || null;
      summary.last_run_status = run.status || null;
      summary.latest_score = run.score ?? null;
      summary.latest_tool_count = run.tool_count ?? null;
      summary.latest_endpoint_count = run.endpoint_count ?? null;
      summary.latest_coverage = run.coverage ?? null;
      summary.latest_compression_ratio = run.compression_ratio ?? null;
      summary.latest_warnings = nextWarnings;
    }

    byIntegration.set(key, summary);
  });

  return Array.from(byIntegration.values()).sort((a, b) => {
    const aRun = a.last_run_id || '';
    const bRun = b.last_run_id || '';
    return bRun.localeCompare(aRun);
  });
}

function buildFallbackActivity(recentRuns, days = 14) {
  const today = new Date();
  const buckets = [];

  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const day = new Date(today);
    day.setDate(today.getDate() - offset);
    const key = day.toISOString().slice(0, 10);
    buckets.push({
      date: key,
      label: day.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      runs: 0,
      successful_runs: 0,
      failed_runs: 0,
      warning_runs: 0,
    });
  }

  const byDate = new Map(buckets.map((item) => [item.date, item]));
  recentRuns.forEach((run) => {
    const key = (run.created_at || '').slice(0, 10);
    const bucket = byDate.get(key);
    if (!bucket) return;
    bucket.runs += 1;
    if (isHealthyStatus(run.status)) bucket.successful_runs += 1;
    if (run.status === 'failed') bucket.failed_runs += 1;
    if ((run.warnings || []).length > 0) bucket.warning_runs += 1;
  });

  return buckets;
}

function SectionHeader({ eyebrow, title, description, action }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 2, mb: 1.25 }}>
      <Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.25 }}>
          {eyebrow}
        </Typography>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.35 }}>
          {title}
        </Typography>
        {description && (
          <Typography variant="caption" color="text.secondary">
            {description}
          </Typography>
        )}
      </Box>
      {action}
    </Box>
  );
}

function MetricCard({ icon: Icon, label, value, subtitle, tint }) {
  return (
    <Card
      sx={{
        height: '100%',
        borderRadius: 2,
        borderColor: (theme) => alpha(theme.palette.text.primary, theme.palette.mode === 'dark' ? 0.12 : 0.08),
        backgroundColor: 'background.paper',
      }}
    >
      <CardContent sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.25 }}>
          <Avatar sx={{ bgcolor: alpha(tint, 0.12), color: tint, width: 34, height: 34 }}>
            <Icon sx={{ fontSize: 18 }} />
          </Avatar>
        </Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.25 }}>
          {label}
        </Typography>
        <Typography variant="h5" fontWeight={700} sx={{ lineHeight: 1.15 }}>
          {value}
        </Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

function ActivityBars({ activity, color }) {
  const maxRuns = Math.max(...activity.map((item) => item.runs || 0), 1);

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(14, minmax(0, 1fr))', gap: 1, alignItems: 'end', minHeight: 220 }}>
      {activity.map((item) => {
        const height = item.runs ? Math.max(22, (item.runs / maxRuns) * 156) : 8;
        return (
          <Tooltip
            key={item.date}
            title={`${item.label}: ${item.runs} runs, ${item.successful_runs} healthy, ${item.failed_runs} failed, ${item.warning_runs} with quality warnings`}
            arrow
          >
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
              <Box
                sx={{
                  width: '100%',
                  maxWidth: 28,
                  height,
                  borderRadius: 999,
                  background: (theme) => item.runs
                    ? `linear-gradient(180deg, ${alpha(color, theme.palette.mode === 'dark' ? 0.95 : 0.85)} 0%, ${alpha(color, 0.32)} 100%)`
                    : alpha(theme.palette.text.primary, theme.palette.mode === 'dark' ? 0.12 : 0.08),
                  border: (theme) => `1px solid ${item.runs ? alpha(color, 0.25) : alpha(theme.palette.text.primary, 0.08)}`,
                }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.62rem' }}>
                {item.label.split(' ')[1]}
              </Typography>
            </Box>
          </Tooltip>
        );
      })}
    </Box>
  );
}

function IntegrationHealthRow({ integration }) {
  const tone = scoreTone(integration.latest_score);
  const status = statusTone(integration.last_run_status);
  const StatusIcon = status.icon;
  const warnings = integration.latest_warnings || [];
  const warningLabel = warnings.length === 1 ? '1 quality warning' : `${warnings.length} quality warnings`;

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: '1.4fr 0.7fr 0.8fr 0.9fr 0.8fr' },
        gap: 1.5,
        alignItems: 'center',
        py: 1.5,
      }}
    >
      <Box sx={{ minWidth: 0, overflow: 'hidden' }}>
        <Tooltip arrow title={integration.name || ''} disableInteractive>
          <Typography
            variant="subtitle2"
            noWrap
            sx={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {integration.name}
          </Typography>
        </Tooltip>
        <Tooltip arrow title={integration.spec || 'Spec unavailable'} disableInteractive>
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            sx={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {integration.spec || 'Spec unavailable'}
          </Typography>
        </Tooltip>
      </Box>
      <Box>
        <Typography variant="body2" fontWeight={700}>
          {integration.latest_score ?? '--'}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {tone.label}
        </Typography>
      </Box>
      <Box>
        <Typography variant="body2" fontWeight={700}>
          {formatPercent(integration.latest_coverage)}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {integration.latest_tool_count ?? 0} tools / {integration.latest_endpoint_count ?? 0} endpoints
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
        <Chip size="small" color={status.color} icon={<StatusIcon />} label={status.label} />
        {warnings.length > 0 && (
          <Tooltip
            arrow
            title={
              <Box sx={{ py: 0.5 }}>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.75 }}>
                  These warnings come from the quality scoring pipeline.
                </Typography>
                {warnings.map((warning) => (
                  <Typography key={warning} variant="caption" sx={{ display: 'block' }}>
                    - {warning}
                  </Typography>
                ))}
              </Box>
            }
          >
            <Chip size="small" color="warning" variant="outlined" label={warningLabel} />
          </Tooltip>
        )}
      </Box>
      <Box sx={{ textAlign: { xs: 'left', md: 'right' } }}>
        <Typography variant="body2" fontWeight={600}>
          {formatRelative(integration.last_run_at)}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {integration.run_count} total runs
        </Typography>
      </Box>
    </Box>
  );
}

/**
 * Colors for scan risk levels. Mirrors the palette used in the Scanner
 * page's SecurityReport component so the two views feel coherent.
 */
const RISK_TONE = {
  critical: { label: 'Critical', color: '#dc2626' },
  high:     { label: 'High',     color: '#ea580c' },
  medium:   { label: 'Medium',   color: '#ca8a04' },
  low:      { label: 'Low',      color: '#2563eb' },
  info:     { label: 'Info',     color: '#6b7280' },
  clean:    { label: 'Clean',    color: '#10b981' },
};

function riskTone(scan) {
  const rl = (scan.risk_level || '').toLowerCase();
  if (rl && RISK_TONE[rl]) return RISK_TONE[rl];
  if ((scan.findings_count || 0) === 0 && scan.status === 'completed') return RISK_TONE.clean;
  return RISK_TONE.info;
}

/**
 * One row in the "Recent scans" card. Clicking navigates to the Scanner
 * page — we write the scan id to localStorage under the same key the
 * Scanner uses to restore its last selection, so the destination page
 * auto-opens the correct scan.
 */
function RecentScanRow({ scan, onOpen }) {
  const tone = riskTone(scan);
  const count = scan.findings_count || 0;
  const isRunning = scan.status && scan.status !== 'completed' && scan.status !== 'failed';

  return (
    <Box
      onClick={() => onOpen(scan)}
      sx={{
        py: 1.25,
        px: 0.5,
        display: 'flex',
        alignItems: 'center',
        gap: 1.25,
        cursor: 'pointer',
        borderRadius: 1,
        '&:hover': { bgcolor: (t) => alpha(t.palette.primary.main, t.palette.mode === 'dark' ? 0.08 : 0.04) },
      }}
    >
      <Box
        sx={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          bgcolor: tone.color,
          flexShrink: 0,
        }}
      />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography variant="body2" fontWeight={600} noWrap>
          {scan.name || scan.id}
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
          {scan.source || '—'} · {formatRelative(scan.created_at)}
        </Typography>
      </Box>
      {isRunning ? (
        <Chip size="small" label={scan.status} sx={{ height: 20, fontSize: '0.65rem' }} />
      ) : (
        <Chip
          size="small"
          label={count === 0 ? 'Clean' : `${count} finding${count === 1 ? '' : 's'}`}
          sx={{
            height: 20,
            fontSize: '0.65rem',
            fontWeight: 700,
            bgcolor: alpha(tone.color, 0.12),
            color: tone.color,
            border: `1px solid ${alpha(tone.color, 0.35)}`,
          }}
        />
      )}
    </Box>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const toast = useStore((s) => s.toast);
  const muiTheme = useTheme();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [recentScans, setRecentScans] = useState([]);
  const [llmStatus, setLlmStatus] = useState(null);

  useEffect(() => {
    fetchDashboard()
      .then(setData)
      .catch((err) => toast(typeof err === 'string' ? err : (err?.message || 'Failed to load'), 'error'))
      .finally(() => setLoading(false));
  }, [toast]);

  // Recent scans live under a different endpoint than the main dashboard
  // payload, so fetch them in parallel. Failures are silent — the card
  // just hides itself, the Security Scanner page remains reachable via
  // the sidebar.
  useEffect(() => {
    fetchScans()
      .then((res) => setRecentScans((res.scans || res || []).slice(0, 5)))
      .catch(() => setRecentScans([]));
  }, []);

  // Fetch LLM configuration status
  useEffect(() => {
    fetchLlmConfigs()
      .then((res) => {
        setLlmStatus({
          configured: !!res.default_config_id,
          provider: res.default_provider,
          model: res.default_model,
          message: res.message,
        });
      })
      .catch(() => {
        setLlmStatus({
          configured: false,
          provider: null,
          model: null,
          message: 'No LLM configured',
        });
      });
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
        <LogoLoader size={96} message="Loading dashboard..." />
      </Box>
    );
  }

  const totals = data?.totals || {};
  const recentRuns = data?.recent_runs || [];
  const integrationSummaries = (data?.integrations && data.integrations.length > 0)
    ? data.integrations
    : buildFallbackIntegrations(recentRuns);
  const activity = (data?.activity && data.activity.length > 0)
    ? data.activity
    : buildFallbackActivity(recentRuns);

  const integrationCount = integrationSummaries.length || totals.integrations || 0;
  const healthyIntegrations = integrationSummaries.length > 0
    ? integrationSummaries.filter((integration) => isHealthyStatus(integration.last_run_status)).length
    : (totals.healthy_integrations || 0);
  const toolCount = totals.tools != null
    ? totals.tools
    : integrationSummaries.reduce((sum, integration) => sum + (integration.latest_tool_count || 0), 0);
  const endpointCount = totals.endpoints != null
    ? totals.endpoints
    : integrationSummaries.reduce((sum, integration) => sum + (integration.latest_endpoint_count || 0), 0);
  const averageLatestScore = totals.average_latest_score != null
    ? totals.average_latest_score
    : (totals.average_score != null
      ? totals.average_score
      : numericAverage(integrationSummaries.map((integration) => integration.latest_score).filter((value) => value != null)));
  const averageLatestCoverage = totals.average_latest_coverage != null
    ? totals.average_latest_coverage
    : numericAverage(integrationSummaries.map((integration) => integration.latest_coverage).filter((value) => value != null));
  const warningRunCount = totals.warning_runs != null
    ? totals.warning_runs
    : recentRuns.filter((run) => (run.warnings || []).length > 0).length;
  const healthyRatio = integrationCount ? (healthyIntegrations / integrationCount) : 0;
  const successRate = totals.success_rate != null ? Math.round(totals.success_rate * 100) : 0;
  const averageCoverage = averageLatestCoverage != null ? Math.round(averageLatestCoverage * 100) : null;
  const highlightedIntegrations = integrationSummaries.slice(0, 5);
  const warningExplanation = 'Warnings come from the quality scoring pipeline, usually incomplete endpoint coverage or tool compression outside the target range.';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
      {/* Show Getting Started guide when no integrations exist */}
      {integrationCount === 0 && (
        <GetStartedGuide completedSteps={[]} />
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} lg={3}>
          <MetricCard
            icon={HubOutlinedIcon}
            label="Integrations"
            value={integrationCount}
            subtitle={`${healthyIntegrations} healthy`}
            tint="#0ea5e9"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <MetricCard
            icon={RuleFolderOutlinedIcon}
            label="Tools mapped"
            value={toolCount}
            subtitle={`${endpointCount} endpoints`}
            tint="#8b5cf6"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <MetricCard
            icon={AutoGraphOutlinedIcon}
            label="Run volume"
            value={totals.runs ?? 0}
            subtitle={`${totals.successful_runs || 0} healthy / ${totals.failed_runs || 0} failed`}
            tint="#10b981"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <MetricCard
            icon={WarningAmberRoundedIcon}
            label="Average quality"
            value={averageLatestScore != null ? Math.round(averageLatestScore) : '--'}
            subtitle={averageCoverage != null ? `${averageCoverage}% coverage` : undefined}
            tint="#f59e0b"
          />
        </Grid>
      </Grid>

      {/* LLM Configuration Status */}
      {llmStatus && (
        <Card sx={{ borderRadius: 2, bgcolor: llmStatus.configured ? 'success.lighter' : 'warning.lighter' }}>
          <CardContent sx={{ p: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <SmartToyOutlinedIcon sx={{ fontSize: 28, color: llmStatus.configured ? 'success.main' : 'warning.main' }} />
              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  AI Analysis Provider
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  {llmStatus.configured ? (
                    <>
                      <Chip
                        size="small"
                        label={llmStatus.provider}
                        variant="outlined"
                        sx={{ mr: 1 }}
                      />
                      {llmStatus.model}
                    </>
                  ) : (
                    <>
                      <Typography variant="caption" color="warning.main">
                        {llmStatus.message}
                      </Typography>
                    </>
                  )}
                </Typography>
              </Box>
              <Button
                size="small"
                variant={llmStatus.configured ? 'outlined' : 'contained'}
                onClick={() => navigate('/llm-config')}
                sx={{ flexShrink: 0 }}
              >
                Configure
              </Button>
            </Box>
          </CardContent>
        </Card>
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} lg={5}>
          <Card sx={{ height: '100%', borderRadius: 2 }}>
            <CardContent sx={{ p: 2 }}>
              <SectionHeader
                eyebrow="Activity"
                title="Run cadence over the last 14 days"
                description="Daily volume with tooltip detail for healthy, failed, and warning-bearing runs."
              />
              {activity.length > 0 ? (
                <>
                  <ActivityBars activity={activity} color={muiTheme.palette.primary.main} />
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
                    <Chip size="small" color="success" variant="outlined" label={`${totals.successful_runs || 0} healthy`} />
                    <Chip size="small" color="error" variant="outlined" label={`${totals.failed_runs || 0} failed`} />
                    <Tooltip title={warningExplanation} arrow>
                      <Chip size="small" color="warning" variant="outlined" label={`${warningRunCount} with warnings`} />
                    </Tooltip>
                  </Box>
                </>
              ) : (
                <Box sx={{ py: 8 }}>
                  <LogoLoader size={72} centered message="No activity yet" />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} lg={7}>
          <Card sx={{ height: '100%', borderRadius: 2 }}>
            <CardContent sx={{ p: 2 }}>
              <SectionHeader
                eyebrow="Integration health"
                title="How each integration is performing"
                description="Latest score, coverage, run health, and warning detail. This is the strongest dashboard data already available in the backend."
                action={<Chip size="small" variant="outlined" label={`${integrationSummaries.length} tracked`} />}
              />
              {highlightedIntegrations.length === 0 ? (
                <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderRadius: 3 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    No integrations yet. Create one to see health metrics and analysis here.
                  </Typography>
                  <Button
                    variant="contained"
                    size="small"
                    onClick={() => navigate('/integrations')}
                  >
                    Create Integration
                  </Button>
                </Paper>
              ) : (
                <Stack divider={<Divider />}>
                  {highlightedIntegrations.map((integration) => (
                    <IntegrationHealthRow key={integration.id} integration={integration} />
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Recent scans — always rendered after the first scan exists. Each
          row deep-links into Scanner by writing the scan id to the same
          storage key the Scanner page uses to restore its last-viewed
          selection. */}
      {recentScans.length > 0 && (
        <Card sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2 }}>
            <SectionHeader
              eyebrow="Security"
              title="Recent scans"
              description="Your latest security scans. Click to open in the Scanner."
              action={
                <Button
                  size="small"
                  variant="text"
                  endIcon={<ShieldOutlinedIcon fontSize="small" />}
                  onClick={() => navigate('/scanner')}
                >
                  View all
                </Button>
              }
            />
            <Stack divider={<Divider />} sx={{ mt: 0.5 }}>
              {recentScans.map((scan) => (
                <RecentScanRow
                  key={scan.id}
                  scan={scan}
                  onOpen={(s) => {
                    // Same key Scanner.jsx reads on mount to restore selection.
                    try { localStorage.setItem('selqor:scanner:last-scan-id', s.id); } catch { /* ignore */ }
                    navigate('/scanner');
                  }}
                />
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}

    </Box>
  );
}

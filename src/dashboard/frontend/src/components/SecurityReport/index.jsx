import React, { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import Stack from '@mui/material/Stack';
import Alert from '@mui/material/Alert';
import Accordion from '@mui/material/Accordion';
import AccordionSummary from '@mui/material/AccordionSummary';
import AccordionDetails from '@mui/material/AccordionDetails';
import LinearProgress from '@mui/material/LinearProgress';
import Divider from '@mui/material/Divider';
import { alpha, useTheme } from '@mui/material/styles';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { computeComplianceReport, OWASP_AGENTIC_TOP_10 } from '../../utils/owaspMapping';

// Severity → MUI palette color. Keep in sync with Scanner.jsx so the two
// views share a visual vocabulary.
const SEVERITY_COLORS = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#ca8a04',
  low: '#2563eb',
  info: '#6b7280',
};

function severityTint(severity, theme) {
  const base = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;
  return alpha(base, theme.palette.mode === 'dark' ? 0.18 : 0.1);
}

/**
 * Compact badge showing a severity label with its signature color.
 */
function SeverityChip({ severity, count }) {
  if (!severity || !count) return null;
  return (
    <Chip
      size="small"
      label={`${count} ${severity}`}
      sx={{
        height: 20,
        fontSize: '0.65rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        bgcolor: alpha(SEVERITY_COLORS[severity] || SEVERITY_COLORS.info, 0.18),
        color: SEVERITY_COLORS[severity] || SEVERITY_COLORS.info,
        border: `1px solid ${alpha(SEVERITY_COLORS[severity] || SEVERITY_COLORS.info, 0.35)}`,
      }}
    />
  );
}

/**
 * The big round score dial at the top-left of the report. Color-coded by
 * tier — we use the same thresholds as the existing Scanner stat cards
 * for consistency.
 */
function ComplianceScoreCard({ score, coveragePct, categoriesClean, totalFindings }) {
  const theme = useTheme();
  const tier = score >= 85 ? 'good' : score >= 60 ? 'warn' : 'bad';
  const tierColor = tier === 'good' ? '#10b981' : tier === 'warn' ? '#f59e0b' : '#dc2626';
  const tierLabel = tier === 'good' ? 'Compliant' : tier === 'warn' ? 'Needs Attention' : 'At Risk';

  return (
    <Paper variant="outlined" sx={{ p: 2.5, height: '100%' }}>
      <Stack direction="row" spacing={2.5} alignItems="center">
        <Box
          sx={{
            position: 'relative',
            width: 92,
            height: 92,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            bgcolor: alpha(tierColor, theme.palette.mode === 'dark' ? 0.2 : 0.12),
            border: `3px solid ${tierColor}`,
            flexShrink: 0,
          }}
        >
          <Typography variant="h4" fontWeight={700} sx={{ color: tierColor, lineHeight: 1 }}>
            {score}
          </Typography>
          <Typography variant="caption" sx={{ position: 'absolute', bottom: 8, color: tierColor, fontSize: '0.55rem', fontWeight: 600 }}>
            / 100
          </Typography>
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5 }}>
            <ShieldOutlinedIcon sx={{ fontSize: 16, color: tierColor }} />
            <Typography variant="subtitle2" fontWeight={700} sx={{ color: tierColor, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {tierLabel}
            </Typography>
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
            OWASP Agentic Top 10 compliance score
          </Typography>
          <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
            <Box>
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', fontSize: '0.65rem' }}>COVERAGE</Typography>
              <Typography variant="body2" fontWeight={600}>{coveragePct}% clean</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', fontSize: '0.65rem' }}>CATEGORIES PASSING</Typography>
              <Typography variant="body2" fontWeight={600}>{categoriesClean} / 10</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', fontSize: '0.65rem' }}>TOTAL FINDINGS</Typography>
              <Typography variant="body2" fontWeight={600}>{totalFindings}</Typography>
            </Box>
          </Stack>
        </Box>
      </Stack>
    </Paper>
  );
}

/**
 * The 10-cell coverage matrix. Each cell shows a category's status at a
 * glance: clean (green checkmark) or worst-severity color-coded.
 */
function CoverageMatrix({ perCategory, onSelect, selectedKey }) {
  const theme = useTheme();
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>OWASP Agentic Top 10 Coverage</Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        Click a category to see its findings. Color indicates the worst severity in that category.
      </Typography>
      <Grid container spacing={1}>
        {perCategory.map((cat) => {
          const isSelected = selectedKey === cat.key;
          const bg = cat.clean
            ? alpha(SEVERITY_COLORS.info === '#6b7280' ? '#10b981' : '#10b981', theme.palette.mode === 'dark' ? 0.18 : 0.1)
            : severityTint(cat.worstSeverity, theme);
          const borderColor = cat.clean ? '#10b981' : (SEVERITY_COLORS[cat.worstSeverity] || SEVERITY_COLORS.info);
          return (
            <Grid item xs={6} sm={4} md={2.4} key={cat.key}>
              <Box
                onClick={() => onSelect(cat.key)}
                sx={{
                  p: 1.25,
                  borderRadius: 1.2,
                  bgcolor: bg,
                  border: `1.5px solid ${alpha(borderColor, isSelected ? 1 : 0.45)}`,
                  cursor: 'pointer',
                  transition: 'border-color 0.15s, transform 0.15s',
                  '&:hover': { borderColor: alpha(borderColor, 0.9), transform: 'translateY(-1px)' },
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 0.5,
                }}
              >
                <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="space-between">
                  <Typography variant="caption" fontWeight={700} sx={{ color: borderColor, fontSize: '0.65rem' }}>
                    {cat.code}
                  </Typography>
                  {cat.clean ? (
                    <CheckCircleOutlineIcon sx={{ fontSize: 14, color: '#10b981' }} />
                  ) : (
                    <WarningAmberOutlinedIcon sx={{ fontSize: 14, color: borderColor }} />
                  )}
                </Stack>
                <Tooltip title={cat.description} placement="top">
                  <Typography variant="body2" fontWeight={600} sx={{ fontSize: '0.75rem', lineHeight: 1.25, minHeight: 32 }}>
                    {cat.title}
                  </Typography>
                </Tooltip>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                  {cat.clean ? 'No findings' : `${cat.count} finding${cat.count === 1 ? '' : 's'}`}
                </Typography>
              </Box>
            </Grid>
          );
        })}
      </Grid>
    </Paper>
  );
}

/**
 * Horizontal bar showing the distribution of findings across severity
 * levels. Lives below the coverage matrix.
 */
function SeverityBreakdownBar({ perCategory }) {
  const totals = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const cat of perCategory) {
    for (const [k, v] of Object.entries(cat.severityCounts)) totals[k] += v;
  }
  const total = Object.values(totals).reduce((a, b) => a + b, 0);
  if (total === 0) {
    return (
      <Alert severity="success" variant="outlined" sx={{ py: 0.75 }}>
        <Typography variant="body2" fontWeight={600}>No findings across any category</Typography>
        <Typography variant="caption" color="text.secondary">
          This scan passed all OWASP Agentic Top 10 checks. You're clear to deploy.
        </Typography>
      </Alert>
    );
  }
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Severity Breakdown</Typography>
      <Box sx={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', mb: 1 }}>
        {['critical', 'high', 'medium', 'low', 'info'].map((sev) => {
          const count = totals[sev];
          if (count === 0) return null;
          const pct = (count / total) * 100;
          return (
            <Tooltip key={sev} title={`${count} ${sev} (${pct.toFixed(0)}%)`}>
              <Box sx={{ width: `${pct}%`, bgcolor: SEVERITY_COLORS[sev] }} />
            </Tooltip>
          );
        })}
      </Box>
      <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
        {['critical', 'high', 'medium', 'low', 'info'].map((sev) => (
          <SeverityChip key={sev} severity={sev} count={totals[sev]} />
        ))}
      </Stack>
    </Paper>
  );
}

/**
 * Drill-down panel shown below the matrix when a category is selected.
 * Lists the findings inside that category with the same visual language
 * as the existing Scanner findings accordion — but focused on a single
 * OWASP bucket.
 */
function CategoryDetails({ category, suggestedFixes }) {
  const theme = useTheme();
  if (!category) {
    return (
      <Alert severity="info" variant="outlined">
        <Typography variant="body2" fontWeight={600}>Select a category above</Typography>
        <Typography variant="caption" color="text.secondary">
          Click any of the 10 cards to see which findings fall under that OWASP Agentic category.
        </Typography>
      </Alert>
    );
  }
  if (category.clean) {
    return (
      <Alert severity="success" variant="outlined" icon={<CheckCircleOutlineIcon />}>
        <Typography variant="body2" fontWeight={600}>
          {category.code} — {category.title}: clean
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {category.description}
        </Typography>
      </Alert>
    );
  }
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Typography variant="subtitle2" fontWeight={700}>
          {category.code} — {category.title}
        </Typography>
        <Chip size="small" label={`${category.count} finding${category.count === 1 ? '' : 's'}`} sx={{ height: 18, fontSize: '0.62rem' }} />
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        {category.description}
      </Typography>
      <Stack spacing={0.75}>
        {category.findings.map((f, i) => {
          const severity = (f.risk_level || f.severity || 'info').toLowerCase();
          const color = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;
          const fix = suggestedFixes.find((x) => x.finding_id === f.id);
          return (
            <Accordion
              key={f.id || i}
              disableGutters
              square
              sx={{
                bgcolor: severityTint(severity, theme),
                borderLeft: `3px solid ${color}`,
                boxShadow: 'none',
                '&:before': { display: 'none' },
              }}
            >
              <AccordionSummary expandIcon={<ExpandMoreIcon fontSize="small" />} sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { my: 0.75 } }}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.25 }}>
                    <Chip size="small" label={severity.toUpperCase()} sx={{ height: 16, fontSize: '0.58rem', fontWeight: 700, bgcolor: color, color: '#fff' }} />
                    <Typography variant="body2" fontWeight={600} noWrap>{f.title}</Typography>
                  </Stack>
                  {(f.metadata?.endpoint || f.file) && (
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', fontSize: '0.65rem' }}>
                      {f.metadata?.endpoint || `${f.file}${f.line ? `:${f.line}` : ''}`}
                    </Typography>
                  )}
                </Box>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0 }}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  {f.description}
                </Typography>
                {f.remediation && (
                  <Alert severity="info" variant="outlined" icon={<InfoOutlinedIcon fontSize="small" />} sx={{ py: 0.5, mb: fix ? 0.75 : 0 }}>
                    <Typography variant="caption" fontWeight={600} sx={{ display: 'block' }}>Remediation</Typography>
                    <Typography variant="caption" color="text.secondary">{f.remediation}</Typography>
                  </Alert>
                )}
                {fix && (
                  <Alert severity="success" variant="outlined" sx={{ py: 0.5 }}>
                    <Typography variant="caption" fontWeight={600} sx={{ display: 'block' }}>
                      Suggested fix: {fix.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {fix.description}
                      {fix.effort ? ` · ${fix.effort} effort` : ''}
                    </Typography>
                  </Alert>
                )}
              </AccordionDetails>
            </Accordion>
          );
        })}
      </Stack>
    </Paper>
  );
}

/**
 * Main entry point. Receives the full scan object as loaded by
 * `fetchScan(id)` and renders the complete OWASP compliance report.
 */
export default function SecurityReport({ scan }) {
  const findings = useMemo(() => scan?.findings || [], [scan]);
  const suggestedFixes = useMemo(() => scan?.suggested_fixes || [], [scan]);
  const report = useMemo(() => computeComplianceReport(findings), [findings]);
  const [selectedKey, setSelectedKey] = useState(() => {
    // Auto-select the first non-clean category so the user lands on
    // something actionable immediately.
    const firstDirty = report.perCategory.find((c) => !c.clean);
    return firstDirty?.key || OWASP_AGENTIC_TOP_10[0].key;
  });

  if (!scan) {
    return (
      <Alert severity="info" variant="outlined">Select a scan to view its security report.</Alert>
    );
  }
  if (scan.status !== 'completed' && scan.status !== 'failed') {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Scan still running</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
          The OWASP compliance report becomes available once the scan completes.
        </Typography>
        <LinearProgress variant={scan.progress_percent != null ? 'determinate' : 'indeterminate'} value={scan.progress_percent || 0} />
      </Paper>
    );
  }

  const selectedCategory = report.perCategory.find((c) => c.key === selectedKey) || null;

  return (
    <Box>
      <Grid container spacing={1.5} sx={{ mb: 1.5 }}>
        <Grid item xs={12} md={7}>
          <ComplianceScoreCard
            score={report.score}
            coveragePct={report.coveragePct}
            categoriesClean={report.categoriesClean}
            totalFindings={report.totalFindings}
          />
        </Grid>
        <Grid item xs={12} md={5}>
          <SeverityBreakdownBar perCategory={report.perCategory} />
        </Grid>
      </Grid>
      <Box sx={{ mb: 1.5 }}>
        <CoverageMatrix perCategory={report.perCategory} onSelect={setSelectedKey} selectedKey={selectedKey} />
      </Box>
      {report.uncategorized.length > 0 && (
        <Alert severity="warning" variant="outlined" sx={{ mb: 1.5 }}>
          <Typography variant="caption" fontWeight={600} sx={{ display: 'block' }}>
            {report.uncategorized.length} finding{report.uncategorized.length === 1 ? '' : 's'} did not match any OWASP category
          </Typography>
          <Typography variant="caption" color="text.secondary">
            These findings will still appear in the main Scanner findings list — they just don't fit the Agentic Top 10 taxonomy.
          </Typography>
        </Alert>
      )}
      <Divider sx={{ mb: 1.5 }} />
      <CategoryDetails category={selectedCategory} suggestedFixes={suggestedFixes} />
    </Box>
  );
}

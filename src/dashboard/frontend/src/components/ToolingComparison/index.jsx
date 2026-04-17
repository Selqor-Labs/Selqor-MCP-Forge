// Feature 4 — Baseline vs curated tooling comparison.
//
// The "value prop" of Selqor Forge is *curation*: we take an API spec
// with hundreds of endpoints and produce a small set of well-shaped MCP
// tools. But without a side-by-side view the user has no way to see
// what curation actually bought them. This component renders a two-
// column panel:
//
//   • LEFT  — Baseline: what an uncurated MCP would look like. One tool
//             per endpoint, no merging, no renaming, no descriptions.
//             Computed client-side from the endpoint catalog.
//   • RIGHT — Curated: the actual tooling from ToolBuilder. Counts,
//             compression ratio, average quality.
//
// The comparison surfaces four metrics that matter most for an MCP:
//   1. Tool count               — smaller = easier for the LLM to pick
//   2. Compression ratio        — tools / endpoints, healthy 0.05–0.40
//   3. Avg endpoints per tool   — higher = more semantic grouping
//   4. Avg quality score        — from toolQuality.js
//
// Scoped as a drop-in panel for ToolBuilderStep. When the Playground
// gains a live "simulate baseline" toggle in the future, this same
// component can be reused there — it takes its data as props.

import React, { useMemo } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import LinearProgress from '@mui/material/LinearProgress';
import Tooltip from '@mui/material/Tooltip';
import Chip from '@mui/material/Chip';
import { alpha, useTheme } from '@mui/material/styles';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import { computeToolQuality } from '../../utils/toolQuality';

/** Short human label for the compression tier. */
function compressionTier(ratio) {
  if (ratio === null || ratio === undefined) return { label: '—', color: '#6b7280' };
  if (ratio <= 0.1) return { label: 'Very compact', color: '#10b981' };
  if (ratio <= 0.25) return { label: 'Healthy', color: '#10b981' };
  if (ratio <= 0.5) return { label: 'Moderate', color: '#f59e0b' };
  return { label: 'Low compression', color: '#dc2626' };
}

/**
 * Single metric row. Shows a label, two values (baseline / curated),
 * and an arrow indicating which direction is better.
 */
function MetricRow({ label, tooltip, baseline, curated, unit = '', improvementDirection = 'down', format = (v) => v }) {
  const theme = useTheme();
  const betterIsLower = improvementDirection === 'down';
  const improved = baseline != null && curated != null
    && (betterIsLower ? curated < baseline : curated > baseline);
  const regressed = baseline != null && curated != null
    && (betterIsLower ? curated > baseline : curated < baseline);

  const arrowColor = improved ? '#10b981' : regressed ? '#dc2626' : theme.palette.text.disabled;
  const ArrowIcon = betterIsLower ? TrendingDownIcon : TrendingUpIcon;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.75 }}>
      <Tooltip title={tooltip || ''} placement="left">
        <Typography variant="caption" sx={{ minWidth: 140, fontWeight: 600, color: 'text.secondary' }}>
          {label}
        </Typography>
      </Tooltip>
      <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="body2" sx={{ minWidth: 60, textAlign: 'right', color: 'text.disabled', textDecoration: 'line-through' }}>
          {baseline != null ? `${format(baseline)}${unit}` : '—'}
        </Typography>
        <ArrowIcon sx={{ fontSize: 16, color: arrowColor }} />
        <Typography variant="body2" fontWeight={700} sx={{ minWidth: 60, color: improved ? '#10b981' : regressed ? '#dc2626' : 'text.primary' }}>
          {curated != null ? `${format(curated)}${unit}` : '—'}
        </Typography>
      </Box>
    </Box>
  );
}

/**
 * Main comparison panel.
 *
 * Props:
 *   tools             — curated tools array (may be ToolBuilder state or
 *                       MCP tools/list response). Only `.length` is required;
 *                       `covered_endpoints` and `input_schema` are used if
 *                       present for richer stats.
 *   endpointCatalog   — optional full endpoint list. Used by ToolBuilder.
 *                       When absent, falls back to `endpointCount` prop and
 *                       skips the quality/avg-assigned metrics.
 *   endpointCount     — optional numeric count when the full catalog isn't
 *                       available (e.g. Playground, which only knows the
 *                       count via the integration summary).
 *   compact           — if true, render a denser horizontal strip
 */
export default function ToolingComparison({
  tools = [],
  endpointCatalog = [],
  endpointCount: endpointCountProp,
  compact = false,
}) {
  const theme = useTheme();

  const stats = useMemo(() => {
    const hasCatalog = endpointCatalog.length > 0;
    const endpointCount = hasCatalog ? endpointCatalog.length : (endpointCountProp || 0);
    const curatedToolCount = tools.length;

    // Build an endpoint map once so quality calc can inspect params.
    const endpointMap = {};
    endpointCatalog.forEach((ep, idx) => {
      const id = ep.id || ep.operation_id || `${ep.method || 'GET'}_${ep.path || idx}`;
      endpointMap[id] = ep;
    });

    // Average assigned endpoints per curated tool. ToolBuilder state
    // exposes `covered_endpoints`; MCP tools/list responses don't, so
    // we fall back to endpointCount / curatedToolCount.
    const hasCoveredEndpoints = tools.some((t) => Array.isArray(t.covered_endpoints));
    const avgAssigned = curatedToolCount > 0
      ? (hasCoveredEndpoints
        ? tools.reduce((acc, t) => acc + (t.covered_endpoints || []).length, 0) / curatedToolCount
        : endpointCount / curatedToolCount)
      : 0;

    // Compression: tools/endpoints. Lower is more compressed.
    const curatedRatio = endpointCount > 0 ? curatedToolCount / endpointCount : null;
    const baselineRatio = endpointCount > 0 ? 1 : null;  // 1:1 by definition

    // Average quality score across curated tools.
    const qualities = tools
      .filter((t) => t.name !== 'custom_request')
      .map((t) => computeToolQuality(t, endpointMap).overall);
    const avgQuality = qualities.length > 0
      ? Math.round(qualities.reduce((a, b) => a + b, 0) / qualities.length)
      : null;

    // Baseline quality estimate — a single-endpoint tool with a
    // default name typically scores ~40 under the heuristic. We
    // simulate one representative endpoint-as-tool to get a
    // concrete number rather than hard-coding.
    const baselineSample = endpointCatalog[0];
    const baselineQuality = baselineSample
      ? computeToolQuality(
        {
          name: (baselineSample.operation_id || `${baselineSample.method || 'get'}_${baselineSample.path || 'op'}`)
            .replace(/[^a-z0-9]+/gi, '_').toLowerCase(),
          description: baselineSample.summary || '',
          covered_endpoints: [baselineSample.id || 'ep0'],
          input_schema: {},
        },
        { [baselineSample.id || 'ep0']: baselineSample },
      ).overall
      : null;

    return {
      endpointCount,
      baselineToolCount: endpointCount,
      curatedToolCount,
      baselineRatio,
      curatedRatio,
      baselineAvgAssigned: 1,
      curatedAvgAssigned: Number(avgAssigned.toFixed(1)),
      baselineQuality,
      curatedQuality: avgQuality,
    };
  }, [tools, endpointCatalog]);

  if (stats.endpointCount === 0) {
    return null;
  }

  const reduction = stats.baselineToolCount > 0
    ? Math.round((1 - stats.curatedToolCount / stats.baselineToolCount) * 100)
    : 0;
  const tier = compressionTier(stats.curatedRatio);

  // ── Compact strip ─────────────────────────────────────────────────
  if (compact) {
    return (
      <Paper variant="outlined" sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <CompareArrowsIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
        <Typography variant="caption" fontWeight={600}>
          {stats.baselineToolCount} → {stats.curatedToolCount} tools
        </Typography>
        <Chip
          size="small"
          label={`${reduction}% reduction`}
          sx={{ height: 18, fontSize: '0.65rem', bgcolor: alpha(tier.color, 0.15), color: tier.color, fontWeight: 700 }}
        />
        <Typography variant="caption" color="text.secondary">·</Typography>
        <Typography variant="caption">
          Quality {stats.curatedQuality ?? '—'}
        </Typography>
      </Paper>
    );
  }

  // ── Full panel ────────────────────────────────────────────────────
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        bgcolor: alpha(theme.palette.primary.main, theme.palette.mode === 'dark' ? 0.05 : 0.03),
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <CompareArrowsIcon sx={{ fontSize: 18, color: 'primary.main' }} />
        <Typography variant="subtitle2" fontWeight={700}>
          Baseline vs Curated
        </Typography>
        <Chip
          size="small"
          label={`${reduction}% reduction`}
          sx={{
            height: 20,
            fontSize: '0.7rem',
            bgcolor: alpha(tier.color, 0.15),
            color: tier.color,
            fontWeight: 700,
            ml: 'auto',
          }}
        />
      </Stack>

      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        Baseline simulates an uncurated MCP (one tool per endpoint, no grouping).
        Curated is your ToolBuilder state. Lower tool counts and higher quality are better.
      </Typography>

      {/* Column headers */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5, pb: 0.5, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ minWidth: 140 }} />
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="caption" sx={{ minWidth: 60, textAlign: 'right', color: 'text.disabled', fontWeight: 700 }}>
            Baseline
          </Typography>
          <Box sx={{ width: 16 }} />
          <Typography variant="caption" sx={{ minWidth: 60, color: 'primary.main', fontWeight: 700 }}>
            Curated
          </Typography>
        </Box>
      </Box>

      <MetricRow
        label="Tool count"
        tooltip="Total number of MCP tools exposed. Smaller tool lists are easier for an LLM to search and pick from."
        baseline={stats.baselineToolCount}
        curated={stats.curatedToolCount}
        improvementDirection="down"
      />
      <MetricRow
        label="Compression ratio"
        tooltip="tools ÷ endpoints. 0.05–0.25 is the healthy band; higher means you're barely merging anything, much lower may mean you're overstuffing single tools."
        baseline={stats.baselineRatio}
        curated={stats.curatedRatio}
        improvementDirection="down"
        format={(v) => (v != null ? v.toFixed(2) : '—')}
      />
      <MetricRow
        label="Avg endpoints/tool"
        tooltip="How many endpoints each curated tool covers on average. Higher = more semantic grouping."
        baseline={stats.baselineAvgAssigned}
        curated={stats.curatedAvgAssigned}
        improvementDirection="up"
      />
      <MetricRow
        label="Avg quality score"
        tooltip="Average of the 4-factor quality score across all curated tools. Baseline is estimated from a single raw endpoint."
        baseline={stats.baselineQuality}
        curated={stats.curatedQuality}
        unit="/100"
        improvementDirection="up"
      />

      {/* Tier indicator bar */}
      <Box sx={{ mt: 1.5 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
          <Typography variant="caption" color="text.secondary">Compression</Typography>
          <Typography variant="caption" fontWeight={600} sx={{ color: tier.color }}>
            {tier.label}
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={Math.min(100, reduction)}
          sx={{
            height: 6,
            borderRadius: 3,
            bgcolor: alpha(tier.color, 0.15),
            '& .MuiLinearProgress-bar': { bgcolor: tier.color },
          }}
        />
      </Box>
    </Paper>
  );
}

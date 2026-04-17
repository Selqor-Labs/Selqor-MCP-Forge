import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Tooltip from '@mui/material/Tooltip';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import { alpha, useTheme } from '@mui/material/styles';
import StarOutlineIcon from '@mui/icons-material/StarOutline';
import AccessibilityOutlinedIcon from '@mui/icons-material/AccessibilityOutlined';
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import { computeToolQuality, qualityTier, QUALITY_WEIGHTS } from '../../utils/toolQuality';

/**
 * Per-factor row: icon · label · horizontal bar · numeric score. The bar
 * uses a tiered color so at a glance the user can tell which dimensions
 * of the tool are strong vs weak.
 */
function FactorRow({ icon: Icon, label, tooltip, weight, score }) {
  const theme = useTheme();
  const tier = qualityTier(score);
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Tooltip title={tooltip} placement="left">
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 120 }}>
          <Icon sx={{ fontSize: 14, color: tier.color }} />
          <Typography variant="caption" fontWeight={600} sx={{ fontSize: '0.7rem' }}>
            {label}
          </Typography>
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem' }}>
            ×{weight}
          </Typography>
        </Box>
      </Tooltip>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <LinearProgress
          variant="determinate"
          value={score}
          sx={{
            height: 5,
            borderRadius: 3,
            bgcolor: alpha(tier.color, theme.palette.mode === 'dark' ? 0.2 : 0.12),
            '& .MuiLinearProgress-bar': { bgcolor: tier.color },
          }}
        />
      </Box>
      <Typography variant="caption" fontWeight={700} sx={{ minWidth: 26, textAlign: 'right', color: tier.color, fontSize: '0.7rem' }}>
        {score}
      </Typography>
    </Box>
  );
}

/**
 * Full breakdown panel. Shows the overall score prominently on the left
 * and the 4 factor bars stacked on the right. Designed to sit next to the
 * existing Confidence chip in ToolBuilderStep's detail panel.
 *
 * Props:
 *   tool         — curated tool object (has `covered_endpoints`, `input_schema`, etc.)
 *   endpointMap  — id → endpoint record, so we can inspect parameters/methods
 *   compact      — if true, omit the side label and render bars only
 */
export default function ToolQualityBreakdown({ tool, endpointMap = {}, compact = false }) {
  const theme = useTheme();
  const q = computeToolQuality(tool, endpointMap);
  const tier = qualityTier(q.overall);

  if (compact) {
    return (
      <Tooltip
        title={
          <Box sx={{ minWidth: 180 }}>
            <Typography variant="caption" fontWeight={700} sx={{ display: 'block', mb: 0.5 }}>Quality breakdown</Typography>
            <Typography variant="caption" sx={{ display: 'block' }}>Importance: {q.importance}</Typography>
            <Typography variant="caption" sx={{ display: 'block' }}>Usability: {q.usability}</Typography>
            <Typography variant="caption" sx={{ display: 'block' }}>Security: {q.security}</Typography>
            <Typography variant="caption" sx={{ display: 'block' }}>Complexity: {q.complexity}</Typography>
          </Box>
        }
      >
        <Box sx={{
          px: 0.75, py: 0.25, borderRadius: 0.75, border: `1px solid ${alpha(tier.color, 0.5)}`,
          bgcolor: alpha(tier.color, 0.1), display: 'inline-flex', alignItems: 'center', gap: 0.5,
        }}>
          <StarOutlineIcon sx={{ fontSize: 12, color: tier.color }} />
          <Typography variant="caption" fontWeight={700} sx={{ color: tier.color, fontSize: '0.6rem' }}>
            Q{q.overall}
          </Typography>
        </Box>
      </Tooltip>
    );
  }

  return (
    <Box sx={{
      p: 1.5,
      borderRadius: 1,
      border: `1px solid ${alpha(tier.color, 0.35)}`,
      bgcolor: alpha(tier.color, theme.palette.mode === 'dark' ? 0.08 : 0.05),
    }}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Box sx={{ minWidth: 80, textAlign: 'center', flexShrink: 0 }}>
          <Typography variant="overline" color="text.secondary" sx={{ fontSize: '0.6rem', lineHeight: 1 }}>
            Quality Score
          </Typography>
          <Typography variant="h5" fontWeight={700} sx={{ color: tier.color, lineHeight: 1.1, mt: 0.25 }}>
            {q.overall}
          </Typography>
          <Typography variant="caption" sx={{ color: tier.color, fontWeight: 600, fontSize: '0.6rem' }}>
            {tier.label}
          </Typography>
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack spacing={0.6}>
            <FactorRow
              icon={StarOutlineIcon}
              label="Importance"
              weight={QUALITY_WEIGHTS.importance}
              score={q.importance}
              tooltip="How much value the tool delivers: endpoint count, mutation verbs, method diversity, documentation depth."
            />
            <FactorRow
              icon={AccessibilityOutlinedIcon}
              label="Usability"
              weight={QUALITY_WEIGHTS.usability}
              score={q.usability}
              tooltip="How easy it is for an agent to pick and invoke: naming convention, description clarity, endpoint count sweet-spot, schema presence."
            />
            <FactorRow
              icon={ShieldOutlinedIcon}
              label="Security"
              weight={QUALITY_WEIGHTS.security}
              score={q.security}
              tooltip="Safety signals: absence of admin/debug paths, DELETE exposure, wildcard paths, and missing input schemas on mutating tools."
            />
            <FactorRow
              icon={TuneOutlinedIcon}
              label="Simplicity"
              weight={QUALITY_WEIGHTS.complexity}
              score={q.complexity}
              tooltip="Inverse of complexity: fewer parameters per endpoint, narrow HTTP method spread, reasonable endpoint count."
            />
          </Stack>
        </Box>
      </Stack>
    </Box>
  );
}

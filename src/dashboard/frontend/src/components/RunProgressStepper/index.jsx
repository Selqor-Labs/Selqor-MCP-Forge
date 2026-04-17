// Copyright (c) Selqor Labs.
// SPDX-License-Identifier: Apache-2.0

import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorRoundedIcon from '@mui/icons-material/ErrorRounded';
import RadioButtonUncheckedRoundedIcon from '@mui/icons-material/RadioButtonUncheckedRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';

/**
 * RunProgressStepper
 * ------------------
 * ChatGPT-style "deep research" progress rows for a pipeline run.
 *
 * Consumes the `progress.steps[]` array emitted by the backend
 * `_StepTracker` (see src/selqor_forge/dashboard/run_worker.py).  Each
 * step renders an icon, a label, an optional detail line ("Batch 2/5"),
 * and an indented list of any warnings that have been surfaced so far.
 *
 * Props:
 *   steps        - array of { key, label, status, detail, warnings[] }
 *   currentStep  - optional stable key of the row that should be
 *                  highlighted as "running" (used to render the shimmer
 *                  bar underneath the active row)
 *   message      - fallback human-readable line shown when steps[] is
 *                  empty (older backends); renders a single progress bar
 */
export default function RunProgressStepper({ steps, currentStep, message }) {
  // Back-compat: if no structured steps, fall back to the flat bar.
  if (!Array.isArray(steps) || steps.length === 0) {
    return (
      <Box>
        <LinearProgress sx={{ mb: 0.75, borderRadius: 1 }} />
        <Typography variant="caption" color="text.secondary">
          {message || 'Working…'}
        </Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={0.25}>
      {steps.map((step) => (
        <StepRow
          key={step.key}
          step={step}
          isCurrent={currentStep === step.key}
        />
      ))}
    </Stack>
  );
}

function StepRow({ step, isCurrent }) {
  const status = step.status || 'pending';
  const isRunning = status === 'running' || isCurrent;
  const isDone = status === 'done';
  const isWarning = status === 'warning';
  const isFailed = status === 'failed';
  const isPending = status === 'pending';

  const labelColor = isPending ? 'text.disabled' : 'text.primary';
  const labelWeight = isRunning ? 600 : isDone || isWarning || isFailed ? 500 : 400;

  return (
    <Box sx={{ py: 0.5 }}>
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Box sx={{ mt: 0.25, width: 20, display: 'flex', justifyContent: 'center' }}>
          <StepIcon status={status} isCurrent={isCurrent} />
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="baseline" sx={{ flexWrap: 'wrap' }}>
            <Typography
              variant="body2"
              sx={{
                color: labelColor,
                fontWeight: labelWeight,
                lineHeight: 1.4,
              }}
            >
              {step.label}
            </Typography>
            {step.detail && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ lineHeight: 1.4 }}
              >
                · {step.detail}
              </Typography>
            )}
          </Stack>

          {/* Shimmer bar beneath the running row */}
          {isRunning && !isFailed && (
            <LinearProgress
              sx={{
                mt: 0.5,
                height: 2,
                borderRadius: 1,
                maxWidth: 220,
              }}
            />
          )}

          {/* Inline warnings beneath the matching row */}
          {Array.isArray(step.warnings) && step.warnings.length > 0 && (
            <Stack spacing={0.25} sx={{ mt: 0.5 }}>
              {step.warnings.map((w, i) => (
                <Stack key={i} direction="row" spacing={0.75} alignItems="flex-start">
                  <WarningAmberRoundedIcon
                    sx={{ fontSize: 12, mt: 0.3, color: 'warning.main', flexShrink: 0 }}
                  />
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ lineHeight: 1.4 }}
                  >
                    {w}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          )}
        </Box>
      </Stack>
    </Box>
  );
}

function StepIcon({ status, isCurrent }) {
  if (status === 'running' || (isCurrent && status === 'pending')) {
    return (
      <Tooltip title="In progress" arrow>
        <CircularProgress size={14} thickness={6} />
      </Tooltip>
    );
  }
  if (status === 'done') {
    return (
      <Tooltip title="Completed" arrow>
        <CheckCircleRoundedIcon sx={{ fontSize: 16, color: 'success.main' }} />
      </Tooltip>
    );
  }
  if (status === 'warning') {
    return (
      <Tooltip title="Completed with warnings" arrow>
        <WarningAmberRoundedIcon sx={{ fontSize: 16, color: 'warning.main' }} />
      </Tooltip>
    );
  }
  if (status === 'failed') {
    return (
      <Tooltip title="Failed" arrow>
        <ErrorRoundedIcon sx={{ fontSize: 16, color: 'error.main' }} />
      </Tooltip>
    );
  }
  // pending
  return (
    <RadioButtonUncheckedRoundedIcon
      sx={{ fontSize: 16, color: 'action.disabled' }}
    />
  );
}

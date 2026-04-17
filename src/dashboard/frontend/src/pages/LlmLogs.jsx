import React from 'react';
import { useEffect, useState, useCallback } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Collapse from '@mui/material/Collapse';
import CircularProgress from '@mui/material/CircularProgress';
import LogoLoader from '../components/LogoLoader';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import { useTheme } from '@mui/material/styles';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import TerminalOutlinedIcon from '@mui/icons-material/TerminalOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import useStore from '../store/useStore';
import { fetchLlmLogs } from '../api';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtLatency(ms) {
  if (ms == null) return null;
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function trimText(text, max = 3000) {
  if (!text) return '';
  const s = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  return s.length > max ? s.slice(0, max) + '\n…[truncated]' : s;
}

function CodeBlock({ label, content, color }) {
  const [copied, setCopied] = useState(false);
  const muiTheme = useTheme();
  const isDark = muiTheme.palette.mode === 'dark';

  function handleCopy() {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <Box sx={{ mb: 1.5 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
        <Typography variant="caption" fontWeight={600} color={color || 'text.secondary'} sx={{ textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</Typography>
        <Tooltip title={copied ? 'Copied!' : 'Copy'}>
          <IconButton size="small" onClick={handleCopy}>
            {copied ? <CheckIcon sx={{ fontSize: 13, color: 'success.main' }} /> : <ContentCopyIcon sx={{ fontSize: 13 }} />}
          </IconButton>
        </Tooltip>
      </Box>
      <Box
        component="pre"
        sx={{
          m: 0, p: 1.5, borderRadius: 1,
          bgcolor: isDark ? '#0d0d0d' : '#f7f7f7',
          border: 1, borderColor: 'divider',
          fontSize: '0.72rem', fontFamily: 'monospace',
          overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          maxHeight: 280, overflowY: 'auto',
          color: color || 'text.primary',
        }}
      >
        {content}
      </Box>
    </Box>
  );
}

function LogEntry({ log, index }) {
  const [open, setOpen] = useState(false);
  const isSuccess = log.success || log.status === 'success';
  const latency = fmtLatency(log.latency_ms);

  const requestText = log.request_payload || log.prompt;
  const responseText = log.response_payload || log.response_text || log.response;

  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      {/* Summary row */}
      <Box
        onClick={() => setOpen((o) => !o)}
        sx={{
          display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.25,
          cursor: 'pointer',
          '&:hover': { bgcolor: 'action.hover' },
        }}
      >
        {isSuccess
          ? <CheckCircleOutlineIcon sx={{ fontSize: 16, color: 'success.main', flexShrink: 0 }} />
          : <ErrorOutlineIcon sx={{ fontSize: 16, color: 'error.main', flexShrink: 0 }} />
        }

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" fontWeight={500} noWrap>
              {log.integration_name || 'Unknown Integration'}
            </Typography>
            {log.run_id && (
              <Typography variant="caption" color="text.disabled" sx={{ fontFamily: 'monospace' }}>
                #{log.run_id.slice(-6)}
              </Typography>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 1, mt: 0.25, flexWrap: 'wrap' }}>
            {log.provider && <Chip size="small" label={log.provider} variant="outlined" sx={{ height: 16, fontSize: '0.6rem' }} />}
            {log.model && <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>{log.model}</Typography>}
            {log.run_mode && <Typography variant="caption" color="text.disabled">{log.run_mode}</Typography>}
            {log.endpoint && <Typography variant="caption" color="text.disabled" sx={{ fontFamily: 'monospace' }}>{log.endpoint}</Typography>}
          </Box>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexShrink: 0 }}>
          {latency && <Typography variant="caption" color="text.secondary">{latency}</Typography>}
          <Typography variant="caption" color="text.disabled">{fmtDate(log.created_at || log.timestamp)}</Typography>
          <Chip
            size="small"
            label={isSuccess ? 'success' : 'failed'}
            color={isSuccess ? 'success' : 'error'}
            variant="outlined"
          />
          {open ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
        </Box>
      </Box>

      {/* Expanded detail */}
      <Collapse in={open}>
        <Divider />
        <Box sx={{ px: 2, py: 1.5 }}>
          {requestText && (
            <CodeBlock
              label="Query Sent"
              content={typeof requestText === 'string' ? requestText : JSON.stringify(requestText, null, 2)}
            />
          )}
          {responseText && (
            <CodeBlock
              label="Response Received"
              content={trimText(responseText)}
            />
          )}
          {log.error && (
            <CodeBlock
              label="Error"
              content={log.error}
              color="error.main"
            />
          )}
          {!requestText && !responseText && !log.error && (
            <Typography variant="caption" color="text.secondary">No detail data available for this log entry.</Typography>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
}

export default function LlmLogs() {
  const toast = useStore((s) => s.toast);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await fetchLlmLogs();
      setLogs(res.logs || res || []);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
        <LogoLoader size={96} message="Loading LLM logs…" />
      </Box>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="body2" color="text.secondary">
          Inspect every query sent to the LLM and the response received — useful for debugging analysis runs
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={12} /> : <RefreshOutlinedIcon />}
          onClick={() => load(true)}
          disabled={refreshing}
          sx={{ flexShrink: 0, ml: 2 }}
        >
          Refresh
        </Button>
      </Box>

      {logs.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 5, textAlign: 'center' }}>
          <TerminalOutlinedIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
          <Typography variant="body2" color="text.secondary">No LLM logs yet.</Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5, maxWidth: 420, mx: 'auto' }}>
            LLM logs are captured when you run an integration analysis with an LLM provider configured
            (Settings → LLM Config), or when you run a security scan with LLM analysis enabled.
          </Typography>
        </Paper>
      ) : (
        <Stack spacing={0.75}>
          {logs.map((log, i) => (
            <LogEntry key={i} log={log} index={i} />
          ))}
        </Stack>
      )}
    </Box>
  );
}

import React from 'react';
import { useState } from 'react';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Alert from '@mui/material/Alert';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import Divider from '@mui/material/Divider';
import CircularProgress from '@mui/material/CircularProgress';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined';
import TerminalIcon from '@mui/icons-material/Terminal';
import HistoryIcon from '@mui/icons-material/History';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import useStore from '../../../store/useStore';
import { createDeployment } from '../../../api';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function DeployStep({ integration, onReload }) {
  const runs = useStore((s) => s.runs);
  const deployments = useStore((s) => s.deployments);
  const toast = useStore((s) => s.toast);
  const [target, setTarget] = useState('typescript');
  const [transport, setTransport] = useState('stdio');
  const [httpPort, setHttpPort] = useState(3333);
  const [deploying, setDeploying] = useState(false);
  const [result, setResult] = useState(null);
  const [copiedField, setCopiedField] = useState(null);

  const completedRuns = runs.filter((r) => r.status === 'completed' || r.status === 'ok');
  const latestRun = completedRuns[0];

  async function handleDeploy() {
    if (!latestRun) { toast('No completed analysis run available', 'error'); return; }
    setDeploying(true); setResult(null);
    try {
      const res = await createDeployment(integration.id, latestRun.run_id, {
        target, transport, http_port: transport === 'http' ? httpPort : undefined,
      });
      setResult(res); toast('Deployment prepared successfully'); onReload();
    } catch (err) { toast(typeof err === 'string' ? err : (err?.message || 'Deployment failed'), 'error'); }
    finally { setDeploying(false); }
  }

  function copy(text, field) {
    navigator.clipboard.writeText(text).then(() => { setCopiedField(field); setTimeout(() => setCopiedField(null), 2000); toast('Copied'); });
  }

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 0.5 }}>Deploy MCP Server</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>Generate and deploy a ready-to-run MCP server from your analyzed API specification.</Typography>

      {!latestRun ? (
        <Alert severity="warning">Complete an analysis run first (Step 1) before deploying.</Alert>
      ) : (<>
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="body2" fontWeight={600} sx={{ mb: 2 }}>Deployment Configuration</Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6}>
                <TextField select label="Target Runtime" value={target} onChange={(e) => setTarget(e.target.value)} helperText="Language for your MCP server">
                  <MenuItem value="typescript">TypeScript (Node.js)</MenuItem>
                  <MenuItem value="rust">Rust</MenuItem>
                </TextField>
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField select label="Transport Protocol" value={transport} onChange={(e) => setTransport(e.target.value)} helperText="How clients communicate with the server">
                  <MenuItem value="stdio">Stdio (recommended for local)</MenuItem>
                  <MenuItem value="http">HTTP / SSE (for remote)</MenuItem>
                </TextField>
              </Grid>
              {transport === 'http' && (
                <Grid item xs={12} sm={6}>
                  <TextField label="HTTP Port" type="number" value={httpPort} onChange={(e) => setHttpPort(parseInt(e.target.value) || 3333)} inputProps={{ min: 1, max: 65535 }} helperText="Port (1-65535)" />
                </Grid>
              )}
            </Grid>
            <Alert severity="info" icon={<InfoOutlinedIcon />} sx={{ mt: 2 }}>
              <Typography variant="caption">
                Generates a <strong>.env</strong> file with auth config and prepares the {target === 'typescript' ? 'Node.js' : 'Rust'} server.
                {transport === 'stdio' ? ' Uses stdio (Claude Desktop, Cursor, etc.).' : ` Listens on port ${httpPort} for SSE.`}
              </Typography>
            </Alert>
            <Button variant="contained" startIcon={deploying ? <CircularProgress size={16} color="inherit" /> : <RocketLaunchIcon />} onClick={handleDeploy} disabled={deploying} sx={{ mt: 2 }}>
              {deploying ? 'Preparing...' : 'Prepare Deployment'}
            </Button>
          </CardContent>
        </Card>

        {result && (
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <Chip size="small" label={result.status} color="success" />
                <Typography variant="body2" fontWeight={600}>Deployment Ready</Typography>
              </Box>
              <Box sx={{ mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                  <FolderOutlinedIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                  <Typography variant="overline" color="text.secondary">Server Path</Typography>
                </Box>
                <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', bgcolor: 'action.hover' }}>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem', wordBreak: 'break-all' }}>{result.server_path}</Typography>
                  <Tooltip title={copiedField === 'path' ? 'Copied!' : 'Copy'}>
                    <IconButton size="small" onClick={() => copy(result.server_path, 'path')}>
                      {copiedField === 'path' ? <CheckIcon sx={{ fontSize: 14 }} color="success" /> : <ContentCopyIcon sx={{ fontSize: 14 }} />}
                    </IconButton>
                  </Tooltip>
                </Paper>
              </Box>
              {result.command && (
                <Box sx={{ mb: 2 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                    <TerminalIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                    <Typography variant="overline" color="text.secondary">Start Command</Typography>
                  </Box>
                  <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', p: 1.5, bgcolor: 'grey.900' }}>
                      <Typography component="pre" sx={{ m: 0, fontFamily: 'monospace', fontSize: '0.75rem', color: '#d4d4d4', whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1 }}>{result.command}</Typography>
                      <Tooltip title={copiedField === 'cmd' ? 'Copied!' : 'Copy'}>
                        <IconButton size="small" onClick={() => copy(result.command, 'cmd')} sx={{ color: 'grey.400', ml: 1 }}>
                          {copiedField === 'cmd' ? <CheckIcon sx={{ fontSize: 14 }} /> : <ContentCopyIcon sx={{ fontSize: 14 }} />}
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Paper>
                </Box>
              )}
              <Divider sx={{ my: 2 }} />
              <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>Quick Start</Typography>
              <Stack spacing={0.75}>
                {['Copy and run the command above', transport === 'stdio' ? 'Add server to Claude Desktop / Cursor via stdio' : `Connect client to http://localhost:${httpPort}/sse`, 'Test tools in Forge Playground'].map((s, i) => (
                  <Box key={i} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Chip size="small" label={i + 1} sx={{ minWidth: 24, fontWeight: 700 }} />
                    <Typography variant="body2">{s}</Typography>
                  </Box>
                ))}
              </Stack>
            </CardContent>
          </Card>
        )}
      </>)}

      {deployments.length > 0 && (
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1.5 }}>
            <HistoryIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
            <Typography variant="subtitle2">Deployment History</Typography>
          </Box>
          <Stack spacing={0.75}>
            {deployments.map((d) => (
              <Card key={d.deployment_id}>
                <CardContent sx={{ py: 1.25, '&:last-child': { pb: 1.25 } }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                    <Chip size="small" label={d.target} variant="outlined" />
                    <Chip size="small" label={d.status} color="success" />
                    <Typography variant="caption" color="text.secondary">{fmtDate(d.created_at)}</Typography>
                  </Box>
                  {d.command && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace', flex: 1 }} noWrap>{d.command}</Typography>
                      <Tooltip title="Copy"><IconButton size="small" onClick={() => copy(d.command, d.deployment_id)}>
                        {copiedField === d.deployment_id ? <CheckIcon sx={{ fontSize: 12 }} color="success" /> : <ContentCopyIcon sx={{ fontSize: 12 }} />}
                      </IconButton></Tooltip>
                    </Box>
                  )}
                </CardContent>
              </Card>
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}

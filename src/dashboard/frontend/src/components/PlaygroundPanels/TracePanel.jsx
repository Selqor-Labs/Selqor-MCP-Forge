import React, { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RefreshIcon from "@mui/icons-material/Refresh";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { fetchPlaygroundTrace } from "../../api";

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function TracePanel({ sessionId, onToast }) {
  const [frames, setFrames] = useState([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await fetchPlaygroundTrace(sessionId, 25);
      setFrames(res.frames || []);
    } catch (err) {
      onToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sessionId]);

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle2" fontWeight={600}>
          JSON-RPC Trace
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {frames.length} frame{frames.length === 1 ? "" : "s"}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<RefreshIcon />} onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Stack>

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}>
          <CircularProgress size={24} />
        </Box>
      ) : frames.length === 0 ? (
        <Alert severity="info" sx={{ fontSize: "0.8rem" }}>
          Execute a tool (manually, via the test suite, or via the agent) to see JSON-RPC frames here.
        </Alert>
      ) : (
        <Stack spacing={1}>
          {frames.map((f) => (
            <Accordion key={f.id} disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", "&:before": { display: "none" } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, "& .MuiAccordionSummary-content": { my: 0.5, alignItems: "center", gap: 1 } }}>
                <Typography variant="caption" sx={{ fontFamily: "monospace", fontWeight: 600, flex: 1 }} noWrap>
                  {f.tool_name}
                </Typography>
                <Chip size="small" label={f.status} color={f.status === "error" ? "error" : "success"} sx={{ height: 18, fontSize: "0.65rem" }} />
                {f.origin && <Chip size="small" label={f.origin} variant="outlined" sx={{ height: 18, fontSize: "0.65rem" }} />}
                <Typography variant="caption" color="text.secondary">{f.latency_ms}ms</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={1}>
                  <Box>
                    <Stack direction="row" alignItems="center" sx={{ mb: 0.5 }}>
                      <Typography variant="caption" fontWeight={600}>Request</Typography>
                      <Box sx={{ flex: 1 }} />
                      <Tooltip title="Copy">
                        <IconButton size="small" onClick={async () => {
                          const ok = await copy(JSON.stringify(f.raw_rpc?.request || {}, null, 2));
                          onToast?.(ok ? "Copied" : "Copy failed", ok ? "" : "error");
                        }}>
                          <ContentCopyIcon fontSize="inherit" sx={{ fontSize: 14 }} />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                    <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontFamily: "monospace", fontSize: "0.7rem", overflow: "auto", maxHeight: 200 }}>
                      {JSON.stringify(f.raw_rpc?.request || {}, null, 2)}
                    </Box>
                  </Box>
                  <Box>
                    <Stack direction="row" alignItems="center" sx={{ mb: 0.5 }}>
                      <Typography variant="caption" fontWeight={600}>Response</Typography>
                      <Box sx={{ flex: 1 }} />
                      <Tooltip title="Copy">
                        <IconButton size="small" onClick={async () => {
                          const ok = await copy(JSON.stringify(f.raw_rpc?.response || {}, null, 2));
                          onToast?.(ok ? "Copied" : "Copy failed", ok ? "" : "error");
                        }}>
                          <ContentCopyIcon fontSize="inherit" sx={{ fontSize: 14 }} />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                    <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontFamily: "monospace", fontSize: "0.7rem", overflow: "auto", maxHeight: 300 }}>
                      {JSON.stringify(f.raw_rpc?.response || {}, null, 2)}
                    </Box>
                  </Box>
                </Stack>
              </AccordionDetails>
            </Accordion>
          ))}
        </Stack>
      )}
    </Box>
  );
}

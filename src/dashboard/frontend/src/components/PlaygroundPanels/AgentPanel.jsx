import React, { useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SendOutlinedIcon from "@mui/icons-material/SendOutlined";
import BoltOutlinedIcon from "@mui/icons-material/BoltOutlined";
import { playgroundAgentChat } from "../../api";

function TraceEntry({ entry }) {
  if (entry.role === "user") {
    return (
      <Paper variant="outlined" sx={{ p: 1.25, bgcolor: "action.hover" }}>
        <Typography variant="caption" color="text.secondary">you</Typography>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{entry.content}</Typography>
      </Paper>
    );
  }
  if (entry.role === "assistant") {
    const hasTools = (entry.tool_calls || []).length > 0;
    return (
      <Paper variant="outlined" sx={{ p: 1.25 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
          <Typography variant="caption" color="text.secondary">assistant</Typography>
          <Chip size="small" label={`turn ${entry.iteration || "?"}`} sx={{ height: 18, fontSize: "0.65rem" }} />
          {entry.stop_reason && <Chip size="small" label={entry.stop_reason} sx={{ height: 18, fontSize: "0.65rem" }} />}
        </Stack>
        {entry.text && (
          <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{entry.text}</Typography>
        )}
        {hasTools && (
          <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", mt: 0.5, "&:before": { display: "none" } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 32, "& .MuiAccordionSummary-content": { my: 0.25 } }}>
              <Typography variant="caption" fontWeight={600}>
                Wants to call {entry.tool_calls.length} tool{entry.tool_calls.length === 1 ? "" : "s"}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={0.5}>
                {entry.tool_calls.map((tc, i) => (
                  <Box key={i}>
                    <Typography variant="caption" sx={{ fontFamily: "monospace", fontWeight: 600 }}>
                      {tc.name}
                    </Typography>
                    <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontFamily: "monospace", fontSize: "0.7rem", overflow: "auto" }}>
                      {JSON.stringify(tc.arguments || {}, null, 2)}
                    </Box>
                  </Box>
                ))}
              </Stack>
            </AccordionDetails>
          </Accordion>
        )}
      </Paper>
    );
  }
  if (entry.role === "tool") {
    const ok = entry.status === "success";
    return (
      <Paper variant="outlined" sx={{ p: 1.25, borderColor: ok ? "success.main" : "error.main", bgcolor: ok ? "success.50" : "error.50", "&.MuiPaper-root": { bgcolor: "transparent" } }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
          <BoltOutlinedIcon fontSize="small" color={ok ? "success" : "error"} />
          <Typography variant="caption" sx={{ fontFamily: "monospace", fontWeight: 600 }}>{entry.tool_name}</Typography>
          <Chip size="small" label={entry.status} color={ok ? "success" : "error"} sx={{ height: 18, fontSize: "0.65rem" }} />
          {entry.latency_ms != null && (
            <Typography variant="caption" color="text.secondary">{entry.latency_ms}ms</Typography>
          )}
        </Stack>
        {entry.result_preview && (
          <Box component="pre" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontFamily: "monospace", fontSize: "0.7rem", overflow: "auto", maxHeight: 200 }}>
            {entry.result_preview}
          </Box>
        )}
        {entry.error && (
          <Typography variant="caption" color="error.main" sx={{ display: "block", mt: 0.5 }}>
            {entry.error}
          </Typography>
        )}
      </Paper>
    );
  }
  return null;
}

export default function AgentPanel({ sessionId, onToast, llmConfigs = [] }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);
  const [maxIter, setMaxIter] = useState(6);

  async function send() {
    if (!message.trim() || !sessionId) return;
    setBusy(true);
    try {
      const res = await playgroundAgentChat(sessionId, {
        message: message.trim(),
        max_iterations: maxIter,
      });
      setLast(res);
      if (res.status !== "completed") {
        onToast?.(`Agent stopped: ${res.status}${res.error ? ` — ${res.error}` : ""}`, "error");
      } else {
        onToast?.(`Agent used ${res.tools_used?.length || 0} tool call${res.tools_used?.length === 1 ? "" : "s"} in ${res.iterations} turn${res.iterations === 1 ? "" : "s"}`);
      }
    } catch (err) {
      onToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const toolsUsedCounts = (last?.tools_used || []).reduce((acc, t) => {
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  return (
    <Box>
      <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
        Agent Chat
      </Typography>
      <Alert severity="info" sx={{ fontSize: "0.8rem", mb: 1.5 }}>
        Types an intent → the default LLM uses the session's tools to answer. Surfaces which tool it picks and why — the real test of tool-description quality.
      </Alert>
      <Stack spacing={1.5}>
        <TextField
          multiline
          rows={3}
          size="small"
          placeholder="e.g. Find all pets with status 'available', then return the first two names."
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          disabled={busy}
          fullWidth
        />
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            size="small"
            type="number"
            label="Max iterations"
            value={maxIter}
            onChange={(e) => setMaxIter(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
            sx={{ width: 140 }}
          />
          <Box sx={{ flex: 1 }} />
          <Button
            variant="contained"
            size="small"
            onClick={send}
            disabled={busy || !sessionId || !message.trim()}
            startIcon={busy ? <CircularProgress size={14} color="inherit" /> : <SendOutlinedIcon />}
          >
            {busy ? "Running..." : "Send"}
          </Button>
        </Stack>

        {last && (
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1 }}>
              <Chip size="small" label={last.status} color={last.status === "completed" ? "success" : "warning"} />
              <Chip size="small" label={`${last.iterations} turn${last.iterations === 1 ? "" : "s"}`} />
              <Chip size="small" label={`${last.total_latency_ms || 0}ms`} />
              <Typography variant="caption" color="text.secondary">
                {last.llm_provider} · {last.llm_model}
              </Typography>
            </Stack>
            {Object.keys(toolsUsedCounts).length > 0 && (
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                {Object.entries(toolsUsedCounts).map(([name, count]) => (
                  <Chip key={name} size="small" variant="outlined" label={`${name} ×${count}`} sx={{ fontFamily: "monospace" }} />
                ))}
              </Stack>
            )}
            <Stack spacing={1}>
              {(last.trace || []).map((entry, i) => (
                <TraceEntry key={i} entry={entry} />
              ))}
            </Stack>
            {last.final_message && (
              <Alert severity="success" sx={{ mt: 1.5, whiteSpace: "pre-wrap" }}>
                {last.final_message}
              </Alert>
            )}
          </Paper>
        )}
      </Stack>
    </Box>
  );
}

import React, { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import IconButton from "@mui/material/IconButton";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Tooltip from "@mui/material/Tooltip";
import Popover from "@mui/material/Popover";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SendOutlinedIcon from "@mui/icons-material/SendOutlined";
import BoltOutlinedIcon from "@mui/icons-material/BoltOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ClearAllOutlinedIcon from "@mui/icons-material/ClearAllOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import { playgroundAgentChat } from "../../api";

const EXAMPLE_PROMPTS = [
  "List everything you can do",
  "Show me all available items",
  "Create a test entry and then fetch it back",
];

function ToolCallsAccordion({ trace }) {
  const toolEntries = (trace || []).filter((e) => e.role === "tool");
  if (toolEntries.length === 0) return null;
  return (
    <Accordion
      disableGutters
      elevation={0}
      sx={{
        border: "1px solid",
        borderColor: "divider",
        bgcolor: "transparent",
        mt: 1,
        "&:before": { display: "none" },
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{ minHeight: 32, "& .MuiAccordionSummary-content": { my: 0.5 } }}
      >
        <Typography variant="caption" fontWeight={600}>
          {toolEntries.length} tool call{toolEntries.length === 1 ? "" : "s"} · click to inspect
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={0.75}>
          {toolEntries.map((entry, i) => {
            const ok = entry.status === "success";
            return (
              <Box key={i}>
                <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.25 }}>
                  <BoltOutlinedIcon fontSize="small" color={ok ? "success" : "error"} />
                  <Typography variant="caption" sx={{ fontFamily: "monospace", fontWeight: 600 }}>
                    {entry.tool_name}
                  </Typography>
                  <Chip
                    size="small"
                    label={entry.status}
                    color={ok ? "success" : "error"}
                    sx={{ height: 16, fontSize: "0.62rem" }}
                  />
                  {entry.latency_ms != null && (
                    <Typography variant="caption" color="text.secondary">
                      {entry.latency_ms}ms
                    </Typography>
                  )}
                </Stack>
                {entry.result_preview && (
                  <Box
                    component="pre"
                    sx={{
                      m: 0,
                      p: 1,
                      bgcolor: "action.hover",
                      borderRadius: 1,
                      fontFamily: "monospace",
                      fontSize: "0.7rem",
                      overflow: "auto",
                      maxHeight: 180,
                    }}
                  >
                    {entry.result_preview}
                  </Box>
                )}
                {entry.error && (
                  <Typography variant="caption" color="error.main" sx={{ display: "block", mt: 0.25 }}>
                    {entry.error}
                  </Typography>
                )}
              </Box>
            );
          })}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}

function UserBubble({ content }) {
  return (
    <Stack direction="row" justifyContent="flex-end" sx={{ px: 1.5, pt: 1 }}>
      <Paper
        elevation={0}
        sx={{
          p: 1.25,
          maxWidth: "78%",
          bgcolor: "primary.main",
          color: "primary.contrastText",
          borderRadius: 2,
          borderTopRightRadius: 4,
        }}
      >
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
          {content}
        </Typography>
      </Paper>
    </Stack>
  );
}

function AgentBubble({ result }) {
  const toolsUsedCounts = (result.tools_used || []).reduce((acc, t) => {
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});
  const final = result.final_message || "(no final response)";
  const isError = result.status && result.status !== "completed";

  return (
    <Stack direction="row" justifyContent="flex-start" sx={{ px: 1.5, pt: 1 }}>
      <Paper
        variant="outlined"
        sx={{
          p: 1.25,
          maxWidth: "88%",
          borderRadius: 2,
          borderTopLeftRadius: 4,
          borderColor: isError ? "warning.main" : "divider",
        }}
      >
        <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.75 }}>
          <AutoAwesomeOutlinedIcon fontSize="small" color="primary" />
          <Typography variant="caption" fontWeight={600} color="text.secondary">
            agent
          </Typography>
          {result.status && (
            <Chip
              size="small"
              label={result.status}
              color={isError ? "warning" : "success"}
              variant="outlined"
              sx={{ height: 18, fontSize: "0.65rem" }}
            />
          )}
          {result.iterations != null && (
            <Chip
              size="small"
              label={`${result.iterations} turn${result.iterations === 1 ? "" : "s"}`}
              sx={{ height: 18, fontSize: "0.65rem" }}
            />
          )}
          {result.total_latency_ms != null && (
            <Typography variant="caption" color="text.secondary">
              {result.total_latency_ms}ms
            </Typography>
          )}
        </Stack>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
          {final}
        </Typography>
        {Object.keys(toolsUsedCounts).length > 0 && (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            {Object.entries(toolsUsedCounts).map(([name, count]) => (
              <Chip
                key={name}
                size="small"
                variant="outlined"
                label={`${name} ×${count}`}
                sx={{ fontFamily: "monospace", height: 20, fontSize: "0.65rem" }}
              />
            ))}
          </Stack>
        )}
        <ToolCallsAccordion trace={result.trace} />
        {(result.llm_provider || result.llm_model) && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75 }}>
            {result.llm_provider}
            {result.llm_model ? ` · ${result.llm_model}` : ""}
          </Typography>
        )}
      </Paper>
    </Stack>
  );
}

function PendingBubble() {
  return (
    <Stack direction="row" justifyContent="flex-start" sx={{ px: 1.5, pt: 1 }}>
      <Paper
        variant="outlined"
        sx={{ p: 1.25, borderRadius: 2, borderTopLeftRadius: 4, display: "flex", alignItems: "center", gap: 1 }}
      >
        <CircularProgress size={14} />
        <Typography variant="body2" color="text.secondary">
          Agent is picking a tool…
        </Typography>
      </Paper>
    </Stack>
  );
}

function EmptyState({ onPick }) {
  return (
    <Box sx={{ p: 3, textAlign: "center", color: "text.secondary" }}>
      <AutoAwesomeOutlinedIcon sx={{ fontSize: 32, mb: 1, opacity: 0.7 }} />
      <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.5 }}>
        Test your tools in plain English
      </Typography>
      <Typography variant="caption" sx={{ display: "block", maxWidth: 480, mx: "auto", mb: 2 }}>
        Ask the agent something — it will pick a tool, call it, and show you exactly which one it chose and why.
        This is the real test of whether your tool descriptions make sense to an LLM.
      </Typography>
      <Stack direction="row" spacing={0.75} justifyContent="center" flexWrap="wrap" useFlexGap>
        {EXAMPLE_PROMPTS.map((p) => (
          <Chip
            key={p}
            label={p}
            size="small"
            variant="outlined"
            onClick={() => onPick(p)}
            sx={{ cursor: "pointer" }}
          />
        ))}
      </Stack>
    </Box>
  );
}

export default function AgentPanel({ sessionId, onToast }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const [maxIter, setMaxIter] = useState(6);
  const [settingsAnchor, setSettingsAnchor] = useState(null);
  const scrollRef = useRef(null);

  // Reset conversation when session changes
  useEffect(() => {
    setMessages([]);
  }, [sessionId]);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, busy]);

  async function send(text) {
    const content = (text ?? message).trim();
    if (!content || !sessionId || busy) return;
    setMessage("");
    setMessages((prev) => [...prev, { role: "user", content }]);
    setBusy(true);
    try {
      const res = await playgroundAgentChat(sessionId, {
        message: content,
        max_iterations: maxIter,
      });
      setMessages((prev) => [...prev, { role: "agent", result: res }]);
      if (res.status !== "completed") {
        onToast?.(`Agent stopped: ${res.status}${res.error ? ` — ${res.error}` : ""}`, "error");
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "agent", result: { status: "error", final_message: err.message, trace: [] } },
      ]);
      onToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        flex: 1,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ px: 1.5, py: 1, borderBottom: "1px solid", borderColor: "divider" }}
      >
        <AutoAwesomeOutlinedIcon fontSize="small" color="primary" />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" fontWeight={600} lineHeight={1.2}>
            Agent Chat
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Ask a question — the LLM picks which of your tools to call.
          </Typography>
        </Box>
        <Tooltip title="Agent settings">
          <IconButton
            size="small"
            onClick={(e) => setSettingsAnchor(e.currentTarget)}
          >
            <TuneOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        {messages.length > 0 && (
          <Tooltip title="Clear conversation">
            <IconButton size="small" onClick={() => setMessages([])} disabled={busy}>
              <ClearAllOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Stack>

      <Popover
        open={Boolean(settingsAnchor)}
        anchorEl={settingsAnchor}
        onClose={() => setSettingsAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ paper: { sx: { p: 2, width: 280 } } }}
      >
        <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 0.25 }}>
          Agent settings
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          Safety cap on the think → call-tool → read-result loop. After this many
          round-trips the agent is forced to stop even if it still wants to keep
          going. Higher = more complex multi-step queries; lower = tighter cost
          control.
        </Typography>
        <TextField
          size="small"
          type="number"
          label="Max turns"
          value={maxIter}
          onChange={(e) => setMaxIter(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
          inputProps={{ min: 1, max: 12 }}
          fullWidth
          helperText="Between 1 and 12 · default 6"
        />
      </Popover>

      {/* Conversation */}
      <Box
        ref={scrollRef}
        sx={{
          flex: 1,
          overflowY: "auto",
          bgcolor: "background.default",
          py: 1,
        }}
      >
        {messages.length === 0 && !busy ? (
          <EmptyState onPick={(p) => send(p)} />
        ) : (
          <>
            {messages.map((m, i) =>
              m.role === "user" ? (
                <UserBubble key={i} content={m.content} />
              ) : (
                <AgentBubble key={i} result={m.result} />
              )
            )}
            {busy && <PendingBubble />}
          </>
        )}
      </Box>

      {/* Composer */}
      <Stack
        direction="row"
        spacing={1}
        alignItems="flex-end"
        sx={{ p: 1, borderTop: "1px solid", borderColor: "divider" }}
      >
        <TextField
          fullWidth
          multiline
          maxRows={4}
          size="small"
          placeholder={
            sessionId
              ? "Type a request — e.g. 'Create a pet named Rex and show me everything available'"
              : "Connect to a session first"
          }
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!sessionId || busy}
        />
        <Tooltip title="Send (Enter)">
          <span>
            <IconButton
              color="primary"
              onClick={() => send()}
              disabled={busy || !sessionId || !message.trim()}
              sx={{ border: "1px solid", borderColor: "divider" }}
            >
              {busy ? <CircularProgress size={18} /> : <SendOutlinedIcon fontSize="small" />}
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    </Paper>
  );
}

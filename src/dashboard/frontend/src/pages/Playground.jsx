import React from "react";
import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import TextField from "@mui/material/TextField";
import Autocomplete from "@mui/material/Autocomplete";
import InputAdornment from "@mui/material/InputAdornment";
import CircularProgress from "@mui/material/CircularProgress";
import LogoLoader from "../components/LogoLoader";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Alert from "@mui/material/Alert";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogActions from "@mui/material/DialogActions";
import MenuItem from "@mui/material/MenuItem";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import PlayArrowOutlinedIcon from "@mui/icons-material/PlayArrowOutlined";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import MonitorHeartOutlinedIcon from "@mui/icons-material/MonitorHeartOutlined";
import SearchIcon from "@mui/icons-material/Search";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import useStore from "../store/useStore";
import ToolingComparison from "../components/ToolingComparison";
import TestCasesPanel from "../components/PlaygroundPanels/TestCasesPanel";
import AgentPanel from "../components/PlaygroundPanels/AgentPanel";
import TracePanel from "../components/PlaygroundPanels/TracePanel";
import StatsPanel from "../components/PlaygroundPanels/StatsPanel";
import {
  fetchPlaygroundSessions,
  connectPlaygroundServer,
  disconnectPlaygroundSession,
  fetchPlaygroundTools,
  executePlaygroundTool,
  fetchPlaygroundHistory,
  playgroundHealthCheck,
  fetchAvailableIntegrations,
  autoConnectIntegration,
  suggestPlaygroundArgs,
} from "../api";

// --------------------------------------------------------------------------
// JSON Schema helpers — mirror how Claude constructs tool arguments
// --------------------------------------------------------------------------

/** Pick a single type string from a schema that may declare multiple. */
function resolveType(schema) {
  const t = schema?.type;
  if (Array.isArray(t)) return t.find((x) => x !== "null") || t[0];
  return t;
}

/**
 * Build a JSON template from a JSON Schema.
 * Includes all required fields with sensible example values so users get
 * a usable starting point instead of an empty object.
 */
function schemaToTemplate(schema) {
  if (!schema || typeof schema !== "object") return null;
  if (schema.default !== undefined) return schema.default;
  if (schema.example !== undefined) return schema.example;
  if (Array.isArray(schema.enum) && schema.enum.length > 0)
    return schema.enum[0];

  const type = resolveType(schema);
  switch (type) {
    case "string":
      if (schema.format === "date-time") return new Date().toISOString();
      if (schema.format === "date")
        return new Date().toISOString().slice(0, 10);
      if (schema.format === "email") return "user@example.com";
      if (schema.format === "uri" || schema.format === "url")
        return "https://example.com";
      return "";
    case "integer":
      return 0;
    case "number":
      return 0;
    case "boolean":
      return false;
    case "array": {
      const item = schema.items ? schemaToTemplate(schema.items) : null;
      return item === null || item === undefined ? [] : [item];
    }
    case "object":
    case undefined: {
      const obj = {};
      const props = schema.properties || {};
      const required = new Set(schema.required || []);
      for (const key of required) {
        if (props[key]) obj[key] = schemaToTemplate(props[key]);
      }
      return obj;
    }
    case "null":
      return null;
    default:
      return null;
  }
}

/** Flatten top-level schema properties into a list for the details table. */
function summarizeSchema(schema) {
  if (!schema || typeof schema !== "object") return [];
  const props = schema.properties || {};
  const required = new Set(schema.required || []);
  return Object.entries(props).map(([name, prop]) => {
    const type = Array.isArray(prop.type)
      ? prop.type.join(" | ")
      : prop.type || "any";
    const enumStr = Array.isArray(prop.enum)
      ? ` (${prop.enum.slice(0, 4).join(", ")}${prop.enum.length > 4 ? "…" : ""})`
      : "";
    return {
      name,
      type: `${type}${enumStr}`,
      required: required.has(name),
      description: prop.description || "",
    };
  });
}

/**
 * Render an MCP tool_call result's ``content[]`` array.
 * Each item may be ``{type:'text',text:'…'}`` or ``{type:'image',data:…}``.
 * Returns a list of { kind, value } items for display.
 */
function parseMcpContent(result) {
  if (!result) return [];
  const content = result.content;
  if (!Array.isArray(content)) {
    return [{ kind: "json", value: JSON.stringify(result, null, 2) }];
  }
  return content.map((item) => {
    if (item.type === "text") {
      const text = item.text || "";
      // Try pretty-print as JSON
      try {
        const parsed = JSON.parse(text);
        return { kind: "json", value: JSON.stringify(parsed, null, 2) };
      } catch {
        return { kind: "text", value: text };
      }
    }
    if (item.type === "image") {
      const mime = item.mimeType || "image/png";
      return { kind: "image", value: `data:${mime};base64,${item.data || ""}` };
    }
    return { kind: "json", value: JSON.stringify(item, null, 2) };
  });
}

/** Copy text to the clipboard, with graceful fallback. */
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Build a shareable curl command that reproduces the current execute request. */
function buildCurlCommand(sessionId, toolName, args) {
  const body = JSON.stringify({ tool_name: toolName, arguments: args });
  return `curl -X POST 'http://localhost:8787/api/playground/sessions/${sessionId}/execute' \\\n  -H 'Content-Type: application/json' \\\n  -d '${body.replace(/'/g, "'\\''")}'`;
}

// --------------------------------------------------------------------------

export default function Playground() {
  const toast = useStore((s) => s.toast);
  const [sessions, setSessions] = useState([]);
  const [availableIntegrations, setAvailableIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState(null);
  const [sessionHealth, setSessionHealth] = useState({});
  const [healthChecking, setHealthChecking] = useState({});

  // Active session state
  const [activeSession, setActiveSession] = useState(null);
  const [tools, setTools] = useState([]);
  const [history, setHistory] = useState([]);
  const [selectedTool, setSelectedTool] = useState(null);
  const [toolArgs, setToolArgs] = useState("{}");
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState(null);

  // AI-fill dialog state
  const [aiOpen, setAiOpen] = useState(false);
  const [aiIntent, setAiIntent] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  // Active tab in the right-hand pane: tools | tests | agent | trace | stats
  const [activeTab, setActiveTab] = useState("tools");

  // Connect form
  const [form, setForm] = useState({
    name: "",
    transport: "stdio",
    command: "",
    server_url: "",
  });

  const selectedToolDef = useMemo(
    () => tools.find((t) => (t.name || t) === selectedTool) || null,
    [tools, selectedTool],
  );

  // Feature 4 — look up the integration backing the active session so we
  // can render a baseline-vs-curated panel. Auto-connected sessions are
  // named after the integration, so name-matching is reliable in practice
  // for the auto-connect flow; manual connects simply won't get the
  // comparison (there's no baseline to compare against anyway).
  const activeIntegration = useMemo(() => {
    if (!activeSession) return null;
    const name = activeSession.name;
    if (!name) return null;
    return (
      availableIntegrations.find(
        (i) => i.integration_name === name || i.integration_id === name,
      ) || null
    );
  }, [activeSession, availableIntegrations]);
  const schema =
    selectedToolDef?.inputSchema || selectedToolDef?.input_schema || null;
  const schemaFields = useMemo(() => summarizeSchema(schema), [schema]);
  const requiredFields = schemaFields.filter((f) => f.required);
  const optionalFields = schemaFields.filter((f) => !f.required);

  async function loadSessions() {
    try {
      const [sessRes, intRes] = await Promise.all([
        fetchPlaygroundSessions(),
        fetchAvailableIntegrations().catch(() => ({ integrations: [] })),
      ]);
      const allSessions = sessRes.sessions || [];
      setSessions(allSessions);
      setAvailableIntegrations(intRes.integrations || []);
      // Auto-select the first connected session on load so the user lands on
      // something usable instead of an empty pane.
      if (!activeSession) {
        const firstConnected = allSessions.find((s) => s.status === "connected");
        if (firstConnected) {
          selectSession(firstConnected);
        }
      }
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSessions(); /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, []);

  async function handleConnect(e) {
    e.preventDefault();
    setConnecting("manual");
    try {
      const res = await connectPlaygroundServer(form);
      toast("Connected to MCP server");
      setConnectOpen(false);
      setForm({ name: "", transport: "stdio", command: "", server_url: "" });
      await loadSessions();
      selectSession(res);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setConnecting(null);
    }
  }

  async function handleAutoConnect(integration) {
    setConnecting(integration.integration_id);
    try {
      const res = await autoConnectIntegration(integration.integration_id);
      toast(`Connected to ${integration.integration_name}`);
      loadSessions();
      selectSession(res);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setConnecting(null);
    }
  }

  function pickTool(toolDef) {
    const name = toolDef.name || toolDef;
    setSelectedTool(name);
    setExecResult(null);
    const sch = toolDef.inputSchema || toolDef.input_schema;
    const template = schemaToTemplate(sch) ?? {};
    setToolArgs(JSON.stringify(template, null, 2));
  }

  async function selectSession(session) {
    const id = session.id;
    setActiveSession(session);
    setExecResult(null);
    setSelectedTool(null);
    setToolArgs("{}");
    try {
      const [t, h] = await Promise.all([
        fetchPlaygroundTools(id),
        fetchPlaygroundHistory(id).catch(() => ({ executions: [] })),
      ]);
      const loaded = t.tools || [];
      setTools(loaded);
      setHistory(h.executions || []);
      // Auto-select the first tool so the user gets a populated editor immediately
      if (loaded.length > 0) pickTool(loaded[0]);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function handleDisconnect() {
    if (!disconnectTarget) return;
    try {
      await disconnectPlaygroundSession(disconnectTarget);
      toast("Session disconnected");
      if (activeSession?.id === disconnectTarget) {
        setActiveSession(null);
        setTools([]);
        setHistory([]);
        setSelectedTool(null);
      }
      setSessionHealth((prev) => {
        const { [disconnectTarget]: _, ...rest } = prev;
        return rest;
      });
      loadSessions();
    } catch (err) {
      toast(err.message, "error");
    }
    setDisconnectTarget(null);
  }

  function validateArgs() {
    let parsed;
    try {
      parsed = JSON.parse(toolArgs || "{}");
    } catch (err) {
      toast(`Invalid JSON: ${err.message}`, "error");
      return null;
    }
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      toast("Arguments must be a JSON object", "error");
      return null;
    }
    // Required-field check based on schema
    const missing = requiredFields
      .map((f) => f.name)
      .filter((name) => !(name in parsed));
    if (missing.length > 0) {
      toast(`Missing required field(s): ${missing.join(", ")}`, "error");
      return null;
    }
    return parsed;
  }

  async function handleExecute() {
    if (!activeSession || !selectedTool) return;
    const args = validateArgs();
    if (args === null) return;
    setExecuting(true);
    setExecResult(null);
    try {
      const res = await executePlaygroundTool(activeSession.id, {
        tool_name: selectedTool,
        arguments: args,
      });
      setExecResult(res);
      if (res.status === "error") {
        toast(res.error || "Execution failed", "error");
      } else {
        toast(`Executed in ${res.latency_ms}ms`);
      }
      const h = await fetchPlaygroundHistory(activeSession.id).catch(() => ({
        executions: [],
      }));
      setHistory(h.executions || []);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setExecuting(false);
    }
  }

  async function handleAiSuggest() {
    if (!activeSession || !selectedTool) return;
    setAiBusy(true);
    try {
      const res = await suggestPlaygroundArgs(activeSession.id, {
        tool_name: selectedTool,
        intent: aiIntent.trim(),
      });
      setToolArgs(JSON.stringify(res.arguments || {}, null, 2));
      toast(`Arguments generated by ${res.model || "LLM"}`);
      setAiOpen(false);
      setAiIntent("");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setAiBusy(false);
    }
  }

  async function handleCopyArgs() {
    const ok = await copyToClipboard(toolArgs);
    toast(ok ? "Arguments copied" : "Copy failed", ok ? "" : "error");
  }

  async function handleCopyCurl() {
    if (!activeSession || !selectedTool) return;
    let args;
    try {
      args = JSON.parse(toolArgs || "{}");
    } catch {
      args = {};
    }
    const cmd = buildCurlCommand(activeSession.id, selectedTool, args);
    const ok = await copyToClipboard(cmd);
    toast(ok ? "curl command copied" : "Copy failed", ok ? "" : "error");
  }

  function rerunFromHistory(entry) {
    if (!entry) return;
    // Switch to the tool in the history row
    const def = tools.find((t) => (t.name || t) === entry.tool_name);
    if (def) setSelectedTool(entry.tool_name);
    setToolArgs(JSON.stringify(entry.arguments || {}, null, 2));
    setExecResult(null);
  }

  function resetTemplate() {
    if (!selectedToolDef) return;
    const template = schemaToTemplate(schema) ?? {};
    setToolArgs(JSON.stringify(template, null, 2));
    toast("Arguments reset to schema template");
  }

  async function handleSessionHealthCheck(sessionId, e) {
    e?.stopPropagation();
    if (!sessionId) return;
    setHealthChecking((prev) => ({ ...prev, [sessionId]: true }));
    try {
      const res = await playgroundHealthCheck(sessionId);
      setSessionHealth((prev) => ({
        ...prev,
        [sessionId]: {
          healthy: res.healthy,
          reason: res.reason,
          checkedAt: Date.now(),
        },
      }));
      toast(
        res.healthy
          ? "Server healthy"
          : `Unhealthy: ${res.reason || "unknown"}`,
        res.healthy ? "" : "error",
      );
    } catch (err) {
      setSessionHealth((prev) => ({
        ...prev,
        [sessionId]: { healthy: false, reason: err.message, checkedAt: Date.now() },
      }));
      toast(err.message, "error");
    } finally {
      setHealthChecking((prev) => ({ ...prev, [sessionId]: false }));
    }
  }

  if (loading) {
    return (
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "50vh",
        }}
      >
        <LogoLoader size={96} message="Loading playground…" />
      </Box>
    );
  }

  const resultItems =
    execResult && execResult.status === "success"
      ? parseMcpContent(execResult.result)
      : [];
  const isErrorResult = execResult && execResult.status === "error";

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: { xs: "column", md: "row" },
        gap: 2,
        alignItems: "flex-start",
      }}
    >
      {/* Sessions Panel — sticky to top of main scroll container */}
      <Box
        sx={{
          width: { xs: "100%", md: 280 },
          flexShrink: 0,
          position: "sticky",
          top: 0,
          zIndex: 3,
          // Cover the page background so content scrolling underneath doesn't bleed through
          bgcolor: "background.default",
          pb: { xs: 1, md: 0 },
        }}
      >
        <Paper
          variant="outlined"
          sx={{
            display: "flex",
            flexDirection: "column",
            maxHeight: { xs: 320, md: "calc(100vh - 130px)" },
            overflow: "hidden",
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              px: 1.5,
              py: 1,
              bgcolor: "background.paper",
              borderBottom: "1px solid",
              borderColor: "divider",
              flexShrink: 0,
            }}
          >
            <Typography variant="subtitle2" fontWeight={600}>
              Sessions
            </Typography>
            <Button
              size="small"
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setConnectOpen(true)}
            >
              Connect
            </Button>
          </Box>

          <Box sx={{ flex: 1, overflow: "auto" }}>
            {sessions.length === 0 && availableIntegrations.length === 0 ? (
              <Box
                sx={{ p: 2, display: "flex", flexDirection: "column", gap: 2 }}
              >
                <Alert severity="info" sx={{ fontSize: "0.8rem", mb: 0 }}>
                  <Typography
                    variant="subtitle2"
                    sx={{ fontWeight: 600, mb: 0.5 }}
                  >
                    No active sessions
                  </Typography>
                  <Typography variant="caption" component="div" sx={{ mb: 1 }}>
                    Test MCP servers before deploying them. You can either:
                  </Typography>
                  <ul style={{ margin: "0.5rem 0", paddingLeft: "1.2rem" }}>
                    <li>
                      <Typography variant="caption" component="span">
                        Complete an integration workflow first (recommended)
                      </Typography>
                    </li>
                    <li>
                      <Typography variant="caption" component="span">
                        Manually connect an MCP server using the button above
                      </Typography>
                    </li>
                  </ul>
                </Alert>
              </Box>
            ) : (
              <>
                {availableIntegrations.length > 0 && (
                  <Box
                    sx={{
                      p: 1.5,
                      borderBottom: "1px solid",
                      borderColor: "divider",
                    }}
                  >
                    <Typography
                      variant="caption"
                      fontWeight={600}
                      color="text.secondary"
                      sx={{ mb: 0.75, display: "block" }}
                    >
                      QUICK CONNECT
                    </Typography>
                    <Stack spacing={0.75}>
                      {availableIntegrations.map((int) => (
                        <Button
                          key={int.integration_id}
                          variant="outlined"
                          size="small"
                          fullWidth
                          onClick={() => handleAutoConnect(int)}
                          disabled={connecting === int.integration_id}
                          sx={{
                            justifyContent: "flex-start",
                            textAlign: "left",
                            py: 0.5,
                          }}
                        >
                          <Stack
                            direction="column"
                            spacing={0}
                            sx={{ flex: 1, minWidth: 0 }}
                          >
                            <Typography variant="body2" fontWeight={500} noWrap>
                              {int.integration_name}
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              noWrap
                            >
                              {int.connection.transport === "http"
                                ? int.connection.server_url
                                : "stdio"}
                            </Typography>
                          </Stack>
                          {connecting === int.integration_id && (
                            <CircularProgress size={14} sx={{ ml: 1 }} />
                          )}
                        </Button>
                      ))}
                    </Stack>
                  </Box>
                )}
                <List disablePadding dense>
                  {sessions.map((s) => {
                    const isConnected = s.status === "connected";
                    return (
                    <React.Fragment key={s.id}>
                      <ListItemButton
                        selected={activeSession?.id === s.id}
                        onClick={() => {
                          if (!isConnected) {
                            toast(
                              "Session is disconnected. Delete it and reconnect from the Connect button.",
                              "error",
                            );
                            return;
                          }
                          selectSession(s);
                        }}
                        sx={{
                          pr: 5,
                          position: "relative",
                          opacity: isConnected ? 1 : 0.55,
                          cursor: isConnected ? "pointer" : "not-allowed",
                        }}
                      >
                        <ListItemText
                          primaryTypographyProps={{ component: "div" }}
                          secondaryTypographyProps={{ component: "div" }}
                          primary={
                            <Stack direction="row" alignItems="center" spacing={0.75}>
                              <Box
                                sx={{
                                  width: 7,
                                  height: 7,
                                  borderRadius: "50%",
                                  flexShrink: 0,
                                  bgcolor: isConnected ? "success.main" : "error.main",
                                }}
                              />
                              <Typography variant="body2" fontWeight={500} noWrap>
                                {s.name || s.id}
                              </Typography>
                            </Stack>
                          }
                          secondary={
                            <Stack
                              direction="row"
                              spacing={0.75}
                              alignItems="center"
                              sx={{ mt: 0.25 }}
                            >
                              <Typography
                                variant="caption"
                                color="text.secondary"
                              >
                                {s.transport}
                              </Typography>
                              {!isConnected && (
                                <Typography
                                  variant="caption"
                                  color="error.main"
                                  fontWeight={600}
                                >
                                  · disconnected
                                </Typography>
                              )}
                              <Chip
                                label={`${s.tools_count || 0} tools`}
                                size="small"
                                sx={{ height: 16, fontSize: "0.65rem" }}
                              />
                            </Stack>
                          }
                        />
                        <Tooltip
                          title={
                            sessionHealth[s.id]
                              ? sessionHealth[s.id].healthy
                                ? "Healthy — click to recheck"
                                : `Unhealthy: ${sessionHealth[s.id].reason || "unknown"} — click to recheck`
                              : "Check health"
                          }
                        >
                          <IconButton
                            size="small"
                            color={
                              sessionHealth[s.id]
                                ? sessionHealth[s.id].healthy
                                  ? "success"
                                  : "error"
                                : "default"
                            }
                            sx={{ position: "absolute", top: 6, right: 30 }}
                            disabled={!!healthChecking[s.id]}
                            onClick={(e) => handleSessionHealthCheck(s.id, e)}
                          >
                            {healthChecking[s.id] ? (
                              <CircularProgress size={12} />
                            ) : (
                              <MonitorHeartOutlinedIcon sx={{ fontSize: 14 }} />
                            )}
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete session">
                          <IconButton
                            size="small"
                            color="error"
                            sx={{ position: "absolute", top: 6, right: 6 }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setDisconnectTarget(s.id);
                            }}
                          >
                            <DeleteOutlineIcon sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Tooltip>
                      </ListItemButton>
                      <Divider component="li" />
                    </React.Fragment>
                    );
                  })}
                </List>
              </>
            )}
          </Box>
        </Paper>
      </Box>

      {/* Tool Execution Panel */}
      <Box sx={{ flex: 1, minWidth: 0, width: "100%" }}>
        {!activeSession ? (
          <Paper
            variant="outlined"
            sx={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              minHeight: 320,
              gap: 1.5,
              p: 3,
            }}
          >
            <PlayArrowOutlinedIcon
              sx={{ fontSize: 48, color: "text.disabled" }}
            />
            <Typography variant="body1" color="text.secondary">
              Select a session to explore and test tools
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ maxWidth: 420, textAlign: "center" }}
            >
              Tools are discovered via the MCP <code>tools/list</code> call.
              Arguments are generated from each tool's JSON Schema, just like
              Claude does when invoking tools.
            </Typography>
          </Paper>
        ) : (
          <Stack spacing={2}>
            {/* Session header */}
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 1,
              }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="subtitle1" fontWeight={600} noWrap>
                  {activeSession.name || activeSession.id}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {tools.length} tool{tools.length === 1 ? "" : "s"} available ·{" "}
                  {activeSession.transport || "mcp"} transport
                </Typography>
              </Box>
            </Box>

            {/* Feature 4 — baseline vs curated. Only rendered for
                  sessions auto-connected from a Selqor integration, since
                  we need the original endpoint count to compute the
                  baseline column. */}
            {activeIntegration && activeIntegration.endpoint_count > 0 && (
              <ToolingComparison
                tools={tools}
                endpointCount={activeIntegration.endpoint_count}
              />
            )}

            {/* Tabs — surface richer workflows beyond one-off tool execution.
                  Each tab is a self-contained component so the shared Playground
                  state (session, selected tool, tools list) stays in this page. */}
            <Tabs
              value={activeTab}
              onChange={(_, v) => setActiveTab(v)}
              variant="scrollable"
              scrollButtons="auto"
              sx={{ borderBottom: 1, borderColor: "divider", minHeight: 36 }}
            >
              <Tab value="tools" label="Tools" sx={{ minHeight: 36, textTransform: "none" }} />
              <Tab value="tests" label="Tests" sx={{ minHeight: 36, textTransform: "none" }} />
              <Tab value="agent" label="Agent Chat" sx={{ minHeight: 36, textTransform: "none" }} />
              <Tab value="trace" label="Trace" sx={{ minHeight: 36, textTransform: "none" }} />
              <Tab value="stats" label="Stats" sx={{ minHeight: 36, textTransform: "none" }} />
            </Tabs>

            {activeTab === "tests" && (
              <Paper variant="outlined" sx={{ p: 2 }}>
                <TestCasesPanel
                  sessionId={activeSession.id}
                  toolName={selectedTool}
                  toolArgs={toolArgs}
                  onToast={toast}
                />
              </Paper>
            )}
            {activeTab === "agent" && (
              <Box
                sx={{
                  position: "sticky",
                  top: 0,
                  height: "calc(100vh - 180px)",
                  minHeight: 420,
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <AgentPanel sessionId={activeSession.id} onToast={toast} />
              </Box>
            )}
            {activeTab === "trace" && (
              <Paper variant="outlined" sx={{ p: 2 }}>
                <TracePanel sessionId={activeSession.id} onToast={toast} />
              </Paper>
            )}
            {activeTab === "stats" && (
              <Paper variant="outlined" sx={{ p: 2 }}>
                <StatsPanel sessionId={activeSession.id} onToast={toast} />
              </Paper>
            )}

            {/* Tool picker — searchable dropdown so the Tools tab stays
                usable as MCPs grow from a handful to 50+ tools. */}
            {activeTab === "tools" && (
              tools.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No tools available for this session.
                </Typography>
              ) : (
                <Autocomplete
                  size="small"
                  options={tools}
                  value={selectedToolDef}
                  onChange={(_evt, option) => {
                    if (option) pickTool(option);
                    else setSelectedTool(null);
                  }}
                  getOptionLabel={(option) =>
                    typeof option === "string" ? option : option?.name || ""
                  }
                  isOptionEqualToValue={(a, b) =>
                    (a?.name || a) === (b?.name || b)
                  }
                  renderOption={(props, option) => {
                    const { key, ...rest } = props;
                    return (
                      <li key={key} {...rest}>
                        <Box sx={{ display: "flex", flexDirection: "column" }}>
                          <Typography
                            variant="body2"
                            fontWeight={600}
                            sx={{ fontFamily: "monospace" }}
                          >
                            {option.name}
                          </Typography>
                          {option.description && (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                maxWidth: 560,
                              }}
                            >
                              {option.description}
                            </Typography>
                          )}
                        </Box>
                      </li>
                    );
                  }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      placeholder={`Search ${tools.length} tool${
                        tools.length === 1 ? "" : "s"
                      } by name or description`}
                      InputProps={{
                        ...params.InputProps,
                        startAdornment: (
                          <>
                            <InputAdornment position="start">
                              <SearchIcon fontSize="small" />
                            </InputAdornment>
                            {params.InputProps.startAdornment}
                          </>
                        ),
                      }}
                    />
                  )}
                  sx={{ maxWidth: 560 }}
                />
              )
            )}

            {/* Selected tool execution */}
            {activeTab === "tools" && selectedTool && selectedToolDef && (
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="body2" fontWeight={600}>
                      {selectedTool}
                    </Typography>
                    {selectedToolDef.description && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: "block", mt: 0.25 }}
                      >
                        {selectedToolDef.description}
                      </Typography>
                    )}
                  </Box>

                  {/* Schema details */}
                  {schemaFields.length > 0 && (
                    <Accordion
                      disableGutters
                      elevation={0}
                      sx={{
                        border: "1px solid",
                        borderColor: "divider",
                        "&:before": { display: "none" },
                      }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandMoreIcon />}
                        sx={{
                          minHeight: 36,
                          "& .MuiAccordionSummary-content": { my: 0.5 },
                        }}
                      >
                        <Typography variant="caption" fontWeight={600}>
                          Input Schema — {requiredFields.length} required,{" "}
                          {optionalFields.length} optional
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails sx={{ p: 0 }}>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell
                                sx={{ fontWeight: 600, fontSize: "0.7rem" }}
                              >
                                Field
                              </TableCell>
                              <TableCell
                                sx={{ fontWeight: 600, fontSize: "0.7rem" }}
                              >
                                Type
                              </TableCell>
                              <TableCell
                                sx={{ fontWeight: 600, fontSize: "0.7rem" }}
                              >
                                Description
                              </TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {[...requiredFields, ...optionalFields].map((f) => (
                              <TableRow key={f.name}>
                                <TableCell>
                                  <Stack
                                    direction="row"
                                    spacing={0.5}
                                    alignItems="center"
                                  >
                                    <Typography
                                      variant="caption"
                                      sx={{
                                        fontFamily: "monospace",
                                        fontWeight: 500,
                                      }}
                                    >
                                      {f.name}
                                    </Typography>
                                    {f.required && (
                                      <Chip
                                        label="required"
                                        size="small"
                                        color="error"
                                        sx={{ height: 14, fontSize: "0.6rem" }}
                                      />
                                    )}
                                  </Stack>
                                </TableCell>
                                <TableCell>
                                  <Typography
                                    variant="caption"
                                    sx={{
                                      fontFamily: "monospace",
                                      color: "text.secondary",
                                    }}
                                  >
                                    {f.type}
                                  </Typography>
                                </TableCell>
                                <TableCell>
                                  <Typography
                                    variant="caption"
                                    color="text.secondary"
                                  >
                                    {f.description || "—"}
                                  </Typography>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Arguments editor */}
                  <TextField
                    label="Arguments (JSON)"
                    helperText="Edit directly, click AI Fill to generate from intent, or Reset to use the schema template."
                    multiline
                    rows={8}
                    value={toolArgs}
                    onChange={(e) => setToolArgs(e.target.value)}
                    size="small"
                    fullWidth
                    sx={{
                      "& textarea": {
                        fontFamily: "monospace",
                        fontSize: "0.8rem",
                      },
                    }}
                  />

                  {/* Action row */}
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleExecute}
                      disabled={executing}
                      startIcon={
                        executing ? (
                          <CircularProgress size={14} color="inherit" />
                        ) : (
                          <PlayArrowOutlinedIcon />
                        )
                      }
                    >
                      {executing ? "Executing..." : "Execute"}
                    </Button>
                    <Tooltip title="Use an LLM to generate arguments from a natural-language intent (how Claude does it)">
                      <span>
                        <Button
                          variant="outlined"
                          size="small"
                          onClick={() => setAiOpen(true)}
                          startIcon={<AutoAwesomeIcon />}
                        >
                          AI Fill
                        </Button>
                      </span>
                    </Tooltip>
                    <Tooltip title="Reset arguments to a fresh schema template">
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={resetTemplate}
                        startIcon={<RestartAltIcon />}
                      >
                        Reset
                      </Button>
                    </Tooltip>
                    <Tooltip title="Copy the arguments JSON">
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleCopyArgs}
                        startIcon={<ContentCopyIcon />}
                      >
                        Copy JSON
                      </Button>
                    </Tooltip>
                    <Tooltip title="Copy a curl command to reproduce this call externally">
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleCopyCurl}
                        startIcon={<ContentCopyIcon />}
                      >
                        Copy curl
                      </Button>
                    </Tooltip>
                  </Stack>

                  {/* Result */}
                  {execResult && (
                    <Paper variant="outlined" sx={{ overflow: "hidden" }}>
                      <Box
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 1,
                          px: 1.5,
                          py: 0.75,
                          borderBottom: "1px solid",
                          borderColor: "divider",
                          bgcolor: "action.hover",
                        }}
                      >
                        <Chip
                          label={execResult.status}
                          size="small"
                          color={isErrorResult ? "error" : "success"}
                        />
                        {execResult.latency_ms != null && (
                          <Typography variant="caption" color="text.secondary">
                            {execResult.latency_ms}ms
                          </Typography>
                        )}
                        {execResult.executed_at && (
                          <Typography variant="caption" color="text.secondary">
                            ·{" "}
                            {new Date(
                              execResult.executed_at,
                            ).toLocaleTimeString()}
                          </Typography>
                        )}
                      </Box>
                      {isErrorResult ? (
                        <Box sx={{ p: 1.5 }}>
                          <Alert
                            severity="error"
                            variant="outlined"
                            sx={{ fontSize: "0.8rem" }}
                          >
                            {execResult.error}
                          </Alert>
                        </Box>
                      ) : (
                        <Box sx={{ p: 1.5 }}>
                          {resultItems.length === 0 ? (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              Empty result
                            </Typography>
                          ) : (
                            <Stack spacing={1}>
                              {resultItems.map((item, i) => (
                                <Box key={i}>
                                  {item.kind === "image" ? (
                                    <Box
                                      component="img"
                                      src={item.value}
                                      alt="tool result"
                                      sx={{ maxWidth: "100%", maxHeight: 300 }}
                                    />
                                  ) : (
                                    <Box
                                      component="pre"
                                      sx={{
                                        m: 0,
                                        p: 1,
                                        bgcolor: "action.hover",
                                        borderRadius: 1,
                                        fontFamily: "monospace",
                                        fontSize: "0.75rem",
                                        overflow: "auto",
                                        maxHeight: 360,
                                        whiteSpace: "pre-wrap",
                                        wordBreak: "break-word",
                                      }}
                                    >
                                      {item.value}
                                    </Box>
                                  )}
                                </Box>
                              ))}
                            </Stack>
                          )}
                        </Box>
                      )}
                    </Paper>
                  )}
                </Stack>
              </Paper>
            )}

            {/* Execution History */}
            {activeTab === "tools" && history.length > 0 && (
              <Paper variant="outlined" sx={{ overflow: "hidden" }}>
                <Box
                  sx={{
                    px: 1.5,
                    py: 1,
                    borderBottom: "1px solid",
                    borderColor: "divider",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <Typography variant="subtitle2" fontWeight={600}>
                    Execution History
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Click a row to re-run
                  </Typography>
                </Box>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>
                        Tool
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>
                        Arguments
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>
                        Status
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>
                        Latency
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {history.slice(0, 20).map((h, i) => (
                      <TableRow
                        key={i}
                        hover
                        onClick={() => rerunFromHistory(h)}
                        sx={{ cursor: "pointer" }}
                      >
                        <TableCell>
                          <Typography
                            variant="caption"
                            sx={{ fontFamily: "monospace" }}
                          >
                            {h.tool_name}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography
                            variant="caption"
                            sx={{
                              fontFamily: "monospace",
                              color: "text.secondary",
                              display: "block",
                              maxWidth: 280,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {(() => {
                              try {
                                return JSON.stringify(h.arguments || {});
                              } catch {
                                return "—";
                              }
                            })()}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={h.status}
                            size="small"
                            color={h.status === "error" ? "error" : "success"}
                            sx={{ height: 18, fontSize: "0.65rem" }}
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption" color="text.secondary">
                            {h.latency_ms}ms
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Paper>
            )}
          </Stack>
        )}
      </Box>

      {/* Connect Dialog */}
      <Dialog
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Connect to MCP Server</DialogTitle>
        <Box component="form" onSubmit={handleConnect}>
          <DialogContent>
            <Stack spacing={2} sx={{ pt: 0.5 }}>
              <TextField
                label="Name (optional)"
                size="small"
                fullWidth
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="My MCP Server"
              />
              <TextField
                label="Transport"
                size="small"
                select
                fullWidth
                value={form.transport}
                onChange={(e) =>
                  setForm({ ...form, transport: e.target.value })
                }
              >
                <MenuItem value="stdio">Stdio</MenuItem>
                <MenuItem value="http">HTTP (SSE)</MenuItem>
              </TextField>
              {form.transport === "stdio" ? (
                <TextField
                  label="Command"
                  size="small"
                  fullWidth
                  value={form.command}
                  onChange={(e) =>
                    setForm({ ...form, command: e.target.value })
                  }
                  placeholder="npx -y @modelcontextprotocol/server"
                  helperText="Full command line to launch the MCP server subprocess"
                />
              ) : (
                <TextField
                  label="Server URL"
                  size="small"
                  fullWidth
                  type="url"
                  value={form.server_url}
                  onChange={(e) =>
                    setForm({ ...form, server_url: e.target.value })
                  }
                  placeholder="http://localhost:3333"
                  helperText="Base URL of a running MCP server that exposes /sse and /messages"
                />
              )}
            </Stack>
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button
              size="small"
              onClick={() => setConnectOpen(false)}
              disabled={connecting === "manual"}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="small"
              variant="contained"
              disabled={connecting === "manual"}
              startIcon={
                connecting === "manual" ? (
                  <CircularProgress size={14} color="inherit" />
                ) : null
              }
            >
              {connecting === "manual" ? "Connecting…" : "Connect"}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>

      {/* AI Fill Dialog */}
      <Dialog
        open={aiOpen}
        onClose={() => !aiBusy && setAiOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>AI Fill Arguments</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ fontSize: "0.85rem", mb: 1.5 }}>
            Describe what you want to do, and the default LLM will generate
            valid arguments for <code>{selectedTool}</code> from its JSON
            schema. Leave blank to generate a reasonable example.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            multiline
            rows={3}
            size="small"
            placeholder="e.g. Find all pets with status 'available' and a limit of 5"
            value={aiIntent}
            onChange={(e) => setAiIntent(e.target.value)}
            disabled={aiBusy}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            size="small"
            onClick={() => setAiOpen(false)}
            disabled={aiBusy}
          >
            Cancel
          </Button>
          <Button
            size="small"
            variant="contained"
            onClick={handleAiSuggest}
            disabled={aiBusy}
            startIcon={
              aiBusy ? (
                <CircularProgress size={14} color="inherit" />
              ) : (
                <AutoAwesomeIcon />
              )
            }
          >
            {aiBusy ? "Generating..." : "Generate"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Disconnect Confirm Dialog */}
      <Dialog
        open={!!disconnectTarget}
        onClose={() => setDisconnectTarget(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Disconnect</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Disconnect this MCP session? Tool state and process (for stdio) will
            be cleaned up.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button size="small" onClick={() => setDisconnectTarget(null)}>
            Cancel
          </Button>
          <Button
            size="small"
            variant="contained"
            color="error"
            onClick={handleDisconnect}
          >
            Disconnect
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

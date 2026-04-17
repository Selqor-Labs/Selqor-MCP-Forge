import React, { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import CircularProgress from "@mui/material/CircularProgress";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PlayArrowOutlinedIcon from "@mui/icons-material/PlayArrowOutlined";
import AddIcon from "@mui/icons-material/Add";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import {
  fetchPlaygroundTestCases,
  createPlaygroundTestCase,
  updatePlaygroundTestCase,
  deletePlaygroundTestCase,
  runPlaygroundSuite,
} from "../../api";

const OP_OPTIONS = [
  { value: "status_is", label: "status_is (value)", needsPath: false, hint: "success | error" },
  { value: "latency_lt", label: "latency_lt (ms)", needsPath: false, hint: "numeric ms" },
  { value: "text_includes", label: "text_includes (value)", needsPath: false, hint: "matches any MCP text block" },
  { value: "equals", label: "equals (path, value)", needsPath: true },
  { value: "contains", label: "contains (path, value)", needsPath: true },
  { value: "exists", label: "exists (path)", needsPath: true, noValue: true },
  { value: "not_exists", label: "not_exists (path)", needsPath: true, noValue: true },
  { value: "regex", label: "regex (path, pattern)", needsPath: true },
  { value: "type", label: "type (path, type)", needsPath: true, hint: "string|number|bool|array|object|null" },
];

const emptyAssertion = { op: "status_is", path: "", value: "success" };

function StatusChip({ status }) {
  if (!status) return null;
  const color = status === "pass" ? "success" : status === "fail" ? "error" : "warning";
  return <Chip size="small" label={status} color={color} sx={{ height: 20, fontSize: "0.7rem" }} />;
}

export default function TestCasesPanel({ sessionId, toolName, toolArgs, onToast }) {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null); // null = creating
  const [runResults, setRunResults] = useState(null); // { summary, results } most recent
  const [form, setForm] = useState({
    name: "",
    description: "",
    argumentsJson: "{}",
    assertions: [emptyAssertion],
  });

  const filteredCases = useMemo(() => {
    if (!toolName) return cases;
    return cases.filter((c) => c.tool_name === toolName);
  }, [cases, toolName]);

  async function load() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await fetchPlaygroundTestCases(sessionId);
      setCases(res.testcases || []);
    } catch (err) {
      onToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sessionId]);

  function openCreate() {
    setEditing(null);
    setForm({
      name: toolName ? `${toolName} — happy path` : "Untitled",
      description: "",
      argumentsJson: toolArgs || "{}",
      assertions: [{ op: "status_is", path: "", value: "success" }],
    });
    setEditorOpen(true);
  }

  function openEdit(tc) {
    setEditing(tc);
    setForm({
      name: tc.name || "",
      description: tc.description || "",
      argumentsJson: JSON.stringify(tc.arguments || {}, null, 2),
      assertions: (tc.assertions || []).length ? tc.assertions.map(a => ({ ...a })) : [emptyAssertion],
    });
    setEditorOpen(true);
  }

  async function save() {
    let parsedArgs;
    try {
      parsedArgs = JSON.parse(form.argumentsJson || "{}");
    } catch (err) {
      onToast?.(`Arguments JSON invalid: ${err.message}`, "error");
      return;
    }
    if (!form.name.trim()) {
      onToast?.("Name is required", "error");
      return;
    }
    const payload = {
      tool_name: editing ? editing.tool_name : toolName,
      name: form.name.trim(),
      description: form.description.trim(),
      arguments: parsedArgs,
      assertions: form.assertions.filter((a) => a.op),
    };
    try {
      if (editing) {
        await updatePlaygroundTestCase(editing.id, {
          name: payload.name,
          description: payload.description,
          arguments: payload.arguments,
          assertions: payload.assertions,
        });
        onToast?.("Test case updated");
      } else {
        if (!payload.tool_name) {
          onToast?.("Select a tool first", "error");
          return;
        }
        await createPlaygroundTestCase(sessionId, payload);
        onToast?.("Test case saved");
      }
      setEditorOpen(false);
      load();
    } catch (err) {
      onToast?.(err.message, "error");
    }
  }

  async function remove(tc) {
    try {
      await deletePlaygroundTestCase(tc.id);
      onToast?.("Deleted");
      load();
    } catch (err) {
      onToast?.(err.message, "error");
    }
  }

  async function runAll(ids) {
    setRunning(true);
    try {
      const body = ids ? { testcase_ids: ids } : {};
      const res = await runPlaygroundSuite(sessionId, body);
      setRunResults(res);
      const s = res.summary || {};
      const msg = `${s.passed || 0}/${s.total || 0} passed${s.failed ? `, ${s.failed} failed` : ""}${s.errored ? `, ${s.errored} errored` : ""}`;
      onToast?.(msg, s.failed || s.errored ? "error" : "");
      load();
    } catch (err) {
      onToast?.(err.message, "error");
    } finally {
      setRunning(false);
    }
  }

  function updateAssertion(idx, patch) {
    setForm((f) => {
      const next = f.assertions.slice();
      next[idx] = { ...next[idx], ...patch };
      return { ...f, assertions: next };
    });
  }

  function removeAssertion(idx) {
    setForm((f) => ({ ...f, assertions: f.assertions.filter((_, i) => i !== idx) }));
  }

  function addAssertion() {
    setForm((f) => ({ ...f, assertions: [...f.assertions, { ...emptyAssertion }] }));
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle2" fontWeight={600}>
          Test Cases {toolName ? `· ${toolName}` : ""}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={openCreate}
          disabled={!sessionId || !toolName}
        >
          New
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={running ? <CircularProgress size={14} color="inherit" /> : <PlayArrowOutlinedIcon />}
          onClick={() => runAll()}
          disabled={running || cases.length === 0}
        >
          {running ? "Running..." : `Run ${filteredCases.length || ""} test${filteredCases.length === 1 ? "" : "s"}`}
        </Button>
      </Stack>

      {runResults && runResults.summary && (
        <Alert severity={runResults.summary.failed || runResults.summary.errored ? "error" : "success"} sx={{ mb: 1.5, fontSize: "0.8rem" }}>
          {runResults.summary.passed}/{runResults.summary.total} passed
          {runResults.summary.failed ? ` · ${runResults.summary.failed} failed` : ""}
          {runResults.summary.errored ? ` · ${runResults.summary.errored} errored` : ""}
        </Alert>
      )}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}>
          <CircularProgress size={24} />
        </Box>
      ) : filteredCases.length === 0 ? (
        <Alert severity="info" sx={{ fontSize: "0.8rem" }}>
          No test cases yet. Pick a tool, fill in arguments, then click <b>New</b> to capture the call as a regression-tested case.
        </Alert>
      ) : (
        <Stack spacing={1}>
          {filteredCases.map((tc) => {
            const runResult = runResults?.results?.find((r) => r.testcase_id === tc.id);
            return (
              <Accordion key={tc.id} disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", "&:before": { display: "none" } }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 40, "& .MuiAccordionSummary-content": { my: 0.5, alignItems: "center", gap: 1 } }}>
                  <Typography variant="body2" fontWeight={500} sx={{ flex: 1, minWidth: 0 }} noWrap>
                    {tc.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                    {tc.tool_name}
                  </Typography>
                  <StatusChip status={runResult?.status || tc.last_status} />
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  {tc.description && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                      {tc.description}
                    </Typography>
                  )}
                  <Typography variant="caption" fontWeight={600} sx={{ display: "block", mb: 0.5 }}>Arguments</Typography>
                  <Box component="pre" sx={{ m: 0, mb: 1, p: 1, bgcolor: "action.hover", borderRadius: 1, fontFamily: "monospace", fontSize: "0.75rem", overflow: "auto", maxHeight: 140 }}>
                    {JSON.stringify(tc.arguments || {}, null, 2)}
                  </Box>
                  <Typography variant="caption" fontWeight={600} sx={{ display: "block", mb: 0.5 }}>
                    Assertions ({(tc.assertions || []).length})
                  </Typography>
                  <Stack spacing={0.5} sx={{ mb: 1 }}>
                    {(tc.assertions || []).map((a, i) => {
                      const outcome = runResult?.assertion_results?.[i];
                      return (
                        <Box key={i} sx={{ display: "flex", alignItems: "center", gap: 1, fontFamily: "monospace", fontSize: "0.75rem" }}>
                          {outcome ? <StatusChip status={outcome.passed ? "pass" : "fail"} /> : <Chip label="—" size="small" sx={{ height: 20 }} />}
                          <Typography variant="caption" sx={{ fontFamily: "monospace" }}>
                            {a.op}{a.path ? ` ${a.path}` : ""}{"value" in a && a.value !== null ? ` = ${JSON.stringify(a.value)}` : ""}
                          </Typography>
                          {outcome && !outcome.passed && (
                            <Typography variant="caption" color="error.main" sx={{ ml: 1 }}>
                              {outcome.message || ""}
                            </Typography>
                          )}
                        </Box>
                      );
                    })}
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" startIcon={<PlayArrowOutlinedIcon />} onClick={() => runAll([tc.id])} disabled={running}>
                      Run
                    </Button>
                    <Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => openEdit(tc)}>
                      Edit
                    </Button>
                    <Tooltip title="Delete">
                      <IconButton size="small" color="error" onClick={() => remove(tc)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </AccordionDetails>
              </Accordion>
            );
          })}
        </Stack>
      )}

      {/* Editor dialog */}
      <Dialog open={editorOpen} onClose={() => setEditorOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "Edit test case" : "New test case"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            <TextField label="Name" size="small" fullWidth value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <TextField label="Description (optional)" size="small" fullWidth value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <TextField
              label="Arguments (JSON)"
              size="small"
              fullWidth
              multiline
              rows={6}
              value={form.argumentsJson}
              onChange={(e) => setForm({ ...form, argumentsJson: e.target.value })}
              sx={{ "& textarea": { fontFamily: "monospace", fontSize: "0.8rem" } }}
            />
            <Box>
              <Stack direction="row" alignItems="center" sx={{ mb: 0.5 }}>
                <Typography variant="caption" fontWeight={600}>Assertions</Typography>
                <Box sx={{ flex: 1 }} />
                <Button size="small" startIcon={<AddIcon />} onClick={addAssertion}>Add</Button>
              </Stack>
              <Stack spacing={1}>
                {form.assertions.map((a, i) => {
                  const spec = OP_OPTIONS.find((o) => o.value === a.op) || OP_OPTIONS[0];
                  return (
                    <Paper key={i} variant="outlined" sx={{ p: 1 }}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <TextField
                          select size="small" label="op"
                          value={a.op || ""}
                          onChange={(e) => updateAssertion(i, { op: e.target.value })}
                          sx={{ minWidth: 160 }}
                        >
                          {OP_OPTIONS.map((o) => (
                            <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
                          ))}
                        </TextField>
                        {spec.needsPath && (
                          <TextField
                            size="small" label="path"
                            placeholder="content[0].text"
                            value={a.path || ""}
                            onChange={(e) => updateAssertion(i, { path: e.target.value })}
                            sx={{ flex: 1 }}
                          />
                        )}
                        {!spec.noValue && (
                          <TextField
                            size="small" label="value"
                            value={a.value === undefined || a.value === null ? "" : typeof a.value === "object" ? JSON.stringify(a.value) : String(a.value)}
                            onChange={(e) => {
                              let parsed = e.target.value;
                              // try to coerce numbers/booleans/JSON
                              if (spec.value === "latency_lt" || a.op === "latency_lt") {
                                const n = Number(parsed);
                                parsed = Number.isFinite(n) ? n : parsed;
                              } else {
                                try { parsed = JSON.parse(e.target.value); } catch { /* leave as string */ }
                              }
                              updateAssertion(i, { value: parsed });
                            }}
                            sx={{ flex: 1 }}
                            helperText={spec.hint || ""}
                          />
                        )}
                        <IconButton size="small" color="error" onClick={() => removeAssertion(i)}>
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    </Paper>
                  );
                })}
              </Stack>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button size="small" onClick={() => setEditorOpen(false)}>Cancel</Button>
          <Button size="small" variant="contained" startIcon={<SaveOutlinedIcon />} onClick={save}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

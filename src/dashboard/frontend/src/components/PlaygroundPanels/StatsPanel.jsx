import React, { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import CircularProgress from "@mui/material/CircularProgress";
import RefreshIcon from "@mui/icons-material/Refresh";
import { fetchPlaygroundStats } from "../../api";

function pct(v) {
  if (v == null) return "—";
  return `${Math.round(v * 1000) / 10}%`;
}
function ms(v) {
  if (v == null) return "—";
  return `${Math.round(v)}ms`;
}

export default function StatsPanel({ sessionId, onToast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await fetchPlaygroundStats(sessionId);
      setData(res);
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
        <Typography variant="subtitle2" fontWeight={600}>Per-tool Stats</Typography>
        {data && (
          <Chip size="small" label={`${data.total_invocations} invocations`} />
        )}
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<RefreshIcon />} onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Stack>

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}>
          <CircularProgress size={24} />
        </Box>
      ) : !data || (data.stats || []).length === 0 ? (
        <Alert severity="info" sx={{ fontSize: "0.8rem" }}>
          No execution data yet. Execute a tool to populate these aggregates.
        </Alert>
      ) : (
        <>
          <Paper variant="outlined" sx={{ overflow: "hidden" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>Tool</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }} align="right">Calls</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }} align="right">Success</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }} align="right">Errors</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }} align="right">p50</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }} align="right">p95</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontSize: "0.7rem" }}>Last error</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.stats.map((s) => (
                  <TableRow key={s.tool_name} hover>
                    <TableCell>
                      <Typography variant="caption" sx={{ fontFamily: "monospace", fontWeight: 500 }}>
                        {s.tool_name}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{s.invocations}</TableCell>
                    <TableCell align="right">{pct(s.success_rate)}</TableCell>
                    <TableCell align="right">
                      {s.errors > 0 ? (
                        <Chip size="small" color="error" label={s.errors} sx={{ height: 18, fontSize: "0.65rem" }} />
                      ) : "0"}
                    </TableCell>
                    <TableCell align="right">{ms(s.p50_ms)}</TableCell>
                    <TableCell align="right">{ms(s.p95_ms)}</TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace", maxWidth: 240, display: "inline-block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {s.last_error || "—"}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            Overall error rate: {pct(data.overall_error_rate)}
          </Typography>
        </>
      )}
    </Box>
  );
}

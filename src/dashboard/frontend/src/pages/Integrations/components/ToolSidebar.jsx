import React from 'react';
import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Checkbox,
  Divider,
  IconButton,
  Tooltip,
  Stack,
  Chip,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';

function getMethodColor(method) {
  const m = (method || 'GET').toUpperCase();
  switch (m) {
    case 'GET':    return { bg: '#3b82f6', text: '#fff' };
    case 'POST':   return { bg: '#16a34a', text: '#fff' };
    case 'PUT':    return { bg: '#eab308', text: '#fff' };
    case 'DELETE': return { bg: '#dc2626', text: '#fff' };
    case 'PATCH':  return { bg: '#8b5cf6', text: '#fff' };
    default:       return { bg: '#64748b', text: '#fff' };
  }
}

export default function ToolSidebar({ tool, index, allEndpoints, onUpdate, onDelete, onClose }) {
  const [name, setName] = useState(tool.name || '');
  const [description, setDescription] = useState(tool.description || '');
  const [endpoints, setEndpoints] = useState(tool.endpoints || tool.apis || []);
  const [search, setSearch] = useState('');

  useEffect(() => {
    setName(tool.name || '');
    setDescription(tool.description || '');
    setEndpoints(tool.endpoints || tool.apis || []);
    setSearch('');
  }, [tool, index]);

  function handleSave() {
    onUpdate({ ...tool, name, description, endpoints });
  }

  function toggleEndpoint(ep) {
    const key = `${ep.method}:${ep.path}`;
    const exists = endpoints.some((e) => `${e.method}:${e.path}` === key);
    if (exists) {
      setEndpoints(endpoints.filter((e) => `${e.method}:${e.path}` !== key));
    } else {
      setEndpoints([...endpoints, ep]);
    }
  }

  function isAssigned(ep) {
    return endpoints.some((e) => e.method === ep.method && e.path === ep.path);
  }

  const filtered = allEndpoints.filter((ep) => {
    const q = search.toLowerCase();
    return (
      (ep.path || '').toLowerCase().includes(q) ||
      (ep.method || '').toLowerCase().includes(q) ||
      (ep.operationId || '').toLowerCase().includes(q)
    );
  });

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        bgcolor: 'background.paper',
        borderLeft: '1px solid',
        borderColor: 'divider',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1.5,
          borderBottom: '1px solid',
          borderColor: 'divider',
          flexShrink: 0,
        }}
      >
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          Edit Tool
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Body */}
      <Box sx={{ flex: 1, overflowY: 'auto', px: 2, py: 1.5 }}>
        <Stack spacing={1.5}>
          <TextField
            label="Name"
            size="small"
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            label="Description"
            size="small"
            fullWidth
            multiline
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />

          <Divider />

          {/* Endpoints Section */}
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, display: 'block', mb: 0.75 }}>
              Assigned APIs ({endpoints.length})
            </Typography>

            {allEndpoints.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                No endpoints available. Run analysis first.
              </Typography>
            ) : (
              <>
                <TextField
                  placeholder="Search endpoints..."
                  size="small"
                  fullWidth
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  sx={{ mb: 1 }}
                />
                <Box
                  sx={{
                    maxHeight: 320,
                    overflowY: 'auto',
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                  }}
                >
                  {filtered.length === 0 ? (
                    <Box sx={{ p: 1.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        No endpoints match your search.
                      </Typography>
                    </Box>
                  ) : (
                    filtered.map((ep, i) => {
                      const method = (ep.method || 'GET').toUpperCase();
                      const colors = getMethodColor(method);
                      const assigned = isAssigned(ep);
                      return (
                        <Box
                          key={i}
                          onClick={() => toggleEndpoint(ep)}
                          sx={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 1,
                            px: 1,
                            py: 0.75,
                            cursor: 'pointer',
                            borderBottom: i < filtered.length - 1 ? '1px solid' : 'none',
                            borderColor: 'divider',
                            bgcolor: assigned ? 'action.selected' : 'transparent',
                            '&:hover': { bgcolor: 'action.hover' },
                            transition: 'background-color 0.12s',
                          }}
                        >
                          <Checkbox
                            size="small"
                            checked={assigned}
                            onChange={() => toggleEndpoint(ep)}
                            onClick={(e) => e.stopPropagation()}
                            sx={{ p: 0 }}
                          />
                          <Chip
                            label={method}
                            size="small"
                            sx={{
                              bgcolor: colors.bg,
                              color: colors.text,
                              fontWeight: 700,
                              fontSize: '0.65rem',
                              height: 20,
                              borderRadius: '4px',
                              flexShrink: 0,
                            }}
                          />
                          <Typography
                            variant="caption"
                            sx={{
                              fontFamily: 'monospace',
                              fontSize: '0.72rem',
                              flex: 1,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {ep.path}
                          </Typography>
                        </Box>
                      );
                    })
                  )}
                </Box>
              </>
            )}
          </Box>
        </Stack>
      </Box>

      {/* Footer */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1.5,
          borderTop: '1px solid',
          borderColor: 'divider',
          flexShrink: 0,
        }}
      >
        <Button
          variant="contained"
          size="small"
          startIcon={<SaveOutlinedIcon />}
          onClick={handleSave}
        >
          Save
        </Button>
        <Button
          variant="text"
          size="small"
          color="error"
          startIcon={<DeleteOutlineIcon />}
          onClick={onDelete}
        >
          Delete Tool
        </Button>
      </Box>
    </Box>
  );
}

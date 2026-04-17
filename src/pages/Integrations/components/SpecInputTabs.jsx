import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Paper from '@mui/material/Paper';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Chip from '@mui/material/Chip';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import ContentPasteIcon from '@mui/icons-material/ContentPaste';
import HistoryIcon from '@mui/icons-material/History';
import LinkIcon from '@mui/icons-material/Link';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import useStore from '../../../store/useStore';
import { useTheme } from '@mui/material/styles';

function TabPanel({ children, value, index, ...props }) {
  return (
    <div role="tabpanel" hidden={value !== index} {...props}>
      {value === index && <Box sx={{ pt: 3 }}>{children}</Box>}
    </div>
  );
}

export default function SpecInputTabs({ onSpecsChange, existingSpecs = [] }) {
  const toast = useStore((s) => s.toast);
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const [tabValue, setTabValue] = useState(0);
  const [specs, setSpecs] = useState(existingSpecs);
  const [urlValue, setUrlValue] = useState('');
  const [urlValidating, setUrlValidating] = useState(false);
  const [urlError, setUrlError] = useState('');
  const [urlSuccess, setUrlSuccess] = useState('');
  const [pasteValue, setPasteValue] = useState('');
  const [pasteError, setPasteError] = useState('');
  const [recentSpecs, setRecentSpecs] = useState([]);
  const [dragOverFile, setDragOverFile] = useState(false);

  // Load recent specs from localStorage on mount
  useEffect(() => {
    const recent = localStorage.getItem('recentSpecs');
    if (recent) {
      try {
        const parsed = JSON.parse(recent);
        setRecentSpecs(Array.isArray(parsed) ? parsed.slice(0, 5) : []);
      } catch {
        // Ignore parse errors
      }
    }
  }, []);

  // Save recent spec when a new URL is added
  const saveRecentSpec = (spec) => {
    try {
      new URL(spec);
    } catch {
      return;
    }

    try {
      const recent = localStorage.getItem('recentSpecs');
      let specs = [];
      if (recent) {
        specs = JSON.parse(recent);
        if (!Array.isArray(specs)) specs = [];
      }
      const filtered = specs.filter((s) => s !== spec);
      const updated = [spec, ...filtered].slice(0, 5);
      localStorage.setItem('recentSpecs', JSON.stringify(updated));
      setRecentSpecs(updated);
    } catch {
      // Ignore errors silently
    }
  };

  // Validate spec URL
  const validateSpecUrl = async (url) => {
    const trimmed = url.trim();
    if (!trimmed) {
      setUrlError('URL cannot be empty');
      setUrlSuccess('');
      return false;
    }

    try {
      new URL(trimmed);
    } catch {
      setUrlError('Invalid URL format. Must start with http:// or https://');
      setUrlSuccess('');
      return false;
    }

    setUrlValidating(true);
    setUrlError('');
    setUrlSuccess('');
    try {
      const res = await fetch(trimmed, { method: 'HEAD', mode: 'cors' });
      if (!res.ok && res.status !== 405) {
        setUrlError(`Server returned ${res.status}. Verify URL is accessible.`);
        setUrlValidating(false);
        return false;
      }
    } catch (err) {
      setUrlError('Could not reach URL. Check it\'s publicly accessible.');
      setUrlValidating(false);
      return false;
    }

    setUrlValidating(false);
    setUrlSuccess('✓ URL is accessible');
    return true;
  };

  // Handle URL input and add
  const handleAddUrl = async () => {
    if (!await validateSpecUrl(urlValue)) return;
    const trimmed = urlValue.trim();
    if (specs.includes(trimmed)) {
      setUrlError('This URL is already added');
      return;
    }
    const updated = [...specs, trimmed];
    setSpecs(updated);
    saveRecentSpec(trimmed);
    setUrlValue('');
    setUrlError('');
    setUrlSuccess('');
    toast('Spec URL added successfully', 'success');
    onSpecsChange(updated);
  };

  // Handle file upload
  const handleFileUpload = async (event) => {
    const files = event.currentTarget.files;
    if (!files?.length) return;

    const file = files[0];
    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
      toast(`File too large. Max 5MB, got ${(file.size / 1024 / 1024).toFixed(1)}MB`, 'error');
      return;
    }

    const validExtensions = ['.json', '.yaml', '.yml'];
    if (!validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      toast('Only JSON and YAML files are supported', 'error');
      return;
    }

    try {
      const content = await file.text();
      try {
        JSON.parse(content);
      } catch {
        if (!content.includes(':') && !content.includes('-')) {
          throw new Error('Content does not appear to be JSON or YAML');
        }
      }

      const fileSpec = JSON.stringify({
        __type: 'file-upload',
        filename: file.name,
        content: content,
        uploadedAt: new Date().toISOString(),
      });

      const updated = [...specs, fileSpec];
      setSpecs(updated);
      toast(`File "${file.name}" added successfully`, 'success');
      onSpecsChange(updated);
      if (event.currentTarget) event.currentTarget.value = '';
    } catch (err) {
      toast(`File error: ${err.message || 'Could not read file'}`, 'error');
    }
  };

  // Handle drag and drop
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverFile(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverFile(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverFile(false);

    const files = e.dataTransfer?.files;
    if (!files?.length) return;

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(files[0]);
    fileInput.files = dataTransfer.files;
    handleFileUpload({ currentTarget: fileInput });
  };

  // Handle paste content
  const handleAddPaste = () => {
    const trimmed = pasteValue.trim();
    if (!trimmed) {
      setPasteError('Content cannot be empty');
      return;
    }

    try {
      JSON.parse(trimmed);
    } catch {
      if (!trimmed.includes(':') && !trimmed.includes('-')) {
        setPasteError('Content does not appear to be valid JSON or YAML');
        return;
      }
    }

    const pasteSpec = JSON.stringify({
      __type: 'pasted-content',
      content: trimmed,
      pastedAt: new Date().toISOString(),
    });

    const updated = [...specs, pasteSpec];
    setSpecs(updated);
    setPasteValue('');
    setPasteError('');
    toast('Spec content added successfully', 'success');
    onSpecsChange(updated);
  };

  // Handle recent spec selection
  const handleSelectRecent = (spec) => {
    if (specs.includes(spec)) {
      toast('This spec is already added', 'error');
      return;
    }
    const updated = [...specs, spec];
    setSpecs(updated);
    toast('Recent spec added', 'success');
    onSpecsChange(updated);
  };

  // Remove a spec
  const handleRemoveSpec = (specToRemove) => {
    const updated = specs.filter((s) => s !== specToRemove);
    setSpecs(updated);
    onSpecsChange(updated);
  };

  const getSpecLabel = (spec) => {
    try {
      const parsed = JSON.parse(spec);
      if (parsed.__type === 'file-upload') {
        return parsed.filename;
      } else if (parsed.__type === 'pasted-content') {
        return 'Pasted Content';
      }
    } catch {
      try {
        return new URL(spec).hostname;
      } catch {
        return spec.substring(0, 30);
      }
    }
  };

  const getSpecIcon = (spec) => {
    try {
      const parsed = JSON.parse(spec);
      if (parsed.__type === 'file-upload') {
        return <CloudUploadIcon sx={{ fontSize: 16 }} />;
      } else if (parsed.__type === 'pasted-content') {
        return <ContentPasteIcon sx={{ fontSize: 16 }} />;
      }
    } catch {
      return <LinkIcon sx={{ fontSize: 16 }} />;
    }
  };

  return (
    <Box sx={{ width: '100%' }}>
      {/* Display added specs */}
      {specs.length > 0 && (
        <Box
          sx={{
            mb: 2.5,
            p: 2,
            bgcolor: isDark ? 'rgba(33, 150, 243, 0.08)' : 'rgba(33, 150, 243, 0.04)',
            borderRadius: 1.5,
            border: 1,
            borderColor: isDark ? 'rgba(33, 150, 243, 0.2)' : 'rgba(33, 150, 243, 0.15)',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.25 }}>
            <CheckCircleIcon sx={{ fontSize: 18, color: 'success.main' }} />
            <Typography variant="caption" fontWeight={600} color="text.secondary">
              Added Specs ({specs.length})
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.75 }}>
            {specs.map((spec, i) => (
              <Chip
                key={i}
                icon={getSpecIcon(spec)}
                label={getSpecLabel(spec)}
                onDelete={() => handleRemoveSpec(spec)}
                variant="outlined"
                color="primary"
                size="small"
                sx={{
                  borderRadius: 1,
                  fontWeight: 500,
                  '& .MuiChip-label': { fontFamily: 'inherit' },
                }}
              />
            ))}
          </Stack>
        </Box>
      )}

      {/* Tabs for different input methods */}
      <Paper
        elevation={0}
        sx={{
          border: 1,
          borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'divider',
          borderRadius: 2,
          bgcolor: isDark ? '#1e1e1e' : '#fafafa',
          overflow: 'hidden',
        }}
      >
        <Tabs
          value={tabValue}
          onChange={(_, v) => setTabValue(v)}
          variant="fullWidth"
          sx={{
            borderBottom: 1,
            borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'divider',
            bgcolor: isDark ? '#121212' : '#f5f5f5',
            '& .MuiTab-root': {
              textTransform: 'none',
              fontWeight: 600,
              fontSize: '0.95rem',
              py: 2,
              color: isDark ? 'rgba(255, 255, 255, 0.5)' : 'rgba(0, 0, 0, 0.6)',
              '&:hover': {
                bgcolor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.04)',
                color: isDark ? 'rgba(255, 255, 255, 0.8)' : 'rgba(0, 0, 0, 0.87)',
              },
              '&.Mui-selected': {
                color: isDark ? '#2196F3' : 'primary.main',
              },
            },
            '& .MuiTabs-indicator': {
              height: 3,
              bgcolor: '#2196F3',
              borderRadius: '3px 3px 0 0',
            },
          }}
        >
          <Tab icon={<LinkIcon sx={{ fontSize: 20, mr: 0.75 }} />} iconPosition="start" label="From URL" />
          <Tab icon={<CloudUploadIcon sx={{ fontSize: 20, mr: 0.75 }} />} iconPosition="start" label="Upload File" />
          <Tab icon={<ContentPasteIcon sx={{ fontSize: 20, mr: 0.75 }} />} iconPosition="start" label="Paste Content" />
          {recentSpecs.length > 0 && <Tab icon={<HistoryIcon sx={{ fontSize: 20, mr: 0.75 }} />} iconPosition="start" label="Recent" />}
        </Tabs>

        {/* Tab 1: From URL */}
        <TabPanel value={tabValue} index={0} sx={{ px: 3, pb: 3 }}>
          <Stack spacing={2}>
            <TextField
              fullWidth
              size="small"
              placeholder="https://api.example.com/openapi.json"
              label="Spec URL"
              value={urlValue}
              onChange={(e) => {
                setUrlValue(e.target.value);
                setUrlError('');
                setUrlSuccess('');
              }}
              onBlur={() => urlValue && validateSpecUrl(urlValue)}
              disabled={urlValidating}
              error={!!urlError}
              helperText={urlError || urlSuccess || 'Enter the URL to your OpenAPI/Swagger spec'}
              sx={{
                '& .MuiOutlinedInput-root': {
                  bgcolor: isDark ? '#2a2a2a' : '#f5f5f5',
                  color: isDark ? '#fff' : '#000',
                  '& fieldset': {
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.23)' : 'rgba(0, 0, 0, 0.23)',
                  },
                  '&:hover fieldset': {
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.5)' : 'rgba(0, 0, 0, 0.5)',
                  },
                  '&.Mui-focused fieldset': {
                    borderColor: '#2196F3',
                  },
                },
                '& .MuiOutlinedInput-input::placeholder': {
                  opacity: 0.6,
                  color: isDark ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.6)',
                },
              }}
            />
            <Button
              variant="contained"
              onClick={handleAddUrl}
              disabled={!urlValue || urlValidating}
              fullWidth
              sx={{
                py: 1.3,
                textTransform: 'none',
                fontSize: '1rem',
                fontWeight: 600,
                borderRadius: 1.2,
                bgcolor: '#2196F3',
                '&:hover': {
                  bgcolor: '#1976D2',
                },
              }}
            >
              {urlValidating ? (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <CircularProgress size={18} color="inherit" />
                  Validating…
                </Box>
              ) : (
                'Add Spec'
              )}
            </Button>
          </Stack>
        </TabPanel>

        {/* Tab 2: Upload File */}
        <TabPanel value={tabValue} index={1} sx={{ px: 3, pb: 3 }}>
          <Stack spacing={2}>
            <Paper
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              sx={{
                p: 4,
                textAlign: 'center',
                border: '2px dashed',
                borderColor: dragOverFile ? '#2196F3' : isDark ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.2)',
                bgcolor: dragOverFile
                  ? isDark
                    ? 'rgba(33, 150, 243, 0.15)'
                    : 'rgba(33, 150, 243, 0.08)'
                  : isDark
                  ? '#2a2a2a'
                  : '#f5f5f5',
                cursor: 'pointer',
                transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              }}
            >
              <CloudUploadIcon sx={{ fontSize: 56, color: '#2196F3', mb: 1.5, opacity: 0.85 }} />
              <Typography variant="body1" fontWeight={700} sx={{ mb: 0.5, color: isDark ? '#fff' : '#000' }}>
                Drag & drop your spec file
              </Typography>
              <Typography variant="body2" color="text.secondary">
                or click below to browse
              </Typography>
              <input
                type="file"
                accept=".json,.yaml,.yml"
                onChange={handleFileUpload}
                style={{ display: 'none' }}
                id="spec-file-input"
              />
              <label htmlFor="spec-file-input" style={{ cursor: 'pointer', display: 'block', marginTop: 20 }}>
                <Box
                  component="span"
                  sx={{
                    display: 'inline-block',
                    px: 3,
                    py: 1,
                    bgcolor: '#2196F3',
                    color: 'white',
                    borderRadius: 1.2,
                    fontSize: '0.95rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    '&:hover': {
                      bgcolor: '#1976D2',
                      transform: 'translateY(-2px)',
                      boxShadow: '0 6px 16px rgba(33, 150, 243, 0.4)',
                    },
                  }}
                >
                  Select File
                </Box>
              </label>
            </Paper>
            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center', display: 'block' }}>
              Supports JSON and YAML files up to 5MB
            </Typography>
          </Stack>
        </TabPanel>

        {/* Tab 3: Paste Content */}
        <TabPanel value={tabValue} index={2} sx={{ px: 3, pb: 3 }}>
          <Stack spacing={2}>
            <TextField
              fullWidth
              multiline
              rows={7}
              placeholder="Paste your OpenAPI spec in JSON or YAML format…"
              label="Spec Content"
              value={pasteValue}
              onChange={(e) => {
                setPasteValue(e.target.value);
                setPasteError('');
              }}
              error={!!pasteError}
              helperText={pasteError || 'Paste valid OpenAPI JSON or YAML content'}
              sx={{
                '& .MuiOutlinedInput-root': {
                  bgcolor: isDark ? '#2a2a2a' : '#f5f5f5',
                  color: isDark ? '#fff' : '#000',
                  '& fieldset': {
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.23)' : 'rgba(0, 0, 0, 0.23)',
                  },
                  '&:hover fieldset': {
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.5)' : 'rgba(0, 0, 0, 0.5)',
                  },
                  '&.Mui-focused fieldset': {
                    borderColor: '#2196F3',
                  },
                },
                '& .MuiOutlinedInput-input': {
                  fontFamily: 'monospace',
                  fontSize: '0.85rem',
                },
              }}
            />
            <Button
              variant="contained"
              onClick={handleAddPaste}
              disabled={!pasteValue}
              fullWidth
              sx={{
                py: 1.3,
                textTransform: 'none',
                fontSize: '1rem',
                fontWeight: 600,
                borderRadius: 1.2,
                bgcolor: '#2196F3',
                '&:hover': {
                  bgcolor: '#1976D2',
                },
              }}
            >
              Add Spec
            </Button>
          </Stack>
        </TabPanel>

        {/* Tab 4: Recent Specs */}
        {recentSpecs.length > 0 && (
          <TabPanel value={tabValue} index={3} sx={{ px: 3, pb: 3 }}>
            <Stack spacing={1.5}>
              {recentSpecs.map((spec, i) => {
                try {
                  const hostname = new URL(spec).hostname;
                  return (
                    <Box
                      key={i}
                      sx={{
                        p: 2,
                        border: 1,
                        borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'divider',
                        borderRadius: 1.2,
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                        bgcolor: isDark ? '#2a2a2a' : '#fafafa',
                        '&:hover': {
                          bgcolor: isDark ? '#323232' : '#f5f5f5',
                          borderColor: '#2196F3',
                          transform: 'translateX(4px)',
                        },
                      }}
                      onClick={() => handleSelectRecent(spec)}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flex: 1, minWidth: 0 }}>
                        <LinkIcon sx={{ fontSize: 20, color: '#2196F3', flexShrink: 0 }} />
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                          <Typography variant="body2" fontWeight={600} noWrap sx={{ color: isDark ? '#fff' : '#000' }}>
                            {hostname}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }} noWrap>
                            {spec.length > 50 ? spec.substring(0, 50) + '…' : spec}
                          </Typography>
                        </Box>
                      </Box>
                      <CheckCircleIcon sx={{ fontSize: 18, color: 'text.secondary', ml: 1, flexShrink: 0 }} />
                    </Box>
                  );
                } catch {
                  return null;
                }
              })}
            </Stack>
          </TabPanel>
        )}
      </Paper>
    </Box>
  );
}

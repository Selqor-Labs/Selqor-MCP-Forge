import React from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Avatar from '@mui/material/Avatar';
import { useTheme } from '@mui/material/styles';
import ExtensionOutlinedIcon from '@mui/icons-material/ExtensionOutlined';
import SecurityOutlinedIcon from '@mui/icons-material/SecurityOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';

/**
 * GetStartedGuide - Interactive checklist showing users the happy path.
 * Shows 4 key steps to get from empty to deployed MCP server.
 */
export default function GetStartedGuide({ completedSteps = [] }) {
  const navigate = useNavigate();
  const theme = useTheme();

  const steps = [
    {
      id: 'integrate',
      number: 1,
      title: 'Create Integration',
      description: 'Upload an OpenAPI spec or URL',
      icon: ExtensionOutlinedIcon,
      ctaLabel: 'Get Started',
      onCta: () => navigate('/integrations'),
      color: theme.palette.primary.main,
    },
    {
      id: 'auth',
      number: 2,
      title: 'Configure Auth',
      description: 'Add API keys, OAuth, headers, etc.',
      icon: SecurityOutlinedIcon,
      ctaLabel: 'Configure',
      onCta: () => navigate('/integrations'),
      color: theme.palette.info.main,
    },
    {
      id: 'test',
      number: 3,
      title: 'Test in Playground',
      description: 'Execute tools and verify behavior',
      icon: PlayArrowOutlinedIcon,
      ctaLabel: 'Test Now',
      onCta: () => navigate('/playground'),
      color: theme.palette.success.main,
    },
    {
      id: 'deploy',
      number: 4,
      title: 'Deploy Server',
      description: 'Generate TypeScript/Rust MCP server',
      icon: CloudUploadOutlinedIcon,
      ctaLabel: 'Deploy',
      onCta: () => navigate('/integrations'),
      color: theme.palette.warning.main,
    },
  ];

  return (
    <Card sx={{ borderRadius: 2, border: `1px solid ${theme.palette.divider}` }}>
      <CardContent sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 0.5, fontWeight: 600 }}>
          Getting Started
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
          Follow these 4 steps to create your first MCP server
        </Typography>

        <Stack spacing={2}>
          {steps.map((step) => {
            const Icon = step.icon;
            const isCompleted = completedSteps.includes(step.id);

            return (
              <Box
                key={step.id}
                sx={{
                  display: 'flex',
                  gap: 2,
                  padding: 1.5,
                  borderRadius: 1,
                  backgroundColor: isCompleted
                    ? 'action.hover'
                    : 'transparent',
                  border: `1px solid ${isCompleted ? theme.palette.success.light : theme.palette.divider}`,
                  transition: 'all 200ms ease',
                  cursor: 'default',
                }}
              >
                {/* Step number badge */}
                <Avatar
                  sx={{
                    width: 40,
                    height: 40,
                    backgroundColor: step.color,
                    color: 'white',
                    flexShrink: 0,
                    fontSize: '0.875rem',
                    fontWeight: 600,
                  }}
                >
                  {step.number}
                </Avatar>

                {/* Step content */}
                <Box sx={{ flex: 1 }}>
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: 600,
                      mb: 0.25,
                      textDecoration: isCompleted ? 'line-through' : 'none',
                      opacity: isCompleted ? 0.6 : 1,
                    }}
                  >
                    {step.title}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ opacity: isCompleted ? 0.5 : 1 }}
                  >
                    {step.description}
                  </Typography>
                </Box>

                {/* Action button */}
                <Box sx={{ display: 'flex', alignItems: 'center' }}>
                  <Button
                    variant={isCompleted ? 'outlined' : 'contained'}
                    size="small"
                    onClick={step.onCta}
                    sx={{
                      backgroundColor: isCompleted ? 'transparent' : step.color,
                      color: isCompleted ? step.color : 'white',
                      border: isCompleted ? `1px solid ${step.color}` : 'none',
                      '&:hover': {
                        backgroundColor: isCompleted
                          ? `${step.color}11`
                          : undefined,
                      },
                    }}
                  >
                    {isCompleted ? 'Done' : step.ctaLabel}
                  </Button>
                </Box>
              </Box>
            );
          })}
        </Stack>

        {/* Progress indicator */}
        <Box sx={{ mt: 2.5, pt: 2, borderTop: `1px solid ${theme.palette.divider}` }}>
          <Typography variant="caption" color="text.secondary">
            Progress: {completedSteps.length} of {steps.length} completed
          </Typography>
          <Box
            sx={{
              width: '100%',
              height: 6,
              backgroundColor: theme.palette.action.disabledBackground,
              borderRadius: 1,
              overflow: 'hidden',
              mt: 0.75,
            }}
          >
            <Box
              sx={{
                height: '100%',
                width: `${(completedSteps.length / steps.length) * 100}%`,
                backgroundColor: theme.palette.success.main,
                transition: 'width 300ms ease',
              }}
            />
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
}

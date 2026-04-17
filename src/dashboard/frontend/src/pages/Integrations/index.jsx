import React from 'react';
import { useEffect, useCallback, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Box, Typography, Button } from '@mui/material';
import useStore from '../../store/useStore';
import IntegrationGrid from './IntegrationGrid';
import IntegrationWorkflow from './IntegrationWorkflow';
import LogoLoader from '../../components/LogoLoader';
import { fetchIntegrations } from '../../api';
import { saveString, STORAGE_KEYS } from '../../utils/persist';

export default function Integrations({ step }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const integrations = useStore((s) => s.integrations);
  const toast = useStore((s) => s.toast);
  const [loading, setLoading] = useState(true);

  const loadIntegrations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchIntegrations();
      useStore.setState({ integrations: res.integrations || [] });
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadIntegrations();
  }, [loadIntegrations]);

  // Remember which integration was last opened so Dashboard "Resume work"
  // and other surfaces can deep-link back. Persisted via utils/persist.
  useEffect(() => {
    if (id) saveString(STORAGE_KEYS.lastIntegrationId, id);
  }, [id]);

  useEffect(() => {
    function onReload() {
      loadIntegrations();
    }
    window.addEventListener('integrations:reload', onReload);
    return () => window.removeEventListener('integrations:reload', onReload);
  }, [loadIntegrations]);

  if (id) {
    const integration = integrations.find((i) => i.id === id);

    if (!integration) {
      if (loading) {
        return (
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              minHeight: '50vh',
            }}
          >
            <LogoLoader size={96} message="Loading integration…" />
          </Box>
        );
      }
      return (
        <Box sx={{ p: 3 }}>
          <Typography variant="body2" color="text.secondary">
            Integration not found.
          </Typography>
          <Button
            variant="text"
            size="small"
            onClick={() => navigate('/integrations')}
            sx={{ mt: 1 }}
          >
            Back to Integrations
          </Button>
        </Box>
      );
    }

    return (
      <IntegrationWorkflow
        integration={integration}
        step={step || 1}
        onBack={() => navigate('/integrations')}
      />
    );
  }

  return <IntegrationGrid loading={loading} />;
}

const JSON_HEADERS = { 'content-type': 'application/json' };
const API_TIMEOUT_MS = 15000;
const LONG_TIMEOUT_MS = 45000;

function withTimeout(options = {}) {
  if (options.signal) {
    return { options, cleanup: () => {} };
  }

  const timeoutMs = options._timeout || API_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const { _timeout, ...fetchOptions } = options;

  return {
    options: { ...fetchOptions, signal: controller.signal },
    cleanup: () => window.clearTimeout(timeoutId),
  };
}

export async function api(path, options) {
  const request = withTimeout(options || {});
  try {
    const response = await fetch(path, request.options);
    const text = await response.text();
    if (!response.ok) {
      let message = text || `Request failed (${response.status})`;
      let fieldErrors = {};
      try {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed.detail)) {
          message = parsed.detail.map((e) => e.msg || JSON.stringify(e)).join('; ');
          for (const entry of parsed.detail) {
            if (!entry || !Array.isArray(entry.loc)) continue;
            const path = entry.loc.slice(1);
            if (path.length === 0) continue;
            const field = path.join('.');
            if (!fieldErrors[field]) fieldErrors[field] = entry.msg || 'Invalid value';
          }
        } else {
          message = parsed.detail || parsed.error || parsed.message || message;
        }
        if (typeof message !== 'string') message = JSON.stringify(message);
      } catch (_) {}
      const err = new Error(message);
      err.status = response.status;
      err.fieldErrors = fieldErrors;
      throw err;
    }
    return text ? JSON.parse(text) : {};
  } catch (error) {
    if (error?.name === 'AbortError') {
      const err = new Error('Request timed out. Check the dashboard backend and database connection.');
      err.status = 0;
      err.fieldErrors = {};
      throw err;
    }
    throw error;
  } finally {
    request.cleanup();
  }
}

export async function apiText(path, options) {
  const request = withTimeout(options || {});
  try {
    const response = await fetch(path, request.options);
    const text = await response.text();
    if (!response.ok) throw new Error(text || `Request failed (${response.status})`);
    return text;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('Request timed out. Check the dashboard backend and database connection.');
    }
    throw error;
  } finally {
    request.cleanup();
  }
}

// Dashboard
export const fetchDashboard = () => api('/api/dashboard');

// Integrations
export const fetchIntegrations = () => api('/api/integrations');
export const createIntegration = (payload) => api('/api/integrations', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const updateIntegration = (id, payload) => api(`/api/integrations/${id}`, { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const deleteIntegration = (id) => api(`/api/integrations/${id}`, { method: 'DELETE' });

// Runs
export const fetchRuns = (id) => api(`/api/integrations/${id}/runs`);
export const startRun = (id, body) => api(`/api/integrations/${id}/run`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) });
export const fetchRunJobStatus = (id, jobId) => api(`/api/integrations/${id}/run-jobs/${jobId}/status`);
export const fetchActiveRunJob = (id) => api(`/api/integrations/${id}/run-jobs/active`);
export const deleteRun = (id, runId) => api(`/api/integrations/${id}/runs/${runId}`, { method: 'DELETE' });

// Artifacts
export const fetchArtifacts = (id, runId) => api(`/api/integrations/${id}/runs/${runId}/artifacts`, { _timeout: LONG_TIMEOUT_MS });
export const fetchArtifactContent = (id, runId, name) => apiText(`/api/integrations/${id}/runs/${runId}/artifact/${name}`, { _timeout: LONG_TIMEOUT_MS });

// Deployments
export const fetchDeployments = (id) => api(`/api/integrations/${id}/deployments`);
export const createDeployment = (id, runId, payload) => api(`/api/integrations/${id}/runs/${runId}/deploy`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });

// Tooling
export const fetchTooling = (id) => api(`/api/integrations/${id}/tooling`);
export const saveTooling = (id, tools) => api(`/api/integrations/${id}/tooling`, { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ tools }) });
export const deleteTooling = (id) => api(`/api/integrations/${id}/tooling`, { method: 'DELETE' });

// Auth
export const fetchAuth = (id) => api(`/api/integrations/${id}/auth`);
export const saveAuth = (id, payload) => api(`/api/integrations/${id}/auth`, { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const testConnection = (id) => api(`/api/integrations/${id}/test-connection`, { method: 'POST', _timeout: LONG_TIMEOUT_MS });

// LLM
export const fetchLlmProviders = () => api('/api/llm/providers');
export const fetchLlmConfigs = () => api('/api/llm/configs');
export const saveLlmConfig = (payload) => api('/api/llm/configs', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const deleteLlmConfig = (id) => api(`/api/llm/configs/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const setDefaultLlmConfig = (id, endpoint) => api(`/api/llm/configs/${encodeURIComponent(id)}/${endpoint}`, { method: 'POST' });
export const testLlmConnection = (id) => api('/api/llm/test-connection', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ config_id: id }), _timeout: LONG_TIMEOUT_MS });
export const fetchLlmLogs = () => api('/api/llm/logs');

// Scanner
export const fetchScans = () => api('/api/scans');
export const createScan = (payload) => api('/api/scans', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload), _timeout: LONG_TIMEOUT_MS });
export const fetchScan = (id) => api(`/api/scans/${encodeURIComponent(id)}`);
export const deleteScan = (id) => api(`/api/scans/${encodeURIComponent(id)}`, { method: 'DELETE' });

// Playground
export const fetchPlaygroundSessions = () => api('/api/playground/sessions');
export const fetchAvailableIntegrations = () => api('/api/playground/available-integrations');
export const connectPlaygroundServer = (payload) => api('/api/playground/connect', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const autoConnectIntegration = (integrationId) => api(`/api/playground/auto-connect/${encodeURIComponent(integrationId)}`, { method: 'POST' });
export const disconnectPlaygroundSession = (id) => api(`/api/playground/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const fetchPlaygroundTools = (id) => api(`/api/playground/sessions/${encodeURIComponent(id)}/tools`);
export const executePlaygroundTool = (id, payload) => api(`/api/playground/sessions/${encodeURIComponent(id)}/execute`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const fetchPlaygroundHistory = (id) => api(`/api/playground/sessions/${encodeURIComponent(id)}/history`);
export const playgroundHealthCheck = (id) => api(`/api/playground/sessions/${encodeURIComponent(id)}/health`, { method: 'POST' });
export const suggestPlaygroundArgs = (id, payload) => api(`/api/playground/sessions/${encodeURIComponent(id)}/suggest-args`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });

// Remediation
export const applyRemediationFixes = (scanId, fixIds) => api(`/api/remediation/scans/${encodeURIComponent(scanId)}/apply`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ fix_ids: fixIds }) });
export const applyAllRemediationFixes = (scanId) => api(`/api/remediation/scans/${encodeURIComponent(scanId)}/apply-all`, { method: 'POST' });
export const fetchRemediationStatus = (scanId) => api(`/api/remediation/scans/${encodeURIComponent(scanId)}/status`);

// CI/CD
export const fetchCicdTemplates = () => api('/api/cicd/templates');
export const generateCicdConfig = (payload) => api('/api/cicd/generate', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const registerWebhook = (payload) => api('/api/cicd/webhooks/register', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const fetchWebhooks = () => api('/api/cicd/webhooks');
export const deleteWebhook = (name) => api(`/api/cicd/webhooks/${encodeURIComponent(name)}`, { method: 'DELETE' });
export const fetchCiRuns = (projectName) => api(`/api/cicd/runs${projectName ? `?project_name=${encodeURIComponent(projectName)}` : ''}`);
export const fetchCiRunStats = (projectName) => api(`/api/cicd/runs/stats${projectName ? `?project_name=${encodeURIComponent(projectName)}` : ''}`);

// Registry
export const fetchRegistries = () => api('/api/registry/registries');
export const prepareRegistryPublish = (payload) => api('/api/registry/prepare', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });

// Versions
export const fetchVersions = (id) => api(`/api/integrations/${id}/versions`);
export const createVersion = (id, payload) => api(`/api/integrations/${id}/versions`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const fetchVersionDiff = (id, v1, v2) => api(`/api/integrations/${id}/versions/${v1}/diff/${v2}`);

// Monitoring
export const fetchMonitoringServers = () => api('/api/monitoring/servers');
export const addMonitoringServer = (payload) => api('/api/monitoring/servers', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const updateMonitoringServer = (id, payload) => api(`/api/monitoring/servers/${encodeURIComponent(id)}`, { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const deleteMonitoringServer = (id) => api(`/api/monitoring/servers/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const checkMonitoringServer = (id) => api(`/api/monitoring/servers/${encodeURIComponent(id)}/check`, { method: 'POST' });
export const checkAllMonitoringServers = () => api('/api/monitoring/servers/check-all', { method: 'POST' });
export const fetchMonitoringHistory = (id) => api(`/api/monitoring/servers/${encodeURIComponent(id)}/history`);
export const fetchMonitoringStats = (id) => api(`/api/monitoring/servers/${encodeURIComponent(id)}/stats`);
export const fetchAlertRules = (id) => api(`/api/monitoring/servers/${encodeURIComponent(id)}/alerts`);
export const createAlertRule = (id, payload) => api(`/api/monitoring/servers/${encodeURIComponent(id)}/alerts`, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const deleteAlertRule = (serverId, ruleId) => api(`/api/monitoring/servers/${encodeURIComponent(serverId)}/alerts/${encodeURIComponent(ruleId)}`, { method: 'DELETE' });
export const fetchFiredAlerts = () => api('/api/monitoring/alerts');
export const acknowledgeAlert = (alertId) => api(`/api/monitoring/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: 'POST' });

// Compliance
export const fetchComplianceBadge = (scanId) => apiText(`/api/compliance/scans/${encodeURIComponent(scanId)}/badge`);
export const fetchComplianceEmbed = (scanId) => api(`/api/compliance/scans/${encodeURIComponent(scanId)}/embed`);
export const generateComplianceCertificate = (scanId) => api(`/api/compliance/scans/${encodeURIComponent(scanId)}/certificate`, { method: 'POST' });

// Settings
export const fetchTeamSettings = () => api('/api/settings/team');
export const sendTeamInvite = (payload) => api('/api/settings/team/invite', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const fetchTeamInvites = () => api('/api/settings/team/invites');
export const cancelTeamInvite = (id) => api(`/api/settings/team/invites/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const fetchPreferences = () => api('/api/settings/preferences');
export const savePreferences = (payload) => api('/api/settings/preferences', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const fetchScanPolicy = () => api('/api/settings/scan-policy');
export const saveScanPolicy = (payload) => api('/api/settings/scan-policy', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const exportAllData = () => api('/api/settings/export');

// Monitoring scheduler
export const startMonitoringScheduler = () => api('/api/monitoring/scheduler/start', { method: 'POST' });
export const stopMonitoringScheduler = () => api('/api/monitoring/scheduler/stop', { method: 'POST' });
export const fetchSchedulerStatus = () => api('/api/monitoring/scheduler/status');

// Notifications
export const fetchNotificationChannels = () => api('/api/notifications/channels');
export const createNotificationChannel = (payload) => api('/api/notifications/channels', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const updateNotificationChannel = (id, payload) => api(`/api/notifications/channels/${encodeURIComponent(id)}`, { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(payload) });
export const deleteNotificationChannel = (id) => api(`/api/notifications/channels/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const testNotificationChannel = (id) => api(`/api/notifications/channels/${encodeURIComponent(id)}/test`, { method: 'POST' });
export const fetchNotificationLogs = () => api('/api/notifications/logs');

// Scan policy check
export const checkScanPolicy = (scanId) => api(`/api/scans/${encodeURIComponent(scanId)}/policy-check`);

// Reports (return URL strings)
export const fetchRunReport = (id, runId, format) => `/api/integrations/${id}/runs/${runId}/report/${format}`;
export const fetchScanReport = (scanId, format) => `/api/scans/${encodeURIComponent(scanId)}/report/${format}`;

import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Integrations from './pages/Integrations';
import LlmConfig from './pages/LlmConfig';
import LlmLogs from './pages/LlmLogs';
import Playground from './pages/Playground';
import Scanner from './pages/Scanner';
import CiCd from './pages/CiCd';
import Monitoring from './pages/Monitoring';
import Settings from './pages/Settings';

function AppRoutes() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/integrations/:id" element={<Integrations />} />
        <Route path="/integrations/:id/auth" element={<Integrations step={2} />} />
        <Route path="/integrations/:id/tools" element={<Integrations step={3} />} />
        <Route path="/integrations/:id/scan" element={<Integrations step={4} />} />
        <Route path="/integrations/:id/deploy" element={<Integrations step={5} />} />
        <Route path="/llm-config" element={<LlmConfig />} />
        <Route path="/llm-logs" element={<LlmLogs />} />
        <Route path="/playground" element={<Playground />} />
        <Route path="/scanner" element={<Scanner />} />
        <Route path="/cicd" element={<CiCd />} />
        <Route path="/monitoring" element={<Monitoring />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppRoutes />
    </ErrorBoundary>
  );
}

import React from 'react';
import { useNavigate } from 'react-router-dom';

const STEPS = [
  { num: 1, label: 'Overview', path: '' },
  { num: 2, label: 'Auth Config', path: '/auth' },
  { num: 3, label: 'Tool Builder', path: '/tools' },
  { num: 4, label: 'Scan & Secure', path: '/scan' },
  { num: 5, label: 'Deploy', path: '/deploy' },
];

export default function Stepper({ integrationId, currentStep, completedSteps = [] }) {
  const navigate = useNavigate();

  return (
    <div className="stepper-vertical">
      {STEPS.map(({ num, label, path }) => {
        const isActive = num === currentStep;
        const isCompleted = completedSteps.includes(num);

        return (
          <button
            key={num}
            className={`stepper-item${isActive ? ' active' : ''}${isCompleted ? ' completed' : ''}`}
            onClick={() => navigate(`/integrations/${integrationId}${path}`)}
          >
            <div className="stepper-indicator">
              {isCompleted ? (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              ) : (
                <span>{num}</span>
              )}
            </div>
            <span className="stepper-label">{label}</span>
          </button>
        );
      })}
    </div>
  );
}

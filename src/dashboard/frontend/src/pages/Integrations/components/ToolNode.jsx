import React from 'react';
import { Handle, Position } from '@xyflow/react';

export default function ToolNode({ data }) {
  const apis = data.apis || [];

  return (
    <div className="tool-node-card">
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      <div className="tool-node-name">{data.name}</div>
      {data.description && (
        <div className="tool-node-desc">{data.description}</div>
      )}
      {apis.length > 0 && (
        <div className="tool-node-apis">
          {apis.slice(0, 4).map((ep, i) => {
            const method = (ep.method || 'GET').toLowerCase();
            const path = ep.path || ep.operationId || '';
            return (
              <span key={i} className={`method-tag method-${method}`}>
                {method.toUpperCase()} {path}
              </span>
            );
          })}
          {apis.length > 4 && (
            <span className="tool-node-more">+{apis.length - 4} more</span>
          )}
        </div>
      )}
      <div className="tool-node-count muted text-xs">
        {apis.length} API{apis.length !== 1 ? 's' : ''} assigned
      </div>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </div>
  );
}

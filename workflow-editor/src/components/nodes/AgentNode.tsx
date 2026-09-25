import { memo } from 'react';
import { Handle, Position, useConnection } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import { Bot, Hand, Wrench } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';
import { IoBadges } from '../studio/IoBadges';
import { StatusGlyph } from '../shell/StatusGlyph';
import { getAgentSummary } from '../../utils/studioDerivedState';
import { laneStyle, nodeStatusShape } from '../../utils/nodeTheme';
import { auxKindForToolType } from '../../utils/connectionRules';
import { useWorkflowStore } from '../../stores/workflowStore';

// Attachment ports along the bottom edge: tool, memory and knowledge nodes plug
// in here instead of joining the main left-to-right flow. Diamonds, as in n8n,
// so they read as a different kind of connection from the round flow handles.
const PORTS: Array<{ id: 'tools' | 'memory' | 'knowledge'; left: string; label: string }> = [
    { id: 'tools', left: '25%', label: 'Tools' },
    { id: 'memory', left: '50%', label: 'Memory' },
    { id: 'knowledge', left: '75%', label: 'Knowledge' },
];

export const AgentNode = memo(({ id, data, selected }: NodeProps<Node<WorkflowNodeData>>) => {
    const summary = getAgentSummary(data.config);

    // While a connection is being dragged from a tool's attach handle, light up
    // the one port that will accept it. Selector form: without it every node
    // re-renders on every pointer move of an in-progress connection.
    const pendingPort = useConnection((conn) =>
        conn.inProgress && conn.fromHandle?.id === 'attach' && conn.fromNode?.type === 'tool'
            ? auxKindForToolType((conn.fromNode?.data as WorkflowNodeData | undefined)?.config?.type)
            : null,
    );
    // Which ports have something attached — a string, so the node re-renders only
    // when that set changes, not on every edge update elsewhere.
    const attached = useWorkflowStore((state) =>
        state.edges.filter((edge) => edge.target === id && edge.targetHandle).map((edge) => edge.targetHandle).sort().join(','),
    );

    const shape = nodeStatusShape(data.status, summary.health, Boolean(data.lastOutput) && data.status !== 'error');
    const state = data.status === 'error' ? 'is-error' : data.status === 'running' ? 'is-running' : '';
    const sub = summary.isSelector ? `Selector · ${summary.model}` : summary.model;
    const hasMeta = summary.toolCount > 0 || summary.humanInput !== 'NEVER' || data.lastInput || data.lastOutput;

    return (
        <div
            className={`node-card is-agent ${state} ${selected ? 'is-selected' : ''}`}
            style={laneStyle('agent')}
            title={summary.issues.length ? summary.issues.join(' · ') : undefined}
        >
            <Handle type="target" position={Position.Left} />

            <span className="tile"><Bot size={19} strokeWidth={1.7} /></span>
            <span className="node-text">
                <span className="node-title" title={data.label}>{data.label || 'Untitled agent'}</span>
                <span className="node-sub">{summary.issues[0] ?? sub}</span>
                {hasMeta && (
                    <span className="node-meta">
                        {summary.toolCount > 0 && <span className="chip"><Wrench size={10} />{summary.toolCount}</span>}
                        {summary.humanInput !== 'NEVER' && <span className="chip" title="Asks a person for input"><Hand size={10} />Human</span>}
                        <IoBadges data={data} />
                    </span>
                )}
            </span>
            {shape && <span className="node-badge"><StatusGlyph shape={shape} /></span>}

            <Handle type="source" position={Position.Right} />

            {PORTS.map((port) => {
                const wanted = pendingPort === port.id;
                return (
                    <Handle
                        key={port.id}
                        id={port.id}
                        type="target"
                        position={Position.Bottom}
                        style={{ left: port.left }}
                        className={[
                            'is-port',
                            attached.split(',').includes(port.id) ? 'is-attached' : '',
                            wanted ? 'is-wanted' : '',
                            pendingPort !== null && !wanted ? 'is-dimmed' : '',
                        ].join(' ')}
                    />
                );
            })}
            <div className="port-labels" aria-hidden="true">
                {PORTS.map((port) => (
                    <span
                        key={port.id}
                        style={{ left: port.left }}
                        className={pendingPort === port.id ? 'is-wanted' : pendingPort !== null ? 'is-dimmed' : ''}
                    >
                        {port.label}
                    </span>
                ))}
            </div>
        </div>
    );
});

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import { GitBranch, ShieldCheck } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';
import { laneStyle } from '../../utils/nodeTheme';

export const RouterNode = memo(({ data, selected }: NodeProps<Node<WorkflowNodeData>>) => {
    const config = (data.config ?? {}) as Record<string, any>;
    const isGuardrail = config.type === 'guardrail';
    const Icon = isGuardrail ? ShieldCheck : GitBranch;
    const caption = isGuardrail
        ? `Guardrail · ${config.output_schema ?? 'text'}`
        : config.routing_mode === 'broadcast' ? 'Broadcast' : 'Conditional';

    return (
        <div className={`node-shape is-square ${selected ? 'is-selected' : ''}`} style={laneStyle('logic')}>
            {/* LR flow: input on the left, outputs fan out right, top and bottom */}
            <Handle type="target" position={Position.Left} />
            <Icon size={24} strokeWidth={1.7} />
            <span className="node-caption" style={{ top: 'calc(100% + 12px)' }}>
                <span className="node-title">{data.label || 'Router'}</span>
                <span className="node-sub">{caption}</span>
            </span>
            <Handle type="source" id="right" position={Position.Right} />
            <Handle type="source" id="top" position={Position.Top} />
            <Handle type="source" id="bottom" position={Position.Bottom} />
        </div>
    );
});

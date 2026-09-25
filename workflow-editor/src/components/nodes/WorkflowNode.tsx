import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import { Workflow } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';
import { StatusGlyph } from '../shell/StatusGlyph';
import { getWorkflowSummary } from '../../utils/studioDerivedState';
import { laneStyle } from '../../utils/nodeTheme';

export const WorkflowNode = memo(({ data, selected }: NodeProps<Node<WorkflowNodeData>>) => {
    const summary = getWorkflowSummary(data.config);
    return (
        <div className={`node-card w-[236px] ${selected ? 'is-selected' : ''}`} style={laneStyle('connect')}>
            <Handle type="target" position={Position.Left} />
            <span className="tile"><Workflow size={16} strokeWidth={1.8} /></span>
            <span className="node-text">
                <span className="node-title">{data.label || 'Workflow'}</span>
                <span className="node-sub">{summary.pattern} · {summary.nodeCount} nodes</span>
            </span>
            {summary.health !== 'ready' && <StatusGlyph shape="warn" />}
            <Handle type="source" position={Position.Right} />
        </div>
    );
});

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import { Flag } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';
import { laneStyle } from '../../utils/nodeTheme';

export const OutputNode = memo(({ data, selected }: NodeProps<Node<WorkflowNodeData>>) => (
    <div className={`node-shape is-square ${selected ? 'is-selected' : ''}`} style={laneStyle('output')}>
        <Handle type="target" position={Position.Left} />
        <Flag size={22} strokeWidth={1.7} />
        <span className="node-caption">
            <span className="node-title">{data.label || 'Answer'}</span>
            <span className="node-sub">Result</span>
        </span>
    </div>
));

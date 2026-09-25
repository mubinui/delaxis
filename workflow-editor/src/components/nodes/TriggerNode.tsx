import { memo, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node, NodeProps } from '@xyflow/react';
import type { LucideIcon } from 'lucide-react';
import { Play, MessageSquare, Link } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import type { WorkflowNodeData } from '../../types/workflow';
import { useWorkflowStore } from '../../stores/workflowStore';
import { runWorkflowLive } from '../../utils/liveRun';
import { laneStyle } from '../../utils/nodeTheme';
import { StatusGlyph } from '../shell/StatusGlyph';

const ICON_FOR_TRIGGER_TYPE: Record<string, LucideIcon> = {
    chat: MessageSquare,
    webhook: Link,
    manual: Play,
};

export const TriggerNode = memo(({ id, data, selected }: NodeProps<Node<WorkflowNodeData>>) => {
    const config = data.config as any;
    const triggerType = config?.trigger_type || 'manual';
    const Icon = ICON_FOR_TRIGGER_TYPE[triggerType] ?? Play;

    // Selector-scoped: this node only re-renders when these specific fields change,
    // not on every node/edge update elsewhere on the canvas.
    const { currentWorkflowId, setExecutingTrigger, executingTriggerId, triggerResult } = useWorkflowStore(
        useShallow((state) => ({
            currentWorkflowId: state.currentWorkflowId,
            setExecutingTrigger: state.setExecutingTrigger,
            executingTriggerId: state.executingTriggerId,
            triggerResult: state.triggerResult,
        })),
    );
    const [localStatus, setLocalStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');

    const isExecuting = executingTriggerId === id || localStatus === 'running';
    const showSuccess = (executingTriggerId === id && triggerResult === 'success') || localStatus === 'success';
    const showError = (executingTriggerId === id && triggerResult === 'error') || localStatus === 'error';

    const handleRun = async (e: React.MouseEvent) => {
        e.stopPropagation();

        // Use configured workflow_id or fall back to current canvas workflow
        const targetWorkflowId = config?.workflow_id || currentWorkflowId;

        if (!targetWorkflowId) {
            alert('Save or open a workflow before running this trigger.');
            return;
        }

        setLocalStatus('running');
        setExecutingTrigger(id, null);

        // Streamed, so the run plays on the canvas: this trigger's wire starts
        // moving, each wire lights as the run reaches the node it feeds, and the
        // path settles green — or red where it failed.
        const outcome = await runWorkflowLive(
            targetWorkflowId,
            config?.trigger_type === 'chat'
                ? String(config?.test_message || 'Hello, trigger test!')
                : '{"trigger": "manual", "source": "workflow_editor"}',
            { source: 'trigger_node', fromNodeIds: [id] },
        );

        setLocalStatus(outcome);
        setExecutingTrigger(id, outcome);
        // The trigger's own mark clears; the wires keep the last run until the next.
        setTimeout(() => {
            setLocalStatus('idle');
            setExecutingTrigger(null, null);
        }, 3000);
    };

    const shape = isExecuting ? 'busy' : showSuccess ? 'ok' : showError ? 'bad' : null;
    const kind = triggerType === 'chat' ? 'Chat message' : triggerType === 'webhook' ? 'Webhook call' : 'Manual run';

    // n8n's trigger shape — rounded on the side the flow starts from — with the
    // title underneath. The run button appears on hover, where a status would sit.
    return (
        <div
            className={`node-shape is-trigger group ${showError ? 'is-error' : ''} ${selected ? 'is-selected' : ''}`}
            style={laneStyle('trigger')}
        >
            <Icon size={24} strokeWidth={1.7} />
            {shape ? (
                <span className="node-badge">
                    <StatusGlyph shape={shape} label={shape === 'busy' ? 'Running' : shape === 'ok' ? 'Ran' : 'Failed'} />
                </span>
            ) : (
                <button
                    type="button"
                    onClick={handleRun}
                    disabled={isExecuting}
                    className="nodrag node-badge opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    style={{ background: 'var(--accent-fill)', color: 'var(--on-accent)', boxShadow: 'none', width: 22, height: 22, top: -6, right: -6 }}
                    title="Run this trigger"
                    aria-label="Run this trigger"
                >
                    <Play size={9} fill="currentColor" />
                </button>
            )}
            <span className="node-caption">
                <span className="node-title">{data.label || 'Start'}</span>
                <span className="node-sub">{kind}</span>
            </span>
            <Handle type="source" position={Position.Right} />
        </div>
    );
});

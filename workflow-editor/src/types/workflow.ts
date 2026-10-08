
import type { Node, Edge, Viewport } from '@xyflow/react';
import type { JsonObject } from './json';

export type NodeType = 'agent' | 'tool' | 'trigger' | 'router' | 'output' | 'workflow';

export interface NodeRunData {
    data: unknown;
    timestamp: string;
}

export interface WorkflowNodeData extends Record<string, unknown> {
    label: string;
    description?: string;
    config?: JsonObject;
    status?: 'configured' | 'error' | 'running' | 'idle';
    /** Data that entered this node during the last live run. */
    lastInput?: NodeRunData;
    /** Data this node produced during the last live run. */
    lastOutput?: NodeRunData;
}

export type VisualNode = Node<WorkflowNodeData, NodeType>;
export type VisualEdge = Edge;

export interface WorkflowCanvasState {
    nodes: VisualNode[];
    edges: VisualEdge[];
    viewport: Viewport;
}

export interface DragItem {
    type: NodeType;
    label: string;
}

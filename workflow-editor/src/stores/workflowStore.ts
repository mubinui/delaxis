
import { create } from 'zustand';
import {
    addEdge,
    applyNodeChanges,
    applyEdgeChanges,
} from '@xyflow/react';
import type {
    Connection,
    NodeChange,
    EdgeChange,
    OnNodesChange,
    OnEdgesChange,
    OnConnect,
} from '@xyflow/react';
import type { VisualNode, VisualEdge } from '../types/workflow';
import { AUX_EDGE_OPTIONS, isAuxHandle } from '../utils/connectionRules';

export interface ExecutionTimelineItem {
    id: string;
    type: string;
    label: string;
    nodeId?: string;
    agentId?: string;
    payload: Record<string, any>;
    status: 'running' | 'success' | 'error' | 'info';
    timestamp: string;
}

interface WorkflowState {
    nodes: VisualNode[];
    edges: VisualEdge[];
    // Current workflow tracking (for n8n-style testing)
    currentWorkflowId: string | null;
    workflowName: string;
    // Trigger execution state
    executingTriggerId: string | null;
    triggerResult: 'success' | 'error' | null;
    liveRunActive: boolean;
    liveResponse: string;
    executionTimeline: ExecutionTimelineItem[];
    // True while a node (or selection) is being dragged on the canvas — used to keep
    // the inspector out of the way until the drag finishes.
    isNodeDragging: boolean;

    onNodesChange: OnNodesChange<VisualNode>;
    onEdgesChange: OnEdgesChange;
    onConnect: OnConnect;
    addNode: (node: VisualNode) => void;
    addNodes: (nodes: VisualNode[]) => void;
    addEdges: (edges: VisualEdge[]) => void;
    updateNodeData: (id: string, data: Record<string, any>) => void;
    setNodes: (nodes: VisualNode[]) => void;
    setEdges: (edges: VisualEdge[]) => void;
    // Workflow tracking actions
    setCurrentWorkflow: (id: string | null, name?: string) => void;
    setWorkflowName: (name: string) => void;
    loadWorkflow: (id: string, name: string, nodes: VisualNode[], edges: VisualEdge[]) => void;
    // Trigger execution actions
    setExecutingTrigger: (id: string | null, result?: 'success' | 'error' | null) => void;
    resetExecution: () => void;
    applyExecutionEvent: (event: Record<string, any>) => void;
    applyNodeIo: (nodeIo?: Record<string, any> | null, toolIo?: Record<string, any> | null) => void;
    /** Start a run's flow at these nodes (triggers): their outgoing wires start moving. */
    beginFlow: (fromNodeIds?: string[]) => void;
    /** End a run: wires still moving turn green, or red if the run failed. */
    finishFlow: (ok: boolean) => void;
    setNodeDragging: (dragging: boolean) => void;
}

/** Where a run has reached on a wire: moving, arrived, or failed. */
export type EdgeFlow = 'running' | 'success' | 'error';

// Nodes that never report events of their own; a run passes straight through
// them, so a wire into a node they feed is lit back through them as well.
const PASS_THROUGH = new Set(['trigger', 'router', 'workflow']);

const RANK: Record<EdgeFlow, number> = { running: 1, success: 2, error: 3 };

const withFlow = (edge: VisualEdge, flow: EdgeFlow | undefined): VisualEdge => {
    const style = { ...(edge.style ?? {}) } as Record<string, unknown>;
    delete style.stroke;
    return { ...edge, animated: false, style, data: { ...(edge.data ?? {}), flow } } as VisualEdge;
};

const flowOf = (edge: VisualEdge): EdgeFlow | undefined => (edge.data as { flow?: EdgeFlow } | undefined)?.flow;

/**
 * Light the wires that lead into a node, and — through triggers and routers,
 * which report nothing themselves — the wires that lead into those. A wire only
 * moves forward: running, then success; error wins over both.
 */
const paintInto = (edges: VisualEdge[], nodes: VisualNode[], nodeId: string, flow: EdgeFlow): VisualEdge[] => {
    const typeOf = new Map(nodes.map((node) => [node.id, node.type]));
    const targets = new Set<string>([nodeId]);
    const queue = [nodeId];
    while (queue.length) {
        const current = queue.shift()!;
        for (const edge of edges) {
            if (edge.target !== current) continue;
            if (PASS_THROUGH.has(String(typeOf.get(edge.source))) && !targets.has(edge.source)) {
                targets.add(edge.source);
                queue.push(edge.source);
            }
        }
    }
    return edges.map((edge) => {
        const touches = targets.has(edge.target) || (edge.source === nodeId && edge.sourceHandle === 'attach');
        if (!touches) return edge;
        const current = flowOf(edge);
        if (current && RANK[current] > RANK[flow]) return edge;
        return withFlow(edge, flow);
    });
};

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
    nodes: [],
    edges: [],
    currentWorkflowId: null,
    workflowName: 'Untitled Workflow',
    executingTriggerId: null,
    triggerResult: null,
    liveRunActive: false,
    liveResponse: '',
    executionTimeline: [],
    isNodeDragging: false,

    setNodeDragging: (dragging: boolean) => {
        set({ isNodeDragging: dragging });
    },

    onNodesChange: (changes: NodeChange<VisualNode>[]) => {
        set({
            nodes: applyNodeChanges(changes, get().nodes),
        });
    },

    onEdgesChange: (changes: EdgeChange[]) => {
        set({
            edges: applyEdgeChanges(changes, get().edges),
        });
    },

    onConnect: (connection: Connection) => {
        // Attachment edges (into an agent's tools/memory/knowledge handle) get a
        // dashed look so they read differently from the main flow.
        const edgeToAdd = isAuxHandle(connection.targetHandle)
            ? { ...connection, ...AUX_EDGE_OPTIONS }
            : connection;
        set({
            edges: addEdge(edgeToAdd, get().edges),
        });
    },

    addNode: (node: VisualNode) => {
        set({
            nodes: [...get().nodes, node],
        });
    },

    addNodes: (nodes: VisualNode[]) => {
        set({
            nodes: [...get().nodes, ...nodes],
        });
    },

    addEdges: (edges: VisualEdge[]) => {
        set({
            edges: [...get().edges, ...edges],
        });
    },

    updateNodeData: (id: string, data: Record<string, any>) => {
        set({
            nodes: get().nodes.map((node) => {
                if (node.id === id) {
                    return {
                        ...node,
                        data: { ...node.data, ...data },
                    };
                }
                return node;
            }),
        });
    },

    setNodes: (nodes: VisualNode[]) => {
        set({ nodes });
    },

    setEdges: (edges: VisualEdge[]) => {
        set({ edges });
    },

    setCurrentWorkflow: (id: string | null, name?: string) => {
        set({
            currentWorkflowId: id,
            workflowName: name || get().workflowName,
        });
    },

    setWorkflowName: (name: string) => {
        set({ workflowName: name });
    },

    loadWorkflow: (id: string, name: string, nodes: VisualNode[], edges: VisualEdge[]) => {
        set({
            currentWorkflowId: id,
            workflowName: name,
            nodes,
            edges,
        });
    },

    setExecutingTrigger: (id: string | null, result?: 'success' | 'error' | null) => {
        set({
            executingTriggerId: id,
            triggerResult: result ?? null,
        });
    },

    resetExecution: () => {
        set({
            liveRunActive: false,
            liveResponse: '',
            executionTimeline: [],
            nodes: get().nodes.map((node) => {
                const data = { ...node.data, status: (node.data?.config ? 'configured' : 'idle') as 'configured' | 'idle' };
                delete data.lastInput;
                delete data.lastOutput;
                return { ...node, data };
            }),
            edges: get().edges.map((edge) => withFlow(edge, undefined)),
        });
    },

    beginFlow: (fromNodeIds?: string[]) => {
        const nodes = get().nodes;
        const starts = new Set(fromNodeIds?.length ? fromNodeIds : nodes.filter((node) => node.type === 'trigger').map((node) => node.id));
        set({ edges: get().edges.map((edge) => (starts.has(edge.source) ? withFlow(edge, 'running') : edge)) });
    },

    finishFlow: (ok: boolean) => {
        const nodes = get().nodes;
        let edges = get().edges.map((edge) => (flowOf(edge) === 'running' ? withFlow(edge, ok ? 'success' : 'error') : edge));
        if (ok) {
            // The answer reports nothing either: light the wires into it from any
            // node the run actually reached.
            const reached = new Set(edges.filter((edge) => flowOf(edge) === 'success').map((edge) => edge.target));
            const outputs = new Set(nodes.filter((node) => node.type === 'output').map((node) => node.id));
            edges = edges.map((edge) => (outputs.has(edge.target) && reached.has(edge.source) ? withFlow(edge, 'success') : edge));
        }
        set({ edges });
    },

    // Populate per-node run data from a completed run's metadata (node_io keyed
    // by topology node id == canvas node id; tool_io keyed by tool name). Used
    // by the non-streaming chat path and as a final fill on the live 'done'.
    applyNodeIo: (nodeIo?: Record<string, any> | null, toolIo?: Record<string, any> | null) => {
        if (!nodeIo && !toolIo) return;
        const timestamp = new Date().toISOString();
        const toolEntries = Object.values(toolIo ?? {}) as Array<Record<string, any>>;
        const ran: string[] = [];
        const nextNodes = get().nodes.map((node) => {
                const config = node.data?.config ?? {};
                const runData: Record<string, unknown> = {};

                const io = nodeIo?.[node.id];
                if (io?.input) runData.lastInput = { data: io.input, timestamp };
                if (io?.output) runData.lastOutput = { data: io.output, timestamp };

                if (node.type === 'tool') {
                    const match = toolEntries.find((entry) =>
                        entry.tool_id === config.id ||
                        entry.tool_id === config.tool_id ||
                        entry.name === config.name ||
                        entry.name === node.data?.label,
                    );
                    if (match) {
                        if (match.args) runData.lastInput = { data: match.args, timestamp };
                        if (match.result != null || match.error) {
                            runData.lastOutput = {
                                data: { result: match.result, error: match.error, duration_ms: match.duration_ms },
                                timestamp,
                            };
                        }
                    }
                }

                if (Object.keys(runData).length === 0) return node;
                ran.push(node.id);
                return { ...node, data: { ...node.data, ...runData } };
            });
        // Every node that produced data was reached: its wires turn green.
        let edges = get().edges;
        for (const id of ran) edges = paintInto(edges, nextNodes, id, 'success');
        set({ nodes: nextNodes, edges });
    },

    applyExecutionEvent: (event: Record<string, any>) => {
        const eventType = String(event.type ?? 'info');
        const payload = (event.payload ?? {}) as Record<string, any>;
        if (eventType === 'done') {
            // Backfill any node/tool data the stream didn't attribute live.
            get().applyNodeIo(payload.metadata?.node_io, payload.metadata?.tool_io);
        }
        const agentId = event.agent_id || payload.agent_id || payload.agent || payload.target_agent;
        const toolName = payload.name || payload.tool_name;
        const targetName = toolName || agentId;
        const nodes = get().nodes;
        // Node lifecycle events carry the exact topology node id (== canvas node
        // id); everything else falls back to the name/label heuristics.
        const exactNode = payload.node_id
            ? nodes.find((candidate) => candidate.id === payload.node_id)
            : undefined;
        // Only look a node up by name when the event names one: otherwise an
        // undefined name "matched" the first node without an id, and events like
        // `start` or an early `error` were pinned on an arbitrary node.
        const node = exactNode ?? (!targetName && !agentId ? undefined : nodes.find((candidate) => {
            const config = candidate.data?.config ?? {};
            return (
                candidate.id === targetName ||
                candidate.data?.label === targetName ||
                config.id === targetName ||
                config.name === targetName ||
                config.agent_id === targetName ||
                candidate.data?.label === agentId ||
                config.id === agentId ||
                config.agent_id === agentId
            );
        }));

        const status =
            eventType === 'error' ? 'error' :
                eventType === 'done' || eventType === 'tool_call_result' || eventType === 'node_output' ? 'success' :
                    eventType === 'token' || eventType === 'reasoning_delta' ? 'info' :
                        'running';

        const nodeLabel = node?.data?.label ?? payload.node_id ?? 'node';
        const labelMap: Record<string, string> = {
            start: 'Workflow started',
            token: 'Response token',
            reasoning_delta: 'Reasoning',
            node_started: `Node started: ${nodeLabel}`,
            node_input: `Input → ${nodeLabel}`,
            node_output: `Output ← ${nodeLabel}`,
            tool_call_start: `Tool call: ${toolName ?? 'tool'}`,
            tool_call_result: `Tool result: ${toolName ?? 'tool'}`,
            agent_transfer: `Transfer to ${payload.target_agent ?? 'agent'}`,
            error: payload.error_message ?? 'Execution error',
            done: 'Workflow completed',
        };

        const timelineItem: ExecutionTimelineItem = {
            id: `${event.sequence ?? Date.now()}-${eventType}`,
            type: eventType,
            label: labelMap[eventType] ?? eventType,
            nodeId: node?.id,
            agentId,
            payload,
            status,
            timestamp: event.timestamp ?? new Date().toISOString(),
        };

        const responseAppend = eventType === 'token' ? String(payload.text ?? payload.content ?? '') : '';
        const doneResult = eventType === 'done' ? payload.result?.response ?? '' : '';

        const eventTimestamp = String(event.timestamp ?? new Date().toISOString());
        set({
            liveRunActive: eventType !== 'done' && eventType !== 'error',
            liveResponse: doneResult || (get().liveResponse + responseAppend),
            executionTimeline: [...get().executionTimeline, timelineItem],
            nodes: nodes.map((candidate) => {
                if (!node || candidate.id !== node.id) return candidate;
                const runData: Record<string, unknown> = {};
                if (eventType === 'node_input') {
                    runData.lastInput = { data: payload.input ?? payload, timestamp: eventTimestamp };
                } else if (eventType === 'node_output') {
                    runData.lastOutput = { data: payload.output ?? payload, timestamp: eventTimestamp };
                } else if (eventType === 'tool_call_start') {
                    runData.lastInput = { data: payload.args ?? payload, timestamp: eventTimestamp };
                } else if (eventType === 'tool_call_result') {
                    runData.lastOutput = { data: payload.result ?? payload, timestamp: eventTimestamp };
                }
                return {
                    ...candidate,
                    data: {
                        ...candidate.data,
                        ...runData,
                        status: status === 'success' ? 'configured' : status === 'error' ? 'error' : 'running',
                    },
                };
            }),
            edges: node
                ? paintInto(get().edges, nodes, node.id, status === 'error' ? 'error' : status === 'success' ? 'success' : 'running')
                : get().edges,
        });
        // A run that ends (or fails) without naming a node settles every wire.
        if (eventType === 'done') get().finishFlow(true);
        if (eventType === 'error' && !node) get().finishFlow(false);
    },
}));


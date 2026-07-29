import type { VisualEdge, VisualNode } from '../types/workflow';

/**
 * Turn a saved workflow config into canvas nodes and edges.
 *
 * A workflow saved from the Studio carries `metadata.visual_canvas` and is
 * restored verbatim. Anything else — a workflow the AI builder just created, a
 * hand-written config, an import — has only a topology, so the graph is laid
 * out here. Without this, builder output lands in the config files and the
 * canvas stays empty.
 */

interface AgentLike {
    id: string;
    name?: string;
    description?: string;
    config?: Record<string, any>;
}

interface ToolLike {
    id: string;
    name?: string;
    description?: string;
    config?: Record<string, any>;
}

export interface CanvasBuildInput {
    config: Record<string, any>;
    /** Saved agents, used to fill in a topology node's model and instructions. */
    agents?: AgentLike[];
    /** Saved tools, used to render attached tool nodes with their real settings. */
    tools?: ToolLike[];
}

const COLUMN_WIDTH = 300;
const ROW_HEIGHT = 190;
const AGENT_Y = 200;
const TOOL_OFFSET_Y = 210;

const isSelectorTopology = (topology: any) => (
    Boolean(topology?.entry_node)
    && Array.isArray(topology?.domain_agents)
    && topology.domain_agents.length > 0
);

/** A canvas the Studio saved: nodes carry `data`, which topology nodes never do. */
const hasVisualCanvas = (canvas: any) =>
    Array.isArray(canvas?.nodes) && canvas.nodes.some((node: any) => node?.data);

const flowEdge = (source: string, target: string, index: number): VisualEdge => ({
    id: `xy-edge__${source}-${target}-${index}`,
    source,
    target,
    type: 'smoothstep',
    animated: true,
    style: { stroke: '#64748b', strokeWidth: 2 },
    markerEnd: { type: 'arrowclosed', color: '#64748b' } as any,
});

const auxEdge = (source: string, target: string, handle: string): VisualEdge => ({
    id: `xy-edge__${source}attach-${target}${handle}`,
    source,
    sourceHandle: 'attach',
    target,
    targetHandle: handle,
    type: 'straight',
    style: { stroke: '#94a3b8', strokeWidth: 1.5, strokeDasharray: '6 4' },
} as VisualEdge);

/**
 * Depth of each node from the entry, so a generated graph is laid out left to
 * right by execution order instead of in one flat row.
 */
function depthByNode(topology: any): Map<string, number> {
    const nodes: any[] = topology?.nodes ?? [];
    const edges: any[] = topology?.edges ?? [];
    const depth = new Map<string, number>();
    const outgoing = new Map<string, string[]>();

    edges.forEach((edge) => {
        const from = String(edge.from_node ?? edge.source ?? '');
        const to = String(edge.to_node ?? edge.target ?? '');
        if (!from || !to) return;
        outgoing.set(from, [...(outgoing.get(from) ?? []), to]);
    });

    const entry = String(topology?.entry_node ?? nodes[0]?.id ?? '');
    const queue: Array<[string, number]> = entry ? [[entry, 0]] : [];
    while (queue.length) {
        const [id, level] = queue.shift()!;
        // A node reached by several paths sits at its deepest level, so an edge
        // never has to point backwards.
        if (depth.has(id) && depth.get(id)! >= level) continue;
        depth.set(id, level);
        (outgoing.get(id) ?? []).forEach((next) => queue.push([next, level + 1]));
    }

    // Selector topologies store routing in domain_agents rather than edges, and
    // anything unreachable still has to be placed somewhere sensible.
    let orphanLevel = depth.size > 0 ? 1 : 0;
    nodes.forEach((node) => {
        if (!depth.has(node.id)) depth.set(node.id, orphanLevel);
    });
    if (isSelectorTopology(topology)) {
        nodes.forEach((node) => {
            if (node.id !== entry) depth.set(node.id, 1);
        });
        orphanLevel = 1;
    }
    return depth;
}

/** Positions nodes in columns by depth, stacking siblings vertically. */
function layout(topology: any): Map<string, { x: number; y: number }> {
    const depth = depthByNode(topology);
    const byLevel = new Map<number, string[]>();
    (topology?.nodes ?? []).forEach((node: any) => {
        const level = depth.get(node.id) ?? 0;
        byLevel.set(level, [...(byLevel.get(level) ?? []), node.id]);
    });

    const positions = new Map<string, { x: number; y: number }>();
    byLevel.forEach((ids, level) => {
        const height = (ids.length - 1) * ROW_HEIGHT;
        ids.forEach((id, index) => {
            positions.set(id, {
                x: 320 + level * COLUMN_WIDTH,
                y: AGENT_Y + index * ROW_HEIGHT - height / 2,
            });
        });
    });
    return positions;
}

export interface CanvasGraph {
    nodes: VisualNode[];
    edges: VisualEdge[];
    /** True when the layout was derived rather than restored from a saved canvas. */
    generated: boolean;
}

export function workflowToCanvas(input: CanvasBuildInput): CanvasGraph {
    const { config, agents = [], tools = [] } = input;
    const topology = config?.topology ?? {};
    const canvas = config?.metadata?.visual_canvas ?? config;

    if (hasVisualCanvas(canvas)) {
        const restoredEdges: VisualEdge[] = Array.isArray(canvas.edges) ? canvas.edges : [];
        return { nodes: canvas.nodes as VisualNode[], edges: restoredEdges, generated: false };
    }

    const agentById = new Map(agents.map((agent) => [agent.id, agent]));
    const toolById = new Map(tools.map((tool) => [tool.id, tool]));
    const selector = isSelectorTopology(topology);
    const positions = layout(topology);
    const topologyNodes: any[] = topology?.nodes ?? [];

    const nodes: VisualNode[] = [];
    const edges: VisualEdge[] = [];

    // Entry point, so the graph reads as a runnable workflow rather than a
    // floating set of agents.
    nodes.push({
        id: 'trigger-chat',
        type: 'trigger',
        position: { x: 40, y: AGENT_Y },
        data: {
            label: 'On Chat',
            config: { trigger_type: 'chat', label: 'On Chat', workflow_id: config?.id ?? '' },
        },
    } as VisualNode);

    topologyNodes.forEach((node: any, index: number) => {
        const agentId = String(node.agent_id ?? node.id);
        const agent = agentById.get(agentId);
        const agentConfig = agent?.config ?? {};
        const position = positions.get(node.id) ?? { x: 320 + index * COLUMN_WIDTH, y: AGENT_Y };

        nodes.push({
            id: node.id,
            type: 'agent',
            position: node.position ?? position,
            data: {
                label: agent?.name ?? agentConfig.name ?? agentId,
                description: node.description ?? agent?.description ?? '',
                config: {
                    id: agentId,
                    agent_id: agentId,
                    name: agent?.name ?? agentConfig.name ?? agentId,
                    type: agentConfig.type ?? 'conversable',
                    instruction: agentConfig.instruction ?? agentConfig.system_message ?? '',
                    system_message: agentConfig.system_message ?? agentConfig.instruction ?? '',
                    model_config: agentConfig.model_config ?? agentConfig.llm_config ?? {},
                    tools: agentConfig.tools ?? [],
                    human_input_mode: agentConfig.human_input_mode ?? 'NEVER',
                    ...(node.config ?? {}),
                    is_selector: Boolean(
                        node.is_router
                        ?? node.config?.is_selector
                        ?? agentConfig.is_selector
                        ?? (selector && node.id === topology.entry_node),
                    ),
                },
            },
        } as VisualNode);
    });

    // Attachments: a topology node's tools/memory/knowledge become real nodes on
    // the aux handles, so what the builder configured is visible and editable.
    topologyNodes.forEach((node: any) => {
        const position = positions.get(node.id) ?? { x: 320, y: AGENT_Y };
        const attached: Array<{ id: string; label: string; config: Record<string, any>; handle: string }> = [];

        (node.tools ?? []).forEach((toolId: string) => {
            const tool = toolById.get(toolId);
            attached.push({
                id: `${node.id}--tool--${toolId}`,
                label: tool?.name ?? toolId,
                config: {
                    id: toolId,
                    name: tool?.name ?? toolId,
                    description: tool?.description ?? '',
                    ...(tool?.config ?? {}),
                },
                handle: 'tools',
            });
        });
        if (node.memory) {
            attached.push({
                id: `${node.id}--memory`,
                label: 'Memory Store',
                config: {
                    type: 'memory',
                    memory_enabled: true,
                    retention: config?.memory?.retention ?? 'session',
                },
                handle: 'memory',
            });
        }
        if (node.knowledge) {
            attached.push({
                id: `${node.id}--knowledge`,
                label: 'Knowledge Source',
                config: {
                    type: 'knowledge',
                    knowledge_enabled: true,
                    collections: config?.knowledge?.collections ?? [],
                    top_k: config?.knowledge?.top_k ?? 5,
                },
                handle: 'knowledge',
            });
        }

        const spread = (attached.length - 1) * 150;
        attached.forEach((item, index) => {
            nodes.push({
                id: item.id,
                type: 'tool',
                position: { x: position.x + index * 150 - spread / 2, y: position.y + TOOL_OFFSET_Y },
                data: { label: item.label, config: item.config },
            } as VisualNode);
            edges.push(auxEdge(item.id, node.id, item.handle));
        });
    });

    // A Guardrail node makes the workflow-level setting visible and editable
    // instead of being an invisible flag.
    if (config?.guardrails?.enabled) {
        const lastLevel = Math.max(0, ...[...positions.values()].map((p) => p.x));
        nodes.push({
            id: 'guardrail-final',
            type: 'router',
            position: { x: lastLevel + COLUMN_WIDTH, y: AGENT_Y },
            data: {
                label: 'Guardrail',
                config: {
                    type: 'guardrail',
                    guardrails_enabled: true,
                    output_schema: config.guardrails.output_schema ?? 'text',
                    human_review: Boolean(config.guardrails.human_review),
                },
            },
        } as VisualNode);
    }

    // Flow edges: explicit topology edges, else the selector's fan-out.
    const topologyEdges: any[] = topology?.edges ?? [];
    if (topologyEdges.length > 0) {
        topologyEdges.forEach((edge, index) => {
            const source = String(edge.from_node ?? edge.source ?? '');
            const target = String(edge.to_node ?? edge.target ?? '');
            if (source && target) edges.push(flowEdge(source, target, index));
        });
    } else if (topologyNodes.length > 1) {
        const entry = String(topology?.entry_node ?? topologyNodes[0].id);
        topologyNodes
            .filter((node) => node.id !== entry)
            .forEach((node, index) => edges.push(flowEdge(entry, node.id, index)));
    }

    const entryNode = String(topology?.entry_node ?? topologyNodes[0]?.id ?? '');
    if (entryNode) edges.push(flowEdge('trigger-chat', entryNode, 999));

    // Terminal agents feed the guardrail when there is one.
    if (config?.guardrails?.enabled) {
        const hasOutgoing = new Set(
            topologyEdges.map((edge) => String(edge.from_node ?? edge.source ?? '')),
        );
        topologyNodes
            .filter((node) => !hasOutgoing.has(node.id))
            .forEach((node, index) => edges.push(flowEdge(node.id, 'guardrail-final', 500 + index)));
    }

    return { nodes, edges, generated: true };
}

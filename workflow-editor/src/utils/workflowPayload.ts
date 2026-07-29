import type { VisualEdge, VisualNode } from '../types/workflow';
import { isAuxHandle } from './connectionRules';

const slugify = (value: string, fallback: string) => {
    const slug = value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '_')
        .replace(/^_+|_+$/g, '');
    return slug || fallback;
};

const agentIdForNode = (node: VisualNode) => {
    const config = node.data?.config ?? {};
    return slugify(String(config.id ?? config.agent_id ?? config.name ?? node.data?.label ?? node.id), 'agent');
};

export interface AgentBinding {
    nodeId: string;
    label: string;
    /** The backend agent id this node will reference on save. */
    agentId: string;
}

/**
 * The backend agent id each agent node on the canvas resolves to. The backend
 * rejects a workflow whose topology references an agent id absent from the
 * agent registry, so callers compare these against the known agents to catch
 * unbound placeholder nodes before saving.
 */
export function getAgentBindings(nodes: VisualNode[]): AgentBinding[] {
    return nodes
        .filter((node) => node.type === 'agent')
        .map((node) => ({
            nodeId: node.id,
            label: String(node.data?.label ?? node.id),
            agentId: agentIdForNode(node),
        }));
}

/** A Guardrail node is a `router` node distinguished by its config type. */
const isGuardrailNode = (node: VisualNode) =>
    node.data?.config?.type === 'guardrail' || Boolean(node.data?.config?.guardrails_enabled);

/** Flow Router: a `router` node that is not a Guardrail. */
const isFlowRouter = (node: VisualNode) => node.type === 'router' && !isGuardrailNode(node);

/**
 * Nodes the flow passes *through* rather than stopping at. They carry no agent,
 * so they cannot be topology nodes — but the connections drawn through them are
 * real, and used to be discarded along with the node (a canvas wired
 * `agent → router → agent` saved as two unconnected agents).
 */
const isPassThrough = (node: VisualNode) => node.type === 'router';

/** Flow edges only: attachment edges bind a tool to an agent, they are not flow. */
const isFlowEdge = (edge: VisualEdge) => !isAuxHandle(edge.targetHandle);

export interface CompiledLink {
    from: string;
    to: string;
    /** The hop went through a Flow Router, so the source is a branching point. */
    viaRouter: boolean;
}

/**
 * Agent→agent links, contracting every pass-through node on the way.
 *
 * `a → router → {b, c}` compiles to `a → b` and `a → c`, both flagged
 * `viaRouter` so the caller can turn `a` into a selector.
 */
export function compileFlowLinks(nodes: VisualNode[], edges: VisualEdge[]): CompiledLink[] {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const flowEdges = edges.filter(isFlowEdge);
    const agentIds = new Set(nodes.filter((node) => node.type === 'agent').map((node) => node.id));

    const reachableAgents = (fromId: string, viaRouter: boolean, visited: Set<string>): CompiledLink[] => {
        const links: CompiledLink[] = [];
        for (const edge of flowEdges.filter((candidate) => candidate.source === fromId)) {
            const target = nodeById.get(edge.target);
            if (!target || visited.has(target.id)) continue;
            if (agentIds.has(target.id)) {
                links.push({ from: '', to: target.id, viaRouter });
                continue;
            }
            if (!isPassThrough(target)) continue;
            // Guardrails do not branch; only a Flow Router marks its source a selector.
            const nextVia = viaRouter || isFlowRouter(target);
            links.push(...reachableAgents(target.id, nextVia, new Set([...visited, target.id])));
        }
        return links;
    };

    const compiled: CompiledLink[] = [];
    const seen = new Set<string>();
    for (const node of nodes) {
        if (node.type !== 'agent') continue;
        for (const link of reachableAgents(node.id, false, new Set([node.id]))) {
            const key = `${node.id}->${link.to}`;
            if (seen.has(key)) continue;
            seen.add(key);
            compiled.push({ from: node.id, to: link.to, viaRouter: link.viaRouter });
        }
    }
    return compiled;
}

/** Agent node ids that branch through a Flow Router, i.e. real selectors. */
const routerSelectorIds = (links: CompiledLink[]) => {
    const branches = new Map<string, number>();
    links.filter((link) => link.viaRouter).forEach((link) => {
        branches.set(link.from, (branches.get(link.from) ?? 0) + 1);
    });
    return new Set([...branches].filter(([, count]) => count >= 2).map(([id]) => id));
};

const inferPattern = (nodes: VisualNode[], links: CompiledLink[], selectors: Set<string>) => {
    const hasSelector = selectors.size > 0 || nodes.some((node) => node.data?.config?.is_selector);
    const hasLoop = nodes.some((node) => node.data?.config?.type === 'LoopAgent');
    const agentCount = nodes.filter((node) => node.type === 'agent').length;
    const branchSources = new Set(
        links.filter((link) => links.filter((other) => other.from === link.from).length > 1).map((link) => link.from),
    );

    if (hasLoop) return 'loop';
    if (hasSelector) return 'selector';
    if (branchSources.size > 0) return 'parallel';
    if (agentCount <= 1) return 'single';
    return 'sequential';
};

const findEntryNode = (nodes: VisualNode[], edges: VisualEdge[], links: CompiledLink[]) => {
    const agentNodes = nodes.filter((node) => node.type === 'agent');
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const flowEdges = edges.filter(isFlowEdge);

    // The first agent a trigger reaches, walking through any pass-through nodes.
    const fromTrigger = (startId: string, visited: Set<string>): VisualNode | null => {
        for (const edge of flowEdges.filter((candidate) => candidate.source === startId)) {
            const target = nodeById.get(edge.target);
            if (!target || visited.has(target.id)) continue;
            if (target.type === 'agent') return target;
            if (isPassThrough(target)) {
                const found = fromTrigger(target.id, new Set([...visited, target.id]));
                if (found) return found;
            }
        }
        return null;
    };

    for (const trigger of nodes.filter((node) => node.type === 'trigger')) {
        const entry = fromTrigger(trigger.id, new Set([trigger.id]));
        if (entry) return entry;
    }

    // Otherwise the agent nothing else feeds into.
    const hasUpstream = new Set(links.map((link) => link.to));
    return agentNodes.find((node) => !hasUpstream.has(node.id)) ?? agentNodes[0];
};

const processForPattern = (pattern: string) => (
    pattern === 'selector' || pattern === 'parallel' ? 'hierarchical' : 'sequential'
);

const taskForNode = (node: VisualNode, index: number) => {
    const config = node.data?.config ?? {};
    return {
        id: `${node.id}_task`,
        node_id: node.id,
        agent_id: agentIdForNode(node),
        description: String(
            config.task
            ?? config.goal
            ?? config.description
            ?? node.data?.description
            ?? `Run ${node.data?.label ?? node.id} as CrewAI task ${index + 1}.`,
        ),
        expected_output: String(
            config.expected_output
            ?? config.output_schema
            ?? 'A structured, useful result for the next node or final response.',
        ),
    };
};

export function buildWorkflowPayload(options: {
    id?: string | null;
    name: string;
    nodes: VisualNode[];
    edges: VisualEdge[];
}) {
    const id = slugify(options.id || options.name, 'workflow');
    const agentNodes = options.nodes.filter((node) => node.type === 'agent');
    const links = compileFlowLinks(options.nodes, options.edges);
    const selectorIds = routerSelectorIds(links);
    const entryNode = findEntryNode(options.nodes, options.edges, links);
    const pattern = inferPattern(options.nodes, links, selectorIds);

    const backendNodes = agentNodes.map((node) => ({
        id: node.id,
        agent_id: agentIdForNode(node),
        position: {
            x: node.position.x,
            y: node.position.y,
        },
        // An agent that fans out through a Flow Router really is a selector, so
        // the backend gives it delegation over its branches.
        config: selectorIds.has(node.id)
            ? { ...(node.data?.config ?? {}), is_selector: true }
            : node.data?.config ?? {},
    }));

    const agentNodeIds = new Set(agentNodes.map((node) => node.id));

    // Auxiliary attachments: edges landing on an agent's tools/memory/knowledge
    // handle bind that tool node to the agent instead of joining the flow.
    const nodeById = new Map(options.nodes.map((node) => [node.id, node]));
    const toolAttachments = new Map<string, string[]>();
    const memoryAttached = new Set<string>();
    const knowledgeAttached = new Set<string>();
    for (const edge of options.edges) {
        if (!isAuxHandle(edge.targetHandle) || !agentNodeIds.has(edge.target)) continue;
        const source = nodeById.get(edge.source);
        if (!source || source.type !== 'tool') continue;
        if (edge.targetHandle === 'memory') {
            memoryAttached.add(edge.target);
        } else if (edge.targetHandle === 'knowledge') {
            knowledgeAttached.add(edge.target);
        } else {
            const config = source.data?.config ?? {};
            const toolId = slugify(String(config.id ?? config.tool_id ?? config.name ?? source.data?.label ?? source.id), 'tool');
            const bucket = toolAttachments.get(edge.target) ?? [];
            if (!bucket.includes(toolId)) bucket.push(toolId);
            toolAttachments.set(edge.target, bucket);
        }
    }

    const connections = links
        .filter((link) => agentNodeIds.has(link.from) && agentNodeIds.has(link.to))
        // The backend validator only accepts 'sequential' | 'parallel'; branch
        // selection is expressed by is_selector on the source node, not here.
        .map((link) => ({
            from_node: link.from,
            to_node: link.to,
            type: 'sequential',
        }));

    const topologyEdges = connections.map((edge) => ({
        from_node: edge.from_node,
        to_node: edge.to_node,
        source: edge.from_node,
        target: edge.to_node,
        context_strategy: 'full',
    }));

    const topology = {
        type: pattern === 'single' ? 'single' : pattern === 'sequential' ? 'sequential' : 'graph',
        nodes: backendNodes.map((node) => ({
            id: node.id,
            agent_id: node.agent_id,
            description: node.config?.description ?? '',
            position: node.position,
            config: node.config,
            // AgentNode.is_router — the backend grants delegation over the
            // branches this node fans out to.
            ...(selectorIds.has(node.id) ? { is_router: true } : {}),
            tools: toolAttachments.get(node.id) ?? [],
            ...(memoryAttached.has(node.id) ? { memory: true } : {}),
            ...(knowledgeAttached.has(node.id) ? { knowledge: true } : {}),
        })),
        edges: topologyEdges,
        entry_node: entryNode?.id ?? backendNodes[0]?.id ?? '',
    };

    const process = processForPattern(pattern);
    const tasks = agentNodes.map(taskForNode);
    // Handle attachments win; the presence scan keeps legacy canvases (memory/
    // knowledge nodes sitting in the main flow) behaving as before.
    const memoryNodes = options.nodes.filter((node) => node.data?.config?.type === 'memory' || node.data?.config?.memory_enabled);
    const knowledgeNodes = options.nodes.filter((node) => node.data?.config?.type === 'knowledge' || node.data?.config?.knowledge_enabled);
    const guardrailNodes = options.nodes.filter((node) => node.type === 'router' && isGuardrailNode(node));

    const memoryEnabled = memoryAttached.size > 0 || memoryNodes.length > 0;
    const knowledgeEnabled = knowledgeAttached.size > 0 || knowledgeNodes.length > 0;

    // Each of these used to be hardcoded, so the node's own settings were
    // discarded — a Guardrail node in particular changed nothing at all, since
    // guardrails were written as `enabled || true`.
    const memoryConfig = memoryNodes[0]?.data?.config ?? {};
    const knowledgeConfig = knowledgeNodes[0]?.data?.config ?? {};
    const guardrailConfig = guardrailNodes[0]?.data?.config ?? {};
    const outputSchema = String(guardrailConfig.output_schema ?? 'text');

    const create = {
        id,
        name: options.name,
        description: `Workflow with ${options.nodes.length} nodes and ${options.edges.length} edges`,
        pattern,
        entry_agent_id: entryNode ? agentIdForNode(entryNode) : backendNodes[0]?.agent_id ?? '',
        max_turns: 10,
        enabled: true,
        workflow_type: pattern === 'single' ? 'chatbot' : pattern,
        persistence: pattern === 'single' ? 'mongo_only' : 'postgres',
        topology,
        execution_strategy: pattern === 'parallel' ? 'parallel' : 'sequential',
        runtime: 'crewai',
        process,
        tasks,
        memory: {
            // Was `memoryEnabled || true` (always on); enabled now actually
            // reflects attached/present memory nodes.
            enabled: memoryEnabled,
            retention: String(memoryConfig.retention ?? 'session'),
        },
        knowledge: {
            enabled: knowledgeEnabled,
            collections: Array.isArray(knowledgeConfig.collections)
                ? knowledgeConfig.collections.map(String)
                : [],
            top_k: Number(knowledgeConfig.top_k ?? 5),
        },
        guardrails: {
            // A Guardrail node now actually switches this on, and carries its
            // own schema/review settings, instead of being decorative.
            enabled: guardrailNodes.length > 0,
            human_review: Boolean(guardrailConfig.human_review),
            output_schema: outputSchema,
        },
        tracing: {
            enabled: true,
            amp_enabled: false,
            event_listeners: ['crew', 'agent', 'task', 'tool', 'llm', 'memory', 'knowledge'],
        },
        event_listeners: [],
        mcp_servers: [],
        output_schema: outputSchema,
        deployment_auth_mode: 'private',
        nodes: backendNodes,
        connections,
        metadata: {
            visual_canvas: {
                nodes: options.nodes,
                edges: options.edges,
                viewport: { x: 0, y: 0, zoom: 1 },
            },
        },
    };

    const update = {
        name: create.name,
        description: create.description,
        pattern,
        entry_agent_id: create.entry_agent_id,
        nodes: backendNodes,
        connections,
        topology,
        execution_strategy: create.execution_strategy,
        process,
        tasks,
        memory: create.memory,
        knowledge: create.knowledge,
        guardrails: create.guardrails,
        tracing: create.tracing,
        event_listeners: create.event_listeners,
        mcp_servers: create.mcp_servers,
        output_schema: create.output_schema,
        deployment_auth_mode: create.deployment_auth_mode,
        metadata: create.metadata,
    };

    return { id, create, update };
}

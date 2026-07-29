import type { ApiProvider, LibraryItem } from '../api/backendTypes';
import type { VisualEdge, VisualNode } from '../types/workflow';
import { isValidConnection } from './connectionRules';
import { getNodeSummary } from './studioDerivedState';
import { getAgentBindings } from './workflowPayload';

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export interface Diagnostic {
    /** Stable within a graph so React keys and "explain" requests are consistent. */
    id: string;
    code: string;
    severity: DiagnosticSeverity;
    title: string;
    detail: string;
    nodeId?: string;
    nodeLabel?: string;
    /** Key into COMPONENT_HELP so a finding can link to its component's docs. */
    component?: string;
    fixHint?: string;
    suggestions?: string[];
}

export interface DiagnosticsInput {
    nodes: VisualNode[];
    edges: VisualEdge[];
    agents?: LibraryItem[];
    tools?: LibraryItem[];
    providers?: ApiProvider[];
}

const label = (node: VisualNode) => String(node.data?.label ?? node.id);

/** Same normalisation buildWorkflowPayload applies when it derives a tool id. */
const slugish = (value: string) =>
    value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');

const modelConfigOf = (node: VisualNode) =>
    (node.data?.config?.model_config ?? node.data?.config?.llm_config ?? {}) as Record<string, any>;

/**
 * Everything wrong with a graph, computed locally.
 *
 * Runs on the live canvas — including work that has never been saved — so the
 * user gets an answer without a round trip. The backend performs the checks the
 * browser cannot (tool entrypoint imports, server-side references); this covers
 * the rest, plus the canvas-only problems the backend can never see because
 * those node types do not exist in its model.
 */
export function diagnoseWorkflow(input: DiagnosticsInput): Diagnostic[] {
    const { nodes, edges, agents = [], tools = [], providers = [] } = input;
    const findings: Diagnostic[] = [];
    const push = (d: Omit<Diagnostic, 'id'>) =>
        findings.push({ ...d, id: `${d.code}:${d.nodeId ?? 'graph'}` });

    if (nodes.length === 0) {
        push({
            code: 'workflow_empty',
            severity: 'info',
            title: 'Canvas is empty',
            detail: 'Drag a trigger and an agent from the palette to start building.',
            component: 'workflow',
        });
        return findings;
    }

    const agentNodes = nodes.filter((n) => n.type === 'agent');
    const knownAgents = new Set(agents.map((a) => a.id));
    const knownTools = new Map(tools.map((t) => [t.id, t]));
    const llmProviders = new Map(providers.filter((p) => p.type === 'llm').map((p) => [p.id, p]));

    // --- Graph shape -------------------------------------------------------
    if (agentNodes.length === 0) {
        push({
            code: 'no_agent',
            severity: 'error',
            title: 'No agent on the canvas',
            detail: 'A workflow needs at least one agent to do any work.',
            component: 'agent',
            fixHint: 'Drag a CrewAI Agent from the palette.',
        });
    }

    if (!nodes.some((n) => n.type === 'trigger')) {
        push({
            code: 'no_trigger',
            severity: 'warning',
            title: 'No trigger node',
            detail: 'Without a trigger this workflow can only be run manually from the studio.',
            component: 'trigger',
            fixHint: 'Add a Manual, Chat or Webhook trigger.',
        });
    }

    // Orphans: ignore aux attachments, which are not flow edges.
    const flowEdges = edges.filter((e) => !e.targetHandle || !['tools', 'memory', 'knowledge'].includes(String(e.targetHandle)));
    if (nodes.length > 1) {
        nodes.forEach((node) => {
            const connected = flowEdges.some((e) => e.source === node.id || e.target === node.id);
            const attached = edges.some((e) => e.source === node.id || e.target === node.id);
            if (!connected && !attached) {
                push({
                    code: 'orphan_node',
                    severity: 'warning',
                    title: `"${label(node)}" is not connected`,
                    detail: 'Nothing flows into or out of this node, so it will never run.',
                    nodeId: node.id,
                    nodeLabel: label(node),
                    component: node.type,
                    fixHint: 'Connect it to the flow, or delete it.',
                });
            }
        });
    }

    // Cycles over flow edges
    for (const cycle of detectCycles(flowEdges)) {
        push({
            code: 'cycle_detected',
            severity: 'warning',
            title: 'Loop in the graph',
            detail: `These nodes form a cycle: ${cycle.join(' → ')}. Unless a Loop agent bounds it, this can run forever.`,
            component: 'workflow',
            fixHint: 'Remove one connection, or set a max iteration limit.',
        });
    }

    // Attachment edges that violate the typed-handle rules. Edges created
    // before those rules existed, or arriving via import, are not re-checked
    // anywhere else.
    edges.forEach((edge) => {
        if (!isValidConnection(edge, nodes)) {
            const source = nodes.find((n) => n.id === edge.source);
            push({
                code: 'invalid_attachment',
                severity: 'error',
                title: 'Invalid attachment',
                detail: `"${source ? label(source) : edge.source}" is attached to a handle that does not accept it.`,
                nodeId: edge.source,
                nodeLabel: source ? label(source) : undefined,
                component: 'tool',
                fixHint: 'Memory attaches to the memory handle, knowledge to knowledge, everything else to tools.',
            });
        }
    });

    // --- Silent data loss on save -----------------------------------------
    // buildWorkflowPayload persists agent nodes plus the connections between
    // them; router and guardrail nodes are compiled into those connections and
    // settings, but an Output node carries nothing and simply disappears.
    // Triggers are excluded: they are managed through the triggers API rather
    // than the topology, so flagging them would fire on every normal canvas.
    const dropped = nodes.filter((n) => n.type === 'output');
    if (dropped.length > 0) {
        push({
            code: 'nodes_dropped_on_save',
            severity: 'info',
            title: `${dropped.length} node${dropped.length === 1 ? '' : 's'} will not be saved`,
            detail:
                `${dropped.map(label).join(', ')} — an Output node is a visual terminator only. ` +
                'The last agent to run supplies the workflow result either way.',
            component: 'output',
        });
    }

    // A Flow Router only means anything when it actually branches: with one
    // outgoing edge it compiles to a plain hand-off.
    nodes
        .filter((n) => n.type === 'router' && n.data?.config?.type !== 'guardrail')
        .forEach((node) => {
            const outgoing = flowEdges.filter((e) => e.source === node.id).length;
            if (outgoing < 2) {
                push({
                    code: 'router_without_branches',
                    severity: 'warning',
                    title: `"${label(node)}" has ${outgoing} branch${outgoing === 1 ? '' : 'es'}`,
                    detail:
                        'A Flow Router makes the agent feeding it delegate between the agents it fans out to. ' +
                        'With fewer than two outgoing connections it just passes the result straight through.',
                    nodeId: node.id,
                    nodeLabel: label(node),
                    component: 'router',
                    fixHint: 'Connect the router to at least two agents, or remove it.',
                });
            }
        });

    // Tool nodes attached to an agent but never registered on the backend.
    // At run time these resolve to nothing: the server logs `crewai_tool_missing`
    // and the agent silently runs without the capability.
    const toolNameOrId = new Set([...knownTools.keys(), ...tools.map((t) => t.name)]);
    edges
        .filter((e) => String(e.targetHandle ?? '') === 'tools')
        .forEach((edge) => {
            const source = nodes.find((n) => n.id === edge.source);
            if (!source || source.type !== 'tool') return;
            const config = (source.data?.config ?? {}) as Record<string, any>;
            const toolId = String(config.id ?? config.tool_id ?? config.name ?? source.data?.label ?? source.id);
            if (toolNameOrId.has(toolId) || toolNameOrId.has(slugish(toolId))) return;
            push({
                code: 'tool_not_registered',
                severity: 'error',
                title: `"${label(source)}" is not registered on the backend`,
                detail:
                    'This tool exists only on the canvas, so the agent will run without it. ' +
                    'Tool nodes have to be saved to the library before a run can resolve them.',
                nodeId: source.id,
                nodeLabel: label(source),
                component: `tool.${config.type ?? ''}`,
                fixHint: 'Open the node and use "Save to Library (registers on backend)".',
            });
        });

    // A Knowledge Source with no collection cannot retrieve anything.
    nodes
        .filter((n) => n.data?.config?.type === 'knowledge')
        .forEach((node) => {
            const collections = node.data?.config?.collections;
            if (!Array.isArray(collections) || collections.length === 0) {
                push({
                    code: 'knowledge_without_collections',
                    severity: 'warning',
                    title: `"${label(node)}" has no collection`,
                    detail:
                        'Retrieval runs against named RAG collections. Without one the agent gets no ' +
                        'search tool and falls back to the workflow description alone.',
                    nodeId: node.id,
                    nodeLabel: label(node),
                    component: 'tool.knowledge',
                    fixHint: 'Name at least one collection on the node.',
                });
            }
        });

    // --- Per-node configuration -------------------------------------------
    nodes.forEach((node) => {
        const summary = getNodeSummary(node);
        summary?.issues.forEach((issue) => {
            push({
                code: `config_${issue.toLowerCase().replace(/[^a-z]+/g, '_').replace(/^_|_$/g, '')}`,
                severity: 'error',
                title: `${label(node)}: ${issue.toLowerCase()}`,
                detail: `This node is missing required configuration: ${issue.toLowerCase()}.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: node.type,
            });
        });
    });

    // Agents pointing at a provider/model that will not resolve
    agentNodes.forEach((node) => {
        const model = modelConfigOf(node);
        const providerId = String(model.provider_id ?? '');
        if (!providerId) return;

        const provider = llmProviders.get(providerId);
        if (!provider) {
            push({
                code: 'provider_missing',
                severity: 'error',
                title: `${label(node)}: unknown provider`,
                detail: `Provider "${providerId}" is not configured.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'agent',
                suggestions: [...llmProviders.keys()].slice(0, 5),
                fixHint: 'Pick a configured provider, or add it under Library → Providers.',
            });
            return;
        }

        // api_key_masked is populated from the inline key, the secret store or
        // the env var, so a null value means nothing will authenticate.
        if (!provider.api_key_masked) {
            push({
                code: 'provider_key_missing',
                severity: 'error',
                title: `${label(node)}: no API key`,
                detail: provider.api_key_env
                    ? `Provider "${providerId}" has no key. Set ${provider.api_key_env} or paste one in the provider settings.`
                    : `Provider "${providerId}" has no key configured.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'agent',
                fixHint: 'Add the key to your .env file, or paste it in the provider settings.',
            });
        }

        const modelName = String(model.model ?? '');
        const known = (provider.models ?? []).map((m: any) => String(m.name ?? '')).filter(Boolean);
        if (modelName && known.length > 0 && !known.includes(modelName)) {
            push({
                code: 'model_unknown_for_provider',
                severity: 'warning',
                title: `${label(node)}: unrecognised model`,
                detail: `"${modelName}" is not in the known list for ${providerId}. It may still work.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'agent',
                suggestions: known.slice(0, 5),
                fixHint: 'Use "Refresh models" to pull the provider\'s current list.',
            });
        }
    });

    // Tools referenced by an agent but missing or disabled
    agentNodes.forEach((node) => {
        const referenced: string[] = Array.isArray(node.data?.config?.tools) ? node.data.config.tools.map(String) : [];
        referenced.forEach((toolName) => {
            const tool = knownTools.get(toolName) ?? [...knownTools.values()].find((t) => t.name === toolName);
            if (!tool) {
                push({
                    code: 'tool_missing',
                    severity: 'error',
                    title: `${label(node)}: unknown tool "${toolName}"`,
                    detail: 'This agent references a tool that is not in the library.',
                    nodeId: node.id,
                    nodeLabel: label(node),
                    component: 'tool',
                    suggestions: [...knownTools.values()].slice(0, 5).map((t) => t.name),
                });
            } else if ((tool.config as any)?.enabled === false) {
                push({
                    code: 'tool_disabled_but_referenced',
                    severity: 'error',
                    title: `${label(node)}: tool "${toolName}" is disabled`,
                    detail: 'A disabled tool is ignored at run time, so the agent cannot call it.',
                    nodeId: node.id,
                    nodeLabel: label(node),
                    component: 'tool',
                    fixHint: 'Enable the tool in the library, or remove it from this agent.',
                });
            }
        });
    });

    // Agent nodes not backed by a saved agent — previously only surfaced inside
    // a confirm() dialog when saving.
    getAgentBindings(nodes).forEach((binding) => {
        if (agents.length > 0 && !knownAgents.has(binding.agentId)) {
            push({
                code: 'agent_not_saved',
                severity: 'warning',
                title: `"${binding.label}" is not in the agent library`,
                detail: `No saved agent with id "${binding.agentId}". It will be created when you save.`,
                nodeId: binding.nodeId,
                nodeLabel: binding.label,
                component: 'agent',
            });
        }
    });

    // Selector agents with nothing to route to
    agentNodes.forEach((node) => {
        if (!node.data?.config?.is_selector) return;
        const outgoing = flowEdges.filter((e) => e.source === node.id).length;
        if (outgoing < 2) {
            push({
                code: 'selector_without_branches',
                severity: 'warning',
                title: `${label(node)}: selector has ${outgoing} branch${outgoing === 1 ? '' : 'es'}`,
                detail: 'A selector chooses between downstream agents, so it needs at least two.',
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'agent',
            });
        }
    });

    return findings;
}

/** DFS cycle detection over flow edges. */
function detectCycles(edges: VisualEdge[]): string[][] {
    const graph = new Map<string, string[]>();
    edges.forEach((edge) => {
        const from = String(edge.source);
        graph.set(from, [...(graph.get(from) ?? []), String(edge.target)]);
    });

    const cycles: string[][] = [];
    const visited = new Set<string>();
    const stack = new Set<string>();
    const path: string[] = [];

    const visit = (node: string): boolean => {
        visited.add(node);
        stack.add(node);
        path.push(node);
        for (const next of graph.get(node) ?? []) {
            if (!visited.has(next)) {
                if (visit(next)) return true;
            } else if (stack.has(next)) {
                cycles.push([...path.slice(path.indexOf(next)), next]);
                return true;
            }
        }
        path.pop();
        stack.delete(node);
        return false;
    };

    for (const node of graph.keys()) {
        if (!visited.has(node)) visit(node);
    }
    return cycles;
}

export function summarizeDiagnostics(diagnostics: Diagnostic[]) {
    const errors = diagnostics.filter((d) => d.severity === 'error').length;
    const warnings = diagnostics.filter((d) => d.severity === 'warning').length;
    return {
        errors,
        warnings,
        tone: errors > 0 ? ('error' as const) : warnings > 0 ? ('warning' as const) : ('ready' as const),
    };
}

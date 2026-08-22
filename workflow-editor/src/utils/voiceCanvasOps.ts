import type { LibraryItem } from '../api/backendTypes';
import type { VisualEdge, VisualNode } from '../types/workflow';
import { autoFixable, fixFor } from './diagnosticFixes';
import type { FixContext } from './diagnosticFixes';
import { diagnoseWorkflow } from './graphDiagnostics';

/**
 * Applies the canvas operations a spoken build conversation asks for.
 *
 * The model addresses everything by name — "the search agent", not a node id —
 * because that is what a person says out loud and therefore what the model
 * hears and repeats. Resolution is fuzzy on purpose: speech transcription drops
 * articles, changes case, and occasionally mishears a word, so an exact match
 * would fail on input a human would have understood.
 *
 * Every operation returns a short sentence describing what happened, and that
 * sentence goes back to the model as the tool result. It is the only thing the
 * model knows about the outcome, so a failure has to say what was wrong and
 * what would work instead — "no agent called X; there is Y and Z" beats "error".
 */

export interface OpsContext {
    nodes: VisualNode[];
    edges: VisualEdge[];
    tools: LibraryItem[];
    agents: LibraryItem[];
    providers: any[];
}

export interface OpsResult {
    nodes?: VisualNode[];
    edges?: VisualEdge[];
    /** Returned to the model, and shown in the transcript. */
    say: string;
    /** Set when the model asked for something that removes work. */
    destructive?: boolean;
}

const newId = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

const labelOf = (node: VisualNode) => String(node.data?.label ?? node.id);
const configOf = (node: VisualNode) => (node.data?.config ?? {}) as Record<string, any>;

const withConfig = (node: VisualNode, patch: Record<string, any>): VisualNode => ({
    ...node,
    data: { ...node.data, config: { ...configOf(node), ...patch } },
});

const normalise = (value: string) =>
    String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/**
 * Find a node by what someone called it.
 *
 * Tries exact, then prefix, then word overlap. "the search agent" should reach
 * a node labelled "SearchAssistant"; requiring an exact match would fail on
 * almost every spoken reference.
 */
const findNode = (nodes: VisualNode[], spoken: string): VisualNode | undefined => {
    const wanted = normalise(spoken);
    if (!wanted) return undefined;

    const exact = nodes.find((n) => normalise(labelOf(n)) === wanted);
    if (exact) return exact;

    const contains = nodes.find((n) => {
        const label = normalise(labelOf(n));
        return label.includes(wanted) || wanted.includes(label);
    });
    if (contains) return contains;

    // Word overlap, ignoring the filler a speaker adds: "the search one".
    const filler = new Set(['the', 'a', 'an', 'agent', 'node', 'one', 'that', 'my', 'our']);
    const words = wanted.split(' ').filter((w) => w && !filler.has(w));
    if (!words.length) return undefined;

    return nodes.find((n) => {
        const label = normalise(labelOf(n));
        return words.some((word) => word.length > 2 && label.includes(word));
    });
};

const listNames = (nodes: VisualNode[]) =>
    nodes.length ? nodes.map((n) => `"${labelOf(n)}"`).join(', ') : 'nothing yet';

/** Place a new node clear of what is already there. */
const nextSpot = (nodes: VisualNode[]) => {
    if (!nodes.length) return { x: 320, y: 220 };
    const maxX = Math.max(...nodes.map((n) => n.position?.x ?? 0));
    const avgY = nodes.reduce((sum, n) => sum + (n.position?.y ?? 0), 0) / nodes.length;
    return { x: maxX + 320, y: Math.round(avgY) };
};

// --------------------------------------------------------------------------- //
// Operations
// --------------------------------------------------------------------------- //

type Operation = (args: Record<string, any>, context: OpsContext) => OpsResult;

const addAgent: Operation = (args, { nodes }) => {
    const name = String(args.name ?? 'Agent').trim() || 'Agent';
    const node: VisualNode = {
        id: newId('agent'),
        type: 'agent',
        position: nextSpot(nodes),
        data: {
            label: name,
            config: {
                type: 'LlmAgent',
                name,
                role: String(args.role ?? ''),
                description: String(args.role ?? ''),
                instruction: String(args.instruction ?? ''),
                tools: [],
            },
        },
    } as VisualNode;

    return { nodes: [...nodes, node], say: `Added an agent called "${name}".` };
};

const addTrigger: Operation = (args, { nodes, edges }) => {
    const kind = ['manual', 'chat', 'webhook'].includes(String(args.kind))
        ? String(args.kind)
        : 'manual';
    const label = kind === 'chat' ? 'On Chat' : kind === 'webhook' ? 'Webhook' : 'Start';

    const node: VisualNode = {
        id: newId('trigger'),
        type: 'trigger',
        position: { x: (nodes.length ? Math.min(...nodes.map((n) => n.position?.x ?? 0)) : 320) - 300, y: 220 },
        data: { label, config: { trigger_type: kind, label } },
    } as VisualNode;

    // Wire it to whatever has nothing feeding it, so it lands in the flow.
    const fed = new Set(edges.map((e) => e.target));
    const entry = nodes.find((n) => n.type === 'agent' && !fed.has(n.id));

    return {
        nodes: [...nodes, node],
        edges: entry ? [...edges, { id: newId('edge'), source: node.id, target: entry.id } as VisualEdge] : edges,
        say: entry
            ? `Added a ${kind} trigger and connected it to "${labelOf(entry)}".`
            : `Added a ${kind} trigger.`,
    };
};

const addTool: Operation = (args, { nodes, tools }) => {
    const toolId = String(args.tool_id ?? '').trim();
    const known = tools.find((t) => t.id === toolId || normalise(t.name) === normalise(toolId));
    if (!known) {
        const near = tools.filter((t) => normalise(t.id).includes(normalise(toolId))).slice(0, 3);
        return {
            say: near.length
                ? `There is no tool called "${toolId}". Did you mean ${near.map((t) => t.id).join(', ')}?`
                : `There is no tool called "${toolId}". Call list_available_tools to see what exists.`,
        };
    }

    const agents = nodes.filter((n) => n.type === 'agent');
    if (!agents.length) return { say: 'There are no agents on the canvas to attach a tool to.' };

    // Default to the most recently added agent: in conversation "give it web
    // search" almost always means the one just created.
    const target = args.agent_name ? findNode(agents, String(args.agent_name)) : agents[agents.length - 1];
    if (!target) {
        return { say: `I could not find an agent called "${args.agent_name}". There is ${listNames(agents)}.` };
    }

    const current: string[] = configOf(target).tools ?? [];
    if (current.includes(known.id)) {
        return { say: `"${labelOf(target)}" already has ${known.id}.` };
    }

    return {
        nodes: nodes.map((n) => (n.id === target.id ? withConfig(n, { tools: [...current, known.id] }) : n)),
        say: `Attached ${known.id} to "${labelOf(target)}".`,
    };
};

const connect: Operation = (args, { nodes, edges }) => {
    const from = findNode(nodes, String(args.from_name ?? ''));
    const to = findNode(nodes, String(args.to_name ?? ''));
    if (!from) return { say: `I could not find "${args.from_name}". There is ${listNames(nodes)}.` };
    if (!to) return { say: `I could not find "${args.to_name}". There is ${listNames(nodes)}.` };
    if (from.id === to.id) return { say: 'Those are the same component, so there is nothing to connect.' };

    if (edges.some((e) => e.source === from.id && e.target === to.id)) {
        return { say: `"${labelOf(from)}" already feeds "${labelOf(to)}".` };
    }

    return {
        edges: [...edges, { id: newId('edge'), source: from.id, target: to.id } as VisualEdge],
        say: `Connected "${labelOf(from)}" to "${labelOf(to)}".`,
    };
};

const setInstruction: Operation = (args, { nodes }) => {
    const target = findNode(nodes.filter((n) => n.type === 'agent'), String(args.agent_name ?? ''));
    if (!target) {
        return { say: `I could not find an agent called "${args.agent_name}".` };
    }
    const instruction = String(args.instruction ?? '').trim();
    if (!instruction) return { say: 'I need the new instruction text to set it.' };

    return {
        nodes: nodes.map((n) => (n.id === target.id ? withConfig(n, { instruction }) : n)),
        say: `Updated the instructions for "${labelOf(target)}".`,
    };
};

const setModel: Operation = (args, { nodes }) => {
    const target = findNode(nodes.filter((n) => n.type === 'agent'), String(args.agent_name ?? ''));
    if (!target) return { say: `I could not find an agent called "${args.agent_name}".` };

    const config = configOf(target);
    const key = config.model_config ? 'model_config' : 'llm_config';
    const patch: Record<string, any> = { ...(config[key] ?? {}) };
    const changed: string[] = [];

    if (args.model) { patch.model = String(args.model); changed.push(`model ${args.model}`); }
    if (typeof args.temperature === 'number') {
        patch.temperature = args.temperature;
        changed.push(`temperature ${args.temperature}`);
    }
    if (!changed.length) return { say: 'Tell me which model or temperature to set.' };

    return {
        nodes: nodes.map((n) => (n.id === target.id ? withConfig(n, { [key]: patch }) : n)),
        say: `Set ${changed.join(' and ')} on "${labelOf(target)}".`,
    };
};

const removeNode: Operation = (args, { nodes, edges }) => {
    const target = findNode(nodes, String(args.name ?? ''));
    if (!target) return { say: `I could not find "${args.name}". There is ${listNames(nodes)}.` };

    return {
        nodes: nodes.filter((n) => n.id !== target.id),
        edges: edges.filter((e) => e.source !== target.id && e.target !== target.id),
        say: `Removed "${labelOf(target)}".`,
        destructive: true,
    };
};

const describeCanvas: Operation = (_args, context) => {
    const { nodes, edges } = context;
    if (!nodes.length) return { say: 'The canvas is empty.' };

    const lines = nodes.map((node) => {
        const config = configOf(node);
        const bits = [`${labelOf(node)} (${node.type})`];
        if (config.tools?.length) bits.push(`tools: ${config.tools.join(', ')}`);
        const model = config.model_config?.model ?? config.llm_config?.model;
        if (model) bits.push(`model: ${model}`);
        if (node.type === 'agent' && !config.instruction) bits.push('no instructions yet');
        return bits.join(' — ');
    });

    const wiring = edges.length
        ? edges
            .map((e) => {
                const from = nodes.find((n) => n.id === e.source);
                const to = nodes.find((n) => n.id === e.target);
                return from && to ? `${labelOf(from)} -> ${labelOf(to)}` : null;
            })
            .filter(Boolean)
            .join('; ')
        : 'nothing is connected yet';

    const problems = diagnoseWorkflow({
        nodes,
        edges,
        agents: context.agents,
        tools: context.tools,
        providers: context.providers,
    }).filter((d) => d.severity === 'error');

    return {
        say: [
            `${nodes.length} component(s): ${lines.join(' | ')}.`,
            `Wiring: ${wiring}.`,
            problems.length ? `Problems: ${problems.map((d) => d.title).join('; ')}.` : 'No blocking problems.',
        ].join(' '),
    };
};

const listTools: Operation = (args, { tools }) => {
    const category = args.category ? normalise(String(args.category)) : '';
    const matching = category
        ? tools.filter((t) => normalise(String(t.category ?? '')) === category)
        : tools;

    if (!matching.length) {
        return { say: category ? `No tools in the ${args.category} category.` : 'No tools are registered.' };
    }

    // Enough to choose from, not so much that it reads the whole catalogue aloud.
    const listed = matching.slice(0, 18).map((t) => `${t.id} (${t.description ?? ''})`.slice(0, 90));
    return {
        say: `${matching.length} tool(s): ${listed.join('; ')}${matching.length > 18 ? '; and more' : ''}.`,
    };
};

const fixProblems: Operation = (_args, context) => {
    const fixContext: FixContext = {
        nodes: context.nodes,
        edges: context.edges,
        agents: context.agents,
        tools: context.tools,
        providers: context.providers,
    };
    const diagnostics = diagnoseWorkflow(fixContext);
    const repairable = autoFixable(diagnostics, fixContext);
    if (!repairable.length) return { say: 'Nothing needs fixing that I can fix on my own.' };

    // Re-derive between repairs: each changes the graph the next reasons about.
    let nodes = context.nodes;
    let edges = context.edges;
    const done: string[] = [];

    for (const diagnostic of repairable) {
        const fix = fixFor(diagnostic);
        if (!fix) continue;
        const result = fix.apply(diagnostic, { ...fixContext, nodes, edges });
        if (!result) continue;
        if (result.nodes) nodes = result.nodes;
        if (result.edges) edges = result.edges;
        done.push(result.summary);
    }

    if (!done.length) return { say: 'Nothing needs fixing that I can fix on my own.' };
    return { nodes, edges, say: done.join(' ') };
};

const OPERATIONS: Record<string, Operation> = {
    add_agent: addAgent,
    add_trigger: addTrigger,
    add_tool: addTool,
    connect,
    set_instruction: setInstruction,
    set_model: setModel,
    remove_node: removeNode,
    describe_canvas: describeCanvas,
    list_available_tools: listTools,
    fix_problems: fixProblems,
};

/** Names the model may call. Kept in step with src/api/voice/canvas_tools.py. */
export const VOICE_OPERATIONS = Object.keys(OPERATIONS);

export const applyVoiceOperation = (
    name: string,
    args: Record<string, any>,
    context: OpsContext,
): OpsResult => {
    const operation = OPERATIONS[name];
    if (!operation) {
        return { say: `I do not know how to do "${name}".` };
    }
    try {
        return operation(args ?? {}, context);
    } catch (error) {
        // The model only learns what happened from this sentence, so an
        // exception has to become one rather than vanishing.
        return { say: `That failed: ${error instanceof Error ? error.message : 'unknown error'}.` };
    }
};

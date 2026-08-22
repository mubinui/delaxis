import type { Diagnostic } from './graphDiagnostics';
import type { LibraryItem } from '../api/backendTypes';
import type { VisualEdge, VisualNode } from '../types/workflow';

/**
 * Repairs for the problems the diagnostics find.
 *
 * The Help panel could already explain a finding. Explaining a dangling tool
 * reference is not much use when the fix is "remove this string from this
 * array" — so each repair below performs that edit directly.
 *
 * Only deterministic repairs live here. Anything needing the user's intent
 * (which collection should a knowledge node read? which two agents should a
 * router branch to?) has no entry, because guessing would produce a workflow
 * that validates and does the wrong thing. Those keep the explanation path.
 */

export interface FixContext {
    nodes: VisualNode[];
    edges: VisualEdge[];
    agents: LibraryItem[];
    tools: LibraryItem[];
    providers: any[];
}

export interface FixResult {
    nodes?: VisualNode[];
    edges?: VisualEdge[];
    /** Past tense, specific — shown after the fix is applied. */
    summary: string;
}

export interface Fix {
    /** Imperative, on a button: "Add a trigger". */
    label: string;
    /**
     * Set when the repair removes something the user made, rather than
     * correcting something the graph got wrong.
     *
     * These are excluded from "Fix all". Deleting every disconnected node is a
     * defensible answer to one finding and a catastrophe applied to ten: the
     * first version of this wiped both agents off a two-agent canvas and left a
     * lone trigger, which is not what anyone means by "fix".
     */
    destructive?: boolean;
    /** What it will do, shown before the user commits. */
    describe: (diagnostic: Diagnostic, context: FixContext) => string;
    apply: (diagnostic: Diagnostic, context: FixContext) => FixResult | null;
}

const newId = (prefix: string) =>
    `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

const nodeLabel = (node: VisualNode | undefined) =>
    String(node?.data?.label ?? node?.id ?? 'the node');

/** Somewhere clear of what is already placed. */
const freeSpot = (nodes: VisualNode[], dx = 0) => {
    if (!nodes.length) return { x: 260, y: 200 };
    const minX = Math.min(...nodes.map((n) => n.position?.x ?? 0));
    const midY = nodes.reduce((sum, n) => sum + (n.position?.y ?? 0), 0) / nodes.length;
    return { x: minX - 260 + dx, y: Math.round(midY) };
};

const configOf = (node: VisualNode) => (node.data?.config ?? {}) as Record<string, any>;

const withConfig = (node: VisualNode, patch: Record<string, any>): VisualNode => ({
    ...node,
    data: { ...node.data, config: { ...configOf(node), ...patch } },
});

/** Tool ids an agent can actually resolve right now. */
const usableToolIds = (tools: LibraryItem[]) =>
    new Set(tools.filter((t) => t.config?.enabled !== false).map((t) => t.id));

const firstWorkingProvider = (providers: any[]) =>
    providers.find((p) => p?.enabled !== false && (p?.has_key || p?.api_key_set || p?.key_present))
    ?? providers.find((p) => p?.enabled !== false);

// --------------------------------------------------------------------------- //
// The repairs
// --------------------------------------------------------------------------- //

const addTrigger: Fix = {
    label: 'Add a trigger',
    describe: (_d, { nodes }) => {
        const entry = nodes.find((n) => n.type === 'agent');
        return entry
            ? `Adds a Manual trigger and connects it to ${nodeLabel(entry)}.`
            : 'Adds a Manual trigger to the canvas.';
    },
    apply: (_d, { nodes, edges }) => {
        const trigger: VisualNode = {
            id: newId('trigger'),
            type: 'trigger',
            position: freeSpot(nodes),
            data: {
                label: 'Start',
                config: { trigger_type: 'manual', label: 'Start' },
            },
        } as VisualNode;

        // Wire it to whatever currently has nothing feeding it, so the trigger
        // lands in the flow rather than beside it.
        const fed = new Set(edges.map((e) => e.target));
        const entry = nodes.find((n) => n.type === 'agent' && !fed.has(n.id))
            ?? nodes.find((n) => n.type === 'agent');

        return {
            nodes: [...nodes, trigger],
            edges: entry
                ? [...edges, { id: newId('edge'), source: trigger.id, target: entry.id } as VisualEdge]
                : edges,
            summary: entry
                ? `Added a Manual trigger and connected it to ${nodeLabel(entry)}.`
                : 'Added a Manual trigger.',
        };
    },
};

const dropDanglingTools: Fix = {
    label: 'Remove the reference',
    describe: (diagnostic, { nodes, tools }) => {
        const node = nodes.find((n) => n.id === diagnostic.nodeId);
        if (!node) return 'Removes the unresolvable tool reference.';
        const usable = usableToolIds(tools);
        const dangling = (configOf(node).tools ?? []).filter((id: string) => !usable.has(id));
        return dangling.length
            ? `Removes ${dangling.map((t: string) => `"${t}"`).join(', ')} from ${nodeLabel(node)}.`
            : 'Removes the unresolvable tool reference.';
    },
    apply: (diagnostic, { nodes, tools }) => {
        const usable = usableToolIds(tools);
        let removed: string[] = [];

        const next = nodes.map((node) => {
            if (diagnostic.nodeId && node.id !== diagnostic.nodeId) return node;
            const current: string[] = configOf(node).tools ?? [];
            const kept = current.filter((id) => usable.has(id));
            if (kept.length === current.length) return node;
            removed = removed.concat(current.filter((id) => !usable.has(id)));
            return withConfig(node, { tools: kept });
        });

        if (!removed.length) return null;
        return {
            nodes: next,
            summary: `Removed ${removed.length} unresolvable tool reference${removed.length > 1 ? 's' : ''}: ${removed.map((t) => `"${t}"`).join(', ')}.`,
        };
    },
};

const deleteOrphan: Fix = {
    label: 'Delete the node',
    destructive: true,
    describe: (diagnostic, { nodes }) =>
        `Deletes ${nodeLabel(nodes.find((n) => n.id === diagnostic.nodeId))}, which nothing connects to.`,
    apply: (diagnostic, { nodes, edges }) => {
        if (!diagnostic.nodeId) return null;
        const target = nodes.find((n) => n.id === diagnostic.nodeId);
        if (!target) return null;
        return {
            nodes: nodes.filter((n) => n.id !== diagnostic.nodeId),
            edges: edges.filter((e) => e.source !== diagnostic.nodeId && e.target !== diagnostic.nodeId),
            summary: `Deleted ${nodeLabel(target)}.`,
        };
    },
};

const removeBadEdges: Fix = {
    label: 'Remove the connection',
    describe: () => 'Removes the connection that is not allowed between these handles.',
    apply: (diagnostic, { nodes, edges }) => {
        if (!diagnostic.nodeId) return null;
        // An invalid attachment is about how this node is wired in, so drop the
        // inbound edges that landed on the wrong handle.
        const offending = edges.filter((e) => e.target === diagnostic.nodeId);
        if (!offending.length) return null;
        return {
            edges: edges.filter((e) => !offending.includes(e)),
            summary: `Removed ${offending.length} invalid connection${offending.length > 1 ? 's' : ''} into ${nodeLabel(nodes.find((n) => n.id === diagnostic.nodeId))}.`,
        };
    },
};

const breakCycle: Fix = {
    label: 'Break the loop',
    describe: () => 'Removes one connection so the graph stops looping back on itself.',
    apply: (_d, { nodes, edges }) => {
        // Walk the graph and drop the first edge that closes a cycle. Removing
        // exactly one keeps the rest of the user's wiring intact.
        const outgoing = new Map<string, VisualEdge[]>();
        for (const edge of edges) {
            outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge]);
        }

        const state = new Map<string, 'open' | 'done'>();
        let culprit: VisualEdge | null = null;

        const visit = (id: string): void => {
            if (culprit || state.get(id) === 'done') return;
            state.set(id, 'open');
            for (const edge of outgoing.get(id) ?? []) {
                if (culprit) return;
                if (state.get(edge.target) === 'open') {
                    culprit = edge;
                    return;
                }
                if (state.get(edge.target) !== 'done') visit(edge.target);
            }
            state.set(id, 'done');
        };

        for (const node of nodes) visit(node.id);
        if (!culprit) return null;

        const edge = culprit as VisualEdge;
        const from = nodeLabel(nodes.find((n) => n.id === edge.source));
        const to = nodeLabel(nodes.find((n) => n.id === edge.target));
        return {
            edges: edges.filter((e) => e !== edge),
            summary: `Removed the connection from ${from} to ${to}, which closed the loop.`,
        };
    },
};

const useWorkingProvider: Fix = {
    label: 'Use a configured provider',
    describe: (_d, { providers }) => {
        const provider = firstWorkingProvider(providers);
        return provider
            ? `Switches the node to ${provider.name ?? provider.id}${provider.models?.[0] ? ` and its ${typeof provider.models[0] === 'string' ? provider.models[0] : provider.models[0]?.name ?? 'first model'}` : ''}.`
            : 'No configured provider is available to switch to.';
    },
    apply: (diagnostic, { nodes, providers }) => {
        const provider = firstWorkingProvider(providers);
        if (!provider || !diagnostic.nodeId) return null;

        const model = provider.models?.[0];
        const modelId = typeof model === 'string' ? model : (model?.id ?? model?.name ?? '');

        const next = nodes.map((node) => {
            if (node.id !== diagnostic.nodeId) return node;
            const config = configOf(node);
            const key = config.model_config ? 'model_config' : 'llm_config';
            return withConfig(node, {
                [key]: { ...(config[key] ?? {}), provider_id: provider.id, ...(modelId ? { model: modelId } : {}) },
            });
        });

        return {
            nodes: next,
            summary: `Switched to ${provider.name ?? provider.id}${modelId ? ` / ${modelId}` : ''}.`,
        };
    },
};

// --------------------------------------------------------------------------- //
// Registry
// --------------------------------------------------------------------------- //

const FIXES: Record<string, Fix> = {
    no_trigger: addTrigger,
    tool_missing: dropDanglingTools,
    tool_not_registered: dropDanglingTools,
    tool_disabled_but_referenced: dropDanglingTools,
    orphan_node: deleteOrphan,
    invalid_attachment: removeBadEdges,
    cycle_detected: breakCycle,
    provider_missing: useWorkingProvider,
    provider_key_missing: useWorkingProvider,
    model_unknown_for_provider: useWorkingProvider,
    // Per-node config findings are coded from their message text; a node with
    // no model can be pointed at a configured provider. A node with no
    // instructions cannot — writing an agent's purpose is not a repair.
    config_missing_model: useWorkingProvider,
};

/** The repair for a finding, or null when it needs a human decision. */
export const fixFor = (diagnostic: Diagnostic): Fix | null => FIXES[diagnostic.code] ?? null;

/** Whether a repair exists and can currently do something. */
export const canFix = (diagnostic: Diagnostic, context: FixContext): boolean => {
    const fix = fixFor(diagnostic);
    if (!fix) return false;
    try {
        return fix.apply(diagnostic, context) !== null;
    } catch {
        return false;
    }
};

/**
 * Findings safe to repair in bulk: everything with a working repair that does
 * not remove the user's own nodes. Destructive repairs stay one-at-a-time and
 * explicitly chosen.
 */
export const autoFixable = (diagnostics: Diagnostic[], context: FixContext): Diagnostic[] =>
    diagnostics.filter((d) => {
        const fix = fixFor(d);
        return Boolean(fix) && !fix!.destructive && canFix(d, context);
    });

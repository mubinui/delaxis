import { describe, expect, it } from 'vitest';
import type { ApiProvider, LibraryItem } from '../api/backendTypes';
import type { VisualEdge, VisualNode } from '../types/workflow';
import { diagnoseWorkflow, summarizeDiagnostics } from './graphDiagnostics';

const agent = (id: string, label: string, config: Record<string, any> = {}): VisualNode => ({
    id,
    type: 'agent',
    position: { x: 0, y: 0 },
    data: {
        label,
        config: {
            name: label,
            type: 'LlmAgent',
            instruction: 'do the thing',
            model_config: { provider_id: 'gemini', model: 'gemini-3.5-flash' },
            ...config,
        },
    },
});

const trigger = (id = 't1'): VisualNode => ({
    id,
    type: 'trigger',
    position: { x: 0, y: 0 },
    data: { label: 'Start', config: { trigger_type: 'manual' } },
});

const node = (id: string, type: VisualNode['type'], config: Record<string, any> = {}): VisualNode => ({
    id,
    type,
    position: { x: 0, y: 0 },
    data: { label: id, config },
});

const flowEdge = (source: string, target: string): VisualEdge => ({
    id: `${source}-${target}`,
    source,
    target,
});

const auxEdge = (source: string, target: string, handle: string): VisualEdge => ({
    id: `${source}-${target}-${handle}`,
    source,
    target,
    sourceHandle: 'attach',
    targetHandle: handle,
});

const provider = (over: Partial<ApiProvider> = {}): ApiProvider => ({
    id: 'gemini',
    name: 'Google Gemini',
    type: 'llm',
    description: '',
    api_key_masked: '****abcd',
    api_key_env: 'GEMINI_API_KEY',
    enabled: true,
    config: {},
    models: [{ name: 'gemini-3.5-flash' }],
    ...over,
});

/** A canvas with nothing wrong, so each test isolates one fault. */
const healthy = () => ({
    nodes: [trigger(), agent('a1', 'Researcher')],
    edges: [flowEdge('t1', 'a1')],
    providers: [provider()],
    agents: [] as LibraryItem[],
    tools: [] as LibraryItem[],
});

const codes = (input: Parameters<typeof diagnoseWorkflow>[0]) =>
    diagnoseWorkflow(input).map((d) => d.code);

describe('diagnoseWorkflow', () => {
    it('reports nothing for a well-formed graph', () => {
        expect(diagnoseWorkflow(healthy())).toEqual([]);
    });

    it('treats an empty canvas as guidance, not an error', () => {
        const found = diagnoseWorkflow({ nodes: [], edges: [] });
        expect(found).toHaveLength(1);
        expect(found[0].code).toBe('workflow_empty');
        expect(found[0].severity).toBe('info');
    });

    it('flags a graph with no agent', () => {
        expect(codes({ nodes: [trigger()], edges: [] })).toContain('no_agent');
    });

    it('warns when there is no trigger', () => {
        expect(codes({ nodes: [agent('a1', 'A')], edges: [], providers: [provider()] })).toContain('no_trigger');
    });

    it('flags nodes connected to nothing', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [...healthy().nodes, agent('a2', 'Stranded')],
        });
        const orphan = found.find((d) => d.code === 'orphan_node');
        expect(orphan?.nodeId).toBe('a2');
    });

    it('does not call an attached tool an orphan', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [...healthy().nodes, node('m1', 'tool', { type: 'memory' })],
            edges: [...healthy().edges, auxEdge('m1', 'a1', 'memory')],
        });
        expect(found.map((d) => d.code)).not.toContain('orphan_node');
    });

    it('detects a cycle', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [trigger(), agent('a1', 'A'), agent('a2', 'B')],
            edges: [flowEdge('t1', 'a1'), flowEdge('a1', 'a2'), flowEdge('a2', 'a1')],
        });
        expect(found.map((d) => d.code)).toContain('cycle_detected');
    });

    it('flags a memory tool attached to the tools handle', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [...healthy().nodes, node('m1', 'tool', { type: 'memory' })],
            edges: [...healthy().edges, auxEdge('m1', 'a1', 'tools')],
        });
        expect(found.map((d) => d.code)).toContain('invalid_attachment');
    });

    it('warns that router and output nodes are not persisted', () => {
        // buildWorkflowPayload keeps only agent nodes, so these vanish on save
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [...healthy().nodes, node('r1', 'router', { type: 'router' })],
            edges: [...healthy().edges, flowEdge('a1', 'r1')],
        });
        const dropped = found.find((d) => d.code === 'nodes_dropped_on_save');
        expect(dropped?.severity).toBe('warning');
        expect(dropped?.detail).toContain('r1');
    });

    describe('provider configuration', () => {
        it('flags an unknown provider and suggests configured ones', () => {
            const base = healthy();
            const found = diagnoseWorkflow({
                ...base,
                nodes: [trigger(), agent('a1', 'A', { model_config: { provider_id: 'ghost', model: 'm' } })],
            });
            const finding = found.find((d) => d.code === 'provider_missing');
            expect(finding?.severity).toBe('error');
            expect(finding?.suggestions).toContain('gemini');
        });

        it('flags a provider with no resolvable key', () => {
            const found = diagnoseWorkflow({
                ...healthy(),
                providers: [provider({ api_key_masked: null })],
            });
            const finding = found.find((d) => d.code === 'provider_key_missing');
            expect(finding?.detail).toContain('GEMINI_API_KEY');
        });

        it('treats an unrecognised model as a warning, since free text is valid', () => {
            const found = diagnoseWorkflow({
                ...healthy(),
                nodes: [trigger(), agent('a1', 'A', { model_config: { provider_id: 'gemini', model: 'brand-new' } })],
            });
            const finding = found.find((d) => d.code === 'model_unknown_for_provider');
            expect(finding?.severity).toBe('warning');
            expect(finding?.suggestions).toContain('gemini-3.5-flash');
        });

        it('says nothing when no provider is chosen, since the server has a default', () => {
            const found = diagnoseWorkflow({
                ...healthy(),
                nodes: [trigger(), agent('a1', 'A', { model_config: {} })],
            });
            expect(found.map((d) => d.code)).not.toContain('provider_missing');
        });
    });

    describe('tools', () => {
        it('flags a referenced tool that does not exist', () => {
            const found = diagnoseWorkflow({
                ...healthy(),
                nodes: [trigger(), agent('a1', 'A', { tools: ['ghost_tool'] })],
                tools: [{ id: 'real', name: 'real', config: {} }] as LibraryItem[],
            });
            expect(found.map((d) => d.code)).toContain('tool_missing');
        });

        it('flags a disabled tool that is still referenced', () => {
            const found = diagnoseWorkflow({
                ...healthy(),
                nodes: [trigger(), agent('a1', 'A', { tools: ['search'] })],
                tools: [{ id: 'search', name: 'search', config: { enabled: false } }] as LibraryItem[],
            });
            const finding = found.find((d) => d.code === 'tool_disabled_but_referenced');
            expect(finding?.severity).toBe('error');
        });
    });

    it('flags an agent node with no saved agent behind it', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            agents: [{ id: 'someone_else', name: 'Someone', config: {} }] as LibraryItem[],
        });
        expect(found.map((d) => d.code)).toContain('agent_not_saved');
    });

    it('warns when a selector has fewer than two branches', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [trigger(), agent('a1', 'Router', { is_selector: true })],
        });
        expect(found.map((d) => d.code)).toContain('selector_without_branches');
    });

    it('surfaces missing instructions from the shared node summary', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [trigger(), agent('a1', 'A', { instruction: '', system_message: '' })],
        });
        expect(found.some((d) => d.title.includes('missing instructions'))).toBe(true);
    });

    it('gives every finding a stable id', () => {
        const found = diagnoseWorkflow({
            ...healthy(),
            nodes: [...healthy().nodes, agent('a2', 'Stranded')],
        });
        expect(new Set(found.map((d) => d.id)).size).toBe(found.length);
    });
});

describe('summarizeDiagnostics', () => {
    it('reports ready when there is nothing to fix', () => {
        expect(summarizeDiagnostics([])).toEqual({ errors: 0, warnings: 0, tone: 'ready' });
    });

    it('lets an error outrank a warning', () => {
        const summary = summarizeDiagnostics(
            diagnoseWorkflow({
                nodes: [agent('a1', 'A', { model_config: { provider_id: 'ghost', model: 'm' } })],
                edges: [],
                providers: [provider()],
            }),
        );
        expect(summary.errors).toBeGreaterThan(0);
        expect(summary.tone).toBe('error');
    });
});

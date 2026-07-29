import { describe, expect, it } from 'vitest';
import { workflowToCanvas } from './workflowToCanvas';

const agents = [
    {
        id: 'researcher',
        name: 'Researcher',
        description: 'Finds things',
        config: {
            name: 'Researcher',
            instruction: 'Search the web',
            model_config: { provider_id: 'openrouter', model: 'gpt-4o' },
            tools: ['web_search'],
        },
    },
    { id: 'writer', name: 'Writer', config: { name: 'Writer', instruction: 'Write it up' } },
];

const tools = [{ id: 'web_search', name: 'search_web', config: { type: 'function' } }];

describe('workflowToCanvas', () => {
    it('restores a canvas the Studio saved, verbatim', () => {
        const saved = {
            id: 'wf',
            metadata: {
                visual_canvas: {
                    nodes: [{ id: 'a', type: 'agent', position: { x: 1, y: 2 }, data: { label: 'A', config: {} } }],
                    edges: [{ id: 'e', source: 'a', target: 'b' }],
                },
            },
        };
        const result = workflowToCanvas({ config: saved });
        expect(result.generated).toBe(false);
        expect(result.nodes).toHaveLength(1);
        expect(result.edges).toHaveLength(1);
    });

    it('lays out a generated workflow that has only a topology', () => {
        const config = {
            id: 'research_brief',
            topology: {
                type: 'sequential',
                entry_node: 'researcher',
                nodes: [
                    { id: 'researcher', agent_id: 'researcher', description: 'Gathers' },
                    { id: 'writer', agent_id: 'writer', description: 'Writes' },
                ],
                edges: [{ from_node: 'researcher', to_node: 'writer' }],
            },
        };
        const { nodes, edges, generated } = workflowToCanvas({ config, agents, tools });

        expect(generated).toBe(true);
        // A trigger plus both agents, so the graph reads as runnable
        expect(nodes.map((n) => n.id)).toEqual(['trigger-chat', 'researcher', 'writer']);
        expect(edges.some((e) => e.source === 'researcher' && e.target === 'writer')).toBe(true);
        expect(edges.some((e) => e.source === 'trigger-chat' && e.target === 'researcher')).toBe(true);
    });

    it('fills agent nodes from the agent library so they are editable', () => {
        const config = {
            id: 'wf',
            topology: { entry_node: 'researcher', nodes: [{ id: 'researcher', agent_id: 'researcher' }], edges: [] },
        };
        const { nodes } = workflowToCanvas({ config, agents, tools });
        const node = nodes.find((n) => n.id === 'researcher')!;
        expect(node.data.label).toBe('Researcher');
        expect(node.data.config!.instruction).toBe('Search the web');
        expect(node.data.config!.model_config).toEqual({ provider_id: 'openrouter', model: 'gpt-4o' });
    });

    it('places attached tools, memory and knowledge as their own nodes', () => {
        const config = {
            id: 'wf',
            knowledge: { collections: ['handbook'], top_k: 8 },
            topology: {
                entry_node: 'researcher',
                nodes: [{ id: 'researcher', agent_id: 'researcher', tools: ['web_search'], memory: true, knowledge: true }],
                edges: [],
            },
        };
        const { nodes, edges } = workflowToCanvas({ config, agents, tools });

        const toolNode = nodes.find((n) => n.id === 'researcher--tool--web_search')!;
        expect(toolNode.data.label).toBe('search_web');
        expect(edges.some((e) => e.source === toolNode.id && e.targetHandle === 'tools')).toBe(true);

        expect(edges.some((e) => e.source === 'researcher--memory' && e.targetHandle === 'memory')).toBe(true);

        const knowledgeNode = nodes.find((n) => n.id === 'researcher--knowledge')!;
        expect(knowledgeNode.data.config!.collections).toEqual(['handbook']);
        expect(knowledgeNode.data.config!.top_k).toBe(8);
    });

    it('adds a Guardrail node when the workflow enables guardrails', () => {
        const config = {
            id: 'wf',
            guardrails: { enabled: true, output_schema: 'json', human_review: true },
            topology: { entry_node: 'writer', nodes: [{ id: 'writer', agent_id: 'writer' }], edges: [] },
        };
        const { nodes, edges } = workflowToCanvas({ config, agents });
        const guardrail = nodes.find((n) => n.id === 'guardrail-final')!;
        expect(guardrail.type).toBe('router');
        expect(guardrail.data.config!.output_schema).toBe('json');
        expect(guardrail.data.config!.human_review).toBe(true);
        expect(edges.some((e) => e.source === 'writer' && e.target === 'guardrail-final')).toBe(true);
    });

    it('fans a selector out to its specialists when there are no edges', () => {
        const config = {
            id: 'wf',
            topology: {
                entry_node: 'triage',
                domain_agents: [{ id: 'researcher' }, { id: 'writer' }],
                nodes: [
                    { id: 'triage', agent_id: 'researcher' },
                    { id: 'researcher', agent_id: 'researcher' },
                    { id: 'writer', agent_id: 'writer' },
                ],
                edges: [],
            },
        };
        const { nodes, edges } = workflowToCanvas({ config, agents });
        expect(edges.some((e) => e.source === 'triage' && e.target === 'researcher')).toBe(true);
        expect(edges.some((e) => e.source === 'triage' && e.target === 'writer')).toBe(true);
        expect(nodes.find((n) => n.id === 'triage')!.data.config!.is_selector).toBe(true);
    });

    it('stacks nodes into columns by depth instead of one flat row', () => {
        const config = {
            id: 'wf',
            topology: {
                entry_node: 'a',
                nodes: [
                    { id: 'a', agent_id: 'researcher' },
                    { id: 'b', agent_id: 'writer' },
                    { id: 'c', agent_id: 'writer' },
                ],
                edges: [{ from_node: 'a', to_node: 'b' }, { from_node: 'a', to_node: 'c' }],
            },
        };
        const { nodes } = workflowToCanvas({ config, agents });
        const byId = new Map(nodes.map((n) => [n.id, n.position]));
        // b and c are downstream of a, so they share a column further right
        expect(byId.get('b')!.x).toBeGreaterThan(byId.get('a')!.x);
        expect(byId.get('c')!.x).toBe(byId.get('b')!.x);
        expect(byId.get('c')!.y).not.toBe(byId.get('b')!.y);
    });

    it('survives a workflow with no topology at all', () => {
        const { nodes, edges } = workflowToCanvas({ config: { id: 'empty' } });
        expect(nodes.map((n) => n.id)).toEqual(['trigger-chat']);
        expect(edges).toEqual([]);
    });
});

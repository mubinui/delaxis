import { describe, expect, it } from 'vitest';
import type { VisualEdge, VisualNode } from '../types/workflow';
import { buildWorkflowPayload, compileFlowLinks, getAgentBindings } from './workflowPayload';

const router = (id: string, label = 'Flow Router'): VisualNode => ({
    id,
    type: 'router',
    position: { x: 0, y: 0 },
    data: { label, config: { type: 'router', routing_mode: 'conditional' } },
});

const guardrail = (id: string, config: Record<string, any> = {}): VisualNode => ({
    id,
    type: 'router',
    position: { x: 0, y: 0 },
    data: { label: 'Guardrail', config: { type: 'guardrail', guardrails_enabled: true, ...config } },
});

const trigger = (id: string): VisualNode => ({
    id,
    type: 'trigger',
    position: { x: 0, y: 0 },
    data: { label: 'Start', config: { trigger_type: 'manual' } },
});

const agent = (id: string, label: string): VisualNode => ({
    id,
    type: 'agent',
    position: { x: 0, y: 0 },
    data: { label, config: { name: label, type: 'LlmAgent' } },
});

const tool = (id: string, label: string, toolType: string): VisualNode => ({
    id,
    type: 'tool',
    position: { x: 0, y: 100 },
    data: { label, config: { id, type: toolType } },
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

describe('getAgentBindings', () => {
    it('resolves the backend agent id per agent node and ignores non-agents', () => {
        const nodes: VisualNode[] = [
            agent('n1', 'Search Assistant'),
            tool('t1', 'MCP Tool', 'mcp'),
            {
                id: 'blank',
                type: 'agent',
                position: { x: 0, y: 0 },
                // Blank palette agent: no id/name → resolves from the label.
                data: { label: 'CrewAI Agent', config: { type: 'LlmAgent' } },
            },
        ];
        const bindings = getAgentBindings(nodes);
        expect(bindings).toEqual([
            { nodeId: 'n1', label: 'Search Assistant', agentId: 'search_assistant' },
            { nodeId: 'blank', label: 'CrewAI Agent', agentId: 'crewai_agent' },
        ]);
    });

    it('prefers config.id over name/label', () => {
        const node: VisualNode = {
            id: 'x',
            type: 'agent',
            position: { x: 0, y: 0 },
            data: { label: 'Some Label', config: { id: 'general_assistant', name: 'Other' } },
        };
        expect(getAgentBindings([node])[0].agentId).toBe('general_assistant');
    });
});

describe('buildWorkflowPayload aux attachments', () => {
    const nodes = [
        agent('agent_a', 'Agent A'),
        agent('agent_b', 'Agent B'),
        tool('mcp_tool', 'MCP Tool', 'mcp'),
        tool('memory_store', 'Memory Store', 'memory'),
        tool('knowledge_src', 'Knowledge Source', 'knowledge'),
    ];
    const edges = [
        flowEdge('agent_a', 'agent_b'),
        auxEdge('mcp_tool', 'agent_a', 'tools'),
        auxEdge('memory_store', 'agent_a', 'memory'),
        auxEdge('knowledge_src', 'agent_b', 'knowledge'),
    ];
    const { create } = buildWorkflowPayload({ id: 'wf', name: 'WF', nodes, edges });

    it('attaches tool ids to the agent topology node', () => {
        const nodeA = create.topology.nodes.find((n) => n.id === 'agent_a')!;
        expect(nodeA.tools).toEqual(['mcp_tool']);
        expect(nodeA.memory).toBe(true);
        expect(nodeA.knowledge).toBeUndefined();
    });

    it('attaches knowledge to the right agent only', () => {
        const nodeB = create.topology.nodes.find((n) => n.id === 'agent_b')!;
        expect(nodeB.knowledge).toBe(true);
        expect(nodeB.memory).toBeUndefined();
        expect(nodeB.tools).toEqual([]);
    });

    it('keeps aux edges out of flow connections and topology edges', () => {
        expect(create.connections).toEqual([
            { from_node: 'agent_a', to_node: 'agent_b', type: 'sequential' },
        ]);
        expect(create.topology.edges).toHaveLength(1);
    });

    it('enables workflow-level memory/knowledge from attachments', () => {
        expect(create.memory.enabled).toBe(true);
        expect(create.knowledge.enabled).toBe(true);
    });

    it('preserves the full visual graph including aux edges', () => {
        expect(create.metadata.visual_canvas.edges).toHaveLength(4);
    });
});

describe('buildWorkflowPayload without attachments', () => {
    it('disables memory when no memory node exists (fixed always-on bug)', () => {
        const { create } = buildWorkflowPayload({
            id: 'wf2',
            name: 'WF2',
            nodes: [agent('agent_a', 'Agent A')],
            edges: [],
        });
        expect(create.memory.enabled).toBe(false);
        expect(create.knowledge.enabled).toBe(false);
        const nodeA = create.topology.nodes[0];
        expect(nodeA.tools).toEqual([]);
        expect(nodeA.memory).toBeUndefined();
    });

    it('legacy presence scan still enables memory for in-flow memory nodes', () => {
        const { create } = buildWorkflowPayload({
            id: 'wf3',
            name: 'WF3',
            nodes: [agent('agent_a', 'Agent A'), tool('memory_store', 'Memory Store', 'memory')],
            edges: [flowEdge('agent_a', 'memory_store')],
        });
        expect(create.memory.enabled).toBe(true);
        // but no per-node attachment without an aux handle edge
        expect(create.topology.nodes[0].memory).toBeUndefined();
    });
});

describe('compileFlowLinks', () => {
    it('contracts a Flow Router so the connection survives the save', () => {
        const nodes = [agent('a', 'A'), router('r1'), agent('b', 'B'), agent('c', 'C')];
        const edges = [flowEdge('a', 'r1'), flowEdge('r1', 'b'), flowEdge('r1', 'c')];
        expect(compileFlowLinks(nodes, edges)).toEqual([
            { from: 'a', to: 'b', viaRouter: true },
            { from: 'a', to: 'c', viaRouter: true },
        ]);
    });

    it('contracts chained pass-through nodes', () => {
        const nodes = [agent('a', 'A'), router('r1'), guardrail('g1'), agent('b', 'B')];
        const edges = [flowEdge('a', 'r1'), flowEdge('r1', 'g1'), flowEdge('g1', 'b')];
        expect(compileFlowLinks(nodes, edges)).toEqual([{ from: 'a', to: 'b', viaRouter: true }]);
    });

    it('does not mark a guardrail-only hop as a router branch', () => {
        const nodes = [agent('a', 'A'), guardrail('g1'), agent('b', 'B')];
        const edges = [flowEdge('a', 'g1'), flowEdge('g1', 'b')];
        expect(compileFlowLinks(nodes, edges)).toEqual([{ from: 'a', to: 'b', viaRouter: false }]);
    });

    it('ignores attachment edges', () => {
        const nodes = [agent('a', 'A'), tool('t1', 'Tool', 'mcp')];
        const edges = [auxEdge('t1', 'a', 'tools')];
        expect(compileFlowLinks(nodes, edges)).toEqual([]);
    });
});

describe('buildWorkflowPayload router nodes', () => {
    const nodes = [trigger('start'), agent('a', 'A'), router('r1'), agent('b', 'B'), agent('c', 'C')];
    const edges = [flowEdge('start', 'a'), flowEdge('a', 'r1'), flowEdge('r1', 'b'), flowEdge('r1', 'c')];
    const { create } = buildWorkflowPayload({ id: 'wf', name: 'WF', nodes, edges });

    it('persists the connections that ran through the router', () => {
        expect(create.connections).toEqual([
            { from_node: 'a', to_node: 'b', type: 'sequential' },
            { from_node: 'a', to_node: 'c', type: 'sequential' },
        ]);
    });

    it('marks the branching agent a router so the backend lets it delegate', () => {
        const nodeA = create.topology.nodes.find((n) => n.id === 'a')!;
        expect(nodeA.is_router).toBe(true);
        expect(nodeA.config.is_selector).toBe(true);
        expect(create.topology.nodes.find((n) => n.id === 'b')!.is_router).toBeUndefined();
    });

    it('infers the selector pattern and a hierarchical process', () => {
        expect(create.pattern).toBe('selector');
        expect(create.process).toBe('hierarchical');
    });

    it('resolves the entry agent through the trigger', () => {
        expect(create.topology.entry_node).toBe('a');
    });

    it('needs two branches before an agent counts as a selector', () => {
        const single = buildWorkflowPayload({
            id: 'wf-single',
            name: 'WF',
            nodes: [agent('a', 'A'), router('r1'), agent('b', 'B')],
            edges: [flowEdge('a', 'r1'), flowEdge('r1', 'b')],
        });
        expect(single.create.topology.nodes.find((n) => n.id === 'a')!.is_router).toBeUndefined();
        expect(single.create.pattern).toBe('sequential');
    });
});

describe('buildWorkflowPayload guardrails', () => {
    it('is off without a Guardrail node (was hardcoded on)', () => {
        const { create } = buildWorkflowPayload({
            id: 'wf',
            name: 'WF',
            nodes: [agent('a', 'A')],
            edges: [],
        });
        expect(create.guardrails.enabled).toBe(false);
        expect(create.output_schema).toBe('text');
    });

    it('takes its schema and review flag from the node', () => {
        const { create } = buildWorkflowPayload({
            id: 'wf',
            name: 'WF',
            nodes: [agent('a', 'A'), guardrail('g1', { output_schema: 'json', human_review: true })],
            edges: [flowEdge('a', 'g1')],
        });
        expect(create.guardrails).toEqual({ enabled: true, human_review: true, output_schema: 'json' });
        expect(create.output_schema).toBe('json');
    });
});

describe('buildWorkflowPayload memory and knowledge settings', () => {
    it('carries retention, collections and top_k from the nodes', () => {
        const memoryNode = tool('mem', 'Memory Store', 'memory');
        memoryNode.data.config = { ...memoryNode.data.config, retention: 'persistent' };
        const knowledgeNode = tool('kb', 'Knowledge Source', 'knowledge');
        knowledgeNode.data.config = { ...knowledgeNode.data.config, collections: ['handbook'], top_k: 8 };

        const { create } = buildWorkflowPayload({
            id: 'wf',
            name: 'WF',
            nodes: [agent('a', 'A'), memoryNode, knowledgeNode],
            edges: [auxEdge('mem', 'a', 'memory'), auxEdge('kb', 'a', 'knowledge')],
        });

        expect(create.memory).toEqual({ enabled: true, retention: 'persistent' });
        expect(create.knowledge).toEqual({ enabled: true, collections: ['handbook'], top_k: 8 });
    });
});

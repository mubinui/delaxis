import { describe, expect, it } from 'vitest';
import { VOICE_OPERATIONS, applyVoiceOperation } from './voiceCanvasOps';
import type { OpsContext, OpsResult } from './voiceCanvasOps';

/**
 * These run against the operations a spoken conversation performs on the canvas.
 *
 * The important cases are the ones speech creates: a name that does not match
 * exactly, an instruction that arrives before the agent exists, a tool the model
 * invented. Each has to come back as a sentence the model can act on, because
 * that sentence is the only thing it learns about the outcome.
 */

// The compiler treats an indexed lookup and an optional `data` as possibly
// undefined. These collapse both in one place rather than scattering `!`
// through every assertion, where it would bury what is actually being checked.
const at = (nodes: OpsResult['nodes'], index = 0) => (nodes as any[])[index] as any;
const byId = (nodes: OpsResult['nodes'], id: string) =>
    (nodes as any[]).find((node) => node.id === id) as any;
const cfg = (node: any) => node.data.config as Record<string, any>;

const agent = (id: string, label: string, config: Record<string, any> = {}) => ({
    id,
    type: 'agent',
    position: { x: 0, y: 0 },
    data: { label, config: { type: 'LlmAgent', ...config } },
}) as any;

const context = (over: Partial<OpsContext> = {}): OpsContext => ({
    nodes: [],
    edges: [],
    tools: [
        { id: 'web_search', name: 'search_web', description: 'Search the web', config: {}, category: 'research' },
        { id: 'detect_pii', name: 'detect_pii', description: 'Find personal data', config: {}, category: 'privacy' },
    ] as any,
    agents: [],
    providers: [],
    ...over,
});

describe('addAgent', () => {
    it('adds a named agent', () => {
        const result = applyVoiceOperation('add_agent', { name: 'Search Specialist' }, context());
        expect(result.nodes).toHaveLength(1);
        expect(at(result.nodes, 0).data.label).toBe('Search Specialist');
        expect(result.say).toContain('Search Specialist');
    });

    it('keeps the instruction it was given', () => {
        const result = applyVoiceOperation(
            'add_agent',
            { name: 'Helper', instruction: 'Answer politely.' },
            context(),
        );
        expect(cfg(at(result.nodes, 0)).instruction).toBe('Answer politely.');
    });

    it('places each agent clear of the last', () => {
        const first = applyVoiceOperation('add_agent', { name: 'A' }, context());
        const second = applyVoiceOperation('add_agent', { name: 'B' }, context({ nodes: first.nodes }));
        const [a, b] = [at(second.nodes, 0), at(second.nodes, 1)];
        expect(b.position.x).toBeGreaterThan(a.position.x);
    });
});

describe('addTool', () => {
    it('attaches to the most recent agent when none is named', () => {
        // "give it web search" almost always means the one just created.
        const nodes = [agent('a1', 'First'), agent('a2', 'Second')];
        const result = applyVoiceOperation('add_tool', { tool_id: 'web_search' }, context({ nodes }));
        expect(cfg(byId(result.nodes, 'a2')).tools).toEqual(['web_search']);
        expect(cfg(byId(result.nodes, 'a1')).tools ?? []).toEqual([]);
    });

    it('attaches to a named agent', () => {
        const nodes = [agent('a1', 'SearchAssistant'), agent('a2', 'Writer')];
        const result = applyVoiceOperation(
            'add_tool',
            { tool_id: 'web_search', agent_name: 'SearchAssistant' },
            context({ nodes }),
        );
        expect(cfg(byId(result.nodes, 'a1')).tools).toEqual(['web_search']);
    });

    it('suggests alternatives for a tool that does not exist', () => {
        const result = applyVoiceOperation('add_tool', { tool_id: 'web_searcher' }, context({ nodes: [agent('a', 'A')] }));
        expect(result.nodes).toBeUndefined();
        expect(result.say).toMatch(/web_search/);
    });

    it('says so when there is no agent to attach to', () => {
        const result = applyVoiceOperation('add_tool', { tool_id: 'web_search' }, context());
        expect(result.say).toMatch(/no agents/i);
    });

    it('does not attach the same tool twice', () => {
        const nodes = [agent('a', 'A', { tools: ['web_search'] })];
        const result = applyVoiceOperation('add_tool', { tool_id: 'web_search' }, context({ nodes }));
        expect(result.nodes).toBeUndefined();
        expect(result.say).toMatch(/already/);
    });
});

describe('name resolution', () => {
    // Transcription drops articles and changes case, so an exact match would
    // fail on input a person would have understood without effort.
    const nodes = [agent('a1', 'SearchAssistant'), agent('a2', 'ResearchWriter')];

    it.each([
        ['SearchAssistant', 'a1'],
        ['search assistant', 'a1'],
        ['the search agent', 'a1'],
        ['Search', 'a1'],
        ['research writer', 'a2'],
    ])('resolves %s', (spoken, expected) => {
        const result = applyVoiceOperation(
            'set_instruction',
            { agent_name: spoken, instruction: 'x' },
            context({ nodes }),
        );
        expect(cfg(byId(result.nodes, expected)).instruction).toBe('x');
    });

    it('lists what exists when the name matches nothing', () => {
        const result = applyVoiceOperation(
            'set_instruction',
            { agent_name: 'Bookkeeper', instruction: 'x' },
            context({ nodes }),
        );
        expect(result.nodes).toBeUndefined();
        expect(result.say).toMatch(/could not find/i);
    });
});

describe('connect', () => {
    const nodes = [agent('a1', 'First'), agent('a2', 'Second')];

    it('wires one component into another', () => {
        const result = applyVoiceOperation('connect', { from_name: 'First', to_name: 'Second' }, context({ nodes }));
        expect(result.edges).toHaveLength(1);
        expect((result.edges as any[])[0]).toMatchObject({ source: 'a1', target: 'a2' });
    });

    it('refuses to connect something to itself', () => {
        const result = applyVoiceOperation('connect', { from_name: 'First', to_name: 'First' }, context({ nodes }));
        expect(result.edges).toBeUndefined();
    });

    it('does not duplicate an existing connection', () => {
        const edges = [{ id: 'e1', source: 'a1', target: 'a2' }] as any;
        const result = applyVoiceOperation('connect', { from_name: 'First', to_name: 'Second' }, context({ nodes, edges }));
        expect(result.edges).toBeUndefined();
        expect(result.say).toMatch(/already/);
    });
});

describe('addTrigger', () => {
    it('wires the trigger into an unfed agent', () => {
        const result = applyVoiceOperation('add_trigger', { kind: 'chat' }, context({ nodes: [agent('a', 'Agent')] }));
        expect(result.edges).toHaveLength(1);
        expect((result.edges as any[])[0].target).toBe('a');
        expect(result.say).toMatch(/chat trigger/i);
    });

    it('falls back to manual for an unknown kind', () => {
        const result = applyVoiceOperation('add_trigger', { kind: 'telepathy' }, context());
        expect(cfg(at(result.nodes, 0)).trigger_type).toBe('manual');
    });
});

describe('setModel', () => {
    it('sets model and temperature', () => {
        const nodes = [agent('a', 'Agent', { llm_config: { provider_id: 'openrouter' } })];
        const result = applyVoiceOperation(
            'set_model',
            { agent_name: 'Agent', model: 'google/gemini-3.5-flash-lite', temperature: 0.2 },
            context({ nodes }),
        );
        const config = cfg(at(result.nodes, 0)).llm_config;
        expect(config.model).toBe('google/gemini-3.5-flash-lite');
        expect(config.temperature).toBe(0.2);
        // The provider it already had must survive the edit.
        expect(config.provider_id).toBe('openrouter');
    });

    it('asks what to set when given nothing', () => {
        const result = applyVoiceOperation('set_model', { agent_name: 'Agent' }, context({ nodes: [agent('a', 'Agent')] }));
        expect(result.nodes).toBeUndefined();
    });
});

describe('removeNode', () => {
    it('is marked destructive so the client can confirm it', () => {
        const nodes = [agent('a', 'Doomed')];
        const result = applyVoiceOperation('remove_node', { name: 'Doomed' }, context({ nodes }));
        expect(result.destructive).toBe(true);
        expect(result.nodes).toHaveLength(0);
    });

    it('drops the edges that pointed at it', () => {
        const nodes = [agent('a1', 'First'), agent('a2', 'Second')];
        const edges = [{ id: 'e1', source: 'a1', target: 'a2' }] as any;
        const result = applyVoiceOperation('remove_node', { name: 'Second' }, context({ nodes, edges }));
        expect(result.edges).toHaveLength(0);
    });

    it('never guesses when the name does not match', () => {
        const nodes = [agent('a', 'Keep me')];
        const result = applyVoiceOperation('remove_node', { name: 'Something else entirely' }, context({ nodes }));
        expect(result.nodes).toBeUndefined();
    });
});

describe('describeCanvas', () => {
    it('reports an empty canvas plainly', () => {
        expect(applyVoiceOperation('describe_canvas', {}, context()).say).toMatch(/empty/i);
    });

    it('names components, wiring and gaps', () => {
        const nodes = [agent('a1', 'First', { tools: ['web_search'] }), agent('a2', 'Second')];
        const edges = [{ id: 'e1', source: 'a1', target: 'a2' }] as any;
        const say = applyVoiceOperation('describe_canvas', {}, context({ nodes, edges })).say;
        expect(say).toContain('First');
        expect(say).toContain('web_search');
        expect(say).toContain('First -> Second');
    });

    it('never mutates anything', () => {
        const result = applyVoiceOperation('describe_canvas', {}, context({ nodes: [agent('a', 'A')] }));
        expect(result.nodes).toBeUndefined();
        expect(result.edges).toBeUndefined();
    });
});

describe('listTools', () => {
    it('lists everything by default', () => {
        expect(applyVoiceOperation('list_available_tools', {}, context()).say).toContain('web_search');
    });

    it('filters by category', () => {
        const say = applyVoiceOperation('list_available_tools', { category: 'privacy' }, context()).say;
        expect(say).toContain('detect_pii');
        expect(say).not.toContain('web_search');
    });
});

describe('unknown and failing calls', () => {
    it('reports an operation it does not have', () => {
        const result = applyVoiceOperation('launch_rocket', {}, context());
        expect(result.nodes).toBeUndefined();
        expect(result.say).toMatch(/do not know how/i);
    });

    it('turns a thrown error into a sentence rather than propagating it', () => {
        // The model only learns the outcome from this string, so an exception
        // must never escape and leave the turn unanswered.
        const broken = { get nodes(): any { throw new Error('boom'); } } as any;
        const result = applyVoiceOperation('describe_canvas', {}, broken);
        expect(result.say).toMatch(/failed/i);
    });
});

describe('operation surface', () => {
    it('matches what the backend declares to the model', () => {
        // Kept in step with src/api/voice/canvas_tools.py; a name in one and not
        // the other is a call that can never succeed.
        expect(new Set(VOICE_OPERATIONS)).toEqual(new Set([
            'add_agent', 'add_trigger', 'add_tool', 'connect',
            'set_instruction', 'set_model', 'remove_node',
            'describe_canvas', 'list_available_tools', 'fix_problems',
        ]));
    });
});

import { beforeEach, describe, expect, it } from 'vitest';
import { useWorkflowStore } from './workflowStore';
import type { VisualEdge, VisualNode } from '../types/workflow';

// On Chat → triage → Router → specialist → Answer, with a tool attached to the specialist.
const nodes = [
    { id: 't', type: 'trigger', position: { x: 0, y: 0 }, data: { label: 'On Chat', config: { trigger_type: 'chat' } } },
    { id: 'triage', type: 'agent', position: { x: 0, y: 0 }, data: { label: 'triage', config: {} } },
    { id: 'r', type: 'router', position: { x: 0, y: 0 }, data: { label: 'Router', config: {} } },
    { id: 'spec', type: 'agent', position: { x: 0, y: 0 }, data: { label: 'spec', config: {} } },
    { id: 'tool', type: 'tool', position: { x: 0, y: 0 }, data: { label: 'calc', config: { name: 'calc' } } },
    { id: 'o', type: 'output', position: { x: 0, y: 0 }, data: { label: 'Answer', config: {} } },
] as unknown as VisualNode[];

const edges = [
    { id: 't-triage', source: 't', target: 'triage' },
    { id: 'triage-r', source: 'triage', target: 'r' },
    { id: 'r-spec', source: 'r', target: 'spec' },
    { id: 'tool-spec', source: 'tool', sourceHandle: 'attach', target: 'spec', targetHandle: 'tools' },
    { id: 'spec-o', source: 'spec', target: 'o' },
] as unknown as VisualEdge[];

const flow = (id: string) =>
    (useWorkflowStore.getState().edges.find((edge) => edge.id === id)?.data as { flow?: string } | undefined)?.flow;

const event = (type: string, nodeId?: string) =>
    useWorkflowStore.getState().applyExecutionEvent({ type, payload: nodeId ? { node_id: nodeId } : {}, timestamp: new Date().toISOString() });

describe('a run playing on the canvas', () => {
    beforeEach(() => {
        useWorkflowStore.setState({ nodes, edges });
        useWorkflowStore.getState().resetExecution();
    });

    it('starts at the trigger, lights each wire as the run arrives, and settles green', () => {
        useWorkflowStore.getState().beginFlow();
        expect(flow('t-triage')).toBe('running');
        expect(flow('triage-r')).toBeUndefined();

        event('node_output', 'triage');
        expect(flow('t-triage')).toBe('success');

        // The router reports nothing; the wire into it lights with the node it feeds.
        event('node_started', 'spec');
        expect(flow('r-spec')).toBe('running');
        expect(flow('triage-r')).toBe('running');
        expect(flow('tool-spec')).toBe('running');

        event('node_output', 'spec');
        event('done');
        for (const id of ['t-triage', 'triage-r', 'r-spec', 'tool-spec', 'spec-o']) expect(flow(id)).toBe('success');
    });

    it('never moves a wire backwards from green to moving', () => {
        event('node_output', 'triage');
        event('node_started', 'triage');
        expect(flow('t-triage')).toBe('success');
    });

    it('turns the path red when the run fails before any node reports', () => {
        useWorkflowStore.getState().beginFlow();
        event('error');
        expect(flow('t-triage')).toBe('error');
        expect(flow('spec-o')).toBeUndefined();
    });

    it('marks the node that failed and the wires into it red', () => {
        useWorkflowStore.getState().beginFlow();
        event('node_output', 'triage');
        event('error', 'spec');
        expect(flow('r-spec')).toBe('error');
        expect(flow('t-triage')).toBe('success');
    });

    it('lights the path after a chat reply from the per-node data it returns', () => {
        useWorkflowStore.getState().beginFlow();
        useWorkflowStore.getState().applyNodeIo({ triage: { output: 'handed over' }, spec: { output: '84' } }, null);
        useWorkflowStore.getState().finishFlow(true);
        for (const id of ['t-triage', 'triage-r', 'r-spec', 'spec-o']) expect(flow(id)).toBe('success');
    });

    it('clears every wire when the next run starts', () => {
        useWorkflowStore.getState().beginFlow();
        event('done');
        useWorkflowStore.getState().resetExecution();
        expect(flow('t-triage')).toBeUndefined();
    });
});

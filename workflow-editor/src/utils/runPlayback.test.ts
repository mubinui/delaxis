import { afterEach, describe, expect, it, vi } from 'vitest';
import { MAX_GAP_MS, MIN_GAP_MS, playRecordedRun, playbackDelays } from './runPlayback';
import { formatDuration, sourceLabel } from './runFormat';
import { runQuery } from '../api/runs';
import type { RunEvent } from '../api/runs';
import { useWorkflowStore } from '../stores/workflowStore';

const at = (ms: number) => ({ timestamp: new Date(Date.UTC(2026, 0, 1) + ms).toISOString() });

describe('playbackDelays', () => {
    it('plays the first frame at once and keeps ordinary gaps', () => {
        expect(playbackDelays([at(0), at(300), at(500)])).toEqual([0, 300, 200]);
    });

    it('caps a long model call and stretches a burst', () => {
        expect(playbackDelays([at(0), at(20_000), at(20_001)])).toEqual([0, MAX_GAP_MS, MIN_GAP_MS]);
    });

    it('scales by speed, and survives a bad timestamp', () => {
        expect(playbackDelays([at(0), at(400)], 2)).toEqual([0, 200]);
        expect(playbackDelays([at(0), { timestamp: 'not a date' }])).toEqual([0, MIN_GAP_MS]);
    });
});

describe('playRecordedRun', () => {
    afterEach(() => {
        vi.useRealTimers();
        useWorkflowStore.getState().resetExecution();
    });

    const frame = (type: string, ms: number, payload = {}): RunEvent => ({ type, payload, agent_id: null, sequence: ms, ...at(ms) });

    it('feeds every frame through the live-run path, in order', async () => {
        vi.useFakeTimers();
        const events = [frame('start', 0), frame('token', 100, { text: 'Hi' }), frame('done', 200, { result: { response: 'Hi' } })];
        const played = playRecordedRun(events);
        await vi.runAllTimersAsync();
        expect(await played).toBe('played');
        const state = useWorkflowStore.getState();
        expect(state.executionTimeline.map((item) => item.type)).toEqual(['start', 'token', 'done']);
        expect(state.liveResponse).toBe('Hi');
        expect(state.liveRunActive).toBe(false);
    });

    it('stops when aborted', async () => {
        vi.useFakeTimers();
        const controller = new AbortController();
        const played = playRecordedRun([frame('start', 0), frame('token', 500), frame('done', 900)], { signal: controller.signal });
        await vi.advanceTimersByTimeAsync(10);
        controller.abort();
        await vi.runAllTimersAsync();
        expect(await played).toBe('stopped');
        expect(useWorkflowStore.getState().executionTimeline).toHaveLength(1);
    });
});

describe('run formatting', () => {
    it('formats durations at a useful precision', () => {
        expect(formatDuration(null)).toBe('—');
        expect(formatDuration(420)).toBe('420 ms');
        expect(formatDuration(12_340)).toBe('12.3 s');
        expect(formatDuration(119_600)).toBe('2 min 0 s');
        expect(formatDuration(95_000)).toBe('1 min 35 s');
    });

    it('names known sources and spells out unknown ones', () => {
        expect(sourceLabel('workflow_execute')).toBe('API');
        expect(sourceLabel('slack_bot')).toBe('slack bot');
    });

    it('leaves empty filters out of the query', () => {
        expect(runQuery({})).toBe('');
        expect(runQuery({ workflow_id: '', status: 'failed', limit: 50, offset: 0 })).toBe('?status=failed&limit=50&offset=0');
        expect(runQuery({ workflow_id: 'a b' })).toBe('?workflow_id=a+b');
    });
});

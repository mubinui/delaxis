import { useWorkflowStore } from '../stores/workflowStore';
import type { RunEvent } from '../api/runs';

/** The longest pause between two frames in a playback, however long the run waited. */
export const MAX_GAP_MS = 900;
/** The shortest, so a burst of frames is still visible one by one. */
export const MIN_GAP_MS = 80;

/**
 * The pause before each frame of a playback: the recorded gap, clamped so a
 * model call that took twenty seconds plays in under one and a burst of tool
 * events does not flash past. The first frame plays at once.
 */
export const playbackDelays = (events: Pick<RunEvent, 'timestamp'>[], speed = 1): number[] => {
    const times = events.map((event) => new Date(event.timestamp).getTime());
    return times.map((time, index) => {
        if (index === 0) return 0;
        const gap = Number.isFinite(time) && Number.isFinite(times[index - 1]) ? time - times[index - 1] : MIN_GAP_MS;
        return Math.round(Math.min(MAX_GAP_MS, Math.max(MIN_GAP_MS, gap)) / speed);
    });
};

/**
 * Play a recorded run on the canvas through the same code path a live run
 * uses, so the wires, node status, Data tabs and timeline show it the way they
 * showed it then. Resolves when the last frame has played; `signal` stops it.
 */
export const playRecordedRun = async (
    events: RunEvent[],
    options: { speed?: number; signal?: AbortSignal } = {},
): Promise<'played' | 'stopped'> => {
    const store = useWorkflowStore.getState();
    store.resetExecution();
    store.beginFlow();
    const delays = playbackDelays(events, options.speed);
    let failed = false;
    for (const [index, event] of events.entries()) {
        if (delays[index]) await new Promise((resolve) => setTimeout(resolve, delays[index]));
        if (options.signal?.aborted) {
            useWorkflowStore.getState().finishFlow(!failed);
            return 'stopped';
        }
        if (event.type === 'error') failed = true;
        useWorkflowStore.getState().applyExecutionEvent({ ...event });
    }
    useWorkflowStore.getState().finishFlow(!failed);
    return 'played';
};

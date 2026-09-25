import { API_BASE_URL } from '../api/client';
import { useWorkflowStore } from '../stores/workflowStore';
import { errorText } from './apiErrors';

/** Read a server-sent event stream, handing each JSON `data:` frame to `onEvent`. */
export const readSse = async (response: Response, onEvent: (event: Record<string, any>) => void) => {
    if (!response.body) throw new Error('No stream body returned');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';
        for (const frame of frames) {
            const dataLine = frame.split('\n').find((line) => line.startsWith('data: '));
            if (!dataLine) continue;
            const raw = dataLine.slice(6);
            if (raw === '[DONE]') continue;
            onEvent(JSON.parse(raw));
        }
    }
};

/**
 * Run a workflow over the streaming endpoint and play it on the canvas: the
 * wires leaving `fromNodeIds` (the triggers, by default) start moving, each wire
 * lights as the run reaches the node it feeds, and the whole path settles green
 * — or red where it failed. The same events fill the run timeline and each
 * node's Data tab.
 */
export const runWorkflowLive = async (
    workflowId: string,
    message: string,
    options: { source?: string; fromNodeIds?: string[] } = {},
): Promise<'success' | 'error'> => {
    const store = useWorkflowStore.getState();
    store.resetExecution();
    store.beginFlow(options.fromNodeIds);

    let failed = false;
    const apply = (event: Record<string, any>) => {
        if (event.type === 'error') failed = true;
        useWorkflowStore.getState().applyExecutionEvent(event);
    };

    try {
        const response = await fetch(`${API_BASE_URL}/api/v1/workflows/${encodeURIComponent(workflowId)}/execute/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, metadata: { source: options.source ?? 'canvas_live_run' }, timeout_seconds: 120 }),
        });
        if (!response.ok) {
            const text = await response.text();
            let detail: unknown = text;
            try {
                detail = JSON.parse(text)?.detail ?? text;
            } catch {
                // Not JSON: the text is the message.
            }
            throw new Error(errorText(detail, `HTTP ${response.status}`));
        }
        await readSse(response, apply);
    } catch (error) {
        apply({
            type: 'error',
            payload: { error_message: (error as Error).message },
            timestamp: new Date().toISOString(),
        });
    }

    // A stream that closes without a final event still settles its wires.
    useWorkflowStore.getState().finishFlow(!failed);
    return failed ? 'error' : 'success';
};

const SOURCE_LABEL: Record<string, string> = {
    chat: 'Chat',
    replay: 'Replay',
    test: 'Test case',
    deployment: 'Deployment',
    workflow_execute: 'API',
    workflow_live_run: 'Live run',
    canvas_live_run: 'Canvas',
    studio_test_chat: 'Test chat',
};

/** A run's source as the Runs page names it. */
export const sourceLabel = (source: string) => SOURCE_LABEL[source] ?? source.replace(/_/g, ' ');

/** How long a run took, at the precision that matters for its length. */
export const formatDuration = (ms: number | null) => {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
    const seconds = Math.round(ms / 1000);
    return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
};

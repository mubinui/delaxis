import { useEffect, useState } from 'react';
import { Play, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import type { StatusShape } from './shell/StatusGlyph';
import { useUiStore } from '../stores/uiStore';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { deleteRun, getRun, listRuns, replayRun } from '../api/runs';
import type { RunDetail, RunStatus, RunSummary } from '../api/runs';
import { playRecordedRun } from '../utils/runPlayback';
import { workflowToCanvas } from '../utils/workflowToCanvas';
import { formatDuration, sourceLabel } from '../utils/runFormat';

const PAGE_SIZE = 50;

const SHAPE: Record<RunStatus, StatusShape> = { running: 'busy', succeeded: 'ok', failed: 'bad' };
const STATUS_LABEL: Record<RunStatus, string> = { running: 'Running', succeeded: 'Succeeded', failed: 'Failed' };

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error));

const formatWhen = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });

interface Listing {
    key: string;
    runs: RunSummary[];
    total: number;
    error: string | null;
    /** The refresh this listing answers, so the refresh button spins until it lands. */
    reload: number;
}

const STATUS_TABS: Array<{ id: RunStatus | ''; label: string }> = [
    { id: '', label: 'All' },
    { id: 'succeeded', label: 'Succeeded' },
    { id: 'failed', label: 'Failed' },
];

/**
 * Every run of every workflow, newest first: what was asked, what answered,
 * which agents and tools ran, and every event on the way. A run can be played
 * back on the canvas or sent again to the workflow as it is now.
 */
export const RunHistory = () => {
    const go = useUiStore((state) => state.go);
    const setTimelineOpen = useUiStore((state) => state.setTimelineOpen);
    const { savedWorkflows, savedAgents, savedTools, fetchLibraryItems } = useLibraryStore();

    const [workflowFilter, setWorkflowFilter] = useState('');
    const [statusFilter, setStatusFilter] = useState<RunStatus | ''>('');
    // The listing is keyed by its filters, so changing a filter never shows the
    // previous filter's runs while the next ones load.
    const filterKey = `${workflowFilter}|${statusFilter}`;
    const [listing, setListing] = useState<Listing | null>(null);
    const [reloads, setReloads] = useState(0);
    const [loadingMore, setLoadingMore] = useState(false);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [detail, setDetail] = useState<RunDetail | null>(null);
    const [busy, setBusy] = useState<'replay' | 'delete' | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        listRuns({ workflow_id: workflowFilter, status: statusFilter, limit: PAGE_SIZE })
            .then((page) => {
                if (!cancelled) setListing({ key: filterKey, runs: page.items, total: page.total, error: null, reload: reloads });
            })
            .catch((error: unknown) => {
                if (!cancelled) setListing({ key: filterKey, runs: [], total: 0, error: errorMessage(error), reload: reloads });
            });
        return () => { cancelled = true; };
    }, [filterKey, workflowFilter, statusFilter, reloads]);

    const current = listing?.key === filterKey ? listing : null;
    const runs = current?.runs ?? [];
    const total = current?.total ?? 0;
    const listError = current?.error ?? null;
    const loading = current === null || current.reload !== reloads || loadingMore;

    const update = (change: (runs: RunSummary[], total: number) => { runs: RunSummary[]; total: number }) =>
        setListing((state) => (state ? { ...state, ...change(state.runs, state.total) } : state));

    const loadMore = async () => {
        setLoadingMore(true);
        try {
            const page = await listRuns({ workflow_id: workflowFilter, status: statusFilter, limit: PAGE_SIZE, offset: runs.length });
            update((items) => ({ runs: [...items, ...page.items], total: page.total }));
        } catch (error) {
            setActionError(errorMessage(error));
        } finally {
            setLoadingMore(false);
        }
    };

    useEffect(() => {
        if (savedWorkflows.length === 0) void fetchLibraryItems().catch(() => undefined);
    }, [savedWorkflows.length, fetchLibraryItems]);

    const shownId = selectedId ?? runs[0]?.id ?? null;
    useEffect(() => {
        if (!shownId) return;
        let cancelled = false;
        getRun(shownId)
            .then((run) => { if (!cancelled) setDetail(run); })
            .catch((error: unknown) => { if (!cancelled) setActionError(errorMessage(error)); });
        return () => { cancelled = true; };
    }, [shownId]);
    const shown = detail && detail.id === shownId ? detail : null;

    const select = (id: string) => {
        setSelectedId(id);
        setActionError(null);
    };

    const replay = async (run: RunDetail) => {
        setBusy('replay');
        setActionError(null);
        try {
            const fresh = await replayRun(run.id);
            const matches = (!workflowFilter || fresh.workflow_id === workflowFilter) && (!statusFilter || fresh.status === statusFilter);
            if (matches) update((items, count) => ({ runs: [fresh, ...items], total: count + 1 }));
            setDetail(fresh);
            setSelectedId(fresh.id);
        } catch (error) {
            setActionError(errorMessage(error));
        } finally {
            setBusy(null);
        }
    };

    const remove = async (run: RunDetail) => {
        setBusy('delete');
        setActionError(null);
        try {
            await deleteRun(run.id);
            update((items, count) => ({ runs: items.filter((item) => item.id !== run.id), total: Math.max(0, count - 1) }));
            setSelectedId(null);
            setDetail(null);
        } catch (error) {
            setActionError(errorMessage(error));
        } finally {
            setBusy(null);
        }
    };

    const playOnCanvas = (run: RunDetail) => {
        const workflows = useWorkflowStore.getState();
        if (workflows.currentWorkflowId !== run.workflow_id) {
            const workflow = savedWorkflows.find((item) => item.id === run.workflow_id);
            if (!workflow) {
                setActionError(`The workflow ${run.workflow_id} no longer exists, so there is no canvas to play this run on.`);
                return;
            }
            if (workflows.nodes.length > 0 && !confirm(`Open ${workflow.name} on the canvas? Unsaved changes to the workflow open now are lost.`)) {
                return;
            }
            const { nodes, edges } = workflowToCanvas({ config: workflow.config, agents: savedAgents, tools: savedTools });
            workflows.loadWorkflow(workflow.id, workflow.name, nodes, edges);
        }
        go('studio');
        setTimelineOpen(true);
        void playRecordedRun(run.events);
    };

    const replayOf = shown?.replay_of ? runs.find((run) => run.id === shown.replay_of) : undefined;

    const empty = !loading && runs.length === 0 && !listError;

    return (
        <>
            <div className="page">
                <div className="page-inner">
                    <div className="page-head">
                        <div>
                            <h1 className="display">Runs</h1>
                            <p className="lead mt-1 max-w-[680px]">
                                Every run of every workflow: the request, the answer, and each agent handoff and tool call on the way.
                                Play one back on the canvas, or send it again to see what your changes do.
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <select
                                className="select !w-auto"
                                value={workflowFilter}
                                onChange={(event) => { setWorkflowFilter(event.target.value); setSelectedId(null); }}
                                aria-label="Workflow"
                            >
                                <option value="">All workflows</option>
                                {savedWorkflows.map((workflow) => (
                                    <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
                                ))}
                            </select>
                            <div className="segmented" role="tablist" aria-label="Status">
                                {STATUS_TABS.map((tab) => (
                                    <button
                                        key={tab.id || 'all'}
                                        type="button"
                                        role="tab"
                                        aria-selected={statusFilter === tab.id}
                                        onClick={() => { setStatusFilter(tab.id); setSelectedId(null); }}
                                    >
                                        {tab.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {listError && <p className="mt-4 text-[12.5px]" role="alert" style={{ color: 'var(--clay)' }}>Could not load the runs: {listError}</p>}

                    {empty && (
                        <div className="panel empty-state mt-5">
                            <div className="headline">{workflowFilter || statusFilter ? 'No runs match' : 'No runs yet'}</div>
                            <p className="hint max-w-[380px]">
                                {workflowFilter || statusFilter
                                    ? 'Change the filters to see more runs.'
                                    : 'Every message sent to a workflow — from the test chat, a live run, a deployed page or the API — is recorded here.'}
                            </p>
                            {!workflowFilter && !statusFilter && <button type="button" className="btn mt-2" onClick={() => go('studio')}>Open the Studio</button>}
                        </div>
                    )}

                    {runs.length > 0 && (
                        <div className="split-layout">
                            <div className="flex min-w-0 flex-col gap-3">
                                <div className="table-box">
                                    <table className="mtable" aria-label="Runs">
                                        <thead>
                                            <tr><th>Request</th><th className="hide-narrow">Source</th><th>Started</th><th className="hide-narrow">Took</th><th>Status</th></tr>
                                        </thead>
                                        <tbody>
                                            {runs.map((run) => (
                                                <tr key={run.id} aria-selected={run.id === shownId} onClick={() => select(run.id)}>
                                                    <td style={{ maxWidth: 0, width: '42%' }}>
                                                        <button type="button" className="row-title" data-row={run.id} onFocus={() => select(run.id)}>{run.message}</button>
                                                        <span className="row-sub mono">{run.workflow_id}</span>
                                                    </td>
                                                    <td className="hide-narrow">{sourceLabel(run.source)}</td>
                                                    <td>{formatWhen(run.started_at)}</td>
                                                    <td className="mono hide-narrow">{formatDuration(run.duration_ms)}</td>
                                                    <td>
                                                        <span className="row-status">
                                                            <StatusGlyph shape={SHAPE[run.status] ?? 'idle'} />
                                                            {STATUS_LABEL[run.status] ?? run.status}
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                <div className="flex items-center gap-3">
                                    <span className="hint">{runs.length} of {total}</span>
                                    {runs.length < total && (
                                        <button type="button" className="btn btn-sm" disabled={loading} onClick={() => void loadMore()}>
                                            {loading ? 'Loading…' : 'Load more'}
                                        </button>
                                    )}
                                </div>
                            </div>

                            {shown && (
                                <aside className="inspector" aria-label="Run details">
                                    <div>
                                        <h2 className="title-2">Run</h2>
                                        <div className="mono text-dim mt-0.5">{shown.id}</div>
                                    </div>
                                    <div className="inspector-status">
                                        <StatusGlyph shape={SHAPE[shown.status] ?? 'idle'} />
                                        {STATUS_LABEL[shown.status] ?? shown.status}
                                        <span className="hint font-normal">· {formatDuration(shown.duration_ms)}</span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null} onClick={() => void replay(shown)}>
                                            <RotateCcw size={12} /> {busy === 'replay' ? 'Replaying…' : 'Replay'}
                                        </button>
                                        <button type="button" className="btn btn-sm" disabled={shown.events.length === 0} onClick={() => playOnCanvas(shown)}>
                                            <Play size={10} fill="currentColor" /> Play on canvas
                                        </button>
                                        <span className="flex-1" />
                                        <button type="button" className="btn btn-danger btn-sm" disabled={busy !== null} onClick={() => void remove(shown)} aria-label="Delete run">
                                            <Trash2 size={12} /> Delete
                                        </button>
                                    </div>
                                    {actionError && <p className="text-[12px]" role="alert" style={{ color: 'var(--clay)' }}>{actionError}</p>}
                                    <div className="rows">
                                        <div><span className="row-k">Workflow</span><span className="row-v mono">{shown.workflow_id}</span></div>
                                        <div><span className="row-k">Source</span><span className="row-v">{sourceLabel(shown.source)}</span></div>
                                        <div><span className="row-k">Started</span><span className="row-v">{formatWhen(shown.started_at)}</span></div>
                                        {shown.user_id && <div><span className="row-k">User</span><span className="row-v mono">{shown.user_id}</span></div>}
                                        {shown.agents_called.length > 0 && <div><span className="row-k">Agents</span><span className="row-v">{shown.agents_called.join(', ')}</span></div>}
                                        {shown.tools_called.length > 0 && <div><span className="row-k">Tools</span><span className="row-v mono">{shown.tools_called.join(', ')}</span></div>}
                                        {typeof shown.usage.total_tokens === 'number' && shown.usage.total_tokens > 0 && (
                                            <div><span className="row-k">Tokens</span><span className="row-v mono">{shown.usage.total_tokens.toLocaleString()}</span></div>
                                        )}
                                        {shown.replay_of && (
                                            <div>
                                                <span className="row-k">Replay of</span>
                                                <span className="row-v mono">
                                                    {replayOf ? <button type="button" className="underline" onClick={() => select(replayOf.id)}>{shown.replay_of.slice(0, 8)}</button> : shown.replay_of.slice(0, 8)}
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex flex-col gap-1.5">
                                        <span className="h-section">Request</span>
                                        <pre className="well max-h-40 overflow-auto whitespace-pre-wrap p-3 text-[12.5px]">{shown.message}</pre>
                                    </div>
                                    {shown.error ? (
                                        <div className="flex flex-col gap-1.5">
                                            <span className="h-section">Error</span>
                                            <pre className="well max-h-40 overflow-auto whitespace-pre-wrap p-3 text-[12.5px]" style={{ color: 'var(--clay)' }}>{shown.error}</pre>
                                        </div>
                                    ) : shown.response !== null && (
                                        <div className="flex flex-col gap-1.5">
                                            <span className="h-section">Response</span>
                                            <pre className="well max-h-60 overflow-auto whitespace-pre-wrap p-3 text-[12.5px]">{shown.response}</pre>
                                        </div>
                                    )}
                                    <div className="flex flex-col gap-1.5">
                                        <span className="h-section">Events · {shown.events.length}</span>
                                        <ol className="flex flex-col" aria-label="Events">
                                            {shown.events.map((event) => (
                                                <li key={event.sequence} className="flex items-baseline gap-2 py-1 text-[12px]" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                                                    <span className="mono min-w-0 flex-1 truncate">{event.type}{event.payload.node_id ? ` · ${event.payload.node_id}` : event.payload.name ? ` · ${event.payload.name}` : ''}</span>
                                                    <span className="mono text-dim">+{((new Date(event.timestamp).getTime() - new Date(shown.events[0].timestamp).getTime()) / 1000).toFixed(1)} s</span>
                                                </li>
                                            ))}
                                        </ol>
                                    </div>
                                </aside>
                            )}
                        </div>
                    )}
                </div>
            </div>
            <Toolbar
                center={<ActivityCapsule onStatusClick={() => go('studio')} />}
                actions={
                    <>
                        <button type="button" className="btn btn-toolbar btn-icon" onClick={() => setReloads((count) => count + 1)} aria-label="Refresh" title="Refresh">
                            <RefreshCw size={15} strokeWidth={1.8} className={loading ? 'animate-spin' : ''} />
                        </button>
                        <MoreMenu />
                    </>
                }
            />
        </>
    );
};

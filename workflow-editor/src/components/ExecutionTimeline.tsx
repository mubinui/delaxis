import { useEffect } from 'react';
import { Play, RotateCcw, X } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import { runWorkflowLive } from '../utils/liveRun';
import { useUiStore } from '../stores/uiStore';
import { StatusGlyph } from './shell/StatusGlyph';
import type { StatusShape } from './shell/StatusGlyph';

const SHAPE: Record<string, StatusShape> = { running: 'busy', success: 'ok', error: 'bad', info: 'idle' };

/**
 * The run timeline hangs from the activity capsule, the way a build log hangs
 * from Xcode's activity view: every agent handoff and tool call, in order.
 */
export const ExecutionTimeline = () => {
    const isOpen = useUiStore((state) => state.timelineOpen);
    const setIsOpen = useUiStore((state) => state.setTimelineOpen);
    const {
        currentWorkflowId,
        executionTimeline,
        liveRunActive,
        liveResponse,
        resetExecution,
    } = useWorkflowStore(
        useShallow((state) => ({
            currentWorkflowId: state.currentWorkflowId,
            executionTimeline: state.executionTimeline,
            liveRunActive: state.liveRunActive,
            liveResponse: state.liveResponse,
            resetExecution: state.resetExecution,
        })),
    );

    const runLive = async () => {
        if (!currentWorkflowId) {
            alert('Save or open a workflow before running it live.');
            return;
        }
        const message = prompt('Live run input:', 'Hello');
        if (!message) return;
        await runWorkflowLive(currentWorkflowId, message);
    };

    useEffect(() => {
        if (!isOpen) return;
        const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setIsOpen(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isOpen, setIsOpen]);

    if (!isOpen) return null;

    const started = executionTimeline[0] ? new Date(executionTimeline[0].timestamp).getTime() : 0;

    return (
        <div
            className="glass-strong absolute z-40 flex flex-col overflow-hidden"
            style={{
                left: '50%', translate: '-50% 0', top: 'calc(var(--toolbar-h) + 4px)',
                width: 'min(520px, calc(100% - 32px))', maxHeight: 'min(440px, 62vh)',
                borderRadius: 'var(--r-lg)', transformOrigin: 'top center', animation: 'pop .2s var(--ease-out) both',
            }}
            role="dialog"
            aria-label="Run timeline"
        >
            <div className="flex shrink-0 items-center gap-2 py-2.5 pl-4 pr-2.5">
                <div className="min-w-0 flex-1">
                    <div className="headline">Run timeline</div>
                    <div className="hint truncate">{liveRunActive ? 'Running the workflow…' : 'Every handoff and tool call, in order'}</div>
                </div>
                <button onClick={resetExecution} className="btn btn-ghost btn-icon" title="Clear the timeline" aria-label="Clear the timeline">
                    <RotateCcw size={14} />
                </button>
                <button onClick={runLive} disabled={liveRunActive} className="btn btn-sm">
                    <Play size={10} fill="currentColor" /> Run live
                </button>
                <button onClick={() => setIsOpen(false)} className="btn btn-ghost btn-icon" title="Close" aria-label="Close the timeline">
                    <X size={14} />
                </button>
            </div>
            <div className="scroll-soft min-h-0 pb-1.5">
                {executionTimeline.length === 0 ? (
                    <p className="hint px-4 pb-3">Run a workflow to see every agent transfer and tool call in order.</p>
                ) : (
                    executionTimeline.map((item) => (
                        <div key={item.id} className="flex gap-2.5 px-4 py-2" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                            <span className="pt-[4px]"><StatusGlyph shape={SHAPE[item.status] ?? 'idle'} /></span>
                            <div className="min-w-0 flex-1">
                                <div className="flex items-baseline gap-2">
                                    <span className="min-w-0 flex-1 truncate text-[12.5px]">{item.label}</span>
                                    <span className="mono text-dim">
                                        {started ? `+${((new Date(item.timestamp).getTime() - started) / 1000).toFixed(1)} s` : ''}
                                    </span>
                                </div>
                                {(item.type.includes('tool') || item.type === 'error' || item.type === 'node_input' || item.type === 'node_output') && (
                                    <pre className="well mono mt-1.5 max-h-28 overflow-auto whitespace-pre-wrap p-2 text-[11px]" style={{ color: 'var(--muted)' }}>{JSON.stringify(item.payload, null, 2)}</pre>
                                )}
                            </div>
                        </div>
                    ))
                )}
            </div>
            {liveResponse && (
                <div className="shrink-0 px-4 py-3" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                    <div className="h-section mb-1">Response</div>
                    <div className="max-h-24 overflow-y-auto whitespace-pre-wrap text-[12.5px]">{liveResponse}</div>
                </div>
            )}
        </div>
    );
};

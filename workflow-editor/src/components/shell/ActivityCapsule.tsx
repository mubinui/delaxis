import { useMemo } from 'react';
import { ChevronDown, FilePlus2, FolderOpen } from 'lucide-react';
import { useStoreWithEqualityFn } from 'zustand/traditional';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../../stores/workflowStore';
import type { VisualNode } from '../../types/workflow';
import { useLibraryStore } from '../../stores/libraryStore';
import { useUiStore } from '../../stores/uiStore';
import { diagnoseWorkflow, summarizeDiagnostics } from '../../utils/graphDiagnostics';
import { StatusGlyph } from './StatusGlyph';
import type { StatusShape } from './StatusGlyph';
import { MenuButton, MenuItem, MenuLabel, MenuSeparator } from './Menu';

// A dragged node gets a new object every frame; only its identity, type and data
// matter here, so the capsule does not re-render while something moves.
const sameGraph = (a: VisualNode[], b: VisualNode[]) =>
    a.length === b.length && a.every((node, i) => node.id === b[i].id && node.type === b[i].type && node.data === b[i].data);

interface ActivityCapsuleProps {
    /** In the Studio the name is editable and the chevron opens saved workflows. */
    editable?: boolean;
    onOpenWorkflow?: (id: string) => void;
    onNewWorkflow?: () => void;
    /** Clicking the status: the run timeline while something runs, otherwise the problems. */
    onStatusClick?: (hasIssues: boolean) => void;
    statusExpanded?: boolean;
}

/**
 * The activity capsule at the centre of the toolbar answers three questions:
 * which workflow is open, what state it is in, and what is running.
 */
export const ActivityCapsule = ({ editable = false, onOpenWorkflow, onNewWorkflow, onStatusClick, statusExpanded }: ActivityCapsuleProps) => {
    const nodes = useStoreWithEqualityFn(useWorkflowStore, (state) => state.nodes, sameGraph);
    const { edges, workflowName, setWorkflowName, currentWorkflowId, liveRunActive, executionTimeline } = useWorkflowStore(
        useShallow((state) => ({
            edges: state.edges,
            workflowName: state.workflowName,
            setWorkflowName: state.setWorkflowName,
            currentWorkflowId: state.currentWorkflowId,
            liveRunActive: state.liveRunActive,
            executionTimeline: state.executionTimeline,
        })),
    );
    const { savedAgents, savedTools, providers, savedWorkflows, fetchLibraryItems } = useLibraryStore();
    const { testRunning, go, screen } = useUiStore();

    const summary = useMemo(
        () => summarizeDiagnostics(diagnoseWorkflow({ nodes, edges, agents: savedAgents, tools: savedTools, providers })),
        [nodes, edges, savedAgents, savedTools, providers],
    );

    const running = testRunning || liveRunActive;
    const current = [...executionTimeline].reverse().find((item) => item.status === 'running');
    const issues = summary.errors + summary.warnings;

    let shape: StatusShape;
    let text: string;
    if (running) {
        shape = 'busy';
        text = current ? `Running · ${current.label}` : 'Running';
    } else if (nodes.length === 0) {
        shape = 'idle';
        text = 'Empty canvas';
    } else if (summary.errors > 0) {
        shape = 'bad';
        text = `${summary.errors} ${summary.errors === 1 ? 'problem' : 'problems'} to fix`;
    } else if (summary.warnings > 0) {
        shape = 'warn';
        text = `${summary.warnings} ${summary.warnings === 1 ? 'warning' : 'warnings'}`;
    } else {
        shape = 'ok';
        text = `${currentWorkflowId ? 'Ready' : 'Not saved'} · ${nodes.length} ${nodes.length === 1 ? 'component' : 'components'}`;
    }

    return (
        <div className="activity liquid">
            {editable ? (
                <>
                    <input
                        className="activity-name"
                        value={workflowName}
                        onChange={(event) => setWorkflowName(event.target.value)}
                        aria-label="Workflow name"
                        spellCheck={false}
                    />
                    <MenuButton
                        align="center"
                        width={280}
                        button={({ open, toggle }) => (
                            <button
                                type="button"
                                className="btn btn-ghost btn-sm btn-icon"
                                onClick={() => {
                                    if (!open) void fetchLibraryItems();
                                    toggle();
                                }}
                                aria-label="Open a workflow"
                                aria-haspopup="menu"
                                aria-expanded={open}
                                title="Open a workflow"
                            >
                                <ChevronDown size={14} />
                            </button>
                        )}
                    >
                        {(close) => (
                            <>
                                <MenuItem icon={FilePlus2} onSelect={() => { close(); onNewWorkflow?.(); }}>New workflow</MenuItem>
                                <MenuSeparator />
                                <MenuLabel>Saved workflows</MenuLabel>
                                <div className="max-h-72 overflow-y-auto">
                                    {savedWorkflows.length === 0 && <div className="hint px-2.5 py-1.5">Nothing saved yet.</div>}
                                    {savedWorkflows.map((workflow) => (
                                        <MenuItem
                                            key={workflow.id}
                                            icon={FolderOpen}
                                            checked={workflow.id === currentWorkflowId ? true : undefined}
                                            onSelect={() => { close(); onOpenWorkflow?.(workflow.id); }}
                                        >
                                            {workflow.name}
                                        </MenuItem>
                                    ))}
                                </div>
                            </>
                        )}
                    </MenuButton>
                </>
            ) : (
                <button
                    type="button"
                    className="activity-name text-left truncate"
                    onClick={() => go('studio')}
                    title={screen === 'studio' ? workflowName : `Open ${workflowName} in the Studio`}
                >
                    {workflowName}
                </button>
            )}
            <span className="activity-sep" aria-hidden="true" />
            <button
                type="button"
                className="activity-status"
                onClick={() => onStatusClick?.(issues > 0 && !running)}
                aria-expanded={statusExpanded}
                title={running ? 'Show the run timeline' : issues > 0 ? 'Show the problems' : 'Show the run timeline'}
            >
                <StatusGlyph shape={shape} />
                <span>{text}</span>
            </button>
            {running && <span className="activity-progress is-indeterminate" aria-hidden="true" />}
        </div>
    );
};

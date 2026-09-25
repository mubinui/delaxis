import React, { useState, useCallback, useRef } from 'react';
import { Blocks, Check, Copy, Download, FilePlus2, LayoutDashboard, LifeBuoy, Play, Save, ShieldCheck, Upload, Zap } from 'lucide-react';
import { useReactFlow } from '@xyflow/react';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { buildWorkflowPayload, getAgentBindings } from '../utils/workflowPayload';
import { workflowToCanvas } from '../utils/workflowToCanvas';
import { describeSaveError } from '../utils/saveErrors';
import { canvasFit, getLayoutedElements } from '../utils/layout';
import { useUiStore } from '../stores/uiStore';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { MenuItem, MenuSeparator } from './shell/Menu';

/**
 * The Studio's toolbar. The activity capsule holds the workflow's name, the
 * saved workflows and its state; related actions share one glass capsule, with
 * Test as the one solid action; everything occasional lives under More.
 */
export const Header: React.FC = () => {
    // Only `workflowName` is subscribed to (the handlers name files and payloads with
    // it) — everything else is read fresh via getState() inside handlers so this
    // toolbar doesn't re-render on every node/edge change (e.g. every mousemove frame
    // while dragging a node on the canvas).
    const workflowName = useWorkflowStore((state) => state.workflowName);
    const { setNodes, setEdges, onNodesChange, setWorkflowName, setCurrentWorkflow, loadWorkflow, updateNodeData } = useWorkflowStore(
        useShallow((state) => ({
            setNodes: state.setNodes,
            setEdges: state.setEdges,
            onNodesChange: state.onNodesChange,
            setWorkflowName: state.setWorkflowName,
            setCurrentWorkflow: state.setCurrentWorkflow,
            loadWorkflow: state.loadWorkflow,
            updateNodeData: state.updateNodeData,
        })),
    );
    const { savedWorkflows, savedAgents, savedTools, saveWorkflow, validateWorkflow, executeWorkflow, isLoading, fetchLibraryItems } = useLibraryStore();
    const { fitView } = useReactFlow();
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [copied, setCopied] = useState(false);
    const { pane, togglePane, testOpen, setTestOpen, timelineOpen, setTimelineOpen } = useUiStore();

    const handleNew = () => {
        if (confirm("Are you sure you want to create a new workflow? Unsaved changes will be lost.")) {
            setNodes([]);
            setEdges([]);
            setWorkflowName('Untitled Workflow');
            setCurrentWorkflow(null);
        }
    };

    const handleLayout = useCallback(() => {
        const { nodes, edges } = useWorkflowStore.getState();
        const { nodes: layoutedNodes } = getLayoutedElements(nodes, edges);
        const changes = layoutedNodes.map((node) => ({
            id: node.id,
            type: 'position',
            position: node.position
        }));
        // @ts-ignore
        onNodesChange(changes);
        setTimeout(() => fitView(canvasFit(useUiStore.getState().paletteOpen, 800)), 100);
    }, [onNodesChange, fitView]);

    const handleSave = async () => {
        const { nodes, edges, currentWorkflowId } = useWorkflowStore.getState();
        if (!nodes.length) {
            alert("Cannot save an empty workflow.");
            return;
        }

        // Pre-flight: the backend rejects a workflow whose topology references an
        // agent id absent from the agent registry. A blank "CrewAI Agent" palette
        // node resolves to an id like `crewai_agent` that was never persisted, so
        // catch that here and offer to create the agents instead of surfacing a
        // raw 422. Refetch first so the check runs against current backend truth.
        try {
            await fetchLibraryItems();
        } catch {
            // Non-fatal: fall through with whatever agents we already have.
        }
        const { savedAgents, saveItem } = useLibraryStore.getState();
        const knownAgentIds = new Set(savedAgents.map((a) => a.id));
        const unbound = getAgentBindings(nodes).filter((b) => !knownAgentIds.has(b.agentId));

        if (unbound.length > 0) {
            const list = unbound.map((b) => ` • ${b.label} → "${b.agentId}"`).join('\n');
            const proceed = confirm(
                `${unbound.length} agent node(s) aren't saved as backend agents yet:\n${list}\n\n` +
                `Click OK to create them in your agent library and save the workflow.\n` +
                `Click Cancel to bind them to existing agents yourself first.`,
            );
            if (!proceed) return;
            try {
                for (const binding of unbound) {
                    const node = nodes.find((n) => n.id === binding.nodeId);
                    // Pin config.id to the resolved id so both the created agent and
                    // the workflow topology reference exactly the same id.
                    const config = { ...(node?.data?.config ?? {}), id: binding.agentId };
                    await saveItem('agent', {
                        name: binding.label,
                        description: String(node?.data?.description ?? ''),
                        config,
                    });
                    updateNodeData(binding.nodeId, { config });
                }
            } catch (e) {
                alert("Couldn't create the missing agents:\n" + describeSaveError((e as Error).message));
                return;
            }
        }

        // Re-read nodes: config.id may have just been written onto unbound nodes.
        const payload = buildWorkflowPayload({
            id: currentWorkflowId,
            name: workflowName,
            nodes: useWorkflowStore.getState().nodes,
            edges,
        });

        try {
            const saved = await saveWorkflow({ ...payload, currentId: currentWorkflowId });
            setCurrentWorkflow(saved.id, saved.name);
            alert("Workflow saved to backend successfully.");
        } catch (e) {
            alert("Failed to save workflow:\n" + describeSaveError((e as Error).message));
        }
    };

    const handleLoadWorkflow = async (workflowId: string) => {
        if (!workflowId) return;
        const workflow = savedWorkflows.find((item) => item.id === workflowId);
        if (!workflow) return;

        const { nodes, edges } = workflowToCanvas({
            config: workflow.config,
            agents: savedAgents,
            tools: savedTools,
        });
        loadWorkflow(workflow.id, workflow.name, nodes, edges);
        // An opened graph gets the full width; the palette is one click away.
        useUiStore.getState().setPaletteOpen(false);
        setTimeout(() => fitView(canvasFit(false, 500)), 100);
    };

    const handleValidate = async () => {
        const { currentWorkflowId } = useWorkflowStore.getState();
        if (!currentWorkflowId) {
            alert('Save or load a workflow before validating.');
            return;
        }
        try {
            const result = await validateWorkflow(currentWorkflowId);
            alert(result.valid ? 'Workflow validation passed.' : `Workflow validation failed:\n${JSON.stringify(result.errors, null, 2)}`);
        } catch (e) {
            alert('Validation failed: ' + (e as Error).message);
        }
    };

    const handleExecute = async () => {
        const { currentWorkflowId } = useWorkflowStore.getState();
        if (!currentWorkflowId) {
            alert('Save or load a workflow before executing.');
            return;
        }
        const message = prompt('Input message for this workflow:', 'Hello');
        if (!message) return;
        try {
            const result = await executeWorkflow(currentWorkflowId, message);
            alert(JSON.stringify(result, null, 2));
        } catch (e) {
            alert('Execution failed: ' + (e as Error).message);
        }
    };

    // --- EXPORT: Download workflow as JSON ---
    const handleExport = () => {
        const { nodes, edges } = useWorkflowStore.getState();
        if (!nodes.length) {
            alert("Nothing to export - canvas is empty.");
            return;
        }

        const workflow = {
            name: workflowName,
            version: '1.0',
            exportedAt: new Date().toISOString(),
            nodes,
            edges,
        };

        const blob = new Blob([JSON.stringify(workflow, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${workflowName.replace(/\s+/g, '_')}.workflow.json`;
        a.click();
        URL.revokeObjectURL(url);
    };

    // --- IMPORT: Upload workflow from JSON ---
    const handleImport = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const content = e.target?.result as string;
                const workflow = JSON.parse(content);

                if (!workflow.nodes || !Array.isArray(workflow.nodes)) {
                    throw new Error('Invalid workflow file: missing nodes array');
                }

                const name = workflow.name || 'Imported Workflow';
                loadWorkflow(
                    workflow.id || `imported_${Date.now()}`,
                    name,
                    workflow.nodes,
                    workflow.edges || []
                );

                // An opened graph gets the full width; the palette is one click away.
                useUiStore.getState().setPaletteOpen(false);
                setTimeout(() => fitView(canvasFit(false, 500)), 100);
                alert(`Workflow "${name}" imported successfully!`);
            } catch (err) {
                alert('Failed to import workflow: ' + (err as Error).message);
            }
        };
        reader.readAsText(file);

        // Reset input so same file can be imported again
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    // --- COPY: Copy workflow JSON to clipboard ---
    const handleCopy = async () => {
        const { nodes, edges } = useWorkflowStore.getState();
        if (!nodes.length) {
            alert("Nothing to copy - canvas is empty.");
            return;
        }

        const workflow = {
            name: workflowName,
            version: '1.0',
            nodes,
            edges,
        };

        try {
            await navigator.clipboard.writeText(JSON.stringify(workflow, null, 2));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            alert('Failed to copy to clipboard');
        }
    };

    return (
        <Toolbar
            center={
                <ActivityCapsule
                    editable
                    onNewWorkflow={handleNew}
                    onOpenWorkflow={(id) => void handleLoadWorkflow(id)}
                    statusExpanded={timelineOpen || pane === 'help'}
                    onStatusClick={(hasIssues) => {
                        if (hasIssues) {
                            setTimelineOpen(false);
                            if (pane !== 'help') togglePane('help');
                        } else {
                            setTimelineOpen(!timelineOpen);
                        }
                    }}
                />
            }
            actions={
                <>
                    <button
                        type="button"
                        onClick={() => togglePane('builder')}
                        className="btn btn-toolbar hide-narrow"
                        aria-pressed={pane === 'builder'}
                        title="Builder — describe what you need and it drafts agents, tools and workflows"
                    >
                        <Blocks size={15} strokeWidth={1.8} />
                        <span className="hidden xl:inline">Builder</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => togglePane('help')}
                        className="btn btn-toolbar btn-icon hide-narrow"
                        aria-pressed={pane === 'help'}
                        aria-label="Help"
                        title="Help — check this workflow for problems and learn what each component does"
                    >
                        <LifeBuoy size={16} strokeWidth={1.8} />
                    </button>
                    <div className="toolbar-group liquid" role="group" aria-label="Workflow">
                        <button type="button" onClick={handleSave} disabled={isLoading} className="btn hide-narrow" title="Save to the backend">
                            <Save size={15} strokeWidth={1.8} />
                            <span className="hidden lg:inline">{isLoading ? 'Saving…' : 'Save'}</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => setTestOpen(!testOpen)}
                            className="btn btn-primary"
                            aria-pressed={testOpen}
                            title="Chat with this workflow"
                        >
                            <Play size={12} fill="currentColor" />
                            Test
                        </button>
                    </div>
                    <MoreMenu>
                        {(close) => (
                            <>
                                <MenuItem icon={FilePlus2} onSelect={() => { close(); handleNew(); }}>New workflow</MenuItem>
                                <MenuItem icon={Upload} onSelect={() => { close(); fileInputRef.current?.click(); }}>Import JSON…</MenuItem>
                                <MenuItem icon={Download} onSelect={() => { close(); handleExport(); }}>Export JSON</MenuItem>
                                <MenuItem icon={copied ? Check : Copy} onSelect={() => { void handleCopy(); close(); }}>Copy as JSON</MenuItem>
                                <MenuItem icon={LayoutDashboard} onSelect={() => { close(); handleLayout(); }}>Auto-arrange</MenuItem>
                                <MenuSeparator />
                                <MenuItem icon={ShieldCheck} onSelect={() => { close(); void handleValidate(); }}>Validate saved workflow</MenuItem>
                                <MenuItem icon={Zap} onSelect={() => { close(); void handleExecute(); }}>Run saved workflow…</MenuItem>
                                <MenuSeparator />
                            </>
                        )}
                    </MoreMenu>
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".json,.workflow.json"
                        onChange={handleImport}
                        className="hidden"
                    />
                </>
            }
        />
    );
};

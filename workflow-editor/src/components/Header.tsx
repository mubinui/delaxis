import React, { useState, useCallback, useRef } from 'react';
import { Check, Copy, Download, Home, Layout, Moon, Play, Plus, Rocket, Save, ShieldCheck, Sparkles, Stethoscope, Sun, Upload, Zap } from 'lucide-react';
import { useReactFlow } from '@xyflow/react';
import { useShallow } from 'zustand/react/shallow';
import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { buildWorkflowPayload, getAgentBindings } from '../utils/workflowPayload';
import { describeSaveError } from '../utils/saveErrors';
import { getLayoutedElements } from '../utils/layout';
import { OakLogo } from './OakLogo';
import { useTheme } from '../hooks/useTheme';

const isSelectorTopology = (topology: any) => (
    Boolean(topology?.entry_node)
    && Array.isArray(topology?.domain_agents)
    && topology.domain_agents.length > 0
);

const buildSelectorEdges = (topology: any) => {
    if (!topology?.entry_node) {
        return [];
    }

    const targetIds = Array.isArray(topology.domain_agents) && topology.domain_agents.length > 0
        ? topology.domain_agents.map((agent: any) => agent.id)
        : (topology.nodes ?? [])
            .map((node: any) => node.id)
            .filter((nodeId: string) => nodeId !== topology.entry_node);

    return targetIds
        .filter((targetId: string) => targetId && targetId !== topology.entry_node)
        .map((targetId: string, index: number) => ({
            id: `selector-edge-${index}`,
            source: topology.entry_node,
            target: targetId,
            type: 'smoothstep',
        }));
};

interface HeaderProps {
    onOpenLanding?: () => void;
    onOpenTester?: () => void;
    onOpenDeploy?: () => void;
    builderOpen?: boolean;
    onToggleBuilder?: () => void;
    helpOpen?: boolean;
    onToggleHelp?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenLanding, onOpenTester, onOpenDeploy, builderOpen = false, onToggleBuilder, helpOpen = false, onToggleHelp }) => {
    // Only `workflowName` is actually rendered here — everything else is read fresh via
    // getState() inside handlers so this header doesn't re-render on every node/edge
    // change (e.g. every mousemove frame while dragging a node on the canvas).
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
    const { savedWorkflows, saveWorkflow, validateWorkflow, executeWorkflow, isLoading, fetchLibraryItems } = useLibraryStore();
    const { fitView } = useReactFlow();
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [copied, setCopied] = useState(false);
    const { isDark, toggleTheme } = useTheme();

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
        setTimeout(() => fitView({ padding: 0.2, duration: 800 }), 100);
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

        const topology = workflow.config?.topology ?? {};
        const selectorTopology = isSelectorTopology(topology);
        const visualCanvas = workflow.config?.metadata?.visual_canvas ?? workflow.config;
        const hasVisualCanvas = Array.isArray(visualCanvas.nodes) && visualCanvas.nodes.some((node: any) => node.data);
        const baseWorkflowNodes = hasVisualCanvas
            ? visualCanvas.nodes
            : (topology.nodes ?? []).map((node: any, index: number) => ({
                id: node.id,
                type: 'agent',
                position: node.position ?? { x: 120 + index * 260, y: 180 },
                data: {
                    label: node.agent_id ?? node.id,
                    description: node.description ?? '',
                    config: {
                        id: node.agent_id ?? node.id,
                        agent_id: node.agent_id ?? node.id,
                        is_selector: selectorTopology && node.id === topology.entry_node,
                        ...(node.config ?? {}),
                    },
                },
            }));
        const workflowNodes = selectorTopology
            ? baseWorkflowNodes.map((node: any) => {
                if (node.id !== topology.entry_node) {
                    return node;
                }
                return {
                    ...node,
                    data: {
                        ...node.data,
                        config: {
                            ...(node.data?.config ?? {}),
                            is_selector: true,
                        },
                    },
                };
            })
            : baseWorkflowNodes;
        const topologyEdges = (topology.edges ?? []).map((edge: any, index: number) => ({
                id: edge.id ?? `edge-${index}`,
                source: edge.source ?? edge.from_node,
                target: edge.target ?? edge.to_node,
                type: 'smoothstep',
            }));
        const workflowEdges = Array.isArray(visualCanvas.edges) && visualCanvas.edges.length > 0
            ? visualCanvas.edges
            : topologyEdges.length > 0
                ? topologyEdges
                : selectorTopology
                    ? buildSelectorEdges(topology)
                    : [];

        loadWorkflow(workflow.id, workflow.name, workflowNodes, workflowEdges);
        setTimeout(() => fitView({ padding: 0.2, duration: 500 }), 100);
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

                setTimeout(() => fitView({ padding: 0.2, duration: 500 }), 100);
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

    // One quiet, uniform style for every secondary action — the previous header mixed
    // blue/purple/emerald bold nav buttons with labeled and icon buttons of different
    // sizes, which read as clutter. Icon-only actions carry a title tooltip.
    const iconAction = 'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white transition-colors';
    const navAction = 'flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white transition-colors';

    return (
        <header className="h-14 shrink-0 bg-white dark:bg-[#0b111b] border-b border-[var(--color-ui-border)] flex items-center justify-between gap-3 px-4 z-20 shadow-sm transition-colors">
            {/* Brand + workflow identity */}
            <div className="flex min-w-0 items-center gap-3">
                <OakLogo className="w-8 h-8 rounded-lg shadow-sm shrink-0" />
                <div className="flex min-w-0 flex-col">
                    <div className="flex items-baseline gap-1.5 whitespace-nowrap">
                        <span className="brand-lockup-title">Open Agent Kit</span>
                        <span className="brand-lockup-tagline hidden xl:inline">Agent Studio</span>
                    </div>
                    <input
                        className="w-44 truncate text-sm font-semibold text-gray-900 dark:text-white bg-transparent border-none p-0 focus:ring-0 hover:bg-gray-50 dark:hover:bg-slate-800/50 rounded px-1 -ml-1 transition-colors"
                        value={workflowName}
                        onChange={(e) => setWorkflowName(e.target.value)}
                        title="Workflow name"
                    />
                </div>
            </div>

            {/* Actions */}
            <div className="flex shrink-0 items-center gap-1">
                {/* AI Builder — collapses into this button; opens as a floating window */}
                {onToggleBuilder && (
                    <button
                        onClick={onToggleBuilder}
                        className={`flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-all ${builderOpen
                            ? 'bg-[var(--color-primary)] text-white shadow-sm'
                            : 'border border-blue-500/40 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40'
                            }`}
                        title={builderOpen ? 'Close the AI Builder' : 'Open the AI Builder — generate agents, tools, and workflows'}
                    >
                        <Sparkles size={14} />
                        <span className="hidden md:inline">Builder</span>
                    </button>
                )}

                {/* Help — diagnoses the graph and documents each component */}
                {onToggleHelp && (
                    <button
                        onClick={onToggleHelp}
                        className={`flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-all ${helpOpen
                            ? 'bg-[var(--color-primary)] text-white shadow-sm'
                            : 'border border-slate-300/60 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800'
                            }`}
                        title={helpOpen ? 'Close help' : 'Help — check this workflow for problems and learn what each component does'}
                    >
                        <Stethoscope size={14} />
                        <span className="hidden md:inline">Help</span>
                    </button>
                )}

                <div className="mx-1.5 h-5 w-px bg-gray-200 dark:bg-slate-800" />

                {/* View navigation */}
                {onOpenLanding && (
                    <button onClick={onOpenLanding} className={navAction} title="Return to welcome hub">
                        <Home size={14} />
                        <span className="hidden lg:inline">Hub</span>
                    </button>
                )}
                {onOpenTester && (
                    <button onClick={onOpenTester} className={navAction} title="Open live LLM tester">
                        <Zap size={14} />
                        <span className="hidden lg:inline">Live API</span>
                    </button>
                )}
                {onOpenDeploy && (
                    <button onClick={onOpenDeploy} className={navAction} title="Open deploy hub">
                        <Rocket size={14} />
                        <span className="hidden lg:inline">Deploy</span>
                    </button>
                )}

                <div className="mx-1.5 h-5 w-px bg-gray-200 dark:bg-slate-800" />

                {/* File actions */}
                <button onClick={handleExport} className={iconAction} title="Download workflow as JSON">
                    <Download size={15} />
                </button>
                <button onClick={() => fileInputRef.current?.click()} className={iconAction} title="Import workflow from JSON">
                    <Upload size={15} />
                </button>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json,.workflow.json"
                    onChange={handleImport}
                    className="hidden"
                />
                <button onClick={handleCopy} className={iconAction} title="Copy workflow to clipboard">
                    {copied ? <Check size={15} className="text-emerald-500" /> : <Copy size={15} />}
                </button>
                <button onClick={handleLayout} className={iconAction} title="Auto-arrange layout">
                    <Layout size={15} />
                </button>

                <div className="mx-1.5 h-5 w-px bg-gray-200 dark:bg-slate-800" />

                {/* Workflow lifecycle */}
                <select
                    onFocus={() => fetchLibraryItems()}
                    onChange={(event) => handleLoadWorkflow(event.target.value)}
                    value=""
                    className="hidden md:block h-8 max-w-40 rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-2 text-xs font-medium text-gray-700 dark:text-gray-200 transition-colors"
                    title="Load workflow from backend"
                >
                    <option value="">Load workflow…</option>
                    {savedWorkflows.map((workflow) => (
                        <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
                    ))}
                </select>
                <button onClick={handleValidate} className={iconAction} title="Validate saved workflow">
                    <ShieldCheck size={15} />
                </button>
                <button onClick={handleExecute} className={iconAction} title="Execute saved workflow">
                    <Play size={15} />
                </button>

                <div className="mx-1.5 h-5 w-px bg-gray-200 dark:bg-slate-800" />

                <button onClick={toggleTheme} className={iconAction} title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}>
                    {isDark ? <Sun size={15} /> : <Moon size={15} />}
                </button>
                <button onClick={handleNew} className={navAction} title="Start a new workflow">
                    <Plus size={14} />
                    <span className="hidden lg:inline">New</span>
                </button>
                <button
                    onClick={handleSave}
                    disabled={isLoading}
                    className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--color-primary)] px-3.5 text-xs font-semibold text-white shadow-sm transition-all hover:bg-[var(--color-primary-hover)] disabled:opacity-70 disabled:cursor-not-allowed"
                >
                    <Save size={14} />
                    {isLoading ? 'Saving…' : 'Save'}
                </button>
            </div>
        </header>
    );
};

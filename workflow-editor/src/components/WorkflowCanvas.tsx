
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    ReactFlow,
    Background,
    Controls,
    useReactFlow,
    ConnectionMode,
    ConnectionLineType,
    BackgroundVariant,
    MarkerType,
} from '@xyflow/react';
import type { Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useWorkflowStore } from '../stores/workflowStore';
import { useLibraryStore } from '../stores/libraryStore';
import { useUiStore } from '../stores/uiStore';
import { canvasFit } from '../utils/layout';
import { workflowToCanvas } from '../utils/workflowToCanvas';
import { isValidConnection as isValidConnectionRule } from '../utils/connectionRules';
import type { NodeType } from '../types/workflow';

import { AgentNode } from './nodes/AgentNode';
import { ToolNode } from './nodes/ToolNode';
import { TriggerNode } from './nodes/TriggerNode';
import { RouterNode } from './nodes/RouterNode';
import { OutputNode } from './nodes/OutputNode';
import { WorkflowNode } from './nodes/WorkflowNode';

const nodeTypes = {
    agent: AgentNode,
    tool: ToolNode,
    trigger: TriggerNode,
    router: RouterNode,
    output: OutputNode,
    workflow: WorkflowNode,
};

const WorkflowCanvasContent = () => {
    const reactFlowWrapper = useRef<HTMLDivElement>(null);
    const [dropActive, setDropActive] = useState(false);
    const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode, addNodes, addEdges, setCurrentWorkflow, setNodeDragging } = useWorkflowStore();
    const { savedAgents, savedTools } = useLibraryStore();
    const { screenToFlowPosition, fitView, getViewport, setViewport, getNodesBounds } = useReactFlow();
    const paletteOpen = useUiStore((state) => state.paletteOpen);
    const rightPane = useUiStore((state) => (state.testOpen ? 380 : state.pane === 'builder' ? 400 : state.pane === 'help' ? 380 : 0));



    const fit = useMemo(() => canvasFit(paletteOpen), [paletteOpen]);

    // Wires are neutral grey. The selected component's wires turn ink and the rest
    // step back, so its connections read at a glance.
    const selectedId = useMemo(() => nodes.find((node) => node.selected)?.id, [nodes]);
    const shownEdges = useMemo(() => {
        const decorate = (edge: (typeof edges)[number]) => {
            const attachment = Boolean(edge.targetHandle && edge.sourceHandle === 'attach');
            const touches = selectedId && (edge.source === selectedId || edge.target === selectedId);
            // A run's path stays visible whatever is selected.
            const flow = (edge.data as { flow?: string } | undefined)?.flow;
            const classes = [
                attachment ? 'is-attachment' : '',
                flow ? `is-flow-${flow}` : '',
                selectedId && !flow ? (touches ? 'is-active' : 'is-muted') : '',
            ].filter(Boolean).join(' ');
            return classes ? { ...edge, className: classes } : edge;
        };
        return edges.map(decorate);
    }, [edges, selectedId]);

    // Pan to reveal: when a pane opens on the right, or the inspector opens for a
    // selected component, slide the graph left at the same zoom so the component
    // (or, with nothing selected, the graph) clears it. Never re-zoom: that would
    // shrink the text.
    useEffect(() => {
        const wrapper = reactFlowWrapper.current;
        const graph = useWorkflowStore.getState().nodes;
        const inset = rightPane ? rightPane + 20 : 0;
        const inspector = selectedId ? 372 : 0;
        if ((!inset && !inspector) || !wrapper || graph.length === 0) return;
        const vp = getViewport();
        const target = selectedId ? graph.filter((node) => node.id === selectedId) : graph;
        const bounds = getNodesBounds(target);
        const all = getNodesBounds(graph);
        const right = (bounds.x + bounds.width) * vp.zoom + vp.x;
        const left = all.x * vp.zoom + vp.x;
        const limit = wrapper.clientWidth - inset - inspector - 36;
        if (right <= limit) return;
        // With something selected it must be seen, even if the graph's far left
        // slides out; otherwise keep the graph's left edge on screen.
        const shift = selectedId ? right - limit : Math.min(right - limit, Math.max(0, left - 24));
        if (shift > 0) setViewport({ ...vp, x: vp.x - shift }, { duration: 260 });
    }, [rightPane, selectedId, getViewport, setViewport, getNodesBounds]);


    // --- SMART MERGE: Preserves non-empty values from base when override has empty/null/undefined ---
    const smartMerge = (base: any, override: any): any => {
        const result = { ...base };

        for (const key in override) {
            const overrideVal = override[key];
            const baseVal = base[key];

            // Skip if override value is empty/null/undefined
            if (overrideVal === null || overrideVal === undefined || overrideVal === '') {
                continue;
            }

            // For arrays, only use override if it has items
            if (Array.isArray(overrideVal)) {
                if (overrideVal.length > 0) {
                    result[key] = overrideVal;
                }
                continue;
            }

            // For objects, recursively merge
            if (typeof overrideVal === 'object' && typeof baseVal === 'object' && !Array.isArray(baseVal)) {
                result[key] = smartMerge(baseVal, overrideVal);
                continue;
            }

            // Otherwise, use override value
            result[key] = overrideVal;
        }

        return result;
    };

    // --- DATA NORMALIZATION ---
    const normalizeConfig = (config: any, type: string) => {
        const newConfig = { ...config };

        // Normalize Agent Configs
        if (type === 'agent' || type === 'LlmAgent' || type === 'ReasoningAgent' || type === 'conversable') {
            // 1. Model Config normalization
            // Merge llm_config into model_config if model_config is missing or incomplete
            const existingModelConfig = newConfig.model_config || {};
            const llmConfig = newConfig.llm_config || {};

            // Spread both sources first so settings this function does not know
            // about (max_iter, top_p, seed, …) survive a drop from the library.
            // Listing keys explicitly here silently deleted every field added
            // after this code was written. No api_key: keys belong in the
            // provider secret store, not in node config, where they would also
            // ride along in any payload built from it.
            newConfig.model_config = {
                ...llmConfig,
                ...existingModelConfig,
                provider_id: existingModelConfig.provider_id || llmConfig.provider_id || 'openai',
                model: existingModelConfig.model || llmConfig.model || '',
                base_url: existingModelConfig.base_url || llmConfig.base_url || '',
                temperature: existingModelConfig.temperature ?? llmConfig.temperature ?? 0.7,
                max_tokens: existingModelConfig.max_tokens || llmConfig.max_tokens || 2048,
            };
            delete newConfig.model_config.api_key;

            // If model has provider prefix like "openai/gpt-4o", extract provider
            if (newConfig.model_config.model && newConfig.model_config.model.includes('/')) {
                const [providerFromModel] = newConfig.model_config.model.split('/');
                if (!existingModelConfig.provider_id && !llmConfig.provider_id) {
                    newConfig.model_config.provider_id = providerFromModel;
                }
            }

            // 2. System Message / Instruction sync
            // Always keep both in sync, preferring 'instruction'
            const instruction = newConfig.instruction || newConfig.system_message || '';
            newConfig.instruction = instruction;
            newConfig.system_message = instruction;

            // 3. Ensure tools array exists
            if (!Array.isArray(newConfig.tools)) {
                newConfig.tools = [];
            }

            // 4. Ensure type is set
            if (!newConfig.type) {
                newConfig.type = 'LlmAgent';
            }
        }

        return newConfig;
    };

    // A palette drag gives no feedback about where it can land unless the canvas
    // says so. dragenter/dragleave fire for every child element crossed, so a
    // depth counter is what keeps the highlight from flickering on the way in.
    const dragDepth = useRef(0);

    const onDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
    }, []);

    const onDragEnter = useCallback((event: React.DragEvent) => {
        if (!event.dataTransfer.types.includes('application/reactflow')) return;
        dragDepth.current += 1;
        setDropActive(true);
    }, []);

    const onDragLeave = useCallback(() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDropActive(false);
    }, []);

    const onDrop = useCallback(
        (event: React.DragEvent) => {
            event.preventDefault();
            dragDepth.current = 0;
            setDropActive(false);

            const type = event.dataTransfer.getData('application/reactflow') as NodeType | 'workflow';
            const label = event.dataTransfer.getData('application/reactflow-label');
            const configStr = event.dataTransfer.getData('application/reactflow-config');

            if (typeof type === 'undefined' || !type) {
                return;
            }

            console.log("DROP EVENT:", { type, label, configStr: configStr ? configStr.substring(0, 50) + "..." : "null" });

            const mousePos = screenToFlowPosition({
                x: event.clientX,
                y: event.clientY,
            });

            let config: any = {};
            if (configStr) {
                try {
                    config = JSON.parse(configStr);
                } catch (e) {
                    console.error("Failed to parse dropped config", e);
                }
            }

            // --- Handle Workflow Expansion ---
            // A dropped workflow is built exactly the way opening one builds it:
            // trigger, agents, the tools, memory and knowledge attached to them,
            // and the answer — with each agent's saved configuration resolved.
            // (Expanding only topology.nodes here used to land the agents alone.)
            if (type === 'workflow') {
                const graph = workflowToCanvas({ config, agents: savedAgents, tools: savedTools });
                if (graph.nodes.length === 0) {
                    console.warn('Dropped workflow has no nodes.', config);
                    return;
                }

                // Keep node ids — run data maps back to them — unless they collide
                // with something already on the canvas (the same workflow dropped twice).
                const taken = new Set(useWorkflowStore.getState().nodes.map((node) => node.id));
                const stamp = Date.now().toString(36);
                const idFor = new Map(graph.nodes.map((node) => [node.id, taken.has(node.id) ? `${node.id}-${stamp}` : node.id]));

                // Centre the whole graph on the drop point.
                const xs = graph.nodes.map((node) => node.position?.x ?? 0);
                const ys = graph.nodes.map((node) => node.position?.y ?? 0);
                const centerX = (Math.min(...xs) + Math.max(...xs)) / 2;
                const centerY = (Math.min(...ys) + Math.max(...ys)) / 2;

                const placedNodes = graph.nodes.map((node) => ({
                    ...node,
                    id: idFor.get(node.id) ?? node.id,
                    position: {
                        x: (node.position?.x ?? 0) - centerX + mousePos.x,
                        y: (node.position?.y ?? 0) - centerY + mousePos.y,
                    },
                    selected: false,
                }));
                const placedEdges = graph.edges.map((edge) => ({
                    ...edge,
                    id: taken.size ? `${edge.id}-${stamp}` : edge.id,
                    source: idFor.get(edge.source) ?? edge.source,
                    target: idFor.get(edge.target) ?? edge.target,
                }));

                addNodes(placedNodes);
                // Edges need their nodes measured first, or React Flow drops them.
                if (placedEdges.length > 0) setTimeout(() => addEdges(placedEdges), 50);

                // Frame everything that is now on the canvas.
                setTimeout(() => fitView({ ...fit, duration: 300 }), 140);

                const workflowId = config.id || config.workflow_id || label || 'canvas_workflow';
                setCurrentWorkflow(workflowId, config.name || label);
                return;
            }

            // --- Handle Single Node Drop ---
            // @ts-ignore - type checking for keys
            const nodeType = nodeTypes[type] ? type : 'default';

            // For agents and tools, look up full config from library
            let fullConfig = { ...config };

            if (type === 'agent' || nodeType === 'agent') {
                // Check if we need to look up from library (if config seems empty or is a reference)
                const agentId = config.id || config.agent_id || config.name || label;
                const libraryAgent = savedAgents.find((a: any) =>
                    a.id === agentId || a.name === agentId || a.config?.id === agentId || a.config?.name === agentId
                );

                if (libraryAgent?.config) {
                    console.log("Found library agent for drop:", libraryAgent.name, libraryAgent.config);
                    // Start with library config, then apply any overrides from drag data
                    fullConfig = smartMerge(libraryAgent.config, config);
                }
            } else if (type === 'tool' || nodeType === 'tool') {
                const toolId = config.id || config.tool_id || config.name || label;
                const libraryTool = savedTools.find((t: any) =>
                    t.id === toolId || t.name === toolId || t.config?.id === toolId || t.config?.name === toolId
                );

                if (libraryTool?.config) {
                    console.log("Found library tool for drop:", libraryTool.name);
                    fullConfig = smartMerge(libraryTool.config, config);
                }
            }

            // Normalize single node config
            const normalizedConfig = normalizeConfig(fullConfig, nodeType);

            const newNode: Node = {
                id: `${type}-${Date.now()}`,
                type: nodeType,
                position: mousePos,
                data: {
                    label: label || normalizedConfig.name || 'Untitled',
                    config: normalizedConfig
                },
            };

            addNode(newNode as any);
        },
        [screenToFlowPosition, fitView, fit, addNode, savedAgents, savedTools]
    );

    // Typed aux handles: only matching tool kinds may land on an agent's
    // tools/memory/knowledge handle; flow connections stay unrestricted.
    const isValidConnection = useCallback(
        (connection: Parameters<typeof isValidConnectionRule>[0]) =>
            isValidConnectionRule(connection, useWorkflowStore.getState().nodes),
        [],
    );

    return (
        <div
            className={`relative h-full w-full ${dropActive ? 'dlx-canvas-dropping' : ''}`}
            style={{ background: 'var(--window)' }}
            ref={reactFlowWrapper}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
        >
            <ReactFlow
                nodes={nodes}
                edges={shownEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                isValidConnection={isValidConnection}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onNodeDragStart={() => setNodeDragging(true)}
                onNodeDragStop={() => setNodeDragging(false)}
                onSelectionDragStart={() => setNodeDragging(true)}
                onSelectionDragStop={() => setNodeDragging(false)}
                nodeTypes={nodeTypes as any}
                fitView
                fitViewOptions={fit}
                minZoom={0.2}
                // animated:false — permanently marching dashes on every edge repaint the
                // canvas nonstop; edges animate only during live execution (set by the store).
                // The stroke is deliberately NOT set here: the stylesheet owns it
                // (.react-flow__edge-path), so edges repaint when the theme changes.
                defaultEdgeOptions={{
                    // Flow wires curve the way n8n draws them; attachments stay straight and dashed.
                    type: 'default',
                    animated: false,
                    style: { strokeWidth: 1.5 },
                    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: 'var(--wire)' },
                } as any}
                // Strict: the drag preview only snaps to valid target handles, so the
                // edge always lands exactly where the preview showed it.
                connectionMode={ConnectionMode.Strict}
                connectionLineType={ConnectionLineType.Bezier}
                // Generous magnet radius so a dropped connection snaps to a nearby handle
                // instead of demanding a pixel-perfect hit on a 10px dot.
                connectionRadius={36}
                // Dragging is free-form (no 15px snap jumps); use Auto-arrange for tidy layout.
                selectNodesOnDrag={false}
                proOptions={{ hideAttribution: true }}
            >
                <Background color="var(--grid-dot)" gap={22} size={1.3} variant={BackgroundVariant.Dots} />
                <Controls
                    showInteractive={false}
                    position="bottom-left"
                    style={{ marginLeft: paletteOpen ? 262 : 12, transition: 'margin-left .24s var(--ease-out)' }}
                />
            </ReactFlow>


            {nodes.length > 0 && !selectedId && (
                <div className="canvas-legend liquid hide-narrow" style={{ right: 14, bottom: 14 }}>
                    <span><i />Flow</span>
                    <span><i className="is-dashed" />Attachment</span>
                    <span className="legend-hint">Click a component to configure it</span>
                </div>
            )}

            {nodes.length === 0 && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center" style={{ paddingLeft: paletteOpen ? 250 : 0 }}>
                    <div className="empty-state max-w-sm">
                        <div className="headline text-[15px]">Start with a trigger</div>
                        <p className="hint">Drag Chat or Manual from the components onto the canvas, add an agent, and connect them. Or open a saved workflow from the name at the top.</p>
                    </div>
                </div>
            )}
        </div>
    );
};

export const WorkflowCanvas = () => (
    <div className="absolute inset-0">
        <WorkflowCanvasContent />
    </div>
);


import React, { useCallback, useRef, useState } from 'react';
import {
    ReactFlow,
    Background,
    Controls,
    MiniMap,
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
import { getLayoutedElements, positionsAreDegenerate } from '../utils/layout';
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
    const { screenToFlowPosition, fitView } = useReactFlow();

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
            if (type === 'workflow') {
                // Check for topology in config (handle various structures)
                const topology = config.topology || config;
                const isSelectorWorkflow = Boolean(
                    topology.entry_node
                    && Array.isArray(topology.domain_agents)
                    && topology.domain_agents.length > 0
                );
                const workflowNodes = topology.nodes || config.nodes || [];
                const workflowEdges = topology.edges || config.edges || [];

                if (workflowNodes.length === 0) {
                    console.warn("Dropped workflow has no nodes.", config);
                    return;
                }

                console.log("Processing Workflow Drop:", {
                    nodeCount: workflowNodes.length,
                    edgeCount: workflowEdges.length,
                    sampleNode: workflowNodes[0]
                });

                // Calculate Center of Mass of dropped workflow to center it on mouse
                const xs = workflowNodes.map((n: any) => n.position?.x || 0);
                const ys = workflowNodes.map((n: any) => n.position?.y || 0);
                const minX = Math.min(...xs), maxX = Math.max(...xs);
                const minY = Math.min(...ys), maxY = Math.max(...ys);

                const width = maxX - minX;
                const height = maxY - minY;
                const centerX = minX + width / 2;
                const centerY = minY + height / 2;

                const idMap = new Map<string, string>();

                const newNodes = workflowNodes.map((n: any) => {
                    // Library nodes carry agent_id instead of a top-level type; without
                    // this fallback the id comes out as "undefined-<timestamp>-<rand>".
                    const idPrefix = n.type || (n.agent_id ? 'agent' : 'node');
                    const newId = `${idPrefix}-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
                    idMap.set(n.id, newId);

                    // Position relative to the center of the workflow, applied to the mouse position
                    const relativeX = (n.position?.x || 0) - centerX;
                    const relativeY = (n.position?.y || 0) - centerY;

                    // Normalize type for frontend
                    let nodeType = 'default';
                    const rawType = n.type || (n.agent_id ? 'agent' : 'default'); // Infer agent if agent_id exists

                    // robust type checking
                    if (['LlmAgent', 'ReasoningAgent', 'SequentialAgent', 'ParallelAgent', 'RecursiveAgent', 'conversable', 'agent'].includes(rawType) || (typeof rawType === 'string' && rawType.toLowerCase().includes('agent'))) {
                        nodeType = 'agent';
                    } else if ((typeof rawType === 'string' && rawType.toLowerCase().includes('tool')) || n.tool) {
                        nodeType = 'tool';
                    } else if (typeof rawType === 'string' && (rawType.toLowerCase() === 'userproxy' || rawType.toLowerCase() === 'trigger')) {
                        nodeType = 'trigger';
                    } else if (typeof rawType === 'string' && (rawType.toLowerCase() === 'router' || rawType.toLowerCase() === 'selector')) {
                        nodeType = 'router';
                    } else if (nodeTypes[rawType as NodeType]) {
                        nodeType = rawType; // It's already valid (e.g. 'agent')
                    }

                    // Ensure label
                    const label = n.data?.label || n.label || n.name || n.config?.name || n.agent_id || 'Untitled Node';

                    // --- Resolve Config from Library ---
                    // If this node references a stored agent/tool, we must fetch its latest config
                    let resolvedConfig: any = {};
                    let libraryAgent: any = null;

                    if (nodeType === 'agent' && n.agent_id) {
                        libraryAgent = savedAgents.find((a: any) => a.id === n.agent_id || a.name === n.agent_id || a.config?.id === n.agent_id);
                        if (libraryAgent) {
                            resolvedConfig = { ...libraryAgent.config };
                            console.log(`Found library agent for ${n.agent_id}:`, libraryAgent.name);
                        } else {
                            console.warn(`Could not find library agent for ${n.agent_id}`);
                        }
                    } else if (nodeType === 'tool') {
                        // Heuristic for tool ID
                        const toolId = n.tool_id || n.tool || n.id;
                        const foundTool = savedTools.find((t: any) => t.id === toolId || t.name === toolId || t.config?.id === toolId);
                        if (foundTool) {
                            resolvedConfig = { ...foundTool.config };
                        }
                    }

                    // Use smartMerge to properly combine library config with any instance overrides
                    // This preserves non-empty values from library when instance config has empty values
                    const instanceConfig = n.data?.config || n.config || {};
                    const rawConfig = smartMerge(resolvedConfig, instanceConfig);

                    // Ensure critical identity fields
                    rawConfig.name = rawConfig.name || instanceConfig.name || resolvedConfig.name || label;
                    rawConfig.type = rawConfig.type || instanceConfig.type || resolvedConfig.type || (nodeType === 'agent' ? 'LlmAgent' : nodeType);

                    // Normalize Tools: PropertiesPanel expects Names, but storage might have IDs
                    if (rawConfig.tools && Array.isArray(rawConfig.tools)) {
                        rawConfig.tools = rawConfig.tools.map((t: string) => {
                            const foundTool = savedTools.find((st: any) => st.id === t || st.name === t || st.config?.id === t);
                            return foundTool ? foundTool.name : t;
                        });
                    }

                    // Validate & Normalize Config
                    const normalizedConfig = normalizeConfig(rawConfig, nodeType);
                    if (isSelectorWorkflow && n.id === topology.entry_node) {
                        normalizedConfig.is_selector = true;
                    }

                    return {
                        ...n,
                        id: newId,
                        type: nodeType, // Enforce normalized type
                        position: {
                            x: mousePos.x + relativeX,
                            y: mousePos.y + relativeY,
                        },
                        data: {
                            ...n.data,
                            label: label,
                            config: normalizedConfig,
                            // Store original agent reference for debugging
                            agent_id: n.agent_id,
                            library_agent_name: libraryAgent?.name
                        },
                        selected: false
                    };
                });

                if (workflowEdges.length === 0 && isSelectorWorkflow && topology.entry_node) {
                    const entryNodeId = idMap.get(topology.entry_node); // Get new ID of entry node
                    const selectorTargets = Array.isArray(topology.domain_agents) && topology.domain_agents.length > 0
                        ? topology.domain_agents.map((agent: any) => agent.id)
                        : Array.from(idMap.keys()).filter((nodeId) => nodeId !== topology.entry_node);
                    if (entryNodeId) {
                        selectorTargets.forEach((targetNodeId: string) => {
                            if (targetNodeId !== topology.entry_node) {
                                workflowEdges.push({
                                    id: `auto-edge-${Date.now()}-${Math.random()}`,
                                    source: topology.entry_node, // Original ID, will be mapped below
                                    target: targetNodeId,
                                    type: 'smoothstep'
                                });
                            }
                        });
                        console.log("Auto-generated edges for selector pattern", workflowEdges.length);
                    }
                }

                const newEdges = workflowEdges.map((e: any) => ({
                    ...e,
                    id: `e-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
                    source: idMap.get(e.source) || e.source,
                    target: idMap.get(e.target) || e.target,
                }));

                // Workflows stored as bare topology often carry no positions, which
                // used to drop every node onto one stacked point until the user hit
                // Format. Auto-layout those, re-centered on the drop point.
                let placedNodes = newNodes;
                if (positionsAreDegenerate(workflowNodes.map((n: any) => n.position))) {
                    const { nodes: layouted } = getLayoutedElements(newNodes, newEdges);
                    const lxs = layouted.map((n) => n.position.x);
                    const lys = layouted.map((n) => n.position.y);
                    const layoutCenterX = (Math.min(...lxs) + Math.max(...lxs)) / 2;
                    const layoutCenterY = (Math.min(...lys) + Math.max(...lys)) / 2;
                    placedNodes = layouted.map((n) => ({
                        ...n,
                        position: {
                            x: n.position.x - layoutCenterX + mousePos.x,
                            y: n.position.y - layoutCenterY + mousePos.y,
                        },
                    }));
                }

                // Bulk add nodes and edges
                addNodes(placedNodes);

                if (newEdges.length > 0) {
                    setTimeout(() => addEdges(newEdges), 50);
                }

                // Frame the dropped workflow at a sane zoom instead of leaving
                // oversized nodes filling the viewport.
                setTimeout(() => fitView({ padding: 0.25, duration: 300 }), 120);

                // Set current workflow ID for testing (n8n-style)
                // Try to extract workflow ID from dropped config
                const workflowId = config.id || config.workflow_id || label || 'canvas_workflow';
                setCurrentWorkflow(workflowId, label);

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
        [screenToFlowPosition, fitView, addNode, savedAgents, savedTools]
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
            className={`relative flex-grow h-full bg-[var(--canvas-bg)] ${dropActive ? 'dlx-canvas-dropping' : ''}`}
            ref={reactFlowWrapper}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
        >
            <ReactFlow
                nodes={nodes}
                edges={edges}
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
                fitViewOptions={{ padding: 0.2 }}
                // animated:false — permanently marching dashes on every edge repaint the
                // canvas nonstop; edges animate only during live execution (set by the store).
                // The stroke is deliberately NOT set here. defaultEdgeOptions are
                // copied into each edge's data at creation, so a literal colour
                // would be frozen at whatever the theme was when the edge was
                // drawn — an edge made in light mode stayed light forever after
                // switching to dark. The stylesheet owns the stroke instead
                // (.react-flow__edge-path), which repaints with the theme.
                defaultEdgeOptions={{
                    type: 'smoothstep',
                    animated: false,
                    style: { strokeWidth: 2 },
                    markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--canvas-edge)' },
                }}
                // Strict: the drag preview only snaps to valid target handles, so the
                // edge always lands exactly where the preview showed it.
                connectionMode={ConnectionMode.Strict}
                connectionLineType={ConnectionLineType.SmoothStep}
                // Generous magnet radius so a dropped connection snaps to a nearby handle
                // instead of demanding a pixel-perfect hit on a 10px dot.
                connectionRadius={36}
                // Dragging is free-form (no 15px snap jumps); use the Format button for tidy layout.
                selectNodesOnDrag={false}
                proOptions={{ hideAttribution: true }}
            >
                <Background
                    color="var(--canvas-dots)"
                    gap={20}
                    size={2}
                    variant={BackgroundVariant.Dots}
                />
                <Controls showInteractive={false} position="bottom-left" className="!bg-[var(--color-ui-bg)] !border-[var(--color-ui-border)] !shadow-lg" />
                {/* Top-right keeps it clear of the chat button (bottom-right) and the
                    controls/timeline (bottom-left); hidden entirely on an empty canvas
                    where it would just render as a blank rectangle. */}
                {nodes.length > 0 && (
                    <MiniMap
                        position="top-right"
                        nodeColor={() => 'var(--minimap-node)'}
                        maskColor="var(--minimap-mask)"
                        className="!bg-[var(--surface-1)] !border-[var(--border-default)] !shadow-lg"
                    />
                )}
            </ReactFlow>
        </div>
    );
};

export const WorkflowCanvas = () => {
    return (
        <div className="flex flex-col h-full bg-[var(--color-canvas-bg)] relative">
            <div className="flex-grow relative">
                <WorkflowCanvasContent />
            </div>
        </div>
    );
};

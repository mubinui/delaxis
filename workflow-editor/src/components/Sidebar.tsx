
import React, { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Bot, Wrench, Play, GitBranch, Square, MessageSquare, Link, Settings, Plus, Brain, FileSearch, ShieldCheck, ListChecks, FolderOpen, X, Server, Database, Mail } from 'lucide-react';
import type { NodeType } from '../types/workflow';
import { useLibraryStore } from '../stores/libraryStore';
import { useLibraryModal } from '../App';
import { ResourceCard } from './studio/ResourceCard';
import { getAgentSummary, getToolSummary, getWorkflowSummary } from '../utils/studioDerivedState';

type PaletteTone = 'agent' | 'tool' | 'workflow' | 'trigger' | 'logic' | 'output';

interface PaletteItem {
    type: NodeType;
    label: string;
    icon: LucideIcon;
    tone: PaletteTone;
    config: Record<string, any>;
}

// The base component palette, grouped for the icon rail. Each tile is a draggable
// tone-colored icon; configuration happens after dropping, in the inspector.
const PALETTE_GROUPS: { id: string; items: PaletteItem[] }[] = [
    {
        id: 'triggers',
        items: [
            { type: 'trigger', label: 'Manual Trigger', icon: Play, tone: 'trigger', config: { trigger_type: 'manual', label: 'Start' } },
            { type: 'trigger', label: 'Chat Trigger', icon: MessageSquare, tone: 'trigger', config: { trigger_type: 'chat', label: 'On Chat' } },
            { type: 'trigger', label: 'Webhook', icon: Link, tone: 'trigger', config: { trigger_type: 'webhook', label: 'Webhook' } },
        ],
    },
    {
        id: 'agents',
        items: [
            { type: 'agent', label: 'CrewAI Agent', icon: Bot, tone: 'agent', config: { type: 'LlmAgent', role: '', goal: '', backstory: '', tools: [] } },
            { type: 'agent', label: 'CrewAI Task', icon: ListChecks, tone: 'agent', config: { type: 'LlmAgent', task: 'Describe the task objective', expected_output: 'Structured task result' } },
        ],
    },
    {
        id: 'logic',
        items: [
            { type: 'router', label: 'Flow Router', icon: GitBranch, tone: 'logic', config: { type: 'router', routing_mode: 'conditional' } },
            { type: 'tool', label: 'Memory Store', icon: Brain, tone: 'tool', config: { type: 'memory', memory_enabled: true, retention: 'session' } },
            { type: 'tool', label: 'Knowledge Source', icon: FileSearch, tone: 'tool', config: { type: 'knowledge', knowledge_enabled: true, top_k: 5 } },
            { type: 'router', label: 'Guardrail', icon: ShieldCheck, tone: 'logic', config: { type: 'guardrail', guardrails_enabled: true, output_schema: 'text' } },
        ],
    },
    {
        id: 'integrations',
        items: [
            { type: 'tool', label: 'MCP Server', icon: Server, tone: 'tool', config: { type: 'mcp', transport: 'stdio', command: '', args: [], tool_filter: [] } },
            { type: 'tool', label: 'Database', icon: Database, tone: 'tool', config: { type: 'database', db_uri_env_var: '', allow_dml: false } },
            { type: 'tool', label: 'Gmail', icon: Mail, tone: 'tool', config: { type: 'gmail', account_email: '', capabilities: ['send', 'search', 'read'], max_results: 10 } },
        ],
    },
    {
        id: 'output',
        items: [
            { type: 'output', label: 'Output', icon: Square, tone: 'output', config: { type: 'output' } },
        ],
    },
];

// --- Library flyout item (draggable card with nesting) ---
interface SidebarItemProps {
    type: NodeType;
    label: string;
    icon: LucideIcon;
    tone: PaletteTone;
    config?: any;
    description?: string;
    children?: React.ReactNode;
    level?: number;
}

const SidebarItem: React.FC<SidebarItemProps> = ({
    type,
    label,
    icon,
    tone,
    config,
    description,
    children,
    level = 0
}) => {
    const [isOpen, setIsOpen] = useState(false);
    const hasChildren = React.Children.count(children) > 0;
    const showChildren = isOpen && hasChildren;

    const agentSummary = type === 'agent' ? getAgentSummary(config) : null;
    const toolSummary = type === 'tool' ? getToolSummary(config) : null;
    const workflowSummary = type === 'workflow' ? getWorkflowSummary(config) : null;
    const badges = [
        agentSummary ? { label: agentSummary.model, tone: agentSummary.health } : null,
        agentSummary ? { label: `${agentSummary.toolCount} tools`, tone: agentSummary.toolCount > 0 ? 'ready' as const : 'muted' as const } : null,
        toolSummary ? { label: toolSummary.type === 'api' ? toolSummary.method : 'function', tone: toolSummary.health } : null,
        toolSummary ? { label: toolSummary.auth === 'none' ? 'no auth' : toolSummary.auth, tone: toolSummary.auth === 'none' ? 'muted' as const : 'warning' as const } : null,
        workflowSummary ? { label: workflowSummary.pattern, tone: workflowSummary.health } : null,
        workflowSummary ? { label: `${workflowSummary.nodeCount} nodes`, tone: 'muted' as const } : null,
    ].filter(Boolean) as Array<{ label: string; tone: 'ready' | 'warning' | 'error' | 'running' | 'muted' }>;

    return (
        <div className="select-none">
            <ResourceCard
                type={type}
                label={label}
                icon={icon}
                tone={tone}
                config={config}
                description={description}
                collapsed={false}
                level={level}
                expandable={hasChildren}
                expanded={isOpen}
                onToggle={() => setIsOpen(!isOpen)}
                badges={badges}
                compact
            />

            {showChildren && (
                <div className="border-l border-gray-100 dark:border-slate-800 ml-[22px] pl-1 relative">
                    {children}
                </div>
            )}
        </div>
    );
};


export const Sidebar = () => {
    const { savedAgents, savedTools, savedWorkflows, fetchLibraryItems } = useLibraryStore();
    const { openLibraryModal } = useLibraryModal();
    const [libraryOpen, setLibraryOpen] = useState(false);

    useEffect(() => {
        fetchLibraryItems();
    }, []);

    const savedCount = savedWorkflows.length + savedAgents.length + savedTools.length;

    // --- Helpers to resolve nested references for the library flyout ---
    const findAgentById = (id: string) => savedAgents.find(a => a.id === id || a.name === id || a.config?.id === id);
    const findToolById = (id: string) => savedTools.find(t => t.id === id || t.name === id || t.config?.id === id);

    const renderAgentTools = (agentConfig: any) => {
        if (!agentConfig?.tools || !Array.isArray(agentConfig.tools)) return null;

        return agentConfig.tools.map((toolRef: string) => {
            const tool = findToolById(toolRef);
            const toolName = tool ? tool.name : toolRef;
            const toolConfig = tool ? tool.config : {};

            return (
                <SidebarItem
                    key={toolRef}
                    type="tool"
                    label={toolName}
                    icon={Wrench}
                    tone="tool"
                    level={2}
                    config={toolConfig}
                />
            );
        });
    };

    const renderWorkflowAgents = (workflow: any) => {
        const nodes = workflow.config?.topology?.nodes || [];
        return nodes.map((node: any) => {
            const agentId = node.agent_id || node.id;
            const agent = findAgentById(agentId);
            const label = agent ? agent.name : (node.name || agentId);
            const config = agent ? agent.config : {};
            const desc = node.description || (agent ? agent.description : '');

            return (
                <SidebarItem
                    key={node.id}
                    type="agent"
                    label={label}
                    icon={Bot}
                    tone="agent"
                    description={desc}
                    level={1}
                    config={config}
                >
                    {renderAgentTools(config)}
                </SidebarItem>
            );
        });
    };

    const flyoutSectionHeader = (label: string, icon: React.ReactNode, manageTab?: 'agents' | 'tools') => (
        <div className="text-[11px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2 pl-1 flex items-center justify-between pr-1">
            <span className="flex items-center gap-1.5">{icon} {label}</span>
            {manageTab && (
                <button
                    onClick={() => openLibraryModal(manageTab)}
                    className="p-1 hover:bg-gray-200 dark:hover:bg-slate-800 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
                    title={`Manage ${label}`}
                >
                    <Settings size={12} />
                </button>
            )}
        </div>
    );

    return (
        <div className="relative z-20 flex h-full shrink-0">
            {/* Icon rail — the whole component palette in 76px */}
            <aside className="flex h-full w-[76px] shrink-0 flex-col items-center gap-0.5 overflow-y-auto border-r border-[var(--color-ui-border)] bg-white dark:bg-[#0b111b] py-3">
                {PALETTE_GROUPS.map((group, groupIndex) => (
                    <React.Fragment key={group.id}>
                        {groupIndex > 0 && <div className="my-1.5 h-px w-10 shrink-0 bg-gray-200 dark:bg-slate-800" />}
                        {group.items.map((item) => (
                            <ResourceCard
                                key={item.label}
                                type={item.type}
                                label={item.label}
                                icon={item.icon}
                                tone={item.tone}
                                config={item.config}
                                collapsed
                            />
                        ))}
                        {/* Creating a tool is the natural next step after placing an
                            agent/task, so the action sits with them rather than at
                            the far bottom of the rail. */}
                        {group.id === 'agents' && (
                            <button
                                onClick={() => openLibraryModal('tools')}
                                title="Create a new tool"
                                className="flex w-16 shrink-0 flex-col items-center gap-1 rounded-lg py-1.5 transition-all duration-150 hover:bg-gray-50 dark:hover:bg-slate-900"
                            >
                                <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-dashed border-orange-300 dark:border-orange-500/40 text-orange-500 dark:text-orange-400 transition-all duration-150 hover:border-orange-400 hover:bg-orange-50 dark:hover:bg-orange-950/30">
                                    <Plus size={15} strokeWidth={2.5} />
                                </span>
                                <span className="text-[9px] font-medium leading-none text-gray-500 dark:text-slate-400">New Tool</span>
                            </button>
                        )}
                    </React.Fragment>
                ))}

                {/* Library, pinned to the bottom */}
                <div className="mt-auto flex shrink-0 flex-col items-center gap-1 pt-2">
                    <div className="mb-1 h-px w-10 bg-gray-200 dark:bg-slate-800" />
                    <button
                        onClick={() => setLibraryOpen((open) => !open)}
                        title="Saved library — workflows, agents, tools"
                        className="flex w-16 flex-col items-center gap-1 rounded-lg py-1.5 transition-all duration-150 hover:bg-gray-50 dark:hover:bg-slate-900"
                    >
                        <span className={`relative flex h-9 w-9 items-center justify-center rounded-xl border transition-all duration-150 ${libraryOpen
                            ? 'border-[var(--color-primary)] bg-[var(--color-primary)] text-white shadow-md'
                            : 'border-[var(--color-ui-border)] text-gray-500 dark:text-slate-400'
                            }`}>
                            <FolderOpen size={15} />
                            {savedCount > 0 && !libraryOpen && (
                                <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--color-primary)] px-0.5 text-[9px] font-bold text-white">
                                    {savedCount}
                                </span>
                            )}
                        </span>
                        <span className="text-[9px] font-medium leading-none text-gray-500 dark:text-slate-400">Library</span>
                    </button>
                </div>
            </aside>

            {/* Library flyout — overlays the canvas on demand instead of consuming layout width */}
            {libraryOpen && (
                <div className="absolute bottom-0 left-[76px] top-0 z-30 flex w-[300px] flex-col border-r border-[var(--color-ui-border)] bg-white/95 dark:bg-[#0b111b]/95 shadow-2xl backdrop-blur-xl animate-in fade-in slide-in-from-left-2 duration-150">
                    <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-ui-border)] px-4 py-3">
                        <div>
                            <div className="text-sm font-bold ag-text">Library</div>
                            <div className="text-[11px] ag-muted">
                                {savedWorkflows.length} workflows · {savedAgents.length} agents · {savedTools.length} tools
                            </div>
                        </div>
                        <button
                            onClick={() => setLibraryOpen(false)}
                            className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-slate-800 dark:hover:text-gray-200"
                            title="Close library"
                        >
                            <X size={15} />
                        </button>
                    </div>

                    <div className="custom-scrollbar min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
                        {savedCount === 0 && (
                            <div className="rounded-xl border border-dashed border-[var(--color-ui-border)] p-4 text-center text-xs ag-muted">
                                Nothing saved yet. Build on the canvas and hit Save, or let the Builder generate a workflow for you.
                            </div>
                        )}

                        {savedWorkflows.length > 0 && (
                            <div className="space-y-1.5">
                                {flyoutSectionHeader('Workflows', <GitBranch size={10} />)}
                                {savedWorkflows.map(w => (
                                    <SidebarItem
                                        key={w.id}
                                        type="workflow"
                                        label={w.name}
                                        icon={GitBranch}
                                        tone="workflow"
                                        config={w.config}
                                        description={w.description}
                                    >
                                        {renderWorkflowAgents(w)}
                                    </SidebarItem>
                                ))}
                            </div>
                        )}

                        {savedAgents.length > 0 && (
                            <div className="space-y-1.5">
                                {flyoutSectionHeader('Agents', <Bot size={10} />, 'agents')}
                                {savedAgents.map(a => (
                                    <SidebarItem
                                        key={a.id}
                                        type="agent"
                                        label={a.name}
                                        icon={Bot}
                                        tone="agent"
                                        config={a.config}
                                        description={a.description}
                                    >
                                        {renderAgentTools(a.config)}
                                    </SidebarItem>
                                ))}
                            </div>
                        )}

                        {savedTools.length > 0 && (
                            <div className="space-y-1.5">
                                {flyoutSectionHeader('Tools', <Wrench size={10} />, 'tools')}
                                {savedTools.map(t => (
                                    <SidebarItem
                                        key={t.id}
                                        type="tool"
                                        label={t.name}
                                        icon={Wrench}
                                        tone="tool"
                                        config={t.config}
                                        description={t.description}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

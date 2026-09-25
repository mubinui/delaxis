import React, { useEffect, useMemo, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    Bot, Wrench, Play, GitBranch, Flag, MessageSquare, Link, Settings, Plus, Brain,
    FileSearch, ShieldCheck, ListChecks, FolderOpen, X, Server, Database, Mail, Search,
    FileUp, ScanEye, ScrollText, Network, EyeOff,
} from 'lucide-react';
import type { NodeType } from '../types/workflow';
import { useLibraryStore } from '../stores/libraryStore';
import { useLibraryModal } from '../App';
import { useUiStore } from '../stores/uiStore';
import { ResourceCard } from './studio/ResourceCard';
import type { ResourceTone } from './studio/ResourceCard';
import { getAgentSummary, getToolSummary, getWorkflowSummary } from '../utils/studioDerivedState';

interface PaletteItem {
    type: NodeType;
    label: string;
    icon: LucideIcon;
    tone: ResourceTone;
    /** Shown in the tile tooltip and matched by palette search. */
    hint: string;
    config: Record<string, any>;
}

interface PaletteGroup {
    id: string;
    /** Rendered above the group in the rail, so the palette has structure at a glance. */
    label: string;
    items: PaletteItem[];
}

// The base component palette. Each tile is a draggable tone-coloured glyph;
// configuration happens after dropping, in the inspector.
const PALETTE_GROUPS: PaletteGroup[] = [
    {
        id: 'triggers',
        label: 'Start',
        items: [
            { type: 'trigger', label: 'Manual', icon: Play, tone: 'trigger', hint: 'Run the workflow on demand', config: { trigger_type: 'manual', label: 'Start' } },
            { type: 'trigger', label: 'Chat', icon: MessageSquare, tone: 'trigger', hint: 'Start when a user sends a message', config: { trigger_type: 'chat', label: 'On Chat' } },
            { type: 'trigger', label: 'Webhook', icon: Link, tone: 'trigger', hint: 'Start from an inbound HTTP call', config: { trigger_type: 'webhook', label: 'Webhook' } },
        ],
    },
    {
        id: 'agents',
        label: 'Agents',
        items: [
            { type: 'agent', label: 'Agent', icon: Bot, tone: 'agent', hint: 'A CrewAI agent with a role, goal, and tools', config: { type: 'LlmAgent', role: '', goal: '', backstory: '', tools: [] } },
            { type: 'agent', label: 'Task', icon: ListChecks, tone: 'agent', hint: 'A discrete task with an expected output', config: { type: 'LlmAgent', task: 'Describe the task objective', expected_output: 'Structured task result' } },
        ],
    },
    {
        id: 'logic',
        label: 'Logic',
        items: [
            { type: 'router', label: 'Router', icon: GitBranch, tone: 'logic', hint: 'Branch the flow on a condition', config: { type: 'router', routing_mode: 'conditional' } },
            { type: 'tool', label: 'Memory', icon: Brain, tone: 'logic', hint: 'Persist state across turns', config: { type: 'memory', memory_enabled: true, retention: 'session' } },
            { type: 'tool', label: 'Knowledge', icon: FileSearch, tone: 'logic', hint: 'Retrieve from a knowledge source', config: { type: 'knowledge', knowledge_enabled: true, top_k: 5 } },
            { type: 'router', label: 'Guardrail', icon: ShieldCheck, tone: 'logic', hint: 'Validate output before it continues', config: { type: 'guardrail', guardrails_enabled: true, output_schema: 'text' } },
        ],
    },
    {
        id: 'data',
        label: 'Data',
        items: [
            { type: 'tool', label: 'SQL', icon: Database, tone: 'data', hint: 'Query a database with schema introspection, read-only by default', config: { type: 'sql', db_uri_env_var: '', allow_writes: false, max_rows: 200 } },
            { type: 'tool', label: 'NL2SQL', icon: Database, tone: 'data', hint: 'Let the model write SQL from a plain-language question', config: { type: 'database', db_uri_env_var: '', allow_dml: false } },
            { type: 'tool', label: 'MongoDB', icon: Database, tone: 'data', hint: 'List, sample, and query MongoDB collections', config: { type: 'mongodb', uri_env_var: '', database: '', collections: [] } },
            { type: 'tool', label: 'Files', icon: FileUp, tone: 'data', hint: 'Analyse uploaded documents, spreadsheets, and images', config: { type: 'function', tool_ids: ['analyze_file', 'analyze_image', 'list_uploaded_files'] } },
            { type: 'tool', label: 'Context', icon: Network, tone: 'data', hint: 'Browse, search, and read a file tree', config: { type: 'function', tool_ids: ['context_tree', 'search_context_tree', 'read_context_file'] } },
        ],
    },
    {
        id: 'governance',
        label: 'Trust',
        items: [
            { type: 'tool', label: 'Security scan', icon: ScanEye, tone: 'security', hint: 'Scan for secrets and prompt injection', config: { type: 'function', tool_ids: ['security_scan', 'scan_for_secrets', 'detect_prompt_injection'] } },
            { type: 'tool', label: 'PII redaction', icon: EyeOff, tone: 'security', hint: 'Detect and redact personal information', config: { type: 'function', tool_ids: ['detect_pii', 'redact_pii'] } },
            { type: 'tool', label: 'Audit', icon: ScrollText, tone: 'security', hint: 'Record and query the tamper-evident audit trail', config: { type: 'function', tool_ids: ['record_audit_event', 'query_audit_log'] } },
        ],
    },
    {
        id: 'integrations',
        label: 'Connect',
        items: [
            { type: 'tool', label: 'MCP server', icon: Server, tone: 'connect', hint: 'Attach an MCP server and its tools', config: { type: 'mcp', transport: 'stdio', command: '', args: [], tool_filter: [] } },
            { type: 'tool', label: 'Gmail', icon: Mail, tone: 'connect', hint: 'Send, search, and read email', config: { type: 'gmail', account_email: '', capabilities: ['send', 'search', 'read'], max_results: 10 } },
        ],
    },
    {
        id: 'output',
        label: 'End',
        items: [
            { type: 'output', label: 'Output', icon: Flag, tone: 'output', hint: 'Where the workflow result leaves the graph', config: { type: 'output' } },
        ],
    },
];

// --- Library flyout item (draggable card with nesting) ---
interface SidebarItemProps {
    type: NodeType;
    label: string;
    icon: LucideIcon;
    tone: ResourceTone;
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
    level = 0,
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
                <div
                    className="relative ml-[22px] pl-1"
                    style={{ borderLeft: '1px solid var(--border-subtle)' }}
                >
                    {children}
                </div>
            )}
        </div>
    );
};

export const Sidebar = () => {
    const { savedAgents, savedTools, savedWorkflows, fetchLibraryItems } = useLibraryStore();
    const { openLibraryModal } = useLibraryModal();
    const setPaletteOpen = useUiStore((state) => state.setPaletteOpen);
    const [libraryOpen, setLibraryOpen] = useState(false);
    const [query, setQuery] = useState('');

    useEffect(() => {
        fetchLibraryItems();
    }, []);

    const savedCount = savedWorkflows.length + savedAgents.length + savedTools.length;

    // Searching the palette filters within groups and drops groups that end up
    // empty, so the rail collapses to just the matches rather than to a list of
    // empty headings.
    const visibleGroups = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) return PALETTE_GROUPS;
        return PALETTE_GROUPS
            .map((group) => ({
                ...group,
                items: group.items.filter(
                    (item) =>
                        item.label.toLowerCase().includes(needle) ||
                        item.hint.toLowerCase().includes(needle) ||
                        group.label.toLowerCase().includes(needle),
                ),
            }))
            .filter((group) => group.items.length > 0);
    }, [query]);

    // --- Helpers to resolve nested references for the library flyout ---
    const findAgentById = (id: string) => savedAgents.find(a => a.id === id || a.name === id || a.config?.id === id);
    const findToolById = (id: string) => savedTools.find(t => t.id === id || t.name === id || t.config?.id === id);

    const renderAgentTools = (agentConfig: any) => {
        if (!agentConfig?.tools || !Array.isArray(agentConfig.tools)) return null;

        return agentConfig.tools.map((toolRef: string) => {
            const tool = findToolById(toolRef);
            return (
                <SidebarItem
                    key={toolRef}
                    type="tool"
                    label={tool ? tool.name : toolRef}
                    icon={Wrench}
                    tone="tool"
                    level={2}
                    config={tool ? tool.config : {}}
                />
            );
        });
    };

    const renderWorkflowAgents = (workflow: any) => {
        const nodes = workflow.config?.topology?.nodes || [];
        return nodes.map((node: any) => {
            const agentId = node.agent_id || node.id;
            const agent = findAgentById(agentId);
            const config = agent ? agent.config : {};

            return (
                <SidebarItem
                    key={node.id}
                    type="agent"
                    label={agent ? agent.name : (node.name || agentId)}
                    icon={Bot}
                    tone="agent"
                    description={node.description || (agent ? agent.description : '')}
                    level={1}
                    config={config}
                >
                    {renderAgentTools(config)}
                </SidebarItem>
            );
        });
    };

    const flyoutSectionHeader = (label: string, manageTab?: 'agents' | 'tools') => (
        <div className="mb-1 flex items-center justify-between px-2">
            <span className="h-section">{label}</span>
            {manageTab && (
                <button
                    type="button"
                    onClick={() => openLibraryModal(manageTab)}
                    className="btn btn-ghost btn-sm btn-icon"
                    title={`Manage ${label.toLowerCase()} in the Library`}
                    aria-label={`Manage ${label.toLowerCase()}`}
                >
                    <Settings size={12} />
                </button>
            )}
        </div>
    );

    const paneTop = 'calc(var(--toolbar-h) + 10px)';

    return (
        <>
            {/* The palette floats over the canvas as glass, so the canvas keeps its width. */}
            <aside
                className="glass-pane palette-pane from-left absolute left-2.5 z-20 w-[240px]"
                style={{ top: paneTop, bottom: 10 }}
                aria-label="Components"
            >
                <div className="flex shrink-0 items-center gap-2 px-3 pb-2 pl-4 pt-3.5">
                    <span className="headline flex-1">Components</span>
                    <button
                        type="button"
                        onClick={() => setPaletteOpen(false)}
                        className="btn btn-ghost btn-sm btn-icon"
                        aria-label="Hide components"
                        title="Hide components"
                    >
                        <X size={14} />
                    </button>
                </div>
                <div className="search-field shrink-0 px-3 pb-1">
                    <Search size={13} style={{ left: 22 }} />
                    <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Find a component"
                        aria-label="Search components"
                        className="input"
                    />
                </div>

                <div className="scroll-soft min-h-0 flex-1 px-1.5 pb-2">
                    {visibleGroups.length === 0 && (
                        <p className="hint px-3 pt-6 text-center">No components match “{query}”.</p>
                    )}

                    {visibleGroups.map((group) => (
                        <div key={group.id} className="px-1 pt-2.5">
                            <div className="h-section px-2 pb-1">{group.label}</div>
                            {group.items.map((item) => (
                                <ResourceCard
                                    key={`${group.id}-${item.label}`}
                                    type={item.type}
                                    label={item.label}
                                    description={item.hint}
                                    icon={item.icon}
                                    tone={item.tone}
                                    config={item.config}
                                    collapsed
                                />
                            ))}
                        </div>
                    ))}
                </div>

                <div className="flex shrink-0 items-center gap-1.5 px-3 pb-3 pt-2.5" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                    <button
                        type="button"
                        onClick={() => setLibraryOpen((open) => !open)}
                        className="btn btn-sm flex-1"
                        aria-expanded={libraryOpen}
                        title="Saved workflows, agents and tools"
                    >
                        <FolderOpen size={13} />
                        Saved{savedCount > 0 ? ` · ${savedCount}` : ''}
                    </button>
                    <button
                        type="button"
                        onClick={() => openLibraryModal('tools')}
                        className="btn btn-sm btn-icon"
                        title="Create a tool in the Library"
                        aria-label="Create a tool"
                    >
                        <Plus size={13} />
                    </button>
                </div>
            </aside>

            {/* Saved items open beside the palette, over the canvas, on demand. */}
            {libraryOpen && (
                <aside
                    className="glass-pane from-left absolute z-20 w-[300px]"
                    style={{ top: paneTop, bottom: 10, left: 260 }}
                    aria-label="Saved items"
                >
                    <div className="flex shrink-0 items-start justify-between gap-2 px-4 pb-2.5 pt-3.5">
                        <div className="min-w-0">
                            <div className="headline">Saved</div>
                            <div className="hint">
                                {savedWorkflows.length} workflows · {savedAgents.length} agents · {savedTools.length} tools
                            </div>
                        </div>
                        <div className="flex items-center gap-1">
                            <button type="button" onClick={() => openLibraryModal('browse')} className="btn btn-sm" title="Open the Library">
                                Library
                            </button>
                            <button type="button" onClick={() => setLibraryOpen(false)} className="btn btn-ghost btn-sm btn-icon" aria-label="Close saved items">
                                <X size={14} />
                            </button>
                        </div>
                    </div>

                    <div className="scroll-soft min-h-0 flex-1 space-y-4 px-2 pb-3">
                        {savedCount === 0 && (
                            <div className="empty-state">
                                <div className="headline">Nothing saved yet</div>
                                <p className="hint">Build on the canvas and choose Save, or add something in the Library.</p>
                            </div>
                        )}

                        {savedWorkflows.length > 0 && (
                            <div>
                                {flyoutSectionHeader('Workflows')}
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
                            <div>
                                {flyoutSectionHeader('Agents', 'agents')}
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
                            <div>
                                {flyoutSectionHeader('Tools', 'tools')}
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
                </aside>
            )}
        </>
    );
};

import React, { useMemo, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    Blocks, Bot, Check, Database, EyeOff, FileUp, GitBranch, Globe, LayoutGrid, Mail,
    Network, Plug, Puzzle, ScanEye, ScrollText, Search, Server, Sliders, Settings2,
    UserRound, Wrench, X,
} from 'lucide-react';
import type { LibraryItem } from '../../api/backendTypes';
import type { ResourceTone } from './ResourceCard';
import { StatusBadge } from './StatusBadge';

/**
 * The library, presented as a store you browse rather than a list you scroll.
 *
 * The list view worked when there were nine tools. With tools spanning privacy,
 * security, audit, data, files and integrations, what you need first is a way
 * to narrow — so a category rail and a search box come before the grid, and a
 * card has to say what the thing does before you commit to it.
 */

export interface StoreEntry {
    id: string;
    name: string;
    description: string;
    category: string;
    /** Tool type (function/api/mcp/sql/…) or resource kind (agent/workflow). */
    kind: string;
    tone: ResourceTone;
    enabled: boolean;
    /** The payload dropped onto the canvas or handed to the editor. */
    item: LibraryItem;
}

interface CategoryMeta {
    label: string;
    icon: LucideIcon;
    tone: ResourceTone;
    blurb: string;
}

// Categories the platform ships. Anything unrecognised still renders, using the
// fallback below, so a user-defined category is never dropped on the floor.
const CATEGORY_META: Record<string, CategoryMeta> = {
    privacy: { label: 'Privacy', icon: EyeOff, tone: 'security', blurb: 'Find and remove personal data before it travels' },
    security: { label: 'Security', icon: ScanEye, tone: 'security', blurb: 'Scan for secrets, injection, and unsafe content' },
    audit: { label: 'Audit', icon: ScrollText, tone: 'security', blurb: 'Record and verify what your agents did' },
    context: { label: 'Context', icon: Network, tone: 'data', blurb: 'Navigate a file tree instead of pasting a corpus' },
    files: { label: 'Files', icon: FileUp, tone: 'data', blurb: 'Read uploaded documents, sheets, and images' },
    knowledge: { label: 'Knowledge', icon: Blocks, tone: 'workflow', blurb: 'Retrieval over your own collections' },
    research: { label: 'Research', icon: Globe, tone: 'workflow', blurb: 'Reach for information on the open web' },
    data: { label: 'Databases', icon: Database, tone: 'data', blurb: 'Query SQL and document stores directly' },
    integrations: { label: 'Integrations', icon: Plug, tone: 'tool', blurb: 'Third-party services and REST endpoints' },
    identity: { label: 'Identity', icon: UserRound, tone: 'agent', blurb: 'Who the current user is, and what they may do' },
    utilities: { label: 'Utilities', icon: Sliders, tone: 'tool', blurb: 'Small, dependable helpers' },
    mcp: { label: 'MCP', icon: Server, tone: 'tool', blurb: 'Tools served by MCP servers' },
    email: { label: 'Email', icon: Mail, tone: 'tool', blurb: 'Send, search, and read mail' },
    agents: { label: 'Agents', icon: Bot, tone: 'agent', blurb: 'Saved agents ready to drop on the canvas' },
    workflows: { label: 'Workflows', icon: GitBranch, tone: 'workflow', blurb: 'Whole graphs you can reuse' },
};

const FALLBACK_META: CategoryMeta = {
    label: 'Other',
    icon: Puzzle,
    tone: 'tool',
    blurb: 'Everything not yet categorised',
};

export const categoryMeta = (category: string): CategoryMeta =>
    CATEGORY_META[category] ?? { ...FALLBACK_META, label: prettify(category) };

function prettify(value: string): string {
    if (!value) return 'Other';
    return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

const KIND_ICON: Record<string, LucideIcon> = {
    function: Wrench,
    api: Globe,
    mcp: Server,
    database: Database,
    sql: Database,
    mongodb: Database,
    gmail: Mail,
    agent: Bot,
    workflow: GitBranch,
};

const StoreCard = ({
    entry,
    onInspect,
    onAdd,
    added,
}: {
    entry: StoreEntry;
    onInspect: (entry: StoreEntry) => void;
    onAdd?: (entry: StoreEntry) => void;
    added?: boolean;
}) => {
    const Icon = KIND_ICON[entry.kind] ?? Wrench;

    const dragStart = (event: React.DragEvent) => {
        // Store cards are drag sources too, so browsing and building are the
        // same gesture — you never have to close the store to place something.
        const nodeType = entry.kind === 'agent' || entry.kind === 'workflow' ? entry.kind : 'tool';
        event.dataTransfer.setData('application/reactflow', nodeType);
        event.dataTransfer.setData('application/reactflow-label', entry.name);
        event.dataTransfer.setData('application/reactflow-config', JSON.stringify(entry.item.config ?? {}));
        event.dataTransfer.effectAllowed = 'move';
    };

    return (
        <div
            draggable
            onDragStart={dragStart}
            data-tone={entry.tone}
            className="dlx-card dlx-draggable flex flex-col p-3.5"
        >
            <div className="flex items-start gap-3">
                <span className="dlx-glyph h-9 w-9">
                    <Icon size={16} strokeWidth={2.1} />
                </span>
                <div className="min-w-0 flex-1">
                    <div className="dlx-text truncate text-[13px] font-semibold">{entry.name}</div>
                    <div className="dlx-faint mt-0.5 font-mono text-[10px]">{entry.kind}</div>
                </div>
                {!entry.enabled && <StatusBadge tone="muted" label="off" compact />}
            </div>

            <p className="dlx-muted mt-2.5 line-clamp-3 flex-1 text-[11.5px] leading-relaxed">
                {entry.description || 'No description provided.'}
            </p>

            <div className="mt-3 flex items-center gap-1.5">
                <button
                    onClick={() => onInspect(entry)}
                    className="dlx-btn dlx-btn-secondary flex-1 px-2 py-1.5 text-[11px]"
                >
                    Details
                </button>
                {onAdd && (
                    <button
                        onClick={() => onAdd(entry)}
                        className={`dlx-btn px-2.5 py-1.5 text-[11px] ${added ? 'dlx-btn-secondary' : 'dlx-btn-primary'}`}
                        title={added ? 'Already attached' : 'Attach to the selected agent'}
                    >
                        {added ? <><Check size={12} /> Added</> : 'Add'}
                    </button>
                )}
            </div>
        </div>
    );
};

export const LibraryStore = ({
    entries,
    onInspect,
    onAdd,
    addedIds,
    onManage,
}: {
    entries: StoreEntry[];
    onInspect: (entry: StoreEntry) => void;
    onAdd?: (entry: StoreEntry) => void;
    addedIds?: Set<string>;
    onManage?: () => void;
}) => {
    const [query, setQuery] = useState('');
    const [activeCategory, setActiveCategory] = useState<string>('all');

    const categories = useMemo(() => {
        const counts = new Map<string, number>();
        for (const entry of entries) {
            counts.set(entry.category, (counts.get(entry.category) ?? 0) + 1);
        }
        return [...counts.entries()]
            .map(([id, count]) => ({ id, count, ...categoryMeta(id) }))
            .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
    }, [entries]);

    const filtered = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return entries.filter((entry) => {
            if (activeCategory !== 'all' && entry.category !== activeCategory) return false;
            if (!needle) return true;
            return (
                entry.name.toLowerCase().includes(needle) ||
                entry.description.toLowerCase().includes(needle) ||
                entry.kind.toLowerCase().includes(needle) ||
                entry.category.toLowerCase().includes(needle)
            );
        });
    }, [entries, query, activeCategory]);

    // With no category selected the grid is grouped by category, so the store
    // reads as a set of shelves rather than one long undifferentiated wall.
    const grouped = useMemo(() => {
        if (activeCategory !== 'all') return null;
        const buckets = new Map<string, StoreEntry[]>();
        for (const entry of filtered) {
            const bucket = buckets.get(entry.category) ?? [];
            bucket.push(entry);
            buckets.set(entry.category, bucket);
        }
        return [...buckets.entries()].sort((a, b) => b[1].length - a[1].length);
    }, [filtered, activeCategory]);

    const active = activeCategory === 'all' ? null : categoryMeta(activeCategory);

    return (
        <div className="flex h-full min-h-0">
            {/* Category rail */}
            <aside
                className="custom-scrollbar hidden w-[188px] shrink-0 overflow-y-auto p-3 md:block"
                style={{ borderRight: '1px solid var(--border-subtle)' }}
            >
                <button
                    onClick={() => setActiveCategory('all')}
                    className={`dlx-btn mb-1 w-full justify-start gap-2 px-2.5 py-2 text-xs ${
                        activeCategory === 'all' ? 'dlx-btn-secondary' : 'dlx-btn-ghost'
                    }`}
                    style={activeCategory === 'all' ? { borderColor: 'var(--accent-border)' } : undefined}
                >
                    <LayoutGrid size={13} />
                    <span className="flex-1 text-left">All</span>
                    <span className="dlx-faint font-mono text-[10px]">{entries.length}</span>
                </button>

                {categories.map((category) => {
                    const Icon = category.icon;
                    const selected = activeCategory === category.id;
                    return (
                        <button
                            key={category.id}
                            onClick={() => setActiveCategory(category.id)}
                            data-tone={category.tone}
                            className={`dlx-btn mb-1 w-full justify-start gap-2 px-2.5 py-2 text-xs ${
                                selected ? 'dlx-btn-secondary' : 'dlx-btn-ghost'
                            }`}
                            style={selected ? { borderColor: 'var(--tone-border)' } : undefined}
                            title={category.blurb}
                        >
                            <Icon size={13} style={{ color: 'var(--tone-fg)' }} />
                            <span className="flex-1 truncate text-left">{category.label}</span>
                            <span className="dlx-faint font-mono text-[10px]">{category.count}</span>
                        </button>
                    );
                })}

                {onManage && (
                    <button
                        onClick={onManage}
                        className="dlx-btn dlx-btn-ghost mt-3 w-full justify-start gap-2 px-2.5 py-2 text-xs"
                        style={{ borderTop: '1px solid var(--border-subtle)', borderRadius: 0 }}
                    >
                        <Settings2 size={13} />
                        <span className="flex-1 text-left">Manage</span>
                    </button>
                )}
            </aside>

            {/* Shelves */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <div className="shrink-0 px-4 pb-3 pt-3.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <div className="relative">
                        <Search size={14} className="dlx-faint pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" />
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search the library — name, description, or type"
                            aria-label="Search the library"
                            className="dlx-input h-9 pl-9 pr-9 text-xs"
                        />
                        {query && (
                            <button
                                onClick={() => setQuery('')}
                                className="dlx-btn dlx-btn-ghost absolute right-1.5 top-1/2 -translate-y-1/2 p-1"
                                title="Clear search"
                            >
                                <X size={13} />
                            </button>
                        )}
                    </div>

                    {active && (
                        <div className="mt-2.5 flex items-baseline gap-2">
                            <span className="dlx-text text-sm font-semibold">{active.label}</span>
                            <span className="dlx-muted text-[11px]">{active.blurb}</span>
                        </div>
                    )}
                </div>

                <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
                    {filtered.length === 0 && (
                        <div className="dlx-muted flex h-full flex-col items-center justify-center gap-2 text-center text-xs">
                            <Search size={22} className="dlx-faint" />
                            <p>Nothing here matches {query ? `“${query}”` : 'this category'}.</p>
                            {query && (
                                <button onClick={() => setQuery('')} className="dlx-btn dlx-btn-secondary mt-1 px-3 py-1.5 text-[11px]">
                                    Clear search
                                </button>
                            )}
                        </div>
                    )}

                    {grouped
                        ? grouped.map(([category, items]) => {
                            const meta = categoryMeta(category);
                            const Icon = meta.icon;
                            return (
                                <section key={category} className="mb-7 last:mb-0">
                                    <header className="mb-2.5 flex items-center gap-2" data-tone={meta.tone}>
                                        <Icon size={13} style={{ color: 'var(--tone-fg)' }} />
                                        <h3 className="dlx-text text-xs font-bold uppercase tracking-wider">{meta.label}</h3>
                                        <span className="dlx-faint font-mono text-[10px]">{items.length}</span>
                                        <span className="dlx-divider ml-1 h-px flex-1" />
                                        <button
                                            onClick={() => setActiveCategory(category)}
                                            className="dlx-btn dlx-btn-ghost px-2 py-0.5 text-[10px]"
                                        >
                                            See all
                                        </button>
                                    </header>
                                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                                        {items.map((entry) => (
                                            <StoreCard
                                                key={entry.id}
                                                entry={entry}
                                                onInspect={onInspect}
                                                onAdd={onAdd}
                                                added={addedIds?.has(entry.id)}
                                            />
                                        ))}
                                    </div>
                                </section>
                            );
                        })
                        : (
                            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                                {filtered.map((entry) => (
                                    <StoreCard
                                        key={entry.id}
                                        entry={entry}
                                        onInspect={onInspect}
                                        onAdd={onAdd}
                                        added={addedIds?.has(entry.id)}
                                    />
                                ))}
                            </div>
                        )}
                </div>
            </div>
        </div>
    );
};

/** Map saved library items onto store entries, inferring a category when absent. */
export const toStoreEntries = (
    tools: LibraryItem[],
    agents: LibraryItem[],
    workflows: LibraryItem[],
): StoreEntry[] => {
    const toneForKind = (kind: string): ResourceTone => {
        if (kind === 'agent') return 'agent';
        if (kind === 'workflow') return 'workflow';
        if (kind === 'sql' || kind === 'database' || kind === 'mongodb') return 'data';
        return 'tool';
    };

    const entries: StoreEntry[] = tools.map((tool) => {
        const kind = String(tool.type ?? tool.config?.type ?? 'function');
        // Tools predating the category field, and anything a user creates
        // without one, still need a shelf — derive it from the type.
        const category = tool.category
            ?? (kind === 'mcp' ? 'mcp'
                : kind === 'gmail' ? 'email'
                : kind === 'api' ? 'integrations'
                : ['sql', 'database', 'mongodb'].includes(kind) ? 'data'
                : 'utilities');
        return {
            id: tool.id,
            name: tool.name,
            description: tool.description ?? '',
            category,
            kind,
            tone: toneForKind(kind),
            enabled: tool.config?.enabled !== false,
            item: tool,
        };
    });

    for (const agent of agents) {
        entries.push({
            id: agent.id,
            name: agent.name,
            description: agent.description ?? '',
            category: 'agents',
            kind: 'agent',
            tone: 'agent',
            enabled: true,
            item: agent,
        });
    }

    for (const workflow of workflows) {
        entries.push({
            id: workflow.id,
            name: workflow.name,
            description: workflow.description ?? '',
            category: 'workflows',
            kind: 'workflow',
            tone: 'workflow',
            enabled: true,
            item: workflow,
        });
    }

    return entries;
};

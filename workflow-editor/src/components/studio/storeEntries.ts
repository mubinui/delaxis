import type { LibraryItem } from '../../api/backendTypes';
import type { ResourceTone } from './ResourceCard';

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

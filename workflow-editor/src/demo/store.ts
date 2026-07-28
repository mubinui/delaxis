/**
 * In-memory stand-in for the Open Agent Kit backend, used by the GitHub Pages demo.
 *
 * The seed is a scrubbed snapshot of the real API's responses (see
 * `scripts/build_demo_seed.py`), so shapes here match production exactly. Every
 * mutation stays in this module, which means the demo supports real create /
 * edit / delete flows — they just reset on reload instead of hitting SQLite.
 */
import seed from './seed.json';

export type Json = Record<string, any>;

/** `structuredClone` keeps the frozen JSON import from leaking into mutable state. */
const clone = <T,>(value: T): T => structuredClone(value);

export interface DemoState {
    workflows: Json[];
    agents: Json[];
    tools: Json[];
    functions: Json[];
    functionSources: Record<string, string>;
    prompts: Json[];
    providers: Json[];
    triggers: Json[];
    deployments: Json[];
    apiKeys: Json[];
    sessions: Record<string, { workflow_id: string; messages: Json[] }>;
    health: Json;
    metrics: Json;
    ragService: Json;
    ragCollections: Json;
    studioState: Json;
    builderModels: Json;
    gmailStatus: Json;
}

/**
 * A real install serves deployed chat pages from the API root at `/d/<name>/`.
 * The Pages demo is hosted under a repo sub-path, so rewrite the seeded URLs to
 * point at the static chat pages the demo build emits alongside the Studio.
 */
const rebaseDeployments = (deployments: Json[]) =>
    deployments.map((deployment) => ({
        ...deployment,
        url: `${import.meta.env.BASE_URL}${String(deployment.url).replace(/^\//, '')}`,
    }));

const build = (): DemoState => ({
    workflows: clone(seed.workflows),
    agents: clone(seed.agents),
    tools: clone(seed.tools),
    functions: clone(seed.functions.functions),
    functionSources: clone(seed.functionSources),
    prompts: clone(seed.prompts),
    providers: clone(seed.providers),
    triggers: clone(seed.triggers),
    deployments: rebaseDeployments(clone(seed.deployments)),
    apiKeys: [
        {
            id: 'key_demo_studio',
            name: 'studio-local',
            prefix: 'oak_live_7f2c',
            created_at: '2026-07-18T14:03:00+00:00',
            last_used_at: '2026-07-20T09:41:00+00:00',
            revoked: false,
        },
    ],
    sessions: {},
    health: clone(seed.health),
    metrics: clone(seed.metrics),
    ragService: clone(seed.ragService),
    ragCollections: clone(seed.ragCollections),
    studioState: clone(seed.studioState),
    builderModels: clone(seed.builderModels),
    gmailStatus: clone(seed.gmailStatus),
});

export const state: DemoState = build();

/** Reset every collection back to the seed without swapping the exported object. */
export const resetDemoState = () => Object.assign(state, build());

export const slugify = (value: string, fallback: string) => {
    const slug = value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
    return slug || fallback;
};

export const nowIso = () => new Date().toISOString();

/**
 * Upsert by `id` and return the stored record. Used by every collection so a
 * POST to an existing id behaves like the backend's idempotent create.
 */
export const upsert = (collection: Json[], record: Json) => {
    const index = collection.findIndex((item) => item.id === record.id);
    if (index >= 0) {
        collection[index] = { ...collection[index], ...record };
        return collection[index];
    }
    collection.push(record);
    return record;
};

export const patch = (collection: Json[], id: string, updates: Json) => {
    const index = collection.findIndex((item) => item.id === id);
    if (index < 0) return null;
    collection[index] = { ...collection[index], ...updates, last_updated: nowIso() };
    return collection[index];
};

export const remove = (collection: Json[], id: string) => {
    const index = collection.findIndex((item) => item.id === id);
    if (index < 0) return false;
    collection.splice(index, 1);
    return true;
};

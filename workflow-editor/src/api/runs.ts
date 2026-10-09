import { api } from './client';
import type { JsonObject } from '../types/json';

export type RunStatus = 'running' | 'succeeded' | 'failed';

/** One frame of a recorded run, in the shape the streaming endpoint sends it. */
export interface RunEvent {
    type: string;
    payload: JsonObject;
    agent_id: string | null;
    sequence: number;
    timestamp: string;
}

export interface RunSummary {
    id: string;
    workflow_id: string;
    session_id: string | null;
    user_id: string | null;
    source: string;
    status: RunStatus;
    message: string;
    response: string | null;
    error: string | null;
    agents_called: string[];
    tools_called: string[];
    usage: JsonObject;
    cost_usd: number | null;
    replay_of: string | null;
    started_at: string;
    finished_at: string | null;
    duration_ms: number | null;
    event_count: number;
    metadata: JsonObject;
}

export interface RunDetail extends RunSummary {
    events: RunEvent[];
}

export interface RunPage {
    items: RunSummary[];
    total: number;
    limit: number;
    offset: number;
}

export interface RunFilters {
    workflow_id?: string;
    status?: RunStatus | '';
    source?: string;
    limit?: number;
    offset?: number;
}

/** The query string for a run listing; empty filters are left out. */
export const runQuery = (filters: RunFilters): string => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
        if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
    }
    const query = params.toString();
    return query ? `?${query}` : '';
};

export const listRuns = (filters: RunFilters = {}) => api<RunPage>(`/api/v1/runs${runQuery(filters)}`);

export const getRun = (id: string) => api<RunDetail>(`/api/v1/runs/${encodeURIComponent(id)}`);

/** Send the run's request to the workflow again; resolves to the new run, failed or not. */
export const replayRun = (id: string, message?: string) =>
    api<RunDetail>(`/api/v1/runs/${encodeURIComponent(id)}/replay`, {
        method: 'POST',
        body: JSON.stringify(message ? { message } : {}),
    });

export const deleteRun = (id: string) =>
    api<void>(`/api/v1/runs/${encodeURIComponent(id)}`, { method: 'DELETE' });

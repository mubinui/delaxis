import { useEffect, useState } from 'react';
import { api } from '../api/client';

export interface BackendStatus {
    /** null while the first check is in flight. */
    up: boolean | null;
    version?: string;
    counts?: { workflows: number; agents: number; tools: number };
}

interface Health { status?: string; version?: string }
interface StudioState { counts?: { workflows?: number; agents?: number; tools?: number } }

// One check per page load, shared by every caller: the sidebar and the landing
// page both show it, and neither should trigger its own round trip.
let pending: Promise<BackendStatus> | null = null;

const check = (): Promise<BackendStatus> => {
    pending ??= (async () => {
        try {
            const health = await api<Health>('/health');
            const state = await api<StudioState>('/api/v1/studio/state').catch(() => null);
            return {
                up: true,
                version: health?.version,
                counts: state?.counts
                    ? {
                        workflows: state.counts.workflows ?? 0,
                        agents: state.counts.agents ?? 0,
                        tools: state.counts.tools ?? 0,
                    }
                    : undefined,
            };
        } catch {
            return { up: false };
        }
    })();
    return pending;
};

export const useBackendStatus = (): BackendStatus => {
    const [status, setStatus] = useState<BackendStatus>({ up: null });
    useEffect(() => {
        let cancelled = false;
        void check().then((result) => { if (!cancelled) setStatus(result); });
        return () => { cancelled = true; };
    }, []);
    return status;
};

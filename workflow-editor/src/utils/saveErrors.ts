import type { JsonObject } from '../types/json';
/**
 * The api() client throws `Error("API <status>: <body>")`. These helpers turn
 * that raw string into something a user can act on — especially the backend's
 * structured `dependency_error`, which otherwise surfaces as a JSON blob.
 */

export interface ParsedApiError {
    status?: number;
    detail?: unknown;
    raw: string;
}

export function parseApiError(message: string): ParsedApiError {
    const match = /^API (\d+): ([\s\S]*)$/.exec(message);
    if (!match) return { raw: message };
    const status = Number(match[1]);
    try {
        const body = JSON.parse(match[2]);
        return { status, detail: body?.detail ?? body, raw: message };
    } catch {
        return { status, raw: match[2] };
    }
}

/** Human-readable summary of a save failure, unwrapping dependency errors. */
export function describeSaveError(message: string): string {
    const { status, detail } = parseApiError(message);

    if (detail && typeof detail === 'object') {
        const d = detail as JsonObject;
        if (d.type === 'dependency_error') {
            const missing: string[] = d.dependencies?.missing ?? [];
            const available: string[] = d.dependencies?.available ?? [];
            const lines = [d.message || 'This workflow references things that do not exist.'];
            if (missing.length) lines.push(`\nMissing: ${missing.join(', ')}`);
            if (available.length) lines.push(`Available: ${available.join(', ')}`);
            lines.push('\nBind each unresolved node to an existing agent, or save it to your agent library first.');
            return lines.join('\n');
        }
        if (typeof d.message === 'string') return d.message;
    }

    if (typeof detail === 'string') return detail;
    return status ? `Save failed (HTTP ${status}).` : message;
}

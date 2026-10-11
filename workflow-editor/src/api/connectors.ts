import { api } from './client';
import type { JsonObject } from '../types/json';

export interface ConnectorParam {
    name: string;
    type: 'string' | 'integer' | 'boolean' | 'array' | 'object';
    description: string;
    required: boolean;
    default: unknown;
    enum: string[] | null;
}

export interface ConnectorAction {
    id: string;
    name: string;
    kind: 'read' | 'write';
    description: string;
    params: ConnectorParam[];
}

export interface ConnectorAuth {
    kind: 'token' | 'oauth';
    base_url: boolean;
    base_url_default: string | null;
    base_url_label: string;
    username_label: string | null;
    username_required: boolean;
    token_label: string;
    token_help: string;
    oauth_start: string | null;
}

export interface ConnectorInfo {
    id: string;
    name: string;
    icon: string;
    description: string;
    auth: ConnectorAuth;
    options: Array<{ key: string; label: string; help: string }>;
    actions: ConnectorAction[];
}

export interface Connection {
    id: string;
    connector: string;
    account_label: string | null;
    base_url: string | null;
    auth_kind: string;
    options: JsonObject;
    created_at: string | null;
    last_status: 'ok' | 'failed' | null;
    last_error: string | null;
    last_verified_at: string | null;
}

export interface ConnectionTest {
    ok: boolean;
    account_label: string | null;
    error: string | null;
}

export interface ConnectionCreate {
    connector: string;
    base_url?: string;
    username?: string;
    token: string;
    options?: JsonObject;
}

const BASE = '/api/v1/integrations';

/** The API's `detail` out of a thrown `api()` error, or the error's own message. */
export const apiDetail = (error: unknown): string => {
    const message = error instanceof Error ? error.message : String(error);
    const match = /^API \d+: ([\s\S]*)$/.exec(message);
    if (!match) return message;
    try {
        const body = JSON.parse(match[1]) as { detail?: unknown };
        return typeof body.detail === 'string' ? body.detail : match[1];
    } catch {
        return match[1];
    }
};

export const listConnectors = async () =>
    (await api<{ connectors: ConnectorInfo[] }>(`${BASE}/connectors`)).connectors;

export const listConnections = async () =>
    (await api<{ connections: Connection[] }>(`${BASE}/connections`)).connections;

export const createConnection = (body: ConnectionCreate) =>
    api<Connection>(`${BASE}/connections`, { method: 'POST', body: JSON.stringify(body) });

export const testConnection = (id: string) =>
    api<ConnectionTest>(`${BASE}/connections/${encodeURIComponent(id)}/test`, { method: 'POST' });

export const deleteConnection = (id: string) =>
    api<void>(`${BASE}/connections/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const runConnectorAction = async (connectionId: string, actionId: string, args: JsonObject, options: JsonObject) =>
    (await api<{ result: unknown }>(
        `${BASE}/connections/${encodeURIComponent(connectionId)}/actions/${encodeURIComponent(actionId)}`,
        { method: 'POST', body: JSON.stringify({ args, options }) },
    )).result;

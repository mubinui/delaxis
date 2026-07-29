import { api, API_BASE_URL } from './client';

export type BuilderType = 'agent' | 'tool' | 'function' | 'workflow';

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export interface ModelInfo {
    model_id: string;
    provider_id: string;
    provider_name: string;
    display_name: string;
}

export interface FrontendGenerateResponse {
    html: string;
    summary: string;
    model_id: string;
    provider_id: string;
    used_fallback: boolean;
    /** Which path produced the page — 'custom' output that failed its checks comes back as 'themed'. */
    mode?: 'themed' | 'custom';
    design?: Record<string, any>;
    warnings?: string[];
}

export function listBuilderModels(): Promise<{ models: ModelInfo[] }> {
    return api<{ models: ModelInfo[] }>('/api/v1/builder/models');
}

export async function streamBuilderChat(body: {
    builder_type: BuilderType;
    message: string;
    history: ChatMessage[];
    provider_id: string;
    model_id: string;
}) {
    const response = await fetch(`${API_BASE_URL}/api/v1/builder/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!response.ok || !response.body) {
        throw new Error(`Builder chat failed: ${response.status}`);
    }
    return response.body.getReader();
}

export function planChatbot(body: {
    prompt: string;
    provider_id: string;
    model_id: string;
}): Promise<Record<string, any>> {
    return api<Record<string, any>>('/api/v1/builder/plan-chatbot', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function normalizeApi(body: {
    raw_api: string;
    specification: string;
    provider_id: string;
    model_id: string;
}): Promise<Record<string, any>> {
    return api<Record<string, any>>('/api/v1/builder/normalize-api', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function applyBuilderPlan(plan: Record<string, any>): Promise<Record<string, any>> {
    return api<Record<string, any>>('/api/v1/builder/apply', {
        method: 'POST',
        body: JSON.stringify({ plan }),
    });
}

export function generateBuilderConfig(body: {
    builder_type: BuilderType;
    history: ChatMessage[];
    provider_id: string;
    model_id: string;
}): Promise<{ builder_type: BuilderType; config: Record<string, any> | string; raw: string }> {
    return api<{ builder_type: BuilderType; config: Record<string, any> | string; raw: string }>('/api/v1/builder/generate', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function generateFrontend(body: {
    prompt: string;
    workflow_id: string;
    title: string;
    greeting: string;
    provider_id: string;
    model_id: string;
    history: ChatMessage[];
    mode?: 'themed' | 'custom';
    theme?: string;
}): Promise<FrontendGenerateResponse> {
    return api<FrontendGenerateResponse>('/api/v1/builder/frontend/generate', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

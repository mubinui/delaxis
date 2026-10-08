import type { VisualEdge, VisualNode } from '../types/workflow';
import type { JsonObject } from '../types/json';

export interface WorkflowConfig {
    id: string;
    name: string;
    description: string;
    topology?: JsonObject;
    execution_strategy?: string;
    enabled?: boolean;
    metadata?: JsonObject;
    workflow_type?: string;
    persistence?: string;
    runtime?: string;
    process?: string;
    tasks?: Array<JsonObject>;
    memory?: JsonObject;
    knowledge?: JsonObject;
    guardrails?: JsonObject;
    tracing?: JsonObject;
    event_listeners?: Array<JsonObject>;
    mcp_servers?: Array<JsonObject>;
    output_schema?: JsonObject | string | null;
    deployment_auth_mode?: string;
    version?: number;
    last_updated?: string;
}

export interface AgentConfig {
    id: string;
    type: string;
    name: string;
    system_message?: string;
    llm_config?: JsonObject | boolean | null;
    human_input_mode?: string;
    code_execution_config?: JsonObject | boolean | null;
    tools: string[];
    max_consecutive_auto_reply?: number;
    retrieve_config?: JsonObject | null;
    description?: string;
}

export interface ToolConfig {
    id: string;
    name: string;
    description: string;
    entrypoint?: string | null;
    enabled: boolean;
    settings: JsonObject;
    /** Presentation grouping for the Library; never affects execution. */
    category?: string | null;
}

export interface FunctionTool {
    id: string;
    name: string;
    description: string;
    entrypoint: string;
    file_path: string;
    enabled: boolean;
}

export interface PromptTemplate {
    id: string;
    name: string;
    description: string;
    template: string;
    variables: string[];
    category?: string | null;
    version?: number;
    etag?: string;
    last_updated?: string;
}

export interface ApiProvider {
    id: string;
    name: string;
    type: string;
    description: string;
    base_url?: string | null;
    api_key_masked?: string | null;
    api_key_env?: string | null;
    /** Where the server finds this provider's key; 'none' means it has none. */
    key_source?: 'inline' | 'secret_store' | 'env' | 'none';
    litellm_prefix?: string | null;
    enabled: boolean;
    config: JsonObject;
    models?: Array<JsonObject>;
    version?: number;
    etag?: string;
    last_updated?: string;
}

export interface ThemePreset {
    id: string;
    label: string;
    vars: Record<string, string>;
}

/** A provider that can host a live voice session (GET /api/v1/voice/providers). */
export interface VoiceProviderInfo {
    provider_id: string;
    name: string;
    models: string[];
    voices: string[];
    /** False when the provider's API key is not configured on the server. */
    key_available: boolean;
    key_env_var: string;
}

export interface VoiceProvidersResponse {
    enabled: boolean;
    providers: VoiceProviderInfo[];
}

export interface TriggerConfig {
    id: string;
    workflow_id: string;
    type: 'chat' | 'webhook' | 'manual';
    enabled: boolean;
    name: string;
    auth_mode: 'public' | 'api_key' | 'jwt';
    provider_id: string;
    model_id: string;
    greeting: string;
    public_slug?: string | null;
    secret?: string | null;
    allowed_origins: string[];
    input_mapping: JsonObject;
    response_mapping: JsonObject;
    metadata: JsonObject;
    created_at: string;
    updated_at: string;
}

export interface DeploymentConfig {
    id: string;
    workflow_id: string;
    name: string;
    api_url?: string;
    trigger_id?: string | null;
    title: string;
    theme: string;
    greeting: string;
    /** Starter prompts shown as chips on an empty conversation (max four). */
    suggestions?: string[];
    provider_id: string;
    model_id: string;
    auth_mode: string;
    status: 'active' | 'error';
    url: string;
    path: string;
    created_at: string;
    updated_at: string;
    error?: string | null;
}

export interface LibraryItem {
    id: string;
    name: string;
    description?: string;
    config: JsonObject;
    type?: string;
    category?: string | null;
    created_at?: string;
    updated_at?: string;
}

export type ItemType = 'workflow' | 'agent' | 'tool';

export interface VisualWorkflowMetadata {
    canvas?: {
        nodes: VisualNode[];
        edges: VisualEdge[];
        viewport?: { x: number; y: number; zoom: number };
    };
}

import { create } from 'zustand';
import { api } from '../api/client';
import type {
    AgentConfig,
    ApiProvider,
    DeploymentConfig,
    FunctionTool,
    ItemType,
    LibraryItem,
    PromptTemplate,
    ToolConfig,
    TriggerConfig,
    WorkflowConfig,
} from '../api/backendTypes';

type JsonObject = Record<string, any>;

interface LibraryState {
    savedWorkflows: LibraryItem[];
    savedAgents: LibraryItem[];
    savedTools: LibraryItem[];
    functions: FunctionTool[];
    prompts: PromptTemplate[];
    providers: ApiProvider[];
    ragConfig: JsonObject | null;
    ragCollections: JsonObject | null;
    health: JsonObject | null;
    metricsDashboard: JsonObject | null;
    triggers: TriggerConfig[];
    deployments: DeploymentConfig[];
    isLoading: boolean;
    error: string | null;

    fetchLibraryItems: () => Promise<void>;
    fetchOperationsData: () => Promise<void>;
    fetchTriggers: (workflowId?: string) => Promise<void>;
    createTrigger: (body: Partial<TriggerConfig> & { workflow_id: string; type: 'chat' | 'webhook' | 'manual' }) => Promise<TriggerConfig>;
    updateTrigger: (triggerId: string, body: Partial<TriggerConfig> & { rotate_secret?: boolean }) => Promise<TriggerConfig>;
    deleteTrigger: (triggerId: string) => Promise<void>;
    fetchDeployments: () => Promise<void>;
    previewDeployment: (body: JsonObject) => Promise<JsonObject>;
    flashDeploy: (body: JsonObject) => Promise<DeploymentConfig>;
    deleteDeployment: (deploymentId: string) => Promise<void>;
    saveWorkflow: (workflowData: any) => Promise<WorkflowConfig>;
    validateWorkflow: (workflowId: string) => Promise<JsonObject>;
    executeWorkflow: (workflowId: string, message: string, dryRun?: boolean) => Promise<JsonObject>;

    saveItem: (itemType: ItemType, itemData: Partial<LibraryItem>) => Promise<LibraryItem>;
    updateItem: (itemType: ItemType, itemId: string, updates: Partial<LibraryItem>) => Promise<LibraryItem>;
    deleteItem: (itemType: ItemType, itemId: string) => Promise<void>;
    executeTool: (toolId: string, args: JsonObject) => Promise<JsonObject>;

    createFunctionTool: (body: { id: string; name: string; description: string; code: string }) => Promise<FunctionTool>;
    getFunctionSource: (toolId: string) => Promise<{ tool_id: string; source: string }>;
    deleteFunctionTool: (toolId: string) => Promise<void>;

    savePrompt: (body: Partial<PromptTemplate>) => Promise<PromptTemplate>;
    updatePrompt: (promptId: string, body: Partial<PromptTemplate>) => Promise<PromptTemplate>;
    deletePrompt: (promptId: string) => Promise<void>;
    saveProvider: (body: Partial<ApiProvider> & { api_key?: string }) => Promise<ApiProvider>;
    updateProvider: (providerId: string, body: Partial<ApiProvider> & { api_key?: string }) => Promise<ApiProvider>;
    deleteProvider: (providerId: string) => Promise<void>;
    testProvider: (providerId: string) => Promise<JsonObject>;
    fetchProviderModels: (providerId: string) => Promise<JsonObject>;

    previewSwagger: (url: string) => Promise<JsonObject>;
    importSwagger: (url: string, selectedEndpoints: string[]) => Promise<JsonObject>;
}

const slugify = (value: string, fallback: string) => {
    // Backend ids must match ^[a-z0-9][a-z0-9_-]*$ — hyphens are allowed
    // (lm-studio), but not as the first character.
    const slug = value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '_')
        .replace(/^[_-]+|[_-]+$/g, '');
    return slug || fallback;
};

const workflowToLibraryItem = (workflow: WorkflowConfig): LibraryItem => ({
    id: workflow.id,
    name: workflow.name,
    description: workflow.description,
    type: workflow.workflow_type ?? workflow.topology?.type ?? 'workflow',
    config: {
        ...workflow,
        ...(workflow.metadata?.visual_canvas
            ? {
                nodes: workflow.metadata.visual_canvas.nodes,
                edges: workflow.metadata.visual_canvas.edges,
            }
            : {}),
    },
    created_at: workflow.last_updated,
    updated_at: workflow.last_updated,
});

const agentToLibraryItem = (agent: AgentConfig): LibraryItem => ({
    id: agent.id,
    name: agent.name,
    description: agent.description,
    type: agent.type,
    config: {
        id: agent.id,
        type: agent.type,
        name: agent.name,
        instruction: agent.system_message ?? '',
        system_message: agent.system_message ?? '',
        model_config: {
            ...(agent.llm_config && typeof agent.llm_config === 'object' ? agent.llm_config : {}),
            ...((agent as any).agent_settings ?? {}),
        },
        is_selector: Boolean((agent as any).is_selector),
        output_key: (agent as any).output_key ?? '',
        human_input_mode: agent.human_input_mode ?? 'NEVER',
        code_execution_config: agent.code_execution_config,
        tools: agent.tools ?? [],
        max_consecutive_auto_reply: agent.max_consecutive_auto_reply ?? 10,
        retrieve_config: agent.retrieve_config,
    },
});

const toolToLibraryItem = (tool: ToolConfig): LibraryItem => ({
    id: tool.id,
    name: tool.name,
    description: tool.description,
    type: tool.settings?.type ?? 'function',
    config: {
        id: tool.id,
        name: tool.name,
        description: tool.description,
        entrypoint: tool.entrypoint ?? '',
        enabled: tool.enabled,
        ...tool.settings,
    },
});

// Backend AgentConfig.type is an autogen-style enum, distinct from the CrewAI
// agent kinds the canvas uses ('LlmAgent', 'RecursiveAgent', …). Passing a
// canvas kind through fails validation, so map unknown kinds to 'conversable'
// (what every seeded agent uses).
const VALID_BACKEND_AGENT_TYPES = new Set([
    'conversable', 'retrieve_user_proxy', 'group_chat_manager', 'assistant', 'code_executor', 'custom',
]);

const itemToAgentCreate = (item: Partial<LibraryItem>) => {
    const config = item.config ?? {};
    const modelConfig = config.model_config ?? config.llm_config ?? {};
    const id = slugify(String(config.id ?? item.name ?? ''), 'agent');
    const name = String(item.name ?? config.name ?? id).replace(/\s+/g, '_');

    const rawType = String(item.type ?? config.type ?? '');
    const type = VALID_BACKEND_AGENT_TYPES.has(rawType) ? rawType : 'conversable';

    // Backend LLMConfig requires provider_id + model; an empty object fails
    // validation, so send null when a real model hasn't been configured. The
    // runtime then falls back to the environment default model.
    const hasModel = Boolean(modelConfig && modelConfig.provider_id && modelConfig.model);
    // Empty strings would override the provider defaults with nothing, so drop them
    const llm_config = hasModel
        ? Object.fromEntries(
            Object.entries(modelConfig).filter(([key, value]) =>
                !(['base_url', 'api_key_env'].includes(key) && !value)),
        )
        : null;

    // agent_settings holds the CrewAI execution knobs; they live alongside the
    // sampling params in model_config on the canvas.
    const agentSettingKeys = [
        'max_iter', 'max_rpm', 'max_execution_time', 'max_retry_limit',
        'allow_delegation', 'respect_context_window', 'cache', 'verbose',
        'inject_date', 'use_system_prompt',
    ];
    const agent_settings = Object.fromEntries(
        Object.entries(modelConfig).filter(([key, value]) => agentSettingKeys.includes(key) && value !== undefined && value !== ''),
    );

    return {
        id,
        type,
        name,
        system_message: String(config.instruction ?? config.system_message ?? 'You are a helpful AI assistant.'),
        llm_config,
        agent_settings: Object.keys(agent_settings).length > 0 ? agent_settings : null,
        is_selector: Boolean(config.is_selector),
        output_key: config.output_key || null,
        human_input_mode: String(config.human_input_mode ?? 'NEVER'),
        code_execution_config: config.code_execution_config ?? false,
        tools: Array.isArray(config.tools) ? config.tools : [],
        max_consecutive_auto_reply: Number(config.max_consecutive_auto_reply ?? 10),
        retrieve_config: config.retrieve_config ?? null,
        description: item.description ?? '',
    };
};

export { itemToAgentCreate };

const itemToToolCreate = (item: Partial<LibraryItem>) => {
    const config = item.config ?? {};
    const id = slugify(String(config.id ?? item.name ?? ''), 'tool');
    const type = String(item.type ?? config.type ?? 'function');
    const settings: JsonObject = {
        ...config,
        type,
    };
    delete settings.id;
    delete settings.name;
    delete settings.description;
    delete settings.entrypoint;
    delete settings.enabled;

    return {
        id,
        name: String(item.name ?? config.name ?? id),
        description: String(item.description ?? config.description ?? ''),
        entrypoint: String(config.entrypoint ?? ''),
        enabled: Boolean(config.enabled ?? true),
        settings,
    };
};

export const useLibraryStore = create<LibraryState>((set, get) => ({
    savedWorkflows: [],
    savedAgents: [],
    savedTools: [],
    functions: [],
    prompts: [],
    providers: [],
    ragConfig: null,
    ragCollections: null,
    health: null,
    metricsDashboard: null,
    triggers: [],
    deployments: [],
    isLoading: false,
    error: null,

    fetchLibraryItems: async () => {
        set({ isLoading: true, error: null });
        try {
            const [workflows, agents, tools, functions, prompts, providers] = await Promise.all([
                api<WorkflowConfig[]>('/api/v1/workflows'),
                api<AgentConfig[]>('/api/v1/agents'),
                api<ToolConfig[]>('/api/v1/tools'),
                api<{ functions: FunctionTool[] }>('/api/v1/functions'),
                api<PromptTemplate[]>('/api/v1/prompts').catch(() => []),
                api<ApiProvider[]>('/api/v1/api-providers').catch(() => []),
            ]);

            set({
                savedWorkflows: workflows.map(workflowToLibraryItem),
                savedAgents: agents.map(agentToLibraryItem),
                savedTools: tools.map(toolToLibraryItem),
                functions: functions.functions ?? [],
                prompts,
                providers,
                isLoading: false,
            });
        } catch (error) {
            set({ error: (error as Error).message, isLoading: false });
        }
    },

    fetchOperationsData: async () => {
        const [ragConfig, ragCollections, health, metricsDashboard, deployments, triggers] = await Promise.all([
            api<JsonObject>('/api/v1/rag-service').catch(() => null),
            api<JsonObject>('/api/v1/rag-service/collections').catch(() => null),
            api<JsonObject>('/api/v1/health').catch(() => null),
            api<JsonObject>('/api/v1/metrics/dashboard').catch(() => null),
            api<DeploymentConfig[]>('/api/v1/deployments').catch(() => []),
            api<TriggerConfig[]>('/api/v1/triggers').catch(() => []),
        ]);
        set({ ragConfig, ragCollections, health, metricsDashboard, deployments, triggers });
    },

    fetchTriggers: async (workflowId) => {
        const query = workflowId ? `?workflow_id=${encodeURIComponent(workflowId)}` : '';
        const triggers = await api<TriggerConfig[]>(`/api/v1/triggers${query}`);
        set({ triggers });
    },

    createTrigger: async (body) => {
        const trigger = await api<TriggerConfig>('/api/v1/triggers', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        await get().fetchTriggers();
        return trigger;
    },

    updateTrigger: async (triggerId, body) => {
        const trigger = await api<TriggerConfig>(`/api/v1/triggers/${triggerId}`, {
            method: 'PUT',
            body: JSON.stringify(body),
        });
        await get().fetchTriggers();
        return trigger;
    },

    deleteTrigger: async (triggerId) => {
        await api<void>(`/api/v1/triggers/${triggerId}`, { method: 'DELETE' });
        await get().fetchTriggers();
    },

    fetchDeployments: async () => {
        const deployments = await api<DeploymentConfig[]>('/api/v1/deployments');
        set({ deployments });
    },

    previewDeployment: (body) => api<JsonObject>('/api/v1/deployments/preview', {
        method: 'POST',
        body: JSON.stringify(body),
    }),

    flashDeploy: async (body) => {
        const deployment = await api<DeploymentConfig>('/api/v1/deployments/flash', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        await get().fetchDeployments();
        return deployment;
    },

    deleteDeployment: async (deploymentId) => {
        await api<void>(`/api/v1/deployments/${deploymentId}`, { method: 'DELETE' });
        await get().fetchDeployments();
    },

    saveWorkflow: async (workflowData: any) => {
        set({ isLoading: true, error: null });
        try {
            const currentId = workflowData.currentId ? String(workflowData.currentId) : '';
            const id = slugify(currentId || workflowData.id || workflowData.name, 'workflow');
            const method = currentId ? 'PUT' : 'POST';
            const path = currentId ? `/api/v1/workflows/${id}` : '/api/v1/workflows';
            const body = currentId ? workflowData.update : workflowData.create;
            const workflow = await api<WorkflowConfig>(path, {
                method,
                body: JSON.stringify(body),
            });
            await get().fetchLibraryItems();
            set({ isLoading: false });
            return workflow;
        } catch (error) {
            set({ error: (error as Error).message, isLoading: false });
            throw error;
        }
    },

    validateWorkflow: (workflowId: string) => api<JsonObject>(`/api/v1/workflows/${workflowId}/validate`, { method: 'POST' }),
    executeWorkflow: (workflowId: string, message: string, dryRun = false) =>
        api<JsonObject>(`/api/v1/workflows/${workflowId}/execute`, {
            method: 'POST',
            body: JSON.stringify({ input: message, message, dry_run: dryRun, include_trace: true }),
        }),

    saveItem: async (itemType, itemData) => {
        if (itemType === 'agent') {
            const agent = await api<AgentConfig>('/api/v1/agents', {
                method: 'POST',
                body: JSON.stringify(itemToAgentCreate(itemData)),
            });
            await get().fetchLibraryItems();
            return agentToLibraryItem(agent);
        }

        if (itemType === 'tool') {
            const tool = await api<ToolConfig>('/api/v1/tools', {
                method: 'POST',
                body: JSON.stringify(itemToToolCreate(itemData)),
            });
            await get().fetchLibraryItems();
            return toolToLibraryItem(tool);
        }

        const workflow = await get().saveWorkflow(itemData);
        return workflowToLibraryItem(workflow);
    },

    updateItem: async (itemType, itemId, updates) => {
        if (itemType === 'agent') {
            const body = itemToAgentCreate({ ...updates, id: itemId } as Partial<LibraryItem>);
            const agent = await api<AgentConfig>(`/api/v1/agents/${itemId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    name: body.name,
                    system_message: body.system_message,
                    llm_config: body.llm_config,
                    human_input_mode: body.human_input_mode,
                    code_execution_config: body.code_execution_config,
                    tools: body.tools,
                    max_consecutive_auto_reply: body.max_consecutive_auto_reply,
                    retrieve_config: body.retrieve_config,
                    description: body.description,
                }),
            });
            await get().fetchLibraryItems();
            return agentToLibraryItem(agent);
        }

        if (itemType === 'tool') {
            const body = itemToToolCreate({ ...updates, id: itemId } as Partial<LibraryItem>);
            const tool = await api<ToolConfig>(`/api/v1/tools/${itemId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    name: body.name,
                    description: body.description,
                    entrypoint: body.entrypoint,
                    enabled: body.enabled,
                    settings: body.settings,
                }),
            });
            await get().fetchLibraryItems();
            return toolToLibraryItem(tool);
        }

        const workflow = await get().saveWorkflow({ currentId: itemId, update: updates });
        return workflowToLibraryItem(workflow);
    },

    deleteItem: async (itemType, itemId) => {
        const path = itemType === 'agent'
            ? `/api/v1/agents/${itemId}`
            : itemType === 'tool'
                ? `/api/v1/tools/${itemId}`
                : `/api/v1/workflows/${itemId}`;
        await api<void>(path, { method: 'DELETE' });
        await get().fetchLibraryItems();
    },

    executeTool: (toolId, args) => api<JsonObject>(`/api/v1/tools/${toolId}/execute`, {
        method: 'POST',
        body: JSON.stringify({ args }),
    }),

    createFunctionTool: async (body) => {
        const created = await api<FunctionTool>('/api/v1/functions', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        await get().fetchLibraryItems();
        return created;
    },

    getFunctionSource: (toolId) => api<{ tool_id: string; source: string }>(`/api/v1/functions/${toolId}/source`),

    deleteFunctionTool: async (toolId) => {
        await api<void>(`/api/v1/functions/${toolId}`, { method: 'DELETE' });
        await get().fetchLibraryItems();
    },

    savePrompt: async (body) => {
        const id = slugify(String(body.id ?? body.name ?? ''), 'prompt');
        const prompt = await api<PromptTemplate>('/api/v1/prompts', {
            method: 'POST',
            body: JSON.stringify({
                id,
                name: body.name ?? id,
                description: body.description ?? '',
                template: body.template ?? '',
                variables: body.variables ?? [],
                category: body.category ?? null,
            }),
        });
        await get().fetchLibraryItems();
        return prompt;
    },

    updatePrompt: async (promptId, body) => {
        const prompt = await api<PromptTemplate>(`/api/v1/prompts/${promptId}`, {
            method: 'PUT',
            body: JSON.stringify(body),
        });
        await get().fetchLibraryItems();
        return prompt;
    },

    deletePrompt: async (promptId) => {
        await api<void>(`/api/v1/prompts/${promptId}`, { method: 'DELETE' });
        await get().fetchLibraryItems();
    },

    saveProvider: async (body) => {
        const id = slugify(String(body.id ?? body.name ?? ''), 'provider');
        const provider = await api<ApiProvider>('/api/v1/api-providers', {
            method: 'POST',
            body: JSON.stringify({
                id,
                name: body.name ?? id,
                type: body.type ?? 'llm',
                description: body.description ?? '',
                base_url: body.base_url ?? null,
                api_key: body.api_key ?? null,
                api_key_env: body.api_key_env ?? null,
                litellm_prefix: body.litellm_prefix ?? null,
                models: body.models ?? null,
                enabled: body.enabled ?? true,
                config: body.config ?? {},
            }),
        });
        await get().fetchLibraryItems();
        return provider;
    },

    updateProvider: async (providerId, body) => {
        const provider = await api<ApiProvider>(`/api/v1/api-providers/${providerId}`, {
            method: 'PUT',
            body: JSON.stringify(body),
        });
        await get().fetchLibraryItems();
        return provider;
    },

    deleteProvider: async (providerId) => {
        await api<void>(`/api/v1/api-providers/${providerId}`, { method: 'DELETE' });
        await get().fetchLibraryItems();
    },

    testProvider: (providerId) => api<JsonObject>(`/api/v1/api-providers/${providerId}/test`, { method: 'POST' }),

    // Reads the provider's live /models catalogue so pickers do not depend on
    // the hardcoded list in api_providers.json going stale.
    fetchProviderModels: (providerId) => api<JsonObject>(`/api/v1/api-providers/${providerId}/models`),

    previewSwagger: async (url) => api<JsonObject>('/api/v1/tools/import-swagger/preview', {
        method: 'POST',
        body: JSON.stringify({ swagger_url: url }),
    }),

    importSwagger: async (url, selectedEndpoints) => {
        const result = await api<JsonObject>('/api/v1/tools/import-swagger', {
            method: 'POST',
            body: JSON.stringify({ swagger_url: url, endpoint_filter: selectedEndpoints }),
        });
        await get().fetchLibraryItems();
        return result;
    },
}));

export type { ItemType, LibraryItem };

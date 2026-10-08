import type { LibraryItem } from '../api/backendTypes';
import type { VisualNode } from '../types/workflow';
import type { JsonObject } from '../types/json';

type ConfigLike = JsonObject | undefined;

const asArray = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

const modelConfig = (config: ConfigLike) => config?.model_config ?? config?.llm_config ?? {};

export const compactModelName = (model?: string) => {
    if (!model) return 'No model';
    return model.split('/').pop() || model;
};

export const getAgentSummary = (config: ConfigLike) => {
    const model = modelConfig(config);
    const tools = asArray(config?.tools);
    const missingModel = !model?.model;
    const missingInstructions = !config?.instruction && !config?.system_message;

    return {
        strategy: String(config?.type ?? 'LlmAgent'),
        provider: String(model?.provider_id ?? 'provider'),
        model: compactModelName(String(model?.model ?? '')),
        toolCount: tools.length,
        tools,
        isSelector: Boolean(config?.is_selector),
        humanInput: String(config?.human_input_mode ?? 'NEVER'),
        health: missingModel || missingInstructions ? 'warning' as const : 'ready' as const,
        issues: [
            missingModel ? 'Missing model' : '',
            missingInstructions ? 'Missing instructions' : '',
        ].filter(Boolean),
    };
};

export const getToolSummary = (config: ConfigLike) => {
    const type = String(config?.type ?? 'function');
    const method = String(config?.http_method ?? 'GET');
    const auth = String(config?.auth_type ?? 'none');

    // Per-type readiness: which required field is missing, and what to show as
    // the "endpoint" (the thing this tool points at).
    let missing = '';
    let endpoint = String(config?.api_url ?? config?.entrypoint ?? '');
    if (type === 'api') {
        if (!config?.api_url) missing = 'Missing API URL';
    } else if (type === 'mcp') {
        const transport = String(config?.transport ?? 'stdio');
        endpoint = transport === 'stdio'
            ? [config?.command, ...(config?.args ?? [])].filter(Boolean).join(' ')
            : String(config?.url ?? '');
        if (transport === 'stdio' && !config?.command) missing = 'Missing command';
        if (transport !== 'stdio' && !config?.url) missing = 'Missing server URL';
    } else if (type === 'database') {
        endpoint = String(config?.db_uri_env_var ? `env:${config.db_uri_env_var}` : (config?.db_uri ?? ''));
        if (!config?.db_uri && !config?.db_uri_env_var) missing = 'Missing database URI';
    } else if (type === 'gmail') {
        endpoint = String(config?.account_email ?? '');
        if (!config?.account_email) missing = 'Missing account email';
    } else if (type === 'memory' || type === 'knowledge') {
        // Canvas helper nodes — always configured enough to display.
        endpoint = type;
    } else if (!config?.entrypoint) {
        missing = 'Missing entrypoint';
    }

    return {
        type,
        method,
        auth,
        endpoint,
        transport: String(config?.transport ?? ''),
        accountEmail: String(config?.account_email ?? ''),
        enabled: config?.enabled !== false,
        health: missing ? 'warning' as const : 'ready' as const,
        issues: missing ? [missing] : [],
    };
};

export const getWorkflowSummary = (config: ConfigLike) => {
    const topology = config?.topology ?? {};
    const nodes = asArray(topology.nodes ?? config?.nodes);
    const edges = asArray(topology.edges ?? config?.edges);

    return {
        pattern: String(config?.pattern ?? topology.type ?? 'workflow'),
        nodeCount: nodes.length || Number(config?.nodes?.length ?? 0),
        edgeCount: edges.length || Number(config?.edges?.length ?? 0),
        entryNode: String(topology.entry_node ?? config?.entry_agent_id ?? 'not set'),
        health: topology.entry_node || config?.entry_agent_id ? 'ready' as const : 'warning' as const,
        issues: topology.entry_node || config?.entry_agent_id ? [] : ['Missing entry node'],
    };
};

export const getNodeSummary = (node: VisualNode) => {
    if (node.type === 'agent') return getAgentSummary(node.data?.config);
    if (node.type === 'tool') return getToolSummary(node.data?.config);
    if (node.type === 'workflow') return getWorkflowSummary(node.data?.config);
    return null;
};

export const countAgentUsage = (agents: LibraryItem[], workflows: LibraryItem[]) => {
    const usage = new Map<string, number>();
    agents.forEach((agent) => usage.set(agent.id, 0));
    workflows.forEach((workflow) => {
        const nodes = workflow.config?.topology?.nodes ?? workflow.config?.nodes ?? [];
        nodes.forEach((node: JsonObject) => {
            const agentId = String(node.agent_id ?? node.id ?? '');
            if (usage.has(agentId)) usage.set(agentId, (usage.get(agentId) ?? 0) + 1);
        });
    });
    return usage;
};

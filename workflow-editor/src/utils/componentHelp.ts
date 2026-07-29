import type { VisualNode } from '../types/workflow';
import type { Diagnostic } from './graphDiagnostics';

/**
 * What each canvas component is and how to use it.
 *
 * Keyed by `type` or `type.config.type`, matching the palette in Sidebar.tsx.
 * The wording follows README's "Core concepts" so the studio and the docs say
 * the same thing.
 */
export interface ComponentHelp {
    id: string;
    label: string;
    summary: string;
    /** Markdown — the Help panel renders it with react-markdown. */
    body: string;
    inputs: string;
    outputs: string;
    /** Diagnostic codes that typically point at this component. */
    commonIssues: string[];
}

export const COMPONENT_HELP: Record<string, ComponentHelp> = {
    trigger: {
        id: 'trigger',
        label: 'Trigger',
        summary: 'How a workflow gets invoked.',
        body: [
            'A trigger is the entry point. Three kinds exist:',
            '',
            '- **Manual** — run it yourself from the studio. Good while building.',
            '- **Chat** — exposes a chat endpoint; this is what a deployed chatbot page talks to.',
            '- **Webhook** — an HTTP endpoint other systems can POST to. Issued with a secret.',
            '',
            'A workflow without a trigger still runs from the studio, but nothing external can start it.',
        ].join('\n'),
        inputs: 'None — this is where a run begins.',
        outputs: 'The incoming message, passed to the agent it connects to.',
        commonIssues: ['no_trigger', 'orphan_node', 'nodes_dropped_on_save'],
    },
    agent: {
        id: 'agent',
        label: 'CrewAI Agent',
        summary: 'A model with a role, instructions and tools.',
        body: [
            'An agent is the unit that does work. It needs:',
            '',
            '- **A provider and model** — which LLM answers. Without these it falls back to the server default.',
            '- **Instructions** — the system prompt defining its behaviour.',
            '- **Tools** *(optional)* — capabilities it may call, attached to the bottom `tools` handle.',
            '',
            'Under **Agent limits** you can cap the number of reasoning iterations (`max_iter`),',
            'wall-clock time, retries and request rate. Under **Sampling** you control temperature',
            'and the output token limit. Only parameters your provider actually supports are shown.',
            '',
            'Marking an agent a **selector** lets it delegate to the agents downstream of it.',
        ].join('\n'),
        inputs: 'A message from a trigger or the preceding agent.',
        outputs: 'Its answer, passed downstream or returned as the workflow result.',
        commonIssues: [
            'provider_missing',
            'provider_key_missing',
            'model_unknown_for_provider',
            'config_missing_model',
            'config_missing_instructions',
            'agent_not_saved',
            'selector_without_branches',
        ],
    },
    tool: {
        id: 'tool',
        label: 'Tool',
        summary: 'Something an agent can call.',
        body: [
            'Tools extend an agent beyond text. Built-in ones include web search, a calculator,',
            'weather and the RAG family. You can add your own as a Python function, a REST',
            'endpoint, an MCP server, or by importing an OpenAPI/Swagger spec.',
            '',
            '**How to use one**',
            '',
            '1. Drop the tool on the canvas and fill in its settings in the inspector.',
            '2. **Save it to the library.** A tool that exists only on the canvas is not',
            '   registered on the backend, so at run time it resolves to nothing and the agent',
            '   quietly runs without it.',
            '3. Drag from the tool\'s top handle onto an agent\'s **tools** handle.',
            '',
            'A disabled tool is ignored at run time even if an agent still references it.',
        ].join('\n'),
        inputs: 'Arguments the agent decides to pass.',
        outputs: 'A result the agent reads before continuing.',
        commonIssues: [
            'tool_missing',
            'tool_not_registered',
            'tool_disabled_but_referenced',
            'invalid_attachment',
            'config_missing_entrypoint',
        ],
    },
    'tool.memory': {
        id: 'tool.memory',
        label: 'Memory Store',
        summary: 'Lets an agent remember across turns.',
        body: [
            'Attach to an agent\'s **memory** handle to give it recall beyond the current message.',
            'The agent is then built with CrewAI memory enabled, and the crew shares a memory',
            'store scoped by `retention` (per-session by default).',
            '',
            'Without a Memory node the workflow saves with memory **off** — it is the node that',
            'switches it on, so a chatbot that should remember earlier turns needs one.',
            '',
            'Memory only attaches to the memory handle — dropping it on the tools handle is rejected.',
        ].join('\n'),
        inputs: 'Conversation history.',
        outputs: 'Relevant prior context, injected into the agent\'s prompt.',
        commonIssues: ['invalid_attachment'],
    },
    'tool.knowledge': {
        id: 'tool.knowledge',
        label: 'Knowledge Source',
        summary: 'Grounds an agent in your documents.',
        body: [
            'Attach to an agent\'s **knowledge** handle to retrieve from an indexed corpus (RAG).',
            '',
            'Name the **collections** to search and set `top_k`. At run time the agent is given a',
            '`search_knowledge` tool pinned to exactly those collections, so it only supplies the',
            'query. This needs the RAG service reachable — `RAG_PIPELINE_ENABLED=true` and',
            '`RAG_PIPELINE_BASE_URL` — and at least one collection: with no collection named,',
            'no search tool is created and the agent is left with the workflow description alone.',
        ].join('\n'),
        inputs: 'The agent\'s query.',
        outputs: 'Retrieved passages added to the agent\'s context.',
        commonIssues: ['invalid_attachment', 'knowledge_without_collections'],
    },
    'tool.mcp': {
        id: 'tool.mcp',
        label: 'MCP Server',
        summary: 'Tools served by a Model Context Protocol server.',
        body: [
            'Connects to an MCP server over stdio (a local command) or HTTP (a URL), exposing',
            'its tools to the agent. Use the tool filter to expose only some of them.',
            '',
            'One MCP node is one server, and it expands into that server\'s whole tool list.',
            'Press **Save to Library** after configuring it — that is what registers it on the',
            'backend. The connection is opened per run and closed when the run ends.',
        ].join('\n'),
        inputs: 'Tool calls from the agent.',
        outputs: 'Whatever the MCP server returns.',
        commonIssues: ['config_missing_command', 'config_missing_server_url', 'tool_not_registered'],
    },
    'tool.database': {
        id: 'tool.database',
        label: 'Database',
        summary: 'Natural-language querying over SQL.',
        body: [
            'Give the agent a database connection so it can answer questions from your data.',
            'The table and column names are introspected at run time and put in the tool',
            'description, so the model writes SQL against the real schema.',
            '',
            'Prefer `db_uri_env_var` over pasting a connection string. Writes stay off unless',
            'you enable DML explicitly. Save to the library to register it.',
        ].join('\n'),
        inputs: 'A question, translated to SQL.',
        outputs: 'Query results.',
        commonIssues: ['config_missing_database_uri', 'tool_not_registered'],
    },
    'tool.gmail': {
        id: 'tool.gmail',
        label: 'Gmail',
        summary: 'Read, search and send mail.',
        body: [
            'Requires Google OAuth to be configured and the account connected under Integrations.',
            '',
            'Each capability you tick becomes a separate tool on the agent —',
            '`send_email`, `search_emails`, `read_email` — so leaving `send` off is a real',
            'restriction, not a hint. Save to the library to register it.',
        ].join('\n'),
        inputs: 'Search terms or a message to send.',
        outputs: 'Matching messages, or the result of sending.',
        commonIssues: ['config_missing_account_email', 'tool_not_registered'],
    },
    router: {
        id: 'router',
        label: 'Flow Router',
        summary: 'Branches the flow between paths.',
        body: [
            'Fans a run out to several agents and lets the agent feeding it choose between them.',
            '',
            '**How to use it**',
            '',
            'Wire `agent → router → {agent A, agent B, …}`. On save the router itself is compiled',
            'away, but its connections are kept: the graph is stored as `agent → A` and',
            '`agent → B`, and the upstream agent is marked a router so it can delegate to those',
            'branches. The workflow runs as a hierarchical crew.',
            '',
            'It needs **at least two** outgoing connections to mean anything — with one it is',
            'just a hand-off. Marking an agent a **selector** in its own inspector does the same',
            'thing without the extra node.',
        ].join('\n'),
        inputs: 'The upstream result.',
        outputs: 'The same payload, sent to the branch the upstream agent picks.',
        commonIssues: ['router_without_branches', 'orphan_node'],
    },
    'router.guardrail': {
        id: 'router.guardrail',
        label: 'Guardrail',
        summary: 'Constrains the shape of the output.',
        body: [
            'Validates the final result and makes the agent retry (twice) when it does not conform.',
            '',
            '**How to use it**',
            '',
            'Put it anywhere in the flow — it is compiled into a workflow-level setting rather',
            'than a step, so it always checks the **final** output. Set its output schema to:',
            '',
            '- `text` — rejects an empty answer.',
            '- `json` — additionally requires the answer to parse as JSON, fenced code blocks',
            '  included, and re-prompts for pure JSON when it does not.',
            '',
            'Without a Guardrail node on the canvas the workflow saves with guardrails off.',
        ].join('\n'),
        inputs: 'The result being checked.',
        outputs: 'The validated result, or a retry.',
        commonIssues: [],
    },
    output: {
        id: 'output',
        label: 'Output',
        summary: 'Marks where the result leaves the workflow.',
        body: [
            'A visual terminator showing where the answer surfaces.',
            '',
            '> Output nodes are not persisted to the topology — they carry no configuration.',
            '> The last agent to run supplies the workflow result either way.',
        ].join('\n'),
        inputs: 'The final agent\'s answer.',
        outputs: 'The workflow response.',
        commonIssues: ['nodes_dropped_on_save', 'orphan_node'],
    },
    workflow: {
        id: 'workflow',
        label: 'Workflow',
        summary: 'The whole graph of agents.',
        body: [
            'A workflow is a topology of agents plus how they hand off. The pattern is inferred',
            'from your canvas: a single agent, a sequential pipeline, or a graph when a selector',
            'or parallel branches are present.',
            '',
            'Crew-level settings cover planning, tool caching, a request-rate cap, and which',
            'model the hierarchical **manager** uses when agents delegate.',
        ].join('\n'),
        inputs: 'The triggering message.',
        outputs: 'The final agent\'s answer.',
        commonIssues: ['workflow_empty', 'no_agent', 'cycle_detected', 'nodes_dropped_on_save'],
    },
};

/** Help for a node, most specific first (`tool.memory` before `tool`). */
export function helpForNode(node: VisualNode): ComponentHelp | undefined {
    const configType = String(node.data?.config?.type ?? '');
    return COMPONENT_HELP[`${node.type}.${configType}`] ?? COMPONENT_HELP[String(node.type)];
}

export function helpForDiagnostic(diagnostic: Diagnostic): ComponentHelp | undefined {
    if (diagnostic.component && COMPONENT_HELP[diagnostic.component]) {
        return COMPONENT_HELP[diagnostic.component];
    }
    return Object.values(COMPONENT_HELP).find((entry) => entry.commonIssues.includes(diagnostic.code));
}

export const ALL_COMPONENT_HELP = Object.values(COMPONENT_HELP);

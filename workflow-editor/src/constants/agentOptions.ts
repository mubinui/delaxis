/**
 * Shared agent option lists and field specs.
 *
 * PropertiesPanel and LibraryModal previously kept their own copies of these
 * lists, so a field added to one silently went missing in the other. Both now
 * render from here.
 */

export const AGENT_TYPES = [
    { id: 'LlmAgent', name: 'LLM Agent (Chat/Reasoning)' },
    { id: 'RecursiveAgent', name: 'Recursive Selector Agent' },
    { id: 'SequentialAgent', name: 'Sequential Agent' },
    { id: 'ParallelAgent', name: 'Parallel Agent' },
    { id: 'LoopAgent', name: 'Loop Agent' },
    { id: 'conversable', name: 'Conversable Agent (Legacy)' },
];

export const HUMAN_INPUT_MODES = [
    { id: 'NEVER', name: 'Never' },
    { id: 'ALWAYS', name: 'Always' },
    { id: 'TERMINATE', name: 'Terminate' },
];

export interface FieldSpec {
    key: string;
    label: string;
    help: string;
    kind: 'number' | 'slider' | 'toggle';
    min?: number;
    max?: number;
    step?: number;
    placeholder?: string;
    /**
     * Which CrewAI routes honour this parameter. Undefined means all of them.
     * Provider classes ignore unknown kwargs silently, so a field shown for a
     * route that drops it would look applied while doing nothing.
     */
    providers?: string[];
}

/** Agent constructor settings — verified present and non-deprecated in crewai 1.14.4. */
export const AGENT_SETTING_FIELDS: FieldSpec[] = [
    {
        key: 'max_iter',
        label: 'Number of iterations',
        help: 'How many reasoning steps the agent may take on one task before it must answer.',
        kind: 'number',
        min: 1,
        max: 100,
        placeholder: '20',
    },
    {
        key: 'max_execution_time',
        label: 'Time limit (seconds)',
        help: 'Abandon the task if it runs longer than this. Blank means no limit.',
        kind: 'number',
        min: 1,
        placeholder: 'no limit',
    },
    {
        key: 'max_retry_limit',
        label: 'Retry limit',
        help: 'Retries when the agent errors. CrewAI default is 2.',
        kind: 'number',
        min: 0,
        max: 10,
        placeholder: '2',
    },
    {
        key: 'max_rpm',
        label: 'Requests per minute',
        help: 'Throttle this agent\'s LLM calls. Useful against rate limits.',
        kind: 'number',
        min: 1,
        placeholder: 'unlimited',
    },
    {
        key: 'respect_context_window',
        label: 'Respect context window',
        help: 'Summarise history to stay inside the model\'s window. This is the only lever on input size — CrewAI has no input-token cap.',
        kind: 'toggle',
    },
    {
        key: 'allow_delegation',
        label: 'Allow delegation',
        help: 'Let this agent hand work to its peers. Defaults on for selector agents.',
        kind: 'toggle',
    },
    {
        key: 'cache',
        label: 'Cache tool results',
        help: 'Reuse identical tool calls within a run.',
        kind: 'toggle',
    },
    {
        key: 'verbose',
        label: 'Verbose logging',
        help: 'Log this agent\'s reasoning steps to the server console.',
        kind: 'toggle',
    },
];

/** Sampling parameters. `providers` gates each one to the routes that accept it. */
export const LLM_PARAM_FIELDS: FieldSpec[] = [
    {
        key: 'temperature',
        label: 'Temperature',
        help: 'Higher is more varied, lower is more deterministic.',
        kind: 'slider',
        min: 0,
        max: 2,
        step: 0.05,
    },
    {
        key: 'max_tokens',
        label: 'Max output tokens',
        help: 'Cap on the reply length. Reasoning models spend part of this budget thinking, so very low values can return an empty answer.',
        kind: 'number',
        min: 1,
        placeholder: '2048',
    },
    {
        key: 'top_p',
        label: 'Top P',
        help: 'Nucleus sampling cutoff. Usually adjust this or temperature, not both.',
        kind: 'slider',
        min: 0,
        max: 1,
        step: 0.05,
    },
    {
        key: 'top_k',
        label: 'Top K',
        help: 'Consider only the K most likely tokens.',
        kind: 'number',
        min: 1,
        providers: ['gemini'],
    },
    {
        key: 'seed',
        label: 'Seed',
        help: 'Fixed seed for reproducible output where the provider supports it.',
        kind: 'number',
        min: 0,
        providers: ['openai', 'openrouter', 'deepseek', 'ollama', 'hosted_vllm', 'dashscope', 'cerebras', 'azure'],
    },
    {
        key: 'frequency_penalty',
        label: 'Frequency penalty',
        help: 'Discourage repeating the same tokens.',
        kind: 'slider',
        min: -2,
        max: 2,
        step: 0.1,
        providers: ['openai', 'openrouter', 'deepseek', 'ollama', 'hosted_vllm', 'dashscope', 'cerebras', 'azure'],
    },
    {
        key: 'presence_penalty',
        label: 'Presence penalty',
        help: 'Encourage introducing new topics.',
        kind: 'slider',
        min: -2,
        max: 2,
        step: 0.1,
        providers: ['openai', 'openrouter', 'deepseek', 'ollama', 'hosted_vllm', 'dashscope', 'cerebras', 'azure'],
    },
    {
        key: 'timeout',
        label: 'Timeout (seconds)',
        help: 'Give up on a single LLM call after this long.',
        kind: 'number',
        min: 1,
        placeholder: '120',
    },
];

/**
 * Fields a route honours.
 *
 * Pass the *effective* provider from GET /api-providers/{id}/capabilities, not
 * the declared one: a native SDK that is not installed falls back to the
 * OpenAI-compatible route, which accepts a different set.
 */
export function fieldsForProvider(specs: FieldSpec[], crewaiProvider?: string): FieldSpec[] {
    if (!crewaiProvider) return specs;
    return specs.filter((spec) => !spec.providers || spec.providers.includes(crewaiProvider));
}

/** Params this route drops, so the UI can say so instead of failing silently. */
export function unsupportedFields(specs: FieldSpec[], crewaiProvider?: string): string[] {
    if (!crewaiProvider) return [];
    return specs.filter((spec) => spec.providers && !spec.providers.includes(crewaiProvider)).map((s) => s.label);
}

/**
 * Simulated CrewAI runtime for the demo build.
 *
 * Produces the same `ResponseDelta` frames as `src/core/events.py` so the canvas,
 * execution timeline, and chat panel behave exactly as they do against a real
 * backend — only the LLM call is replaced with scripted output. Arithmetic is
 * genuinely evaluated so the calculator specialist gives real answers.
 */
import type { Json } from './store';
import { state } from './store';

/** Every specialist the seeded agents can route to, with the tool it calls. */
const SPECIALISTS = [
    {
        agentId: 'calculator_agent',
        tool: 'calculate',
        domain: 'math',
        matches: (message: string) => /\d\s*[+\-*/^]\s*\d|calculat|arithmetic|how much is|what is \d/i.test(message),
    },
    {
        agentId: 'search_assistant',
        tool: 'web_search',
        domain: 'web_search',
        matches: (message: string) => /search|news|weather|latest|who is|what is happening|current/i.test(message),
    },
    {
        agentId: 'rag_assistant',
        tool: 'rag_query',
        domain: 'knowledge_base',
        matches: (message: string) => /document|knowledge base|policy|handbook|our |internal|kb\b|onboarding/i.test(message),
    },
] as const;

/**
 * Evaluate a simple arithmetic expression without `eval`.
 *
 * Shunting-yard over a strict token set — anything the tokenizer doesn't
 * recognise aborts, so no user string can reach a code path that executes it.
 */
export const evaluateArithmetic = (expression: string): number | null => {
    const tokens = expression.match(/\d+\.?\d*|[+\-*/()^]/g);
    if (!tokens) return null;

    const precedence: Record<string, number> = { '+': 1, '-': 1, '*': 2, '/': 2, '^': 3 };
    const output: (number | string)[] = [];
    const operators: string[] = [];

    for (const token of tokens) {
        if (/^\d/.test(token)) {
            output.push(Number(token));
        } else if (token === '(') {
            operators.push(token);
        } else if (token === ')') {
            while (operators.length && operators[operators.length - 1] !== '(') {
                output.push(operators.pop()!);
            }
            if (operators.pop() !== '(') return null;
        } else {
            while (
                operators.length &&
                operators[operators.length - 1] !== '(' &&
                precedence[operators[operators.length - 1]] >= precedence[token]
            ) {
                output.push(operators.pop()!);
            }
            operators.push(token);
        }
    }
    while (operators.length) {
        const operator = operators.pop()!;
        if (operator === '(') return null;
        output.push(operator);
    }

    const stack: number[] = [];
    for (const token of output) {
        if (typeof token === 'number') {
            stack.push(token);
            continue;
        }
        const right = stack.pop();
        const left = stack.pop();
        if (left === undefined || right === undefined) return null;
        if (token === '+') stack.push(left + right);
        else if (token === '-') stack.push(left - right);
        else if (token === '*') stack.push(left * right);
        else if (token === '/') stack.push(right === 0 ? NaN : left / right);
        else if (token === '^') stack.push(left ** right);
    }

    const result = stack.pop();
    return stack.length === 0 && result !== undefined && Number.isFinite(result) ? result : null;
};

export interface RoutedAnswer {
    agentId: string;
    tool: string;
    domain: string;
    toolArgs: Json;
    toolResult: Json;
    response: string;
}

const DEMO_NOTE = '\n\n_Scripted response — this demo runs without an LLM backend._';

/** Pick the specialist for a message and produce its tool call plus final answer. */
export const routeMessage = (message: string): RoutedAnswer => {
    const specialist = SPECIALISTS.find((candidate) => candidate.matches(message)) ?? SPECIALISTS[1];

    if (specialist.agentId === 'calculator_agent') {
        const value = evaluateArithmetic(message);
        const expression = message.match(/[\d.+\-*/()^\s]{3,}/)?.[0].trim() ?? message;
        return {
            agentId: specialist.agentId,
            tool: specialist.tool,
            domain: specialist.domain,
            toolArgs: { expression },
            toolResult: { result: value, expression },
            response:
                value === null
                    ? `I couldn't parse an arithmetic expression from that. Try something like \`(12 + 8) * 3\`.${DEMO_NOTE}`
                    : `**${expression} = ${value}**\n\nI routed this to the \`calculator_agent\` specialist, which called the \`calculate\` tool. This particular answer is computed for real in the browser.`,
        };
    }

    if (specialist.agentId === 'rag_assistant') {
        return {
            agentId: specialist.agentId,
            tool: specialist.tool,
            domain: specialist.domain,
            toolArgs: { query: message, collection: 'default', top_k: 3 },
            toolResult: {
                matches: [
                    { source: 'onboarding-guide.md', score: 0.88, snippet: 'New engineers get repository access on day one…' },
                    { source: 'architecture.md', score: 0.81, snippet: 'The runtime translates workflow JSON into a CrewAI crew…' },
                ],
            },
            response:
                `Here's what the knowledge base returned for **"${message}"**:\n\n` +
                '| Source | Score | Snippet |\n|---|---|---|\n' +
                '| `onboarding-guide.md` | 0.88 | New engineers get repository access on day one… |\n' +
                '| `architecture.md` | 0.81 | The runtime translates workflow JSON into a CrewAI crew… |\n\n' +
                `The \`rag_assistant\` handled this via the \`rag_query\` tool against the \`default\` collection.${DEMO_NOTE}`,
        };
    }

    return {
        agentId: specialist.agentId,
        tool: specialist.tool,
        domain: specialist.domain,
        toolArgs: { query: message, max_results: 3 },
        toolResult: {
            results: [
                { title: 'Open Agent Kit — GitHub', url: 'https://github.com/mubinui/open-agent-kit' },
                { title: 'CrewAI documentation', url: 'https://docs.crewai.com' },
            ],
        },
        response:
            `The \`search_assistant\` specialist picked this up and called the \`web_search\` tool for **"${message}"**.\n\n` +
            'Top results it would summarise:\n\n' +
            '1. [Open Agent Kit — GitHub](https://github.com/mubinui/open-agent-kit)\n' +
            '2. [CrewAI documentation](https://docs.crewai.com)\n\n' +
            `Run the project locally with your own API key to get live search and a real model answer.${DEMO_NOTE}`,
    };
};

/** Resolve a workflow's topology into the canvas node ids the run should light up. */
const runPlan = (workflow: Json | undefined, routed: RoutedAnswer) => {
    const nodes: Json[] = workflow?.topology?.nodes ?? [];
    if (nodes.length === 0) return [{ nodeId: 'agent', agentId: routed.agentId }];

    const entryId = workflow?.topology?.entry_node;
    const entry = nodes.find((node) => node.id === entryId) ?? nodes[0];
    const target = nodes.find((node) => node.agent_id === routed.agentId);

    // A selector workflow visits the router, then the chosen specialist; a linear
    // one just walks its declared nodes in order.
    const isSelector = Boolean(workflow?.topology?.domain_agents?.length);
    const chain = isSelector && target && target.id !== entry.id ? [entry, target] : nodes;

    return chain.map((node) => ({ nodeId: node.id, agentId: node.agent_id ?? node.id }));
};

export interface StreamFrame {
    type: string;
    session_id: string;
    sequence: number;
    payload: Json;
    agent_id: string | null;
    correlation_id: string;
    timestamp: string;
    /** Milliseconds to wait before emitting this frame, so the UI animates. */
    delayMs: number;
}

/** Script the full delta sequence for one workflow run. */
export const buildExecutionFrames = (
    workflowId: string,
    message: string,
    sessionId: string,
): { frames: StreamFrame[]; routed: RoutedAnswer; nodeIo: Json; toolIo: Json } => {
    const workflow = state.workflows.find((item) => item.id === workflowId);
    const routed = routeMessage(message);
    const plan = runPlan(workflow, routed);
    const correlationId = `demo-${Date.now().toString(36)}`;

    const frames: StreamFrame[] = [];
    const nodeIo: Json = {};
    const toolIo: Json = {};
    let sequence = 0;

    const push = (type: string, payload: Json, agentId: string | null, delayMs: number) => {
        frames.push({
            type,
            session_id: sessionId,
            sequence: sequence++,
            payload,
            agent_id: agentId,
            correlation_id: correlationId,
            timestamp: new Date().toISOString(),
            delayMs,
        });
    };

    push('start', { workflow_id: workflowId, message }, null, 120);

    plan.forEach((step, index) => {
        const isLast = index === plan.length - 1;
        push('node_started', { node_id: step.nodeId, agent_id: step.agentId }, step.agentId, 220);
        push('node_input', { node_id: step.nodeId, input: { message } }, step.agentId, 180);
        nodeIo[step.nodeId] = { input: { message } };

        if (!isLast && plan.length > 1) {
            push(
                'agent_transfer',
                { node_id: step.nodeId, target_agent: plan[index + 1].agentId, reason: `Routing to ${routed.domain} specialist` },
                step.agentId,
                260,
            );
            const handoff = { routed_to: plan[index + 1].agentId, domain: routed.domain };
            push('node_output', { node_id: step.nodeId, output: handoff }, step.agentId, 200);
            nodeIo[step.nodeId].output = handoff;
            return;
        }

        push('tool_call_start', { node_id: step.nodeId, name: routed.tool, args: routed.toolArgs }, step.agentId, 260);
        push('tool_call_args', { node_id: step.nodeId, name: routed.tool, args: routed.toolArgs }, step.agentId, 140);
        push('tool_call_result', { node_id: step.nodeId, name: routed.tool, result: routed.toolResult }, step.agentId, 420);
        toolIo[routed.tool] = { input: routed.toolArgs, output: routed.toolResult };

        // Token-by-token so the timeline streams like a real model response.
        for (const chunk of routed.response.match(/\S+\s*/g) ?? []) {
            push('token', { text: chunk }, step.agentId, 18);
        }

        push('node_output', { node_id: step.nodeId, output: { response: routed.response } }, step.agentId, 160);
        nodeIo[step.nodeId].output = { response: routed.response };
    });

    push(
        'done',
        {
            result: { response: routed.response },
            metadata: { node_io: nodeIo, tool_io: toolIo, demo: true, tokens_used: 214, latency_ms: 1840 },
        },
        null,
        200,
    );

    return { frames, routed, nodeIo, toolIo };
};

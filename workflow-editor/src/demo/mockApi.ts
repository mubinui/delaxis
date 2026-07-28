/**
 * Installs a `fetch` interceptor that answers every `/api/v1/*` call from the
 * in-memory demo store, so the Studio runs as a static site on GitHub Pages.
 *
 * Only requests to the API prefix are intercepted; everything else falls through
 * to the real `fetch`, so assets and outbound links keep working.
 */
import type { Json } from './store';
import { nowIso, patch, remove, slugify, state, upsert } from './store';
import type { StreamFrame } from './runtime';
import { buildExecutionFrames, routeMessage } from './runtime';

const API_PREFIX = '/api/v1';
/** The landing page probes this bare path, outside the versioned prefix. */
const ROOT_HEALTH_PATH = '/health';

const json = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });

const notFound = (what: string) => json({ detail: `${what} not found` }, 404);

/** Network-ish pause so loading states in the UI actually render. */
const settle = (ms = 140) => new Promise((resolve) => setTimeout(resolve, ms));

const parseBody = (init: RequestInit): Json => {
    if (typeof init.body !== 'string' || !init.body) return {};
    try {
        return JSON.parse(init.body) as Json;
    } catch {
        return {};
    }
};

/** Replay scripted deltas as a real SSE stream, respecting each frame's delay. */
const sseResponse = (frames: StreamFrame[]) => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
            for (const frame of frames) {
                const { delayMs, ...delta } = frame;
                await settle(delayMs);
                controller.enqueue(encoder.encode(`event: ${delta.type}\ndata: ${JSON.stringify(delta)}\n\n`));
            }
            controller.enqueue(encoder.encode('data: [DONE]\n\n'));
            controller.close();
        },
    });
    return new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    });
};

/** Stream plain text tokens the way `/builder/chat` does. */
const textStream = (text: string) => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
            for (const chunk of text.match(/\S+\s*/g) ?? []) {
                await settle(22);
                controller.enqueue(encoder.encode(chunk));
            }
            controller.close();
        },
    });
    return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/plain' } });
};

const DEMO_BLURB = 'This is the read-only Pages demo, so no model is called. Clone the repo and add an API key to use the real AI Builder.';

/** Drop a submitted key: the demo never stores one, and only ever echoes a mask. */
const withoutApiKey = (body: Json): Json => {
    const copy = { ...body };
    delete copy.api_key;
    return copy;
};

type Handler = (match: RegExpMatchArray, body: Json, init: RequestInit) => Response | Promise<Response>;

const DEMO_THEMES = [
    {
        "id": "midnight",
        "label": "Midnight",
        "vars": {
            "bg": "#101820",
            "surface": "#121d29",
            "panel": "#0f1720",
            "border": "#263241",
            "text": "#e6edf3",
            "muted": "#9fb0c2",
            "accent": "#2f6fed",
            "accent-text": "#ffffff",
            "assistant-bubble": "#1b2a3a",
            "assistant-border": "#314257",
            "input-bg": "#111c28",
            "input-border": "#34465c",
            "code-bg": "#0b1220",
            "code-text": "#f8fafc",
            "link": "#93c5fd",
            "ok": "#74d99f",
            "shadow": "rgba(0,0,0,.28)"
        }
    },
    {
        "id": "daylight",
        "label": "Daylight",
        "vars": {
            "bg": "#f6f7fb",
            "surface": "#ffffff",
            "panel": "#eef1f7",
            "border": "#d8deea",
            "text": "#172033",
            "muted": "#5b6b83",
            "accent": "#2563eb",
            "accent-text": "#ffffff",
            "assistant-bubble": "#eef3ff",
            "assistant-border": "#dbe4f8",
            "input-bg": "#ffffff",
            "input-border": "#cbd5e1",
            "code-bg": "#111827",
            "code-text": "#f8fafc",
            "link": "#2563eb",
            "ok": "#16a34a",
            "shadow": "rgba(15,23,42,.12)"
        }
    },
    {
        "id": "ocean",
        "label": "Ocean",
        "vars": {
            "bg": "#04121b",
            "surface": "#072433",
            "panel": "#051a26",
            "border": "#12405a",
            "text": "#d8f0fa",
            "muted": "#86b3c7",
            "accent": "#06b6d4",
            "accent-text": "#04222d",
            "assistant-bubble": "#0a3346",
            "assistant-border": "#155a77",
            "input-bg": "#06202e",
            "input-border": "#17506c",
            "code-bg": "#021018",
            "code-text": "#e0f2fe",
            "link": "#67e8f9",
            "ok": "#5eead4",
            "shadow": "rgba(0,0,0,.35)"
        }
    },
    {
        "id": "forest",
        "label": "Forest",
        "vars": {
            "bg": "#0c130d",
            "surface": "#131f15",
            "panel": "#0f1810",
            "border": "#28402b",
            "text": "#e7f0e7",
            "muted": "#9bb59d",
            "accent": "#22c55e",
            "accent-text": "#052e13",
            "assistant-bubble": "#1a2b1c",
            "assistant-border": "#2f4a33",
            "input-bg": "#122014",
            "input-border": "#33523a",
            "code-bg": "#081109",
            "code-text": "#ecfdf5",
            "link": "#86efac",
            "ok": "#4ade80",
            "shadow": "rgba(0,0,0,.32)"
        }
    },
    {
        "id": "sunset",
        "label": "Sunset",
        "vars": {
            "bg": "#1a1023",
            "surface": "#241531",
            "panel": "#1e1229",
            "border": "#3f2a52",
            "text": "#f4e8f7",
            "muted": "#bda3c9",
            "accent": "#f97316",
            "accent-text": "#331303",
            "assistant-bubble": "#2e1c3d",
            "assistant-border": "#4c3361",
            "input-bg": "#251733",
            "input-border": "#503a66",
            "code-bg": "#140b1c",
            "code-text": "#fdf4ff",
            "link": "#fdba74",
            "ok": "#86efac",
            "shadow": "rgba(0,0,0,.35)"
        }
    },
    {
        "id": "mono",
        "label": "Mono",
        "vars": {
            "bg": "#ffffff",
            "surface": "#ffffff",
            "panel": "#f4f4f5",
            "border": "#d4d4d8",
            "text": "#111111",
            "muted": "#52525b",
            "accent": "#111111",
            "accent-text": "#ffffff",
            "assistant-bubble": "#f4f4f5",
            "assistant-border": "#d4d4d8",
            "input-bg": "#ffffff",
            "input-border": "#a1a1aa",
            "code-bg": "#18181b",
            "code-text": "#fafafa",
            "link": "#111111",
            "ok": "#16a34a",
            "shadow": "rgba(0,0,0,.10)"
        }
    }
];

const routes: [string, RegExp, Handler][] = [
    // ---- workflows ----
    ['GET', /^\/workflows$/, () => json(state.workflows)],
    ['GET', /^\/workflows\/([^/]+)$/, (m) => {
        const workflow = state.workflows.find((item) => item.id === m[1]);
        return workflow ? json(workflow) : notFound('Workflow');
    }],
    ['POST', /^\/workflows$/, (_m, body) => {
        const id = slugify(String(body.id ?? body.name ?? ''), 'workflow');
        return json(upsert(state.workflows, { enabled: true, ...body, id, version: 1, last_updated: nowIso() }), 201);
    }],
    ['PUT', /^\/workflows\/([^/]+)$/, (m, body) => {
        const updated = patch(state.workflows, m[1], body);
        // The Studio saves a workflow that only exists on the canvas via PUT, so
        // treat a miss as a create rather than failing the save.
        return json(updated ?? upsert(state.workflows, { ...body, id: m[1], last_updated: nowIso() }));
    }],
    ['DELETE', /^\/workflows\/([^/]+)$/, (m) => (remove(state.workflows, m[1]) ? json(null, 204) : notFound('Workflow'))],
    ['POST', /^\/workflows\/([^/]+)\/validate$/, (m) => {
        const workflow = state.workflows.find((item) => item.id === m[1]);
        if (!workflow) return notFound('Workflow');
        const nodeCount = workflow.topology?.nodes?.length ?? 0;
        return json({
            valid: nodeCount > 0,
            workflow_id: m[1],
            errors: nodeCount > 0 ? [] : ['Workflow has no nodes'],
            warnings: nodeCount > 3 ? ['Large topologies may exceed the default 300s timeout'] : [],
            checked_at: nowIso(),
        });
    }],
    ['POST', /^\/workflows\/([^/]+)\/execute$/, async (m, body) => {
        await settle(600);
        const routed = routeMessage(String(body.message ?? body.input ?? ''));
        return json({
            workflow_id: m[1],
            response: routed.response,
            status: 'completed',
            metadata: { agent_id: routed.agentId, tool: routed.tool, demo: true },
        });
    }],
    ['POST', /^\/workflows\/([^/]+)\/execute\/stream$/, (m, body) => {
        const { frames } = buildExecutionFrames(m[1], String(body.message ?? ''), `demo-session-${Date.now()}`);
        return sseResponse(frames);
    }],

    // ---- agents ----
    ['GET', /^\/agents$/, () => json(state.agents)],
    ['POST', /^\/agents$/, (_m, body) => json(upsert(state.agents, { ...body, id: slugify(String(body.id ?? body.name ?? ''), 'agent') }), 201)],
    ['PUT', /^\/agents\/([^/]+)$/, (m, body) => {
        const updated = patch(state.agents, m[1], body);
        return updated ? json(updated) : notFound('Agent');
    }],
    ['DELETE', /^\/agents\/([^/]+)$/, (m) => (remove(state.agents, m[1]) ? json(null, 204) : notFound('Agent'))],

    // ---- tools ----
    ['GET', /^\/tools$/, () => json(state.tools)],
    ['POST', /^\/tools$/, (_m, body) => json(upsert(state.tools, { enabled: true, settings: {}, ...body, id: slugify(String(body.id ?? body.name ?? ''), 'tool') }), 201)],
    ['PUT', /^\/tools\/([^/]+)$/, (m, body) => {
        const updated = patch(state.tools, m[1], body);
        return updated ? json(updated) : notFound('Tool');
    }],
    ['DELETE', /^\/tools\/([^/]+)$/, (m) => (remove(state.tools, m[1]) ? json(null, 204) : notFound('Tool'))],
    ['POST', /^\/tools\/([^/]+)\/execute$/, async (m, body) => {
        await settle(420);
        const routed = routeMessage(JSON.stringify(body.args ?? {}));
        return json({ tool_id: m[1], status: 'success', result: routed.toolResult, demo: true, elapsed_ms: 412 });
    }],
    ['POST', /^\/tools\/import-swagger\/preview$/, async (_m, body) => {
        await settle(700);
        return json({
            source: body.swagger_url,
            title: 'Demo Petstore API',
            version: '1.0.0',
            endpoints: [
                { operation_id: 'listPets', method: 'GET', path: '/pets', summary: 'List all pets' },
                { operation_id: 'createPet', method: 'POST', path: '/pets', summary: 'Create a pet' },
                { operation_id: 'getPetById', method: 'GET', path: '/pets/{petId}', summary: 'Fetch a pet by id' },
            ],
            demo: true,
        });
    }],
    ['POST', /^\/tools\/import-swagger$/, async (_m, body) => {
        await settle(600);
        const selected: string[] = body.endpoint_filter ?? [];
        const created = selected.map((operationId) =>
            upsert(state.tools, {
                id: slugify(operationId, 'imported_tool'),
                name: operationId,
                description: `Imported from ${body.swagger_url}`,
                entrypoint: 'src.tools.api_executor.execute',
                enabled: true,
                settings: { type: 'api', source: body.swagger_url },
            }),
        );
        return json({ imported: created.length, tools: created, demo: true });
    }],
    ['POST', /^\/tools\/mcp\/inspect$/, async () => {
        await settle(500);
        return json({
            server: 'demo-mcp-server',
            status: 'reachable',
            tools: [
                { name: 'list_files', description: 'List files in a workspace directory' },
                { name: 'read_file', description: 'Read a UTF-8 text file' },
            ],
            demo: true,
        });
    }],

    // ---- function tools ----
    ['GET', /^\/functions$/, () => json({ functions: state.functions, total: state.functions.length })],
    ['POST', /^\/functions$/, (_m, body) => {
        const id = slugify(String(body.id ?? body.name ?? ''), 'function');
        if (typeof body.code === 'string') state.functionSources[id] = body.code;
        return json(upsert(state.functions, {
            id,
            name: body.name ?? id,
            description: body.description ?? '',
            entrypoint: id,
            file_path: `data/functions/${id}.py`,
            enabled: true,
        }), 201);
    }],
    ['GET', /^\/functions\/([^/]+)\/source$/, (m) => {
        const source = state.functionSources[m[1]];
        return source === undefined ? notFound('Function') : json({ tool_id: m[1], source });
    }],
    ['DELETE', /^\/functions\/([^/]+)$/, (m) => {
        delete state.functionSources[m[1]];
        return remove(state.functions, m[1]) ? json(null, 204) : notFound('Function');
    }],

    // ---- prompts ----
    ['GET', /^\/prompts$/, () => json(state.prompts)],
    ['POST', /^\/prompts$/, (_m, body) => json(upsert(state.prompts, { variables: [], ...body, id: slugify(String(body.id ?? body.name ?? ''), 'prompt'), version: 1, last_updated: nowIso() }), 201)],
    ['PUT', /^\/prompts\/([^/]+)$/, (m, body) => {
        const updated = patch(state.prompts, m[1], body);
        return updated ? json(updated) : notFound('Prompt');
    }],
    ['DELETE', /^\/prompts\/([^/]+)$/, (m) => (remove(state.prompts, m[1]) ? json(null, 204) : notFound('Prompt'))],

    // ---- providers ----
    ['GET', /^\/api-providers$/, () => json(state.providers)],
    ['POST', /^\/api-providers$/, (_m, body) => {
        return json(upsert(state.providers, {
            enabled: true,
            config: {},
            models: [],
            ...withoutApiKey(body),
            id: slugify(String(body.id ?? body.name ?? ''), 'provider'),
            api_key_masked: 'sk-demo-****************************',
            last_updated: nowIso(),
        }), 201);
    }],
    ['PUT', /^\/api-providers\/([^/]+)$/, (m, body) => {
        const updated = patch(state.providers, m[1], withoutApiKey(body));
        return updated ? json(updated) : notFound('Provider');
    }],
    ['DELETE', /^\/api-providers\/([^/]+)$/, (m) => (remove(state.providers, m[1]) ? json(null, 204) : notFound('Provider'))],
    ['POST', /^\/api-providers\/([^/]+)\/test$/, async (m) => {
        await settle(650);
        const provider = state.providers.find((item) => item.id === m[1]);
        if (!provider) return notFound('Provider');
        return json({
            provider_id: m[1],
            status: 'ok',
            reachable: true,
            latency_ms: 318,
            models_discovered: provider.models?.length ?? 0,
            detail: 'Simulated connectivity check — the Pages demo makes no outbound calls.',
        });
    }],

    // ---- triggers ----
    ['GET', /^\/triggers$/, (_m, _b, init) => {
        const workflowId = new URL((init as Json).__url).searchParams.get('workflow_id');
        return json(workflowId ? state.triggers.filter((item) => item.workflow_id === workflowId) : state.triggers);
    }],
    ['POST', /^\/triggers$/, (_m, body) => json(upsert(state.triggers, {
        id: `trg_${Math.random().toString(36).slice(2, 9)}`,
        enabled: true,
        auth_mode: 'public',
        greeting: '',
        public_slug: slugify(String(body.name ?? 'trigger'), 'trigger'),
        secret: body.auth_mode === 'api_key' ? 'whsec_demo_****' : null,
        allowed_origins: [],
        input_mapping: {},
        response_mapping: {},
        metadata: {},
        created_at: nowIso(),
        ...body,
        updated_at: nowIso(),
    }), 201)],
    ['PUT', /^\/triggers\/([^/]+)$/, (m, body) => {
        const { rotate_secret: rotate, ...rest } = body;
        const updated = patch(state.triggers, m[1], rotate ? { ...rest, secret: `whsec_demo_${Math.random().toString(36).slice(2, 8)}` } : rest);
        return updated ? json(updated) : notFound('Trigger');
    }],
    ['DELETE', /^\/triggers\/([^/]+)$/, (m) => (remove(state.triggers, m[1]) ? json(null, 204) : notFound('Trigger'))],

    // ---- deployments ----
    ['GET', /^\/deployments$/, () => json(state.deployments)],
    ['GET', /^\/deployments\/themes$/, () => json(DEMO_THEMES)],
    ['POST', /^\/deployments\/preview$/, async (_m, body) => {
        await settle(400);
        const id = slugify(String(body.name ?? body.workflow_id ?? ''), 'deployment').replace(/_/g, '-');
        return json({
            url: `/d/${id}/`,
            path: `data/deployments/${id}`,
            warnings: [],
            html: '<!doctype html><title>Preview</title><p>Deployment preview is generated server-side in a full install.</p>',
        });
    }],
    ['POST', /^\/deployments\/flash$/, async (_m, body) => {
        await settle(900);
        const id = slugify(String(body.name ?? body.workflow_id ?? ''), 'deployment').replace(/_/g, '-');
        return json(upsert(state.deployments, {
            status: 'active',
            theme: 'midnight',
            auth_mode: 'public',
            trigger_id: null,
            api_url: '',
            error: null,
            created_at: nowIso(),
            ...body,
            id,
            name: body.name ?? body.workflow_id,
            title: body.title ?? body.name ?? 'Deployment',
            url: `/d/${id}/`,
            path: `data/deployments/${id}`,
            updated_at: nowIso(),
        }), 201);
    }],
    ['DELETE', /^\/deployments\/([^/]+)$/, (m) => (remove(state.deployments, m[1]) ? json(null, 204) : notFound('Deployment'))],

    // ---- sessions / chat ----
    ['POST', /^\/sessions$/, (_m, body) => {
        const sessionId = `demo-${Math.random().toString(36).slice(2, 11)}`;
        state.sessions[sessionId] = { workflow_id: String(body.workflow_id ?? ''), messages: [] };
        return json({ session_id: sessionId, workflow_id: body.workflow_id, created_at: nowIso() }, 201);
    }],
    ['POST', /^\/sessions\/([^/]+)\/messages$/, async (m, body) => {
        const session = state.sessions[m[1]];
        if (!session) return json({ detail: 'Session not found' }, 404);
        await settle(850);
        const message = String(body.message ?? '');
        const { routed, nodeIo, toolIo } = buildExecutionFrames(session.workflow_id, message, m[1]);
        session.messages.push({ role: 'user', content: message }, { role: 'assistant', content: routed.response });
        return json({
            session_id: m[1],
            response: routed.response,
            status: 'completed',
            metadata: { node_io: nodeIo, tool_io: toolIo, agent_id: routed.agentId, demo: true },
        });
    }],

    // ---- studio ----
    ['GET', /^\/studio\/state$/, () => json(state.studioState)],
    ['POST', /^\/studio\/test-llm$/, async (_m, body) => {
        await settle(900);
        const prompt = String(body.user_prompt ?? '');
        const routed = routeMessage(prompt);
        const completionTokens = Math.max(24, Math.round(routed.response.length / 4));
        return json({
            response: `${routed.response}\n\n---\n\nModel: \`${body.model ?? 'openai/gpt-oss-20b'}\` · Provider: \`${body.provider ?? 'openrouter'}\``,
            latency_ms: 872,
            token_usage: { prompt_tokens: 96, completion_tokens: completionTokens, total_tokens: 96 + completionTokens },
            estimated_cost_usd: Number(((96 * 0.02 + completionTokens * 0.1) / 1_000_000).toFixed(8)),
            status: 'success',
        });
    }],

    // ---- ops ----
    ['GET', /^\/health$/, () => json(state.health)],
    ['GET', /^\/metrics\/dashboard$/, () => json(state.metrics)],
    ['GET', /^\/rag-service$/, () => json(state.ragService)],
    ['GET', /^\/rag-service\/collections$/, () => json(state.ragCollections)],
    ['GET', /^\/integrations\/gmail\/status$/, () => json(state.gmailStatus)],
    ['GET', /^\/integrations\/gmail\/auth-url$/, () => json({ auth_url: null, detail: 'Gmail OAuth is unavailable in the Pages demo.', demo: true })],

    // ---- auth ----
    ['POST', /^\/auth\/token$/, async (_m, _b, init) => {
        await settle(400);
        const form = new URLSearchParams(typeof init.body === 'string' ? init.body : '');
        const username = form.get('username') ?? '';
        if (!username) return json({ detail: 'Username is required' }, 401);
        return json({ access_token: `demo.jwt.${btoa(username).replace(/=/g, '')}`, token_type: 'bearer', expires_in: 3600 });
    }],
    ['GET', /^\/auth\/users\/me$/, () => json({ username: 'demo-user', email: 'demo@example.invalid', role: 'admin', is_active: true, demo: true })],
    ['GET', /^\/auth\/api-keys$/, () => json(state.apiKeys)],
    ['POST', /^\/auth\/api-keys$/, (_m, body) => {
        const id = `key_${Math.random().toString(36).slice(2, 10)}`;
        const prefix = `oak_live_${Math.random().toString(36).slice(2, 6)}`;
        upsert(state.apiKeys, { id, name: body.name ?? 'studio-key', prefix, created_at: nowIso(), last_used_at: null, revoked: false });
        return json({ id, name: body.name ?? 'studio-key', key: `${prefix}_${Math.random().toString(36).slice(2)}demo`, prefix }, 201);
    }],
    ['DELETE', /^\/auth\/api-keys\/([^/]+)$/, (m) => (remove(state.apiKeys, m[1]) ? json(null, 204) : notFound('API key'))],

    // ---- AI builder ----
    ['GET', /^\/builder\/models$/, () => json(state.builderModels)],
    ['POST', /^\/builder\/chat$/, (_m, body) =>
        textStream(`I'd normally design a ${body.builder_type ?? 'workflow'} for you here, wiring agents and tools from your description. ${DEMO_BLURB}`)],
    ['POST', /^\/builder\/generate$/, async (_m, body) => {
        await settle(800);
        return json({
            builder_type: body.builder_type ?? 'agent',
            config: {
                id: 'demo_generated_agent',
                name: 'Demo Generated Agent',
                type: 'conversable',
                system_message: 'You are a helpful assistant generated by the AI Builder.',
                tools: ['web_search'],
            },
            raw: DEMO_BLURB,
        });
    }],
    ['POST', /^\/builder\/plan-chatbot$/, async () => {
        await settle(800);
        return json({
            plan: {
                workflow: { id: 'demo_planned_bot', name: 'Demo Planned Bot', pattern: 'selector' },
                agents: [{ id: 'demo_planner', name: 'Planner', tools: ['web_search'] }],
                tools: ['web_search', 'calculate'],
            },
            summary: `A two-agent chatbot skeleton. ${DEMO_BLURB}`,
        });
    }],
    ['POST', /^\/builder\/normalize-api$/, async () => {
        await settle(700);
        return json({ normalized: { method: 'GET', path: '/pets', parameters: [] }, summary: DEMO_BLURB });
    }],
    ['POST', /^\/builder\/apply$/, async () => {
        await settle(500);
        return json({ applied: false, detail: `Applying a generated plan writes to disk, which the Pages demo cannot do. ${DEMO_BLURB}` });
    }],
    ['POST', /^\/builder\/frontend\/generate$/, async (_m, body) => {
        await settle(900);
        return json({
            html: `<!doctype html><title>${body.title ?? 'Chat'}</title><main><h1>${body.title ?? 'Chat'}</h1><p>${body.greeting ?? 'Hello!'}</p></main>`,
            summary: `A minimal chat page scaffold. ${DEMO_BLURB}`,
            model_id: body.model_id ?? 'openai/gpt-oss-20b',
            provider_id: body.provider_id ?? 'openrouter',
            used_fallback: true,
        });
    }],
];

/** Replace `window.fetch` with the demo router. Safe to call more than once. */
export const installDemoApi = () => {
    const realFetch = window.fetch.bind(window);
    if ((window as Json).__oakDemoInstalled) return;
    (window as Json).__oakDemoInstalled = true;

    window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        const url = new URL(rawUrl, window.location.origin);

        if (url.pathname === ROOT_HEALTH_PATH) return json(state.health);
        if (!url.pathname.startsWith(API_PREFIX)) return realFetch(input, init);

        const path = url.pathname.slice(API_PREFIX.length);
        const method = (init.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
        const body = parseBody(init);

        for (const [routeMethod, pattern, handler] of routes) {
            if (routeMethod !== method) continue;
            const match = path.match(pattern);
            if (!match) continue;
            // Handlers that need the query string read it back off this marker.
            return handler(match, body, Object.assign({}, init, { __url: url.href }));
        }

        return json({ detail: `The Pages demo does not implement ${method} ${url.pathname}.`, demo: true }, 501);
    };
};

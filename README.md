<div align="center">

# 🌳 Open Agent Kit (OAK)

**An open-source multi-agent development kit — design, test, and deploy AI agent workflows from one place.**

[![Docker](https://img.shields.io/github/actions/workflow/status/mubinui/open-agent-kit/docker-release.yml?label=Docker%20Build)](../../actions/workflows/docker-release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CrewAI](https://img.shields.io/badge/runtime-CrewAI-orange.svg)](https://crewai.com)

### [▶ Try the live demo](https://mubinui.github.io/open-agent-kit/)

No install, no API key — the real Studio running against an in-browser stub of the API.

</div>

![Open Agent Kit Studio](docs/images/studio-canvas.png)

---

## Contents

- [What it is](#what-it-is)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Choosing an LLM provider](#choosing-an-llm-provider) — OpenAI, Gemini, Grok, Claude, local models
- [Core concepts](#core-concepts)
- [How it works](#how-it-works)
- [Configuration reference](#configuration-reference)
- [API](#api)
- [Project layout](#project-layout)
- [Development](#development)
- [Production deployment](#production-deployment)
- [Troubleshooting](#troubleshooting)

---

## What it is

Open Agent Kit is a self-hosted platform for building multi-agent AI applications:

- 🎨 **Visual Studio** — a React Flow canvas for composing agent workflows (selector, sequential, parallel topologies) with drag-and-drop agents, tools, and triggers
- 🤖 **CrewAI runtime** — workflows execute on [CrewAI](https://crewai.com), with any LLM via LiteLLM (OpenAI, Gemini, Grok, Claude, OpenRouter, self-hosted vLLM, local Ollama)
- 🛠️ **Tools out of the box** — web search, RAG, a calculator, Gmail, and any REST API via Swagger/OpenAPI import
- ⚡ **Live LLM tester** — validate keys, models, latency, and cost before wiring them into agents
- 🚀 **Flash deployments** — publish any workflow as a standalone chat page served at `/d/<name>/`, embeddable anywhere with an iframe
- 🔐 **Optional auth** — local users + API keys (SQL-backed), or Keycloak SSO
- 📦 **One container** — API, Studio UI, and SQLite persistence in a single Docker image

Everything is configuration-driven. Agents, workflows, tools, prompts, and providers live in `configs/*.json` and are editable via the Studio UI, the REST API, or a text editor (hot-reload in development).

## Screenshots

| Live LLM tester | Deployment hub |
|---|---|
| ![Live LLM tester](docs/images/llm-tester.png) | ![Deployments](docs/images/deployments.png) |

Every screenshot above is from the [live demo](https://mubinui.github.io/open-agent-kit/) — click through it yourself before installing anything.

## Installation

### Prerequisites

| Method | Requirements |
|---|---|
| Docker (recommended) | Docker 24+ (or Docker Desktop) |
| Local development | Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js 22+ |

You'll also want an LLM API key — see [Choosing an LLM provider](#choosing-an-llm-provider). An [OpenRouter](https://openrouter.ai/keys) key works out of the box and reaches every major model with one credential.

### Option 1 — Docker (recommended)

Pull the prebuilt image from GitHub Container Registry:

```bash
docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v oak_data:/app/data \
  ghcr.io/mubinui/open-agent-kit:latest
```

Or build it yourself:

```bash
git clone https://github.com/mubinui/open-agent-kit.git
cd open-agent-kit
docker build -t open-agent-kit .

docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v oak_data:/app/data \
  open-agent-kit
```

Open **http://localhost:8000** — the Studio UI, API (`/docs`), and deployed chatbots are all served from this one container. On first boot the database schema is created automatically on the `oak_data` volume; no other services are required.

### Option 2 — Docker Compose

```bash
git clone https://github.com/mubinui/open-agent-kit.git
cd open-agent-kit
cp .env.example .env        # add your API key
docker compose up
```

Optional production services are behind profiles:

```bash
docker compose --profile postgres up     # PostgreSQL instead of SQLite
docker compose --profile qdrant up       # Qdrant vector store
docker compose --profile redis up        # Redis cache
```

With the `postgres` profile, set `DATABASE_URL=postgresql://oak:oak_pass@postgres:5432/oak` in `.env`.

### Option 3 — Local development

Backend (Python 3.10+, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --extra dev
uv run uvicorn src.api.main:app --reload      # API on :8000
```

Studio (Node 22+):

```bash
cd workflow-editor
npm ci
npm run dev                                    # Vite dev server on :5173, proxies /api to :8000
```

CLI chat:

```bash
uv run oak --workflow demo_multi_agent --message "What is 2 + 2 * 5?"
```

## Choosing an LLM provider

Workflows run on CrewAI, which calls models through [LiteLLM](https://docs.litellm.ai/docs/providers). That means **any LiteLLM-supported provider works** — OpenAI, Google Gemini, xAI Grok, Anthropic Claude, Groq, Mistral, DeepSeek, Azure OpenAI, AWS Bedrock, or a local Ollama/vLLM server.

There are two ways to get there, and the difference matters.

### Path A — one key for everything (OpenRouter, the default)

[OpenRouter](https://openrouter.ai/keys) proxies every major vendor behind a single API key. This is the default and the least fiddly option: set one key, then name any model using **OpenRouter's model id**.

```bash
OPENROUTER_API_KEY=sk-or-...
LLM_MODEL=openai/gpt-4o          # or any id below
```

| You want | `LLM_MODEL` value |
|---|---|
| OpenAI GPT | `openai/gpt-4o`, `openai/gpt-4o-mini` |
| Google Gemini | `google/gemini-2.5-pro`, `google/gemini-2.5-flash` |
| xAI Grok | `x-ai/grok-4` |
| Anthropic Claude | `anthropic/claude-sonnet-4.5` |
| Meta Llama | `meta-llama/llama-3.3-70b-instruct` |
| DeepSeek | `deepseek/deepseek-chat` |
| Open-weight default | `openai/gpt-oss-20b` |

Under the default `LLM_PROVIDER=openrouter`, any `vendor/model` string is automatically prefixed with `openrouter/` before it reaches LiteLLM, so you write the plain OpenRouter id and routing is handled for you. Browse the full catalogue at [openrouter.ai/models](https://openrouter.ai/models).

### Path B — talk to a provider directly

To bill a vendor directly instead of going through OpenRouter, use LiteLLM's own provider prefix and supply that vendor's key.

> [!IMPORTANT]
> Set `LLM_PROVIDER` to something other than `openrouter` (e.g. `LLM_PROVIDER=openai`). Otherwise a string like `xai/grok-4` is rewritten to `openrouter/xai/grok-4` and your direct key is never used. The prefixes `gemini/`, `ollama/`, `azure/`, and `openrouter/` are always passed through untouched and don't need this.

```bash
LLM_PROVIDER=openai              # disables OpenRouter rewriting
LLM_MODEL=gemini/gemini-2.5-pro
GEMINI_API_KEY=...
```

| Provider | `LLM_MODEL` prefix | Key environment variable |
|---|---|---|
| OpenAI | `gpt-4o` (bare) or `openai/gpt-4o` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-pro` | `GEMINI_API_KEY` |
| xAI Grok | `xai/grok-4` | `XAI_API_KEY` |
| Anthropic Claude | `anthropic/claude-sonnet-4.5` | `ANTHROPIC_API_KEY` |
| Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| Azure OpenAI | `azure/<your-deployment>` | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` |

Prefixes and key names follow [LiteLLM's provider conventions](https://docs.litellm.ai/docs/providers) — check there for vendors not listed above.

### Path C — local and self-hosted models

No API key, no egress:

```bash
# Ollama (https://ollama.com) — passed through regardless of LLM_PROVIDER
LLM_MODEL=ollama/llama3.1
OLLAMA_API_BASE=http://localhost:11434

# vLLM or any OpenAI-compatible server
LLM_PROVIDER=local
LLM_API_BASE=http://localhost:8000/v1
LLM_API_KEY=dummy
```

### Per-agent models

The global `LLM_MODEL` is only the default. Each agent can override it in the Studio's properties panel — useful for running a cheap model for routing and an expensive one for the final answer. Agent `model_config` accepts:

| Field | Purpose |
|---|---|
| `model` | LiteLLM model string (resolved exactly as above) |
| `temperature`, `max_tokens`, `top_p`, `timeout` | Sampling and limits |
| `base_url` | Point this agent at a different OpenAI-compatible endpoint |
| `api_key_env` | Name of an environment variable to read this agent's key from |

Use the **Live API** tester in the Studio to verify a key, model, latency, and cost before wiring it into an agent.

## Core concepts

| Concept | What it is |
|---|---|
| **Workflow** | A topology of agents. Patterns: `single`, `sequential` (pipeline), `graph` (selector/parallel). Stored in `configs/workflows.json`. |
| **Agent** | A CrewAI agent — role, goal, backstory, model config, and a list of tools. |
| **Tool** | Something an agent can call. Built in: `web_search`, `calculate`, `get_weather`, the `rag_*` family, Gmail. Add your own as a Python function, a REST endpoint, an MCP server, or a Swagger/OpenAPI import. |
| **Trigger** | How a workflow is invoked — `chat`, `webhook`, or `manual` — each with its own auth mode (`public`, `api_key`, `jwt`). |
| **Deployment** | A flash-published chat page at `/d/<name>/`, embeddable via iframe. |
| **Prompt** | A reusable, versioned template with variables. |

Canvas node types: Manual Trigger, Chat Trigger, Webhook, CrewAI Agent, CrewAI Task, Flow Router, Memory Store, Knowledge Source, Guardrail, MCP Server, Database (NL2SQL), Gmail, Output.

The bundled **demo_multi_agent** workflow routes user questions between three specialists — web search, knowledge base (RAG), and calculator — and is a good starting template.

## How it works

```
┌─────────────────────────────────────────────────────┐
│                   Open Agent Kit                    │
│                                                     │
│  Studio SPA (React 19 + React Flow)   ← served at / │
│  FastAPI backend                      ← /api/v1/*   │
│  Deployed chat pages                  ← /d/<name>/  │
│                                                     │
│  CrewAI runtime ──→ LiteLLM ──→ any LLM provider    │
│                                                     │
│  configs/*.json   agents · workflows · tools        │
│  data/            SQLite DB · sessions · deployments│
└─────────────────────────────────────────────────────┘
```

A run streams Server-Sent Events back to the canvas, so the timeline and node badges update live. Event types: `start`, `token`, `reasoning_delta`, `node_started`, `node_input`, `node_output`, `tool_call_start`, `tool_call_args`, `tool_call_result`, `agent_transfer`, `citation`, `error`, `done`.

## Configuration reference

All settings come from environment variables (see [.env.example](.env.example)). Everything has a sensible default except the LLM API key.

**LLM**

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Key for the default provider |
| `LLM_MODEL` | `openrouter/google/gemma-3-27b-it` | Default model for agents without their own |
| `LLM_PROVIDER` | `openrouter` | Set to anything else to disable OpenRouter model-string rewriting |
| `LLM_API_BASE` / `LLM_API_KEY` | — | For `LLM_PROVIDER=local` (vLLM, LM Studio, any OpenAI-compatible server) |

**Application**

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8000` | API + Studio port |
| `ENVIRONMENT` | `development` | `production` enforces authentication |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `FRONTEND_URL` | `*` | Comma-separated allowed CORS origins |

**Database**

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/oak.db` | SQLite by default; any PostgreSQL URL works |
| `OAK_AUTO_MIGRATE` | `true` | Run DB migrations on startup |

**Authentication** (optional)

| Variable | Default | Purpose |
|---|---|---|
| `OAK_ADMIN_USERNAME` / `OAK_ADMIN_PASSWORD` | — | Create the first admin account on boot |
| `SECRET_KEY` | — | JWT signing key — set a strong random value in production |
| `KEYCLOAK_ENABLED` | `false` | Optional Keycloak SSO (plus `KEYCLOAK_SERVER_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`) |

Authentication is **off by default** in development mode: every endpoint works unauthenticated so you can start building immediately. For production, set `ENVIRONMENT=production` and either create local users/API keys or enable Keycloak.

**Optional services**

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | — | Redis cache |
| `QDRANT_URL` / `QDRANT_API_KEY` / `QDRANT_COLLECTION` | — | Qdrant vector store |
| `RAG_PIPELINE_ENABLED` / `RAG_PIPELINE_BASE_URL` / `RAG_PIPELINE_API_KEY` | `false` | External RAG service powering the `rag_*` tools |
| `ENABLE_METRICS` / `PROMETHEUS_PORT` / `OTEL_EXPORTER_OTLP_ENDPOINT` | `true` / `9090` | Observability |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `ENCRYPTION_KEY` | — | Gmail integration via Google OAuth 2.0 |

## API

The full interactive reference lives at `/docs`. The essentials:

```bash
# Create a session for a workflow
curl -X POST localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id": "demo_multi_agent"}'

# Chat
curl -X POST localhost:8000/api/v1/sessions/<session_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is the weather in Berlin?"}'

# Stream a run as Server-Sent Events
curl -N -X POST localhost:8000/api/v1/workflows/demo_multi_agent/execute/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is (12 + 8) * 3?"}'
```

Plus full CRUD for agents, workflows, tools (with Swagger import), prompts, providers, triggers/webhooks, deployments, and workflow test cases.

## Project layout

```
src/                  FastAPI backend
  api/routers/        one router per resource (workflows, agents, tools, …)
  crewai_runtime/     workflow → CrewAI translation & execution
  config/             pydantic config models, registries, LLM provider resolution
  core/               typed streaming event models
  tools/              built-in tools (web search, RAG, calculator, Gmail, API executor)
workflow-editor/      Studio SPA (React 19 + TypeScript + Vite + React Flow)
  src/demo/           in-browser API stub powering the GitHub Pages demo
configs/              agent/workflow/tool/provider definitions (JSON)
alembic/              database migrations
scripts/              maintenance and build scripts
helm/  k8s/           Kubernetes deployment manifests
```

## Development

```bash
uv run pytest tests/unit -q          # backend unit tests
uv run pytest tests/integration -q   # integration tests
cd workflow-editor && npm test       # frontend unit tests (vitest)
cd workflow-editor && npm run lint   # frontend lint
docker build -t open-agent-kit .     # full image build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### The GitHub Pages demo

GitHub Pages serves static files only, so the [live demo](https://mubinui.github.io/open-agent-kit/)
replaces the backend with an in-browser stub in `workflow-editor/src/demo/`. It answers every
`/api/v1/*` route the Studio calls — including the SSE execution stream — from fixtures in
`seed.json`, a scrubbed snapshot of the real API. Edits are real but in-memory and reset on reload;
no LLM is ever called.

```bash
# Regenerate the fixtures from a running API server
uv run uvicorn src.api.main:app --port 8000
python scripts/build_demo_seed.py

# Build the demo locally (output in workflow-editor/dist-demo)
cd workflow-editor && npm run build:demo
```

`#demo` resolves to `src/demo/stub.ts` unless `VITE_DEMO_MODE=true`, so the stub and its fixtures
never reach the bundle the API server ships. Pushing to the `demo` branch publishes via
[pages-demo.yml](.github/workflows/pages-demo.yml).

## Production deployment

- **Docker** — the published image at `ghcr.io/mubinui/open-agent-kit:latest` is the fastest path; mount a volume at `/app/data` to persist the database.
- **Kubernetes** — manifests in [k8s/](k8s/) cover deployment, ingress, HPA, network policy, and optional Postgres/Redis/RabbitMQ StatefulSets.
- **Helm** — the chart in [helm/open-agent-kit/](helm/open-agent-kit/) ships `values-dev.yaml` and `values-prod.yaml`.

For production, set `ENVIRONMENT=production`, a strong `SECRET_KEY`, a PostgreSQL `DATABASE_URL`, and restrict `FRONTEND_URL` to your own origins.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Agents reply but ignore their tools | The model lacks function-calling support — pick one whose capabilities include `function_calling`. |
| `AuthenticationError` despite a valid vendor key | `LLM_PROVIDER` is still `openrouter`, so your model string was rewritten to route through OpenRouter. See [Path B](#path-b--talk-to-a-provider-directly). |
| Canvas nodes show "Missing model" | The agent has no `model_config.model` and no `LLM_MODEL` fallback is set. |
| Studio loads but shows "Backend unreachable" | The API isn't running on the expected port, or `FRONTEND_URL` is blocking the origin. |
| `rag_*` tools return errors | The RAG pipeline is optional — set `RAG_PIPELINE_ENABLED=true` and `RAG_PIPELINE_BASE_URL`. |

## License

[MIT](LICENSE)

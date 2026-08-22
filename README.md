<div align="center">

<!-- The mark inverts with the reader's GitHub theme, the same way the favicon
     and the Studio header do. -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="workflow-editor/svg/delaxis-tile-paper-blue-dark.svg">
  <img src="workflow-editor/svg/delaxis-tile-paper-blue-light.svg" alt="Delaxis" width="88" height="88">
</picture>

# Delaxis

**An open-source multi-agent development kit — design, test, and deploy AI agent workflows from one place.**

[![Release](https://img.shields.io/github/v/release/mubinui/delaxis?label=release)](../../releases/latest)
[![Docker](https://img.shields.io/github/actions/workflow/status/mubinui/delaxis/docker-release.yml?label=Docker%20Build)](../../actions/workflows/docker-release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CrewAI](https://img.shields.io/badge/runtime-CrewAI-orange.svg)](https://crewai.com)

### [▶ Try the live demo](https://mubinui.github.io/delaxis/)

No install, no API key — the real Studio running against an in-browser stub of the API.

</div>

![Delaxis Studio](docs/images/studio-canvas.png)

---

## Contents

- [What it is](#what-it-is)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Choosing an LLM provider](#choosing-an-llm-provider) — OpenAI, Gemini, Grok, Claude, local models
- [Live voice](#live-voice) — talking to a chatbot over Gemini Live
- [The Builder](#the-builder) — per-step model routing and spoken progress
- [Retrieval](#retrieval)
- [Tools](#tools) — data access, privacy, security, and audit
- [Core concepts](#core-concepts)
- [How it works](#how-it-works)
- [Configuration reference](#configuration-reference)
- [API](#api)
- [Embedding a chatbot](docs/integration.md) — widget, iframe, or direct API
- [Project layout](#project-layout)
- [Development](#development)
- [Production deployment](#production-deployment)
- [Troubleshooting](#troubleshooting)

---

## What it is

Delaxis is a self-hosted platform for building multi-agent AI applications:

- **Visual Studio** — a React Flow canvas for composing agent workflows (selector, sequential, parallel topologies) with drag-and-drop agents, tools, and triggers
- **CrewAI runtime** — workflows execute on [CrewAI](https://crewai.com), with any LLM via LiteLLM (OpenAI, Gemini, Grok, Claude, OpenRouter, self-hosted vLLM, local Ollama)
- **Tools out of the box** — web search, RAG, a calculator, Gmail, and any REST API via Swagger/OpenAPI import
- **Data access** — [SQL and MongoDB](#data-tools) with schema introspection and read-only enforcement, a browsable file tree, and analysis of uploaded PDFs, spreadsheets, and images
- **Privacy, security, and audit** — [PII detection and redaction](#trust-tools), secret and prompt-injection scanning, and an append-only, hash-chained audit trail
- **Live LLM tester** — validate keys, models, latency, and cost before wiring them into agents
- **Flash deployments** — publish any workflow as a standalone chat page at `/d/<name>/`, with conversation history, starter prompts and a settings drawer; embed it anywhere with one script tag
- **Live voice** — [talk to a chatbot](#live-voice) over Gemini Live, in the Studio test panel or on a deployed page; audio is relayed server-side so the provider key never reaches the browser
- **Optional auth** — local users + API keys (SQL-backed), or Keycloak SSO
- **One container** — API, Studio UI, and SQLite persistence in a single Docker image

Everything is configuration-driven. Agents, workflows, tools, prompts, and providers live in `configs/*.json` and are editable via the Studio UI, the REST API, or a text editor (hot-reload in development).

## Screenshots

| Live LLM tester | Deployment hub |
|---|---|
| ![Live LLM tester](docs/images/llm-tester.png) | ![Deployments](docs/images/deployments.png) |

Every screenshot above is from the [live demo](https://mubinui.github.io/delaxis/) — click through it yourself before installing anything.

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
  -v delaxis_data:/app/data \
  ghcr.io/mubinui/delaxis:latest
```

Or build it yourself:

```bash
git clone https://github.com/mubinui/delaxis.git
cd delaxis
docker build -t delaxis .

docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v delaxis_data:/app/data \
  delaxis
```

Open **http://localhost:8000** — the Studio UI, API (`/docs`), and deployed chatbots are all served from this one container. On first boot the database schema is created automatically on the `delaxis_data` volume; no other services are required.

### Option 2 — Docker Compose

```bash
git clone https://github.com/mubinui/delaxis.git
cd delaxis
cp .env.example .env        # add your API key
docker compose up
```

Optional production services are behind profiles:

```bash
docker compose --profile postgres up     # PostgreSQL instead of SQLite
docker compose --profile qdrant up       # Qdrant vector store
docker compose --profile redis up        # Redis cache
```

With the `postgres` profile, set `DATABASE_URL=postgresql://delaxis:delaxis_pass@postgres:5432/delaxis` in `.env`.

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
uv run delaxis --workflow support_triage --message "What is 2 + 2 * 5?"
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

## Live voice

You can talk to a chatbot instead of typing, powered by the **Gemini Live** realtime audio API. It shows up in two places:

- the Studio's test panel — a mic next to Send, so you can hear a workflow before deploying it
- the Studio's **Builder** — talk through what you want to build; see [The Builder](#the-builder)
- a deployed page at `/d/<name>/` — enable **Live voice** in the Launchpad's Deploy tab

Setup is one key:

```bash
GEMINI_API_KEY=...            # the only requirement
GEMINI_LIVE_MODEL=...         # optional; defaults to the provider's configured live model
```

Then check it is wired up:

```bash
curl localhost:8000/api/v1/voice/health
# {"ok":true,"model":"gemini-3.1-flash-live-preview","input_sample_rate":16000,...}
```

> [!IMPORTANT]
> **Voice replies come straight from the realtime model — your workflow does not run.**
> Native realtime audio means the model converses directly, seeded with the deployment's
> persona (or, if you leave that blank, the entry agent's own system message). Tools, RAG
> and multi-agent routing are all bypassed, so a spoken answer can differ from a typed one
> in the same chatbot. Spoken turns are still written into the normal message history, so
> they appear in the transcript on reload.

### How it works

The browser never talks to Google. It streams microphone PCM to this application, which relays it to the realtime model and streams speech back:

```
browser ──PCM16 16kHz──▶ /api/v1/voice/ws ──▶ Gemini Live
        ◀─PCM16 24kHz──                    ◀──
```

That indirection is what keeps `GEMINI_API_KEY` server-side, and it is enforced: a deployed page that references an external WebSocket host fails validation and will not publish.

### Limits

A realtime session bills for as long as it is open, and WebSocket connections do not pass through the HTTP rate-limiting middleware. So a socket carries no credentials of its own — the client first calls the authenticated, rate-limited `POST /api/v1/voice/ticket` and redeems a short-lived single-use ticket when connecting. On top of that:

| Setting | Default | Purpose |
|---|---|---|
| `DELAXIS_VOICE_ENABLED` | `true` | Global kill switch |
| `DELAXIS_VOICE_MAX_SESSION_SECONDS` | `300` | Hard cap per session |
| `DELAXIS_VOICE_MAX_CONCURRENT` | `4` | Concurrent sessions per process |
| `DELAXIS_VOICE_TICKET_TTL_SECONDS` | `30` | How long a ticket stays redeemable |

The realtime model id is configuration, not code — Google has published these under several names, so the allow-list lives under the provider's `live.models` in `configs/api_providers.json`. A model that does not look like a realtime audio model is refused before a session can open.

## The Builder

The Studio's Builder panel turns a one-line brief into agents, tools, a workflow, and a deployable frontend.

**Each step picks its own model.** Builder work is one-shot and high-leverage — a bad plan costs far more than the tokens saved by running it cheaply — so with the model selector on **Auto** (the default) the server routes each step to the strongest model you actually have a key for:

| Step | Gets |
|---|---|
| Planning a chatbot, generating configs, repairing an API into a tool, generating a frontend | the most capable model available |
| Colour/design JSON, interactive chat | a fast model |
| Explaining one diagnostic | the cheapest capable model |

Pick a specific model from the dropdown and that choice is always honoured — auto-select only decides what "Auto" means. Naming a provider without a model narrows the choice to that provider rather than silently moving your request elsewhere. Rankings live in [`src/api/builder_models.py`](src/api/builder_models.py); the model that actually ran is returned in the response and logged as `builder_model_selected`.

**You can describe it out loud.** The mic under the brief box opens a Gemini Live conversation with a build assistant: it asks one clarifying question at a time — who uses it, which APIs it needs, what it must never do — and everything you say is appended to the brief above, so the conversation produces exactly the text the Build button consumes. It deliberately does not claim to build anything; realtime voice cannot call the platform's endpoints, so it helps you write the brief and you press Build.

**And it narrates while it works.** The speaker button in the Builder header reads progress out loud — which model it escalated to, how many agents came back, whether the generated page passed validation — so a 30-second build is not a silent spinner. Narration uses the browser's built-in speech synthesis rather than a cloud voice: it starts instantly, costs nothing, needs no key, and cannot fail a build. Off until you turn it on; the preference is remembered.

## Retrieval

Ask questions of your own documents. Upload a file — in the Studio chat, in a
deployed chatbot, over the API, or from the command line — and it is split into
overlapping passages, embedded, and stored so agents can retrieve from it.

Nothing needs configuring to start. Vectors go to a SQLite file under `data/`
and text is embedded locally, so retrieval works on a fresh checkout with no
keys and no extra service.

```bash
# index a directory
python scripts/ingest_rag_documents.py --dir ./docs --collection handbook
python scripts/ingest_rag_documents.py --list --collection handbook

# or over HTTP, uploading and indexing in one request
curl -F files=@handbook.pdf localhost:8000/api/v1/rag/collections/handbook/files
curl -X POST localhost:8000/api/v1/rag/collections/handbook/query \
     -H 'Content-Type: application/json' -d '{"query": "what is the refund window?"}'
```

Both halves are swappable, and everything above them is unchanged either way:

| | Options |
|---|---|
| **Vector store** (`RAG_BACKEND`) | `sqlite` (default) · `qdrant` · `pgvector` · `pinecone` · `faiss` · `chromadb` |
| **Embeddings** (`RAG_EMBEDDING_PROVIDER`) | `local` (default, no key) · `openai` · `gemini` |

The `openai` provider is any service speaking that API, so `RAG_EMBEDDING_BASE_URL`
points it at Ollama, LM Studio, vLLM, OpenRouter or Together just as easily. The
`local` provider matches on words and word fragments rather than meaning — a good
keyword search rather than a poor semantic one — which is the honest trade for
needing no key.

Backends other than `sqlite` and `pgvector` need their client installed:

```bash
uv pip install -e ".[qdrant]"        # or faiss, pinecone, chroma
uv pip install -e ".[vectorstores]"  # all of them
```

### Attaching files to a chat

The paperclip in either chat composer uploads a file, indexes it against that
conversation alone, and sends the relevant passages with your question — so the
agent answers from the document whether or not that workflow has a retrieval
tool wired up.

### Documents agents can hand back

`generate_document` turns Markdown into a file with a download link: PDF, Word,
Excel, HTML, Markdown, CSV, JSON or text. Headings, lists, tables and code
blocks survive into all of them.

## Tools

Every capability below is a tool your agents call, registered in
[`configs/tools.json`](configs/tools.json) and grouped by `category` so the
Studio's Library can shelve it. Add your own as a Python function, a REST
endpoint, or an MCP server.

### Data tools

| Tool type | What it does |
|---|---|
| `sql` | Schema introspection plus a query runner over any SQLAlchemy URL — PostgreSQL, MySQL, SQLite, SQL Server, Oracle, whatever dialect you have installed. Read-only unless you set `allow_writes`. |
| `database` | NL2SQL: the model writes the query from a plain-language question. Use `sql` instead when you want to control what runs. |
| `mongodb` | Collection listing, schema sampling (Mongo has no declared schema, so it infers one), and `find`. Read-only by default. |
| `context_tree` and friends | Let an agent walk a file tree, search it, and open only what matters, instead of being handed a whole corpus. |
| `analyze_file`, `analyze_image` | Read uploaded PDFs, DOCX, XLSX, CSV, and JSON — CSVs come back with a per-column profile. Images report dimensions always, and a written description when a vision model is configured. |

**Read-only is enforced, not requested.** The `sql` tool parses the statement:
stacked statements, writes hidden inside a CTE, and verbs obscured by comments
are all rejected. Treat that as a second line of defence — for a production
database, a read-only database role is still the control that matters.

**Uploads and the sandbox.** Files posted to `POST /api/v1/files` land in the
uploads directory, which is also a context root. Every path an agent supplies is
resolved before it is checked, so `../`, absolute paths, and symlinks planted
inside the tree all fail rather than escape. Roots are configured with
`DELAXIS_CONTEXT_ROOTS`; the default is the uploads directory plus
`data/context`, never the whole filesystem.

### Trust tools

| Tool | What it does |
|---|---|
| `detect_pii`, `redact_pii` | Find emails, phone numbers, cards, national IDs, IBANs, keys, and dates of birth — validated with Luhn, IBAN mod-97, and SSA issuance rules rather than raw pattern matching, so the hit rate is worth acting on. Redact by masking, labelling, hashing, or removing. Install `presidio-analyzer` to add names, places, and organisations. |
| `scan_for_secrets` | Credential-shaped strings confirmed by an entropy floor, with placeholders like `your_key_here` ignored. Findings are reported masked. |
| `detect_prompt_injection` | Weighted scoring over instruction-override, role-reassignment, exfiltration, and guardrail-bypass signals. Run it on anything from outside the workflow before an agent acts on it. |
| `security_scan` | All three at once, returning one verdict: pass, review, or block. |
| `record_audit_event`, `query_audit_log`, `verify_audit_integrity` | An append-only, hash-chained trail. Alter or drop a row and every hash after it breaks; verification names the first entry that fails. |

The audit trail lives in `data/audit_trail.db` and is readable through
`GET /api/v1/audit/entries`, with `GET /api/v1/audit/verify` for the integrity
check. There is deliberately no write endpoint — entries come from the code path
that performed the action, not from whoever can reach the API.

These raise the cost of an attack and give a workflow something concrete to
branch on. They do not make an agent safe to point at hostile input on their
own.

## Core concepts

| Concept | What it is |
|---|---|
| **Workflow** | A topology of agents. Patterns: `single`, `sequential` (pipeline), `graph` (selector/parallel). Stored in `configs/workflows.json`. |
| **Agent** | A CrewAI agent — role, goal, backstory, model config, and a list of tools. |
| **Tool** | Something an agent can call. Built in: `web_search`, `calculate`, `get_weather`, the `rag_*` family, Gmail. Add your own as a Python function, a REST endpoint, an MCP server, or a Swagger/OpenAPI import. |
| **Trigger** | How a workflow is invoked — `chat`, `webhook`, or `manual` — each with its own auth mode (`public`, `api_key`, `jwt`). |
| **Deployment** | A flash-published chat page at `/d/<name>/`, embeddable with one script tag. See [docs/integration.md](docs/integration.md). |
| **Prompt** | A reusable, versioned template with variables. |

Canvas node types: Manual Trigger, Chat Trigger, Webhook, CrewAI Agent, CrewAI Task, Flow Router, Memory Store, Knowledge Source, Guardrail, MCP Server, Database (NL2SQL), Gmail, Output. The Studio's **Help** panel explains every one of them and what it compiles to on save.

### Starter workflows

`configs/workflows.json` ships six workflows that run as-is. Open one in the Studio and
adapt it rather than starting from an empty canvas.

| Workflow | Pattern | What it shows | Needs |
|---|---|---|---|
| `assistant_chat` | single | One agent with session memory — the smallest thing worth deploying | a provider key |
| `web_research_chat` | single | Web search with citations before answering | a provider key |
| `research_brief` | sequential | Gather → write, with a guardrail on the final answer | a provider key |
| `content_pipeline` | sequential | Outline → draft → edit, three agents handing off | a provider key |
| `docs_qa` | single | Retrieval pinned to a named collection | nothing — retrieval is built in |
| `support_triage` | selector | A triage agent delegating to three specialists | a provider key |

Each carries `metadata.setup` listing exactly what it needs beyond an API key.

## How it works

```
┌─────────────────────────────────────────────────────┐
│                   Delaxis                    │
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
| `DATABASE_URL` | `sqlite:///./data/delaxis.db` | SQLite by default; any PostgreSQL URL works |
| `DELAXIS_AUTO_MIGRATE` | `true` | Run DB migrations on startup |

**Authentication** (optional)

| Variable | Default | Purpose |
|---|---|---|
| `DELAXIS_ADMIN_USERNAME` / `DELAXIS_ADMIN_PASSWORD` | — | Create the first admin account on boot |
| `SECRET_KEY` | — | JWT signing key — set a strong random value in production |
| `KEYCLOAK_ENABLED` | `false` | Optional Keycloak SSO (plus `KEYCLOAK_SERVER_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`) |

Authentication is **off by default** in development mode: every endpoint works unauthenticated so you can start building immediately. For production, set `ENVIRONMENT=production` and either create local users/API keys or enable Keycloak.

**Optional services**

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | — | Redis cache |
| `QDRANT_URL` / `QDRANT_API_KEY` / `QDRANT_COLLECTION` | — | Qdrant vector store |
| `RAG_BACKEND` | `sqlite` | Where vectors live: `sqlite`, `qdrant`, `pgvector`, `pinecone`, `faiss`, `chromadb` |
| `RAG_EMBEDDING_PROVIDER` | `local` | How text becomes vectors: `local` (no key), `openai`, `gemini` |
| `RAG_EMBEDDING_MODEL` / `RAG_EMBEDDING_BASE_URL` | — | Embedding model, and the endpoint for OpenAI-compatible servers |
| `PGVECTOR_URL` / `PINECONE_API_KEY` / `FAISS_PATH` / `CHROMA_PATH` | — | Settings for the backend you chose |
| `RAG_PIPELINE_ENABLED` | `true` | Master switch for the `rag_*` tools |
| `ENABLE_METRICS` / `PROMETHEUS_PORT` / `OTEL_EXPORTER_OTLP_ENDPOINT` | `true` / `9090` | Observability |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `ENCRYPTION_KEY` | — | Gmail integration via Google OAuth 2.0 |
| `DELAXIS_VOICE_ENABLED` | `true` | [Live voice](#live-voice) kill switch (needs `GEMINI_API_KEY`) |
| `DELAXIS_VOICE_MAX_SESSION_SECONDS` / `DELAXIS_VOICE_MAX_CONCURRENT` | `300` / `4` | Realtime session caps |
| `GEMINI_LIVE_MODEL` | — | Override the realtime voice model (must be allow-listed in `configs/api_providers.json`) |

## API

The full interactive reference lives at `/docs`. The essentials:

```bash
# Create a session for a workflow
curl -X POST localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id": "support_triage"}'

# Chat
curl -X POST localhost:8000/api/v1/sessions/<session_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is the weather in Berlin?"}'

# Stream a run as Server-Sent Events
curl -N -X POST localhost:8000/api/v1/workflows/support_triage/execute/stream \
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
docker build -t delaxis .     # full image build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### The GitHub Pages demo

GitHub Pages serves static files only, so the [live demo](https://mubinui.github.io/delaxis/)
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

- **Docker** — the published image at `ghcr.io/mubinui/delaxis:latest` is the fastest path; mount a volume at `/app/data` to persist the database.
- **Kubernetes** — manifests in [k8s/](k8s/) cover deployment, ingress, HPA, network policy, and optional Postgres/Redis/RabbitMQ StatefulSets.
- **Helm** — the chart in [helm/delaxis/](helm/delaxis/) ships `values-dev.yaml` and `values-prod.yaml`.

For production, set `ENVIRONMENT=production`, a strong `SECRET_KEY`, a PostgreSQL `DATABASE_URL`, and restrict `FRONTEND_URL` to your own origins.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Agents reply but ignore their tools | The model lacks function-calling support — pick one whose capabilities include `function_calling`. |
| `AuthenticationError` despite a valid vendor key | `LLM_PROVIDER` is still `openrouter`, so your model string was rewritten to route through OpenRouter. See [Path B](#path-b--talk-to-a-provider-directly). |
| Canvas nodes show "Missing model" | The agent has no `model_config.model` and no `LLM_MODEL` fallback is set. |
| Studio loads but shows "Backend unreachable" | The API isn't running on the expected port, or `FRONTEND_URL` is blocking the origin. |
| `rag_*` tools return errors | The RAG pipeline is optional — set `RAG_PIPELINE_ENABLED=true` and `RAG_PIPELINE_BASE_URL`. |
| Mic button does nothing / "Voice unavailable" | Check `GET /api/v1/voice/health` — usually a missing `GEMINI_API_KEY` or a `GEMINI_LIVE_MODEL` that is not in the provider's `live.models` allow-list. |
| Voice answers differ from typed ones | Expected: [voice bypasses the workflow](#live-voice) and uses the persona alone. |
| Voice works in production but not `npm run dev` | The Vite proxy needs `ws: true` on `/api` (already set in `vite.config.ts`). |

## Upgrading from Open Agent Kit (OAK)

The project was renamed to Delaxis. Environment variables moved from `OAK_*` to `DELAXIS_*`; the old names still work and log a deprecation warning on first read, and are removed in 0.6.0.

Three things need a manual step:

```bash
# 1. The default SQLite database moved. Startup warns and names this command
#    if it finds the old file — it is never moved automatically.
mv data/oak.db data/delaxis.db

# 2. Docker volume / Helm release / k8s namespace names all changed.
#    Existing containers and releases are not upgraded in place.
docker compose down && docker compose up -d   # after migrating the volume

# 3. Nothing to do for API keys: existing oak_ keys keep authenticating.
#    Newly created keys start with dlx_.
```

The CLI is now `delaxis` (with `dlx` as a short alias), the Python package is `delaxis`, and host pages calling `window.OakChat` keep working via an alias to `window.DelaxisChat`.

## License

[MIT](LICENSE)

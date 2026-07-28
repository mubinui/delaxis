#!/usr/bin/env python3
"""Build the fixture bundle behind the GitHub Pages demo of the Studio.

The demo replaces the backend with an in-browser stub (see
``workflow-editor/src/demo/mockApi.ts``). Rather than hand-writing fixtures that
drift from the API, this script snapshots the real endpoints, strips anything
sensitive, and fills in the few collections a fresh checkout leaves empty so the
published demo exercises every feature.

Usage::

    uv run uvicorn src.api.main:app --port 8000     # in another shell
    python scripts/build_demo_seed.py

    python scripts/build_demo_seed.py --source snapshot.json   # offline replay
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = REPO_ROOT / "workflow-editor" / "src" / "demo" / "seed.json"

ENDPOINTS = {
    "workflows": "/workflows",
    "agents": "/agents",
    "tools": "/tools",
    "functions": "/functions",
    "prompts": "/prompts",
    "providers": "/api-providers",
    "triggers": "/triggers",
    "deployments": "/deployments",
    "health": "/health",
    "metrics": "/metrics/dashboard",
    "ragService": "/rag-service",
    "ragCollections": "/rag-service/collections",
    "studioState": "/studio/state",
    "builderModels": "/builder/models",
    "gmailStatus": "/integrations/gmail/status",
}

# Placeholder shown wherever the real API returns a (already masked) key. Even a
# masked key leaks its last characters, and this bundle is published publicly.
MASKED_KEY = "sk-demo-****************************"
SECRET_FIELD = re.compile(r"^(api_key|secret|token|password)$", re.I)

DEMO_MODEL = {
    "provider_id": "openrouter",
    "model": "openai/gpt-oss-20b",
    "temperature": 0.7,
    "max_tokens": 800,
}

NOW = "2026-07-20T09:12:00+00:00"


def fetch_all(base_url: str) -> dict[str, Any]:
    """Snapshot every endpoint the Studio reads on startup."""
    snapshot: dict[str, Any] = {}
    for key, path in ENDPOINTS.items():
        url = f"{base_url.rstrip('/')}/api/v1{path}"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                snapshot[key] = json.load(response)
        except (urllib.error.URLError, TimeoutError) as error:
            sys.exit(f"Could not read {url}: {error}\nIs the API server running?")
    return snapshot


def scrub(value: Any) -> Any:
    """Replace every credential-shaped field with an obvious placeholder."""
    if isinstance(value, dict):
        return {
            key: MASKED_KEY if SECRET_FIELD.match(key) and isinstance(inner, str) and inner else scrub(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


SHOWCASE_WORKFLOW = "demo_multi_agent"

# Laid out left to right: trigger → selector → three specialists → output, with
# each specialist's tool hanging off its aux handle. Node ids for agents match
# the topology node ids so streamed execution events light up the right node.
CANVAS_AGENTS = [
    ("demo_selector_agent", 300, 300),
    ("search_assistant", 760, 20),
    ("rag_assistant", 760, 330),
    ("calculator_agent", 760, 660),
]

# (node id, tool id from configs/tools.json, agent to attach to, aux handle, x, y)
# Tools sit ~190px below their agent — enough clearance for an agent card that
# grows a footer row when it has run data or a configuration warning.
CANVAS_TOOLS = [
    ("tool-web-search", "web_search", "search_assistant", "tools", 760, 210),
    ("tool-rag-query", "rag_query", "rag_assistant", "tools", 680, 520),
    ("tool-calculate", "calculate", "calculator_agent", "tools", 760, 850),
]

# Canvas-only helper nodes: they have no configs/tools.json entry.
CANVAS_HELPERS = [
    ("tool-memory", "Memory Store", {"type": "memory", "memory_enabled": True, "retention": "session"},
     "demo_selector_agent", "memory", 300, 490),
    ("tool-knowledge", "Knowledge Source", {"type": "knowledge", "knowledge_enabled": True, "top_k": 5},
     "rag_assistant", "knowledge", 930, 520),
]

FLOW_EDGE_STYLE = {"stroke": "#64748b", "strokeWidth": 2}
FLOW_EDGE_MARKER = {"type": "arrowclosed", "color": "#64748b"}
AUX_EDGE_STYLE = {"stroke": "#94a3b8", "strokeWidth": 1.5, "strokeDasharray": "6 4"}


def build_canvas(data: dict[str, Any]) -> None:
    """Give the showcase workflow a hand-laid-out, fully wired canvas.

    Without this the Studio falls back to auto-placing topology nodes in a row
    with no edges, because a selector topology stores its routing in
    ``domain_agents`` rather than as explicit edges. That renders as a line of
    disconnected agents, which misrepresents how the product actually looks.
    """
    workflow = next((item for item in data["workflows"] if item["id"] == SHOWCASE_WORKFLOW), None)
    if not workflow:
        return

    agents = {agent["id"]: agent for agent in data["agents"]}
    tools = {tool["id"]: tool for tool in data["tools"]}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    nodes.append(
        {
            "id": "trigger-chat",
            "type": "trigger",
            "position": {"x": 40, "y": 322},
            "data": {
                "label": "On Chat",
                "config": {
                    "trigger_type": "chat",
                    "label": "On Chat",
                    "workflow_id": SHOWCASE_WORKFLOW,
                },
            },
        }
    )

    for agent_id, x, y in CANVAS_AGENTS:
        agent = agents.get(agent_id)
        if not agent:
            continue
        is_selector = agent_id == workflow.get("topology", {}).get("entry_node")
        nodes.append(
            {
                "id": agent_id,
                "type": "agent",
                "position": {"x": x, "y": y},
                "data": {
                    "label": agent_id,
                    "description": agent.get("description", ""),
                    "config": {
                        "id": agent_id,
                        "agent_id": agent_id,
                        "name": agent.get("name", agent_id),
                        "type": agent.get("type", "conversable"),
                        "instruction": agent.get("system_message", ""),
                        "system_message": agent.get("system_message", ""),
                        "model_config": dict(agent.get("llm_config") or DEMO_MODEL),
                        "tools": agent.get("tools") or [],
                        "human_input_mode": agent.get("human_input_mode", "NEVER"),
                        "is_selector": is_selector,
                    },
                },
            }
        )

    def tool_node(node_id: str, label: str, config: dict[str, Any], x: int, y: int) -> dict[str, Any]:
        return {
            "id": node_id,
            "type": "tool",
            "position": {"x": x, "y": y},
            "data": {"label": label, "config": config},
        }

    def aux_edge(source: str, target: str, handle: str) -> dict[str, Any]:
        return {
            "id": f"xy-edge__{source}attach-{target}{handle}",
            "source": source,
            "sourceHandle": "attach",
            "target": target,
            "targetHandle": handle,
            "type": "straight",
            "style": dict(AUX_EDGE_STYLE),
        }

    for node_id, tool_id, agent_id, handle, x, y in CANVAS_TOOLS:
        tool = tools.get(tool_id)
        if not tool:
            continue
        nodes.append(
            tool_node(
                node_id,
                tool["name"],
                {
                    "id": tool["id"],
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "entrypoint": tool.get("entrypoint") or "",
                    "enabled": tool.get("enabled", True),
                    **(tool.get("settings") or {}),
                },
                x,
                y,
            )
        )
        edges.append(aux_edge(node_id, agent_id, handle))

    for node_id, label, config, agent_id, handle, x, y in CANVAS_HELPERS:
        nodes.append(tool_node(node_id, label, config, x, y))
        edges.append(aux_edge(node_id, agent_id, handle))

    nodes.append(
        {
            "id": "output-final",
            "type": "output",
            "position": {"x": 1280, "y": 352},
            "data": {"label": "Answer", "config": {"type": "output"}},
        }
    )

    def flow_edge(source: str, target: str) -> dict[str, Any]:
        return {
            "id": f"xy-edge__{source}-{target}",
            "source": source,
            "target": target,
            "type": "smoothstep",
            "animated": False,
            "style": dict(FLOW_EDGE_STYLE),
            "markerEnd": dict(FLOW_EDGE_MARKER),
        }

    entry = workflow.get("topology", {}).get("entry_node", "demo_selector_agent")
    specialists = [agent_id for agent_id, _, _ in CANVAS_AGENTS if agent_id != entry]

    edges.append(flow_edge("trigger-chat", entry))
    for specialist in specialists:
        edges.append(flow_edge(entry, specialist))
        edges.append(flow_edge(specialist, "output-final"))

    # The API returns metadata as an explicit null when unset, so setdefault alone
    # would leave it None.
    if not isinstance(workflow.get("metadata"), dict):
        workflow["metadata"] = {}
    workflow["metadata"]["visual_canvas"] = {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 0.75},
    }


def load_config_instructions() -> dict[str, str]:
    """Map agent id → instruction text straight from configs/agents.json."""
    path = REPO_ROOT / "configs" / "agents.json"
    if not path.exists():
        return {}
    agents = json.loads(path.read_text()).get("agents", [])
    return {
        agent["id"]: agent.get("instruction") or agent.get("system_message") or ""
        for agent in agents
        if agent.get("id")
    }


def enrich(data: dict[str, Any]) -> dict[str, Any]:
    """Populate collections a fresh checkout leaves empty, and bind models.

    Seeded agents ship without an LLM binding, which renders every canvas node
    as "Missing model". That is honest for a local checkout but misleading in a
    showcase, so the demo binds them to the default OpenRouter model.
    """
    for provider in data["providers"]:
        if provider.get("api_key_masked"):
            provider["api_key_masked"] = MASKED_KEY

    # The seeded agents come back from the API with an empty system_message even
    # though configs/agents.json defines one under `instruction`, which makes every
    # canvas node render as "Missing instructions". Backfill from the config file
    # so the demo reflects a correctly configured install.
    instructions = load_config_instructions()

    for agent in data["agents"]:
        config = agent.get("llm_config")
        if not isinstance(config, dict) or not config.get("model"):
            agent["llm_config"] = dict(DEMO_MODEL)
        if not agent.get("system_message"):
            agent["system_message"] = instructions.get(agent["id"], "")

    agents_by_id = {agent["id"]: agent for agent in data["agents"]}

    # Canvas nodes read their model and instructions off the topology node's own
    # config, so mirror each referenced agent's settings onto the node.
    for workflow in data["workflows"]:
        for node in (workflow.get("topology") or {}).get("nodes") or []:
            agent = agents_by_id.get(node.get("agent_id"))
            if not agent:
                continue
            config = node.setdefault("config", {})
            config.setdefault("model_config", dict(agent["llm_config"]))
            config.setdefault("system_message", agent.get("system_message") or "You are a helpful assistant.")
            config.setdefault("tools", agent.get("tools") or [])

    data["functions"] = {
        "functions": [
            {
                "id": "sentiment_score",
                "name": "sentiment_score",
                "description": "Score text sentiment from -1 (negative) to 1 (positive).",
                "entrypoint": "sentiment_score",
                "file_path": "data/functions/sentiment_score.py",
                "enabled": True,
            },
            {
                "id": "slugify_title",
                "name": "slugify_title",
                "description": "Convert a headline into a URL-safe slug.",
                "entrypoint": "slugify_title",
                "file_path": "data/functions/slugify_title.py",
                "enabled": True,
            },
            {
                "id": "fx_convert",
                "name": "fx_convert",
                "description": "Convert an amount between two currencies at a fixed demo rate.",
                "entrypoint": "fx_convert",
                "file_path": "data/functions/fx_convert.py",
                "enabled": True,
            },
        ],
        "total": 3,
    }

    data["functionSources"] = {
        "sentiment_score": (
            'def sentiment_score(text: str) -> float:\n'
            '    """Score text sentiment from -1 (negative) to 1 (positive)."""\n'
            '    positive = {"good", "great", "love", "excellent", "happy"}\n'
            '    negative = {"bad", "terrible", "hate", "awful", "sad"}\n'
            '    words = [w.strip(".,!?").lower() for w in text.split()]\n'
            "    score = sum(w in positive for w in words) - sum(w in negative for w in words)\n"
            "    return max(-1.0, min(1.0, score / max(len(words), 1) * 5))\n"
        ),
        "slugify_title": (
            "import re\n\n\n"
            'def slugify_title(title: str) -> str:\n'
            '    """Convert a headline into a URL-safe slug."""\n'
            '    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())\n'
            '    return slug.strip("-")\n'
        ),
        "fx_convert": (
            'RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79, "BDT": 121.5}\n\n\n'
            'def fx_convert(amount: float, source: str, target: str) -> dict:\n'
            '    """Convert an amount between two currencies at a fixed demo rate."""\n'
            "    if source not in RATES or target not in RATES:\n"
            '        raise ValueError(f"Unsupported currency pair {source}->{target}")\n'
            "    converted = amount / RATES[source] * RATES[target]\n"
            '    return {"amount": round(converted, 2), "currency": target, "rate": RATES[target] / RATES[source]}\n'
        ),
    }

    data["triggers"] = [
        {
            "id": "trg_chat_demo",
            "workflow_id": "demo_multi_agent",
            "type": "chat",
            "enabled": True,
            "name": "Support chat widget",
            "auth_mode": "public",
            "provider_id": "openrouter",
            "model_id": "openai/gpt-oss-20b",
            "greeting": "Hi! Ask me about search, your knowledge base, or maths.",
            "public_slug": "support-chat",
            "secret": None,
            "allowed_origins": ["https://example.com"],
            "input_mapping": {"message": "$.message"},
            "response_mapping": {"reply": "$.response"},
            "metadata": {},
            "created_at": NOW,
            "updated_at": NOW,
        },
        {
            "id": "trg_webhook_ingest",
            "workflow_id": "rag_assistant",
            "type": "webhook",
            "enabled": True,
            "name": "Docs ingest webhook",
            "auth_mode": "api_key",
            "provider_id": "openrouter",
            "model_id": "openai/gpt-oss-20b",
            "greeting": "",
            "public_slug": "docs-ingest",
            "secret": "whsec_demo_****",
            "allowed_origins": [],
            "input_mapping": {"message": "$.body.text"},
            "response_mapping": {"status": "$.status"},
            "metadata": {},
            "created_at": NOW,
            "updated_at": NOW,
        },
        {
            "id": "trg_manual_nightly",
            "workflow_id": "e2e_search_demo",
            "type": "manual",
            "enabled": False,
            "name": "Nightly research run",
            "auth_mode": "jwt",
            "provider_id": "openrouter",
            "model_id": "google/gemini-3.1-flash-lite",
            "greeting": "",
            "public_slug": None,
            "secret": None,
            "allowed_origins": [],
            "input_mapping": {},
            "response_mapping": {},
            "metadata": {},
            "created_at": NOW,
            "updated_at": NOW,
        },
    ]

    if not any(item["id"] == "support-chat" for item in data["deployments"]):
        data["deployments"].append(
            {
                "id": "support-chat",
                "workflow_id": "demo_multi_agent",
                "name": "demo_multi_agent",
                "api_url": "",
                "trigger_id": "trg_chat_demo",
                "title": "Support Assistant",
                "theme": "aurora",
                "greeting": "Hi! Ask me about search, your knowledge base, or maths.",
                "provider_id": "openrouter",
                "model_id": "openai/gpt-oss-20b",
                "auth_mode": "public",
                "status": "active",
                "url": "/d/support-chat/",
                "path": "data/deployments/support-chat",
                "created_at": NOW,
                "updated_at": NOW,
                "error": None,
            }
        )

    # A fresh database reports zeroes across the board, which makes the Ops tab
    # look broken rather than idle.
    data["metrics"].update(
        {
            "total_agents": len(data["agents"]),
            "total_tools": len(data["tools"]),
            "total_workflows": len(data["workflows"]),
            "active_sessions": 3,
            "total_messages": 1284,
            "cache_hit_rate": 0.72,
            "avg_response_time": 1.84,
            "error_rate": 0.012,
        }
    )

    data["health"] = {
        "status": "healthy",
        "service": "open-agent-kit",
        "version": "0.1.0",
        "mode": "demo",
    }

    build_canvas(data)

    return data


def assert_no_secrets(seed: dict[str, Any]) -> None:
    """Fail loudly rather than publish a bundle containing a live credential."""
    blob = json.dumps(seed)
    patterns = {
        "OpenAI/OpenRouter key": r"sk-(?!demo)[A-Za-z0-9_-]{12,}",
        "GitHub token": r"gh[pousr]_[A-Za-z0-9]{16,}",
        "Google API key": r"AIza[A-Za-z0-9_-]{20,}",
        "Slack token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
        "email address": r"[A-Za-z0-9._%+-]+@(?!example\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    }
    for label, pattern in patterns.items():
        match = re.search(pattern, blob)
        if match:
            sys.exit(f"Refusing to write seed: possible {label} found ({match.group()[:12]}…)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Running API server")
    parser.add_argument("--source", type=Path, help="Replay a previously saved snapshot instead of fetching")
    parser.add_argument("--out", type=Path, default=SEED_PATH, help="Where to write the seed bundle")
    args = parser.parse_args()

    raw = json.loads(args.source.read_text()) if args.source else fetch_all(args.base_url)
    seed = enrich(scrub(raw))
    assert_no_secrets(seed)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, indent=1, sort_keys=True) + "\n")

    print(
        f"Wrote {args.out.relative_to(REPO_ROOT)} — "
        f"{len(seed['workflows'])} workflows, {len(seed['agents'])} agents, "
        f"{len(seed['tools'])} tools, {len(seed['triggers'])} triggers, "
        f"{len(seed['deployments'])} deployments"
    )


if __name__ == "__main__":
    main()

"""System prompts for the Studio Builder.

Each builder type gets a prompt describing the exact schema the platform
validates against, and every prompt is assembled with a live inventory of the
tools, agents and workflows that actually exist (see
:mod:`src.api.builder_context`).

That inventory is the difference between a Builder that works and one that
looks like it works. Given only a schema, a model invents plausible tool ids
and agent references that fail the moment the plan is applied; given the real
catalogue with descriptions, it picks things that exist and validate.

Prompts are built per request rather than defined as constants, because a tool
registered a minute ago must be usable in the next build.
"""

from __future__ import annotations

from src.api.builder_context import TOOL_SELECTION_GUIDANCE, render_capability_brief

# --------------------------------------------------------------------------- #
# Schema fragments — kept next to the real configs they describe
# --------------------------------------------------------------------------- #

_AGENT_SCHEMA = """\
## Agent schema

```json
{
  "id": "unique_snake_case_id",
  "type": "LlmAgent",
  "name": "HumanReadableName",
  "description": "One line: what this agent is for",
  "instruction": "The agent's system prompt. Be specific about scope, tone, and when to defer.",
  "tools": ["tool_id_from_the_catalogue"],
  "llm_config": {
    "provider_id": "openrouter",
    "model": "google/gemini-3.5-flash-lite",
    "temperature": 0.4,
    "max_tokens": 2000
  },
  "output_key": "agent_result",
  "is_selector": false,
  "human_input_mode": "NEVER"
}
```

- `type`: use `LlmAgent` for anything conversational or reasoning-based. The
  other values are `RecursiveAgent`, `SequentialAgent`, `ParallelAgent`,
  `LoopAgent`, and `conversable` (legacy — do not choose it for new agents).
- `is_selector`: true only for an agent whose job is routing to other agents.
- `temperature`: 0.1-0.3 for factual and structured work, 0.6-0.8 for creative
  or conversational work.
- `tools`: ids from the catalogue below, or tools you define in the same plan.\
"""

_TOOL_SCHEMA = """\
## Tool schema

A tool's `settings.type` decides which other fields are required.

**function** — a Python callable already in the codebase:
```json
{
  "id": "snake_case_id", "name": "function_name", "category": "utilities",
  "description": "What it does, and the parameters, so an agent knows when to call it",
  "entrypoint": "src.tools.module:function_name",
  "enabled": true, "is_async": false, "settings": {}
}
```

**api** — any REST endpoint:
```json
{
  "id": "get_weather", "name": "get_weather", "category": "integrations",
  "description": "...",
  "entrypoint": "src.tools.api_tool_executor:execute_api_tool",
  "settings": {
    "type": "api", "api_url": "https://api.example.com/x", "http_method": "GET",
    "auth_type": "none", "timeout": 30,
    "parameters": [
      {"name": "city", "in": "query", "required": true,
       "schema": {"type": "string"}, "description": "City name"}
    ]
  }
}
```
Declare every parameter you document — a parameter named only in the
description is not callable.

**sql** — schema introspection plus a guarded query runner (read-only unless
`allow_writes`). Prefer this over `database` when the queries are known:
```json
{"settings": {"type": "sql", "db_uri_env_var": "APP_DB_URI",
              "tables": ["orders"], "max_rows": 200, "allow_writes": false}}
```

**database** — NL2SQL, where the model writes the query from a question.
**mongodb** — `{"type": "mongodb", "uri_env_var": "MONGO_URI", "database": "app"}`.
**mcp** — `{"type": "mcp", "transport": "stdio", "command": "npx", "args": [...]}`.
**gmail** — `{"type": "gmail", "account_email": "...", "capabilities": ["send", "search", "read"]}`.

Never inline a credential. Always use the `*_env_var` form naming an
environment variable, and list that variable under `missing_secrets`.\
"""

_WORKFLOW_SCHEMA = """\
## Workflow schema

```json
{
  "id": "workflow_snake_case_id",
  "name": "Human Readable Name",
  "description": "What this workflow does",
  "enabled": true,
  "pattern": "single",
  "workflow_type": "chatbot",
  "topology": {
    "type": "graph",
    "entry_node": "node_id",
    "nodes": [
      {"id": "node_id", "agent_id": "agent_id", "description": "Role", "tools": ["tool_id"]}
    ],
    "edges": [{"from_node": "a", "to_node": "b"}]
  },
  "execution_config": {"max_turns": 15, "timeout_seconds": 300, "enable_streaming": false}
}
```

Hard rules — breaking any of these makes the workflow fail to apply:
- Every `nodes[].agent_id` must be an agent you defined in this plan, or one
  that already exists.
- `topology.entry_node` must be one of the node ids.
- Repeat each agent's tools on its topology node.
- Prefer the fewest agents that do the job. One is very often correct.

Patterns: `single` (one agent), `selector` (a routing agent delegating to
specialists), `sequential` (a fixed pipeline), `parallel` (concurrent, then
merged), `loop` (repeats until a condition holds).\
"""

_FUNCTION_RULES = """\
## Python function tools

- A standalone sync or async function with type annotations on every parameter
  and on the return.
- A docstring that states what it does, each parameter, and what comes back —
  the agent reads this to decide when to call it.
- Return a string or a JSON-serialisable dict. Return errors as data
  (`{"error": "..."}`), never by raising — an exception reaches the agent as a
  stack trace it cannot act on.
- Standard library, `httpx`, and `requests` are available.
- Saved to `src/tools/generated/` and registered automatically.
- No shell commands, and no filesystem writes outside the uploads directory.

```python
import json
import httpx


def lookup_order(order_id: str) -> str:
    \"\"\"
    Look up an order by its id and return its status and line items.

    Args:
        order_id: The order reference, e.g. "ORD-10231".

    Returns:
        JSON with status, placed_at, and items; or {"error": ...} when the
        order cannot be found.
    \"\"\"
    try:
        response = httpx.get(f"https://api.example.com/orders/{order_id}", timeout=15)
        if response.status_code == 404:
            return json.dumps({"error": f"No order named '{order_id}'."})
        response.raise_for_status()
        return json.dumps(response.json())
    except Exception as exc:
        return json.dumps({"error": f"Order lookup failed: {exc}"})
```\
"""

_SHARED_BEHAVIOUR = """\
## How to work

- Ask one clarifying question at a time, and only when the answer changes what
  you build. Do not interrogate the user for details you can choose sensibly.
- State assumptions rather than stalling on them.
- When the configuration is complete, reply with `CONFIG READY` followed by the
  final JSON in a single ```json block. For Python, `CODE READY` and a
  ```python block.
- Emit one object, not a list, and no prose inside the code block.\
"""


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

_ROLES: dict[str, tuple[str, str]] = {
    "agent": (
        "You design agents for a CrewAI-based multi-agent platform.",
        _AGENT_SCHEMA,
    ),
    "tool": (
        "You design tools for a CrewAI-based multi-agent platform.",
        _TOOL_SCHEMA,
    ),
    "function": (
        "You write Python tool functions for AI agents on a CrewAI-based platform.",
        _FUNCTION_RULES,
    ),
    "workflow": (
        "You architect multi-agent workflows for a CrewAI-based platform.",
        _WORKFLOW_SCHEMA,
    ),
}

BUILDER_TYPES: tuple[str, ...] = tuple(_ROLES)


def get_builder_prompt(builder_type: str) -> str:
    """Assemble the system prompt for one builder type, with the live inventory."""
    role = _ROLES.get(builder_type)
    if role is None:
        raise ValueError(
            f"Unknown builder type: {builder_type!r}. Must be one of: {list(_ROLES)}"
        )

    intro, schema = role

    # A tool builder does not need the agent roster, and a function builder needs
    # neither — trimming keeps the prompt focused on the decision at hand.
    include_agents = builder_type in ("agent", "workflow")
    include_workflows = builder_type == "workflow"

    parts = [intro, "", schema, "", _SHARED_BEHAVIOUR]

    if builder_type != "function":
        parts += [
            "",
            render_capability_brief(
                include_agents=include_agents,
                include_workflows=include_workflows,
            ),
            "",
            TOOL_SELECTION_GUIDANCE,
        ]

    return "\n".join(parts)


# Kept for callers that still import the mapping; each entry is rendered on
# access so a newly registered tool shows up without a restart.
class _LazyPrompts:
    def __getitem__(self, key: str) -> str:
        return get_builder_prompt(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        try:
            return get_builder_prompt(key)
        except ValueError:
            return default

    def __contains__(self, key: str) -> bool:
        return key in _ROLES

    def __iter__(self):
        return iter(_ROLES)

    def keys(self):
        return _ROLES.keys()


BUILDER_PROMPTS = _LazyPrompts()

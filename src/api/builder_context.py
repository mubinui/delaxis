"""What the Builder is allowed to build with, rendered for a prompt.

The builder prompts used to be static text listing a schema and, at most, a
bare list of tool ids. A model given `detect_pii, context_tree, analyze_file`
and nothing else cannot know what those do or when they apply, so it either
ignored them or attached them at random and `_normalize_plan` cleaned up after.

This module reads the platform's actual configuration and renders it as compact
prompt text: every tool with what it is for, every agent that already exists,
the workflows already built, and the enum values the API will accept. The
result is that the Builder proposes things that exist and validate, instead of
plausible-looking ids that fail on apply.

Everything is read fresh per request. The Studio can register a tool at any
time, and a plan built against a stale inventory is exactly the failure this
is meant to remove.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.audit_logging import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Enough to tell the model what a tool is for; the full text is often several
# hundred characters of parameter documentation it does not need while planning.
_SUMMARY_CHARS = 160

# Category order is deliberate: the families a chatbot most often needs come
# first, so the most relevant tools are nearest the top of a long prompt.
_CATEGORY_ORDER = [
    "research", "knowledge", "files", "context", "data",
    "privacy", "security", "audit", "integrations", "identity", "utilities",
]


def _config_dir() -> Path:
    from src.config.env_compat import env

    return Path(env("DELAXIS_CONFIG_DIR", str(_PROJECT_ROOT / "configs")) or str(_PROJECT_ROOT / "configs"))


def _load(name: str) -> dict[str, Any]:
    path = _config_dir() / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("builder_context_config_unreadable", config=name, error=str(exc))
        return {}


def _summarise(text: str) -> str:
    """First sentence of a tool description, without its parameter block."""
    body = (text or "").split("\n\nParameters:")[0].split("\nParameters:")[0].strip()
    body = " ".join(body.split())
    if len(body) <= _SUMMARY_CHARS:
        return body
    cut = body[:_SUMMARY_CHARS]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[: stop + 1] if stop > 60 else cut.rstrip() + "…").strip()


# --------------------------------------------------------------------------- #
# Inventory pieces
# --------------------------------------------------------------------------- #


def tool_inventory() -> list[dict[str, Any]]:
    """Every enabled tool, with what it is for and how it is configured."""
    tools = []
    for tool in _load("tools.json").get("tools", []):
        if not isinstance(tool, dict) or not tool.get("enabled", True):
            continue
        settings = tool.get("settings") or {}
        tools.append(
            {
                "id": tool.get("id", ""),
                "name": tool.get("name", ""),
                "category": tool.get("category") or "utilities",
                "type": settings.get("type", "function"),
                "summary": _summarise(tool.get("description", "")),
                # A tool whose credentials are not set will fail at run time, and
                # the model should prefer one that works.
                "needs_config": bool(
                    settings.get("db_uri_env_var")
                    or settings.get("uri_env_var")
                    or settings.get("auth_env_var")
                    or settings.get("account_email") == ""
                ),
            }
        )
    return tools


def agent_inventory() -> list[dict[str, str]]:
    """Agents already defined, so the Builder can reuse rather than duplicate."""
    raw = _load("agents.json")
    agents = raw.get("agents", raw if isinstance(raw, list) else [])
    out = []
    for agent in agents if isinstance(agents, list) else []:
        if not isinstance(agent, dict):
            continue
        out.append(
            {
                "id": agent.get("id", ""),
                "name": agent.get("name", ""),
                "description": _summarise(agent.get("description") or agent.get("system_message", "")),
                "tools": ", ".join(agent.get("tools") or []) or "none",
            }
        )
    return out


def workflow_inventory() -> list[dict[str, str]]:
    """Workflows already built, as worked examples of the shape that validates."""
    raw = _load("workflows.json")
    workflows = raw.get("workflows", raw if isinstance(raw, list) else [])
    out = []
    for workflow in workflows if isinstance(workflows, list) else []:
        if not isinstance(workflow, dict) or not workflow.get("enabled", True):
            continue
        topology = workflow.get("topology") or {}
        out.append(
            {
                "id": workflow.get("id", ""),
                "name": workflow.get("name", ""),
                "pattern": str(workflow.get("pattern", "")),
                "nodes": str(len(topology.get("nodes") or [])),
            }
        )
    return out


def allowed_values() -> dict[str, list[str]]:
    """The enums the API validates against, read from the source of truth."""
    values: dict[str, list[str]] = {}

    try:
        from src.config.tool_models import VALID_TOOL_TYPES

        values["tool_types"] = sorted(VALID_TOOL_TYPES)
    except Exception:
        values["tool_types"] = ["function", "api", "mcp", "database", "sql", "mongodb", "gmail"]

    try:
        from src.config.workflow_models import ConversationPattern

        values["patterns"] = [member.value for member in ConversationPattern]
    except Exception:
        values["patterns"] = ["single", "sequential", "selector", "parallel", "loop"]

    return values


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_tool_catalogue(include_config_state: bool = True) -> str:
    """The tool list as prompt text, grouped by category."""
    tools = tool_inventory()
    if not tools:
        return "No tools are registered. Define any tool you need under tools[]."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        grouped.setdefault(tool["category"], []).append(tool)

    ordered = sorted(
        grouped.items(),
        key=lambda item: (_CATEGORY_ORDER.index(item[0]) if item[0] in _CATEGORY_ORDER else 99, item[0]),
    )

    lines = []
    for category, items in ordered:
        lines.append(f"\n{category.upper()}")
        for tool in sorted(items, key=lambda t: t["id"]):
            note = ""
            if include_config_state and tool["needs_config"]:
                note = "  [needs credentials before it will run]"
            lines.append(f"  {tool['id']} — {tool['summary']}{note}")
    return "\n".join(lines).strip()


def render_agent_catalogue() -> str:
    agents = agent_inventory()
    if not agents:
        return "No agents exist yet."
    return "\n".join(
        f"  {a['id']} ({a['name']}) — {a['description']} | tools: {a['tools']}" for a in agents
    )


def render_workflow_catalogue() -> str:
    workflows = workflow_inventory()
    if not workflows:
        return "No workflows exist yet."
    return "\n".join(
        f"  {w['id']} — {w['name']} | pattern: {w['pattern']}, {w['nodes']} node(s)" for w in workflows
    )


def render_capability_brief(include_agents: bool = True, include_workflows: bool = True) -> str:
    """The full inventory block appended to a builder system prompt."""
    values = allowed_values()
    sections = [
        "# What this platform actually has",
        "",
        "Everything below is live configuration. Prefer these over inventing new",
        "ids: a tool id that does not exist here will fail when the plan is applied.",
        "",
        "## Tools you can attach to an agent",
        render_tool_catalogue(),
        "",
        f"## Valid tool types\n  {', '.join(values['tool_types'])}",
        f"\n## Valid workflow patterns\n  {', '.join(values['patterns'])}",
    ]

    if include_agents:
        sections += ["", "## Agents that already exist", render_agent_catalogue()]
    if include_workflows:
        sections += ["", "## Workflows that already exist", render_workflow_catalogue()]

    return "\n".join(sections)


# --------------------------------------------------------------------------- #
# Guidance the model needs regardless of builder type
# --------------------------------------------------------------------------- #

TOOL_SELECTION_GUIDANCE = """\
# Choosing tools

Tools are opt-in, not a menu to fill. Most assistants need zero or one. An agent
with no tools is a normal, good answer.

Attach a tool only when the brief describes something the agent cannot do by
talking: reading live data, arithmetic it must get exactly right, searching the
user's own documents, calling a named system. Never attach one speculatively or
because it exists — a tool the agent does not need makes it slower and less
reliable.

Some pairings that are usually right:
  - "search the web", "current", "latest"      -> web_search
  - "our documents", "knowledge base", "PDFs"  -> rag_query (and rag_ingest_file to load them)
  - "uploaded file", "spreadsheet", "image"    -> analyze_file / analyze_image
  - "browse a folder", "find in these files"   -> context_tree, search_context_tree, read_context_file
  - "database", "SQL", "our records"           -> a sql tool you define, or query_audit_log for audit data
  - "personal data", "GDPR", "redact"          -> detect_pii, redact_pii
  - "untrusted input", "prompt injection"      -> security_scan, detect_prompt_injection
  - "compliance", "who did what", "audit"      -> record_audit_event, query_audit_log
  - exact arithmetic                           -> calculate

For every tool attached, be able to name the phrase in the brief that requires
it. If you cannot, leave it off.\
"""

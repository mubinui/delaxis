"""The operations a spoken build conversation may perform on the canvas.

The realtime session used to be audio-only: ``setup`` declared a model, a voice
and transcription, and nothing else. With no tools declared, the model had no
mechanism to act, which is why the persona had to forbid it from claiming it
had built anything — it genuinely could not.

Declaring these changes that. The model can now say "I'll add a search agent"
and actually add one, because each function below is relayed to the browser,
applied to the live canvas, and answered with the result.

Two rules shape the schema:

* **Everything is named, nothing is addressed by index.** The model is holding a
  conversation, not a data structure; "the search agent" is something it can say
  reliably, ``node_7`` is not.
* **Removal is separate and explicit.** Adding the wrong thing during a chat is
  a small annoyance; deleting the wrong thing is the failure that makes someone
  stop trusting the feature. Destructive calls are marked so the client can
  require confirmation without the model deciding that for itself.
"""

from __future__ import annotations

from typing import Any, Final

# Calls the client should confirm with the user before applying. Kept here
# rather than in the browser so the policy travels with the schema.
DESTRUCTIVE: Final[frozenset[str]] = frozenset({"remove_node", "clear_canvas"})


def _string(description: str) -> dict[str, Any]:
    return {"type": "STRING", "description": description}


CANVAS_FUNCTIONS: Final[list[dict[str, Any]]] = [
    {
        "name": "add_agent",
        "description": (
            "Add an AI agent to the canvas. Use when the person asks for a new "
            "worker, specialist, assistant, or step that reasons. Returns the "
            "name it was given."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": _string("Short name, e.g. 'Search Specialist' or 'Refund Agent'"),
                "role": _string("One line: what this agent is responsible for"),
                "instruction": _string(
                    "The agent's system prompt. Write it properly — this is what "
                    "the agent actually follows at run time."
                ),
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_tool",
        "description": (
            "Attach a tool to an agent so it can do something it cannot do by "
            "talking. Call list_available_tools first if unsure what exists."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tool_id": _string("Tool id from the catalogue, e.g. 'web_search' or 'detect_pii'"),
                "agent_name": _string(
                    "Which agent to attach it to. Omit to attach to the most "
                    "recently added agent."
                ),
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "add_trigger",
        "description": "Add the entry point that starts the workflow.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {
                    "type": "STRING",
                    "enum": ["manual", "chat", "webhook"],
                    "description": "manual = run by hand, chat = a user message, webhook = an inbound HTTP call",
                },
            },
            "required": ["kind"],
        },
    },
    {
        "name": "connect",
        "description": (
            "Wire one component's output into another's input, setting the order "
            "work flows through the graph."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "from_name": _string("Name of the component work flows out of"),
                "to_name": _string("Name of the component work flows into"),
            },
            "required": ["from_name", "to_name"],
        },
    },
    {
        "name": "set_instruction",
        "description": (
            "Rewrite an agent's system prompt. Use when the person says to change "
            "what an agent should do, its tone, or its rules."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "agent_name": _string("Which agent to change"),
                "instruction": _string("The complete new system prompt, not a fragment"),
            },
            "required": ["agent_name", "instruction"],
        },
    },
    {
        "name": "set_model",
        "description": "Change which model an agent runs on, or its temperature.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "agent_name": _string("Which agent to change"),
                "model": _string("Model id, e.g. 'google/gemini-3.5-flash-lite'"),
                "temperature": {
                    "type": "NUMBER",
                    "description": "0.1-0.3 for factual work, 0.6-0.8 for creative work",
                },
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "remove_node",
        "description": (
            "Delete a component from the canvas. Only call this when the person "
            "clearly asked for it to be removed."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": _string("Name of the component to delete")},
            "required": ["name"],
        },
    },
    {
        "name": "describe_canvas",
        "description": (
            "Read what is currently on the canvas — every component, how they are "
            "wired, and what still needs configuring. Call this before answering "
            "any question about the current state, and after a change you are "
            "unsure landed."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "list_available_tools",
        "description": (
            "List the tools installed on this platform, with what each is for. "
            "Call before attaching a tool so you name one that exists."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": _string(
                    "Optional filter: privacy, security, audit, context, files, "
                    "data, knowledge, research, integrations, utilities"
                ),
            },
        },
    },
    {
        "name": "fix_problems",
        "description": (
            "Repair what the workflow diagnostics can fix on their own — a missing "
            "trigger, an unresolvable tool reference, a broken connection. Use when "
            "the person asks to fix or tidy things up."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]


def build_tool_declaration() -> list[dict[str, Any]]:
    """The ``setup.tools`` value for a build conversation."""
    return [{"functionDeclarations": CANVAS_FUNCTIONS}]


def is_destructive(name: str) -> bool:
    return name in DESTRUCTIVE


FUNCTION_NAMES: Final[frozenset[str]] = frozenset(f["name"] for f in CANVAS_FUNCTIONS)

"""The system instruction handed to the realtime model.

Native realtime voice talks to the model directly — the canvas workflow, its
tools and its routing do not run. So the model has to be told who it is, and it
should describe itself the same way the text agent does or the deployment will
appear to have two personalities.

The chain therefore prefers an explicit per-deployment prompt, then falls back
to the entry agent's own ``system_message``/``description`` — mirroring the
backstory fallback the CrewAI runtime uses when it builds that same agent.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Appended to every persona. Realtime output is spoken, and everything a text
# model reasonably does — markdown, bullet lists, code fences, emoji — is either
# unspeakable or read out literally.
VOICE_ADDENDUM = """
You are speaking out loud, and your reply will be converted to speech.
Keep answers to one or two short sentences unless the user asks for detail.
Never use markdown, bullet points, numbered lists, code blocks, or emoji — they
cannot be spoken. Write numbers, units and abbreviations the way they should be
said. If you do not know something, say so briefly.
""".strip()

GENERIC_PERSONA = "You are a helpful voice assistant for {title}."

# The Studio's build assistant. Native realtime voice cannot call this
# application's endpoints, so this agent deliberately does not pretend to build
# anything — it interviews you, and what you say is captured into the build brief
# for the button to use. Saying otherwise would be the fastest way to make the
# feature feel broken.
BUILDER_PERSONA = """
You are the build partner for Delaxis, a studio for designing multi-agent AI
workflows. You are talking with someone while they build, and you can change the
canvas yourself as you talk.

You have tools that add agents, attach tools to them, wire them together, rewrite
an agent's instructions, change its model, and repair problems. Use them. When
someone says "add a search agent", add it — do not describe how they could. When
they say "give it web search", attach it. Then say in one short sentence what you
did, and stop. They can see the canvas; you do not need to narrate it.

Work in small steps, the way a colleague at the same keyboard would:

- Do the obvious thing immediately rather than asking permission for it. If they
  say "add an agent that answers from our docs", add the agent and attach the
  document tool.
- Ask only when the answer changes what you build and you cannot reasonably
  guess. One short question, then act.
- Call describe_canvas before answering any question about what is there, and
  whenever you have lost track. Never guess at the current state.
- Call list_available_tools before attaching a tool, so you name one that exists.
- Deleting is different from adding: only remove something when they clearly
  asked you to.

If a tool call fails, say plainly what did not work and what you need — do not
pretend it succeeded, and do not silently try something else instead.

Vocabulary, so you can be specific: an *agent* is one AI worker with a role and
tools; a *tool* is a function or REST API an agent may call; a *workflow* wires
agents together in sequence, in parallel, or behind a router; a *deployment*
publishes a workflow as a chat page.
""".strip()

# Realtime setup frames are sent once per session and count against context;
# there is no value in shipping a novel.
MAX_INSTRUCTION_CHARS = 4000

# Enough recent turns to keep voice continuous with the text conversation in the
# same session, without re-sending an entire history every time the mic opens.
RECENT_TURNS = 6


def _entry_agent_persona(workflow_id: str) -> str:
    """The entry agent's own self-description, or "" if it cannot be resolved."""
    if not workflow_id:
        return ""
    try:
        from src.config.loader import load_agents_config
        from src.config.workflow_registry import get_workflow_registry

        workflow = get_workflow_registry().get_workflow(workflow_id)
        if workflow is None:
            return ""

        topology = getattr(workflow, "topology", None)
        entry_node_id = getattr(topology, "entry_node", None)
        nodes = list(getattr(topology, "nodes", []) or [])
        node = next((n for n in nodes if getattr(n, "id", None) == entry_node_id), None)
        if node is None and nodes:
            node = nodes[0]
        agent_id = getattr(node, "agent_id", None) if node is not None else None
        if not agent_id:
            return ""

        agent = load_agents_config().get_agent(str(agent_id))
        if agent is None:
            return ""
        return str(getattr(agent, "system_message", "") or getattr(agent, "description", "") or "")
    except Exception as exc:
        # A persona is a nicety; never fail a voice session over it.
        logger.warning("voice_persona_lookup_failed", workflow_id=workflow_id, error=str(exc))
        return ""


def _recent_conversation(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for message in history[-RECENT_TURNS:]:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        speaker = "User" if role == "user" else "You"
        lines.append(f"{speaker}: {content}")
    if not lines:
        return ""
    return "Recent conversation in this session:\n" + "\n".join(lines)


def build_builder_instruction(*, draft: str = "") -> str:
    """The instruction for the Studio's spoken build assistant.

    ``draft`` is whatever is already in the brief box, so the conversation picks
    up from what has been written rather than starting cold.
    """
    parts = [BUILDER_PERSONA, VOICE_ADDENDUM]
    draft = (draft or "").strip()
    if draft:
        parts.append(
            "They have already written this much of the brief — build on it "
            f"rather than starting over:\n{draft[:1500]}"
        )
    instruction = "\n\n".join(parts)
    return instruction[:MAX_INSTRUCTION_CHARS]


def build_system_instruction(
    *,
    title: str = "this assistant",
    system_prompt: str = "",
    workflow_id: str = "",
    history: list[dict] | None = None,
) -> str:
    """Assemble the realtime system instruction, first non-empty persona wins."""
    persona = (system_prompt or "").strip()
    if not persona:
        persona = _entry_agent_persona(workflow_id).strip()
    if not persona:
        persona = GENERIC_PERSONA.format(title=title or "this assistant")

    parts = [persona, VOICE_ADDENDUM]
    recent = _recent_conversation(history)
    if recent:
        parts.append(recent)

    instruction = "\n\n".join(parts)
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        # Trim the persona rather than the addendum — the speaking rules are what
        # keep the output listenable, so they must survive.
        budget = MAX_INSTRUCTION_CHARS - len(VOICE_ADDENDUM) - 2
        instruction = f"{persona[:max(0, budget)].rstrip()}\n\n{VOICE_ADDENDUM}"
    return instruction

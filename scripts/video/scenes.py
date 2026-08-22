"""The narration script for the Delaxis product video.

One list, read by both halves of the pipeline: ``make_narration.py`` turns each
``say`` into audio and measures it, and ``record.mjs`` holds each scene on
screen for exactly that long. Keeping the text and the on-screen action in the
same record is what keeps them in sync — there is no separate timing file to
drift.

Lines are deliberately short. An earlier cut ran four and a half minutes and
dragged; the same material at half the word count moves. Say one thing per
shot and let the screen carry the rest.

``action`` names a step implemented in ``record.mjs``; ``card`` scenes are
animated title frames rendered from ``titles/`` instead of the live app.
"""

from dataclasses import dataclass


@dataclass
class Scene:
    id: str
    action: str
    say: str
    #: Held after the narration ends, so a click has time to land visually.
    tail_seconds: float = 0.5
    #: Title card to render instead of driving the app.
    card: str = ""


SCENES: list[Scene] = [
    Scene(
        id="intro",
        action="title_card",
        card="intro",
        say="Introducing Delaxis, version two point one.",
        tail_seconds=1.4,
    ),
    Scene(
        id="open",
        action="landing",
        say=(
            "An open source studio for building AI systems where several agents "
            "work together. It runs entirely on your own machine."
        ),
    ),
    Scene(
        id="who",
        action="landing_features",
        say=(
            "It's built for two people at once. Describe what you want in plain "
            "words, or open the hood and configure every detail."
        ),
    ),
    Scene(
        id="builder_open",
        action="open_builder",
        say="Start with plain words. This is the Builder.",
    ),
    Scene(
        id="builder_type",
        action="type_brief",
        say=(
            "One sentence: a support assistant that answers from our docs and "
            "escalates what it can't handle."
        ),
    ),
    Scene(
        id="builder_knows",
        action="hold_builder",
        say=(
            "It can see all twenty seven installed tools and every existing agent, "
            "so it picks real components instead of inventing names that fail."
        ),
    ),
    Scene(
        id="canvas",
        action="show_canvas",
        say=(
            "What it builds lands on the canvas. Every box is an agent or a tool. "
            "The lines are the path a conversation takes."
        ),
    ),
    Scene(
        id="run",
        action="run_workflow",
        say=(
            "And you can run it right here. The execution timeline lists every "
            "agent handover and tool call in order, so you see exactly what ran."
        ),
        tail_seconds=2.4,
    ),
    Scene(
        id="palette",
        action="palette_drag",
        say="Drag anything from the palette to change it. That's the whole gesture.",
    ),
    Scene(
        id="library",
        action="open_store",
        say=(
            "The library is a store. Forty eight components, shelved by what they "
            "do, all draggable."
        ),
    ),
    Scene(
        id="library_category",
        action="filter_store",
        say=(
            "Handling personal data? The privacy shelf finds and removes it before "
            "it ever reaches a model."
        ),
    ),
    Scene(
        id="technical",
        action="open_inspector",
        say="Now the other audience. Nothing is hidden from you.",
    ),
    Scene(
        id="technical_depth",
        action="inspector_tabs",
        say=(
            "Model and temperature. Which tools it can reach. Turn limits, and "
            "whether a human approves before it acts. Override any of it."
        ),
    ),
    Scene(
        id="tools",
        action="show_tool_families",
        say=(
            "Query SQL and Mongo with read only enforced. Read uploaded PDFs. "
            "Catch leaked credentials and prompt injection. Write to an audit "
            "trail that can't be quietly edited."
        ),
    ),
    Scene(
        id="help_open",
        action="open_help",
        say=(
            "Something wrong? Help reads your workflow and says exactly what's "
            "broken, and where."
        ),
    ),
    Scene(
        id="help_fix",
        action="help_fix",
        say=(
            "Then it fixes it. A missing trigger, added and wired. A broken "
            "reference, removed. Anything needing your judgement, it explains "
            "instead."
        ),
    ),
    Scene(
        id="outro",
        action="title_card",
        card="outro",
        say=(
            "Delaxis two point one. Free, open source, and yours to self host. "
            "Pull the container, or try the live demo in your browser right now."
        ),
        tail_seconds=2.2,
    ),
]

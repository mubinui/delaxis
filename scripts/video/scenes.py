"""The narration script for the Delaxis product video.

One list, read by both halves of the pipeline: ``make_narration.py`` turns each
``say`` into audio and measures it, and ``record.mjs`` holds each scene on
screen for exactly that long. Keeping the text and the on-screen action in the
same record is what keeps them in sync — there is no separate timing file to
drift.

Each scene's ``action`` names a step implemented in ``record.mjs``. Adding a
scene here without adding the matching action there fails loudly rather than
silently recording a still frame.
"""

from dataclasses import dataclass


@dataclass
class Scene:
    id: str
    action: str
    say: str
    #: Held after the narration ends, so a click has time to land visually.
    tail_seconds: float = 0.8


SCENES: list[Scene] = [
    Scene(
        id="open",
        action="landing",
        say=(
            "This is Delaxis. It's an open source studio for building AI systems "
            "where several agents work together. It runs entirely on your own "
            "machine, and everything you're about to see is the real product."
        ),
    ),
    Scene(
        id="who",
        action="landing_features",
        say=(
            "It's built for two kinds of people at once. If you've never written "
            "code, you can describe what you want in plain language and get a "
            "working chatbot. If you're an engineer, every setting underneath is "
            "yours to change. Let's start with the plain language route."
        ),
    ),
    Scene(
        id="builder_open",
        action="open_builder",
        say=(
            "This is the Builder. You tell it what you need in ordinary words. "
            "No diagram, no configuration files, no decisions about model "
            "parameters. Just describe the assistant you want."
        ),
    ),
    Scene(
        id="builder_type",
        action="type_brief",
        say=(
            "Here I'm asking for a customer support assistant that can search our "
            "documentation and hand difficult cases to a human. That's the whole "
            "input. In a moment the Builder turns that sentence into agents, "
            "tools, and a working workflow."
        ),
    ),
    Scene(
        id="builder_knows",
        action="hold_builder",
        say=(
            "The important part is that the Builder knows what this platform "
            "actually contains. It can see all twenty seven installed tools, what "
            "each one is for, and which agents already exist. So it picks real "
            "components that work, instead of inventing names that fail later."
        ),
    ),
    Scene(
        id="canvas",
        action="show_canvas",
        say=(
            "What it produces lands here, on the canvas. Every box is an agent or "
            "a tool, and the lines are the path a conversation takes through them. "
            "You can read the whole system at a glance."
        ),
    ),
    Scene(
        id="palette",
        action="palette_drag",
        say=(
            "You're never locked into what was generated. The palette on the left "
            "holds every building block, grouped by what it does. Drag one onto "
            "the canvas and it becomes part of the system. That's the entire "
            "gesture."
        ),
    ),
    Scene(
        id="library",
        action="open_store",
        say=(
            "The library works like a store. Forty eight components, sorted into "
            "categories: agents, data, files, privacy, security, audit. Search it, "
            "browse a shelf, and drag anything straight onto your canvas."
        ),
    ),
    Scene(
        id="library_category",
        action="filter_store",
        say=(
            "Say you need to handle personal data carefully. Open the privacy "
            "shelf and there are tools that find and remove personal information "
            "before it ever reaches a model. Attaching one is a single click."
        ),
    ),
    Scene(
        id="technical",
        action="open_inspector",
        say=(
            "Now for the other audience. If you know what you're doing, nothing is "
            "hidden from you. Select any agent and the inspector opens every "
            "setting behind it."
        ),
    ),
    Scene(
        id="technical_depth",
        action="inspector_tabs",
        say=(
            "Which model it runs on and at what temperature. Which tools it can "
            "reach. How many turns it may take, and whether a human is asked "
            "before it acts. The plain language route sets sensible defaults for "
            "all of this. You can override every one of them."
        ),
    ),
    Scene(
        id="tools",
        action="show_tool_families",
        say=(
            "The tools go well beyond web search. Agents can query SQL and MongoDB "
            "databases with read only access enforced, read uploaded PDFs and "
            "spreadsheets, walk a folder of documents, detect leaked credentials "
            "and prompt injection attempts, and write to an audit trail that can't "
            "be quietly edited afterwards."
        ),
    ),
    Scene(
        id="help_open",
        action="open_help",
        say=(
            "If something's wrong, Help is where you learn. It reads your workflow "
            "and lists what's actually broken, in plain terms, pointing at the "
            "exact component causing each problem."
        ),
    ),
    Scene(
        id="help_fix",
        action="help_fix",
        say=(
            "And it doesn't stop at describing the problem. Where the fix is "
            "unambiguous, Help applies it for you. A missing trigger gets added "
            "and connected. A broken tool reference gets removed. Anything that "
            "needs your judgement, it leaves alone and explains instead."
        ),
    ),
    Scene(
        id="help_learn",
        action="help_components",
        say=(
            "It also works as documentation. Every component has an explanation of "
            "what it does and when you'd reach for it, right next to the thing "
            "itself. It's the fastest way to learn the system while you build in "
            "it."
        ),
    ),
    Scene(
        id="close",
        action="closing",
        say=(
            "When it's ready, one click publishes it as a chat page you can share "
            "or embed anywhere. Delaxis is open source and free to self host. "
            "Describe what you want, or build it yourself piece by piece. It works "
            "the same either way."
        ),
        tail_seconds=1.6,
    ),
]

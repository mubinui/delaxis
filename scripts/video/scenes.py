"""The narration script for the Delaxis product video.

One list, read by both halves of the pipeline: ``make_narration.py`` turns each
``say`` into audio and measures it, and ``record.mjs`` holds each scene on
screen for exactly that long. Keeping the text and the on-screen action in the
same record is what keeps them in sync — there is no separate timing file to
drift.

Lines are deliberately short. An earlier cut ran four and a half minutes and
dragged; the same material at half the word count moves. Say one thing per
shot and let the screen carry the rest.

``action`` names a step implemented in ``record.mjs``. ``card`` scenes are
animated title frames rendered from ``titles/`` instead of the live app.
``chapter`` groups scenes into one continuous take — the recorder starts a fresh
capture at every change, and the assembler dissolves between them, which is what
gives the cut its section breaks.
"""

from dataclasses import dataclass


@dataclass
class Scene:
    id: str
    action: str
    say: str
    #: Scenes sharing a chapter are recorded as one take; a change starts a new
    #: take, and the assembler crossfades the seam.
    chapter: str = "body"
    #: Held after the narration ends, so a click has time to land visually.
    tail_seconds: float = 0.5
    #: Title card to render instead of driving the app.
    card: str = ""


#: Spoken into the browser's microphone during the voice chapter. Chromium is
#: given this as a fake capture device, so the session recorded is a real one —
#: a real model hearing a real sentence and really adding the agent. Nothing in
#: that chapter is staged.
VOICE_INSTRUCTION = (
    "Add an agent called Docs Answerer that answers questions from our "
    "documentation, and give it web search."
)


SCENES: list[Scene] = [
    Scene(
        id="intro",
        action="title_card",
        chapter="intro",
        card="intro",
        say="Introducing Delaxis, version two point one.",
        tail_seconds=4.0,
    ),

    # -- what it is ---------------------------------------------------------
    Scene(
        id="open",
        action="landing",
        chapter="landing",
        say=(
            "An open source studio for building AI systems where several agents "
            "work together. It runs entirely on your own machine."
        ),
    ),
    Scene(
        id="who",
        action="landing_features",
        chapter="landing",
        say=(
            "Built for two people at once. Describe what you want in plain words, "
            "or configure every detail yourself."
        ),
    ),

    # -- describing it ------------------------------------------------------
    Scene(
        id="builder_open",
        action="open_builder",
        chapter="builder",
        say="Start with plain words. This is the Builder.",
    ),
    Scene(
        id="builder_type",
        action="type_brief",
        chapter="builder",
        say=(
            "One sentence: a support assistant that answers from our docs and "
            "escalates what it can't handle."
        ),
    ),
    Scene(
        id="builder_knows",
        action="hold_builder",
        chapter="builder",
        say=(
            "It can see all twenty seven installed tools and every existing "
            "agent, so it picks real components instead of inventing names."
        ),
    ),

    # -- talking to it ------------------------------------------------------
    Scene(
        id="voice_open",
        action="voice_open",
        chapter="voice",
        say="Or skip the typing altogether. Press the microphone and talk.",
    ),
    Scene(
        id="voice_build",
        action="voice_build",
        chapter="voice",
        say=(
            "This is a live conversation, not a recording. It listens, and it "
            "builds while you are still speaking."
        ),
        tail_seconds=2.0,
    ),
    Scene(
        id="voice_result",
        action="voice_result",
        chapter="voice",
        say=(
            "That agent is real, on the canvas and ready to configure. Keep "
            "talking and it keeps changing it."
        ),
    ),

    # -- the canvas ---------------------------------------------------------
    Scene(
        id="canvas",
        action="show_canvas",
        chapter="canvas",
        say=(
            "Everything lands on the canvas. Every box is an agent or a tool. "
            "The lines are the path a conversation takes."
        ),
    ),
    Scene(
        id="run",
        action="run_workflow",
        chapter="canvas",
        say=(
            "And you can run it right here. The execution timeline lists every "
            "agent handover and tool call in order."
        ),
        tail_seconds=2.0,
    ),

    # -- composing by hand --------------------------------------------------
    Scene(
        id="palette",
        action="palette_drag",
        chapter="compose",
        say="Drag anything from the palette to change it. That's the whole gesture.",
    ),
    Scene(
        id="library",
        action="open_store",
        chapter="compose",
        say="The library is a store. Forty eight components, shelved by what they do.",
    ),
    Scene(
        id="library_category",
        action="filter_store",
        chapter="compose",
        say=(
            "Handling personal data? The privacy shelf finds and removes it "
            "before it ever reaches a model."
        ),
    ),

    # -- for the technical audience ----------------------------------------
    Scene(
        id="technical",
        action="open_inspector",
        chapter="inspect",
        say="Now the other audience. Nothing here is hidden from you.",
    ),
    Scene(
        id="technical_depth",
        action="inspector_tabs",
        chapter="inspect",
        say=(
            "Model and temperature. Which tools it can reach. Turn limits, and "
            "whether a human approves before it acts."
        ),
    ),
    Scene(
        id="tools",
        action="show_tool_families",
        chapter="inspect",
        say=(
            "Query SQL and Mongo with read only enforced. Read uploaded files. "
            "Catch leaked credentials and prompt injection. Write to an audit "
            "trail that cannot be quietly edited."
        ),
    ),

    # -- fixing it ----------------------------------------------------------
    Scene(
        id="help_open",
        action="open_help",
        chapter="help",
        say=(
            "Something wrong? Help reads your workflow and says exactly what's "
            "broken, and where."
        ),
    ),
    Scene(
        id="help_fix",
        action="help_fix",
        chapter="help",
        say=(
            "Then it fixes it. A missing trigger, added and wired. Anything "
            "needing your judgement, it explains instead."
        ),
    ),

    # -- shipping it --------------------------------------------------------
    Scene(
        id="deploy_open",
        action="deploy_open",
        chapter="deploy",
        say=(
            "When it works, ship it. Pick a theme, write the greeting, and "
            "Flash Deploy publishes the whole thing."
        ),
    ),
    Scene(
        id="deploy_publish",
        action="deploy_publish",
        chapter="deploy",
        say=(
            "You get a hosted URL, an embed snippet for your own site, and an "
            "API endpoint. There is no separate frontend project to build."
        ),
        tail_seconds=1.2,
    ),

    # -- the thing you shipped ---------------------------------------------
    Scene(
        id="frontend_open",
        action="frontend_open",
        chapter="frontend",
        say=(
            "Here is that page, live on its own address. Themed, with chat "
            "history and voice already in it."
        ),
    ),
    Scene(
        id="frontend_chat",
        action="frontend_chat",
        chapter="frontend",
        say=(
            "A real answer, from the workflow you just built. Anyone you send "
            "the link to can use it."
        ),
        # The workflow really runs here — about five seconds — and then the
        # answer wants a beat to be read.
        tail_seconds=4.5,
    ),

    Scene(
        id="outro",
        action="title_card",
        chapter="outro",
        card="outro",
        say=(
            "Delaxis two point one. Free, open source, and yours to self host. "
            "Pull the container, or try the live demo in your browser right now."
        ),
        tail_seconds=4.0,
    ),
]

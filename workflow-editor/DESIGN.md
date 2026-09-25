# Delaxis Studio — design system

Delaxis is drawn as a macOS 27 ("Golden Gate") pro app: the window is the frame,
a Liquid Glass sidebar runs flush to its leading edge, a frosted toolbar band
lies over the content, and content is opaque. The accent is **Graphite**. Colour
is kept for status (always paired with a shape) and for the *kind* of a canvas
component. There is no blue, no orange and no brown anywhere in the chrome.

The system is ported from the Weft build of the same language; this file records
what it looks like in Delaxis and where it departs.

Everything lives in `src/index.css`. Tokens are CSS custom properties on `:root`
and `.dark`; components use the classes described below, and Tailwind utilities
for layout.

## Rules

1. **Graphite accent.** `--accent-fill` is `#1d1d1f` on light and `#f5f5f7` on
   dark, so the primary button is the darkest thing on a light window and the
   lightest on a dark one. Links are told apart by an underline, not a hue. One
   solid (`.btn-primary`) button per view — in the Studio that is **Test**.
2. **Status has a shape.** `<StatusGlyph shape>`: ready is a green disc, attention
   a yellow ring, error a red diamond, idle a thin ring, busy a spinning ring.
   `StatusBadge` leads with the same glyph. Never a bare coloured dot.
3. **Yellow is never text on a light window.** `--amber` is only a glyph, a tint or
   a meter; `--amber-text` is ink on light and yellow on dark.
4. **Glass is chrome, and it sits flat.** Only the sidebar, the toolbar band and
   its capsules, menus, popovers, toasts, and panes floating over the canvas are
   translucent. Pages, tables and grouped boxes are opaque. The glass keeps its
   blur and edge but only a faint sheen and a 1–3px shadow: nothing lifts, scales
   or bounces on hover.
5. **System fonts only.** `-apple-system … system-ui`; SF Mono only for machine
   data (ids, model strings, code). 13px body, 28px large titles, 11px semibold
   section labels in sentence case. `.uppercase` and wide tracking are neutralised
   globally.
6. **Tables, not card walls,** for lists of things with state (Deployments), with
   an inspector for the selected row. Headline numbers go in one `.figures` strip.
7. **The canvas gets the room.** In the Studio the sidebar is a 64px icon rail
   (the sidebar button expands it; that choice sticks). The palette, inspector,
   test chat, Builder and Help float over the canvas as `.glass-pane`s, 10px from
   its edges. Opening a workflow closes the palette; opening a pane or selecting
   a component pans the graph clear of it at the same zoom — it never re-zooms.
8. **Wires are neutral grey** (`--wire`) bezier curves, as n8n draws them. The
   selected component's wires turn ink and the rest fade to 35%; attachment wires
   are straight and dashed. A running path is ink.
9. **Scrolling is quiet.** Scrollbars are macOS overlay thumbs that appear only
   while the pointer is over the region; lists inside panes use `.scroll-soft`, so
   content fades at the edges instead of being cut by a hard line.

## Tokens

| Group | Tokens |
|---|---|
| Materials | `--window` `--glass` `--glass-raised` `--glass-sunken` `--popover` `--sidebar` `--solid` |
| Fills and lines | `--fill` `--fill-hover` `--fill-active` `--line` `--line-strong` `--field-border` |
| Text | `--text` `--muted` `--dim` |
| Accent | `--accent-fill` `--accent-hi` `--accent-lo` `--accent-wash` `--on-accent` `--focus` |
| Status | `--sage(-wash)` `--amber` `--amber-text` `--amber-wash` `--clay(-wash)` |
| Liquid Glass | `--lg-fill` `--lg-edge` `--lg-spec` `--lg-sheen` `--lg-lift` `--toolbar-band` |
| Wallpaper | `--wall-a/b/c` — painted on `.app`, seen only through the sidebar |
| Place hues | `--hue-1`…`--hue-9`, one per sidebar place, icon only |
| Kinds | `--k-trigger` teal, `--k-agent` violet, `--k-logic` magenta, `--k-tool` cyan, `--k-data` green, `--k-trust` purple, `--k-connect` pink, `--k-output` graphite |

Light and dark values are defined together; dark is applied by the `.dark` class
that `useTheme` sets from the Light / Dark / Match system menu (More ⋯ →
Appearance).

### Legacy names

Older code reaches for `--surface-*`, `--text-primary`, `--accent`, `--tone-*`,
`--status-*` and `--color-*`. These are aliases onto the tokens above, so every
component follows the system without being rewritten. Tailwind's `gray`,
`slate`, `zinc` ramps are re-pointed at neutral Apple greys, `blue`/`sky`/`indigo`
at Graphite, and `orange`/`amber`/`yellow` at a yellow whose text shades are ink.
New code should use the tokens and classes, not palette utilities.

## Shell

- **Sidebar** (`AppSidebar`, `.app-nav`): 232px flush glass; 204px below 1280px, a
  68px icon rail below 1024px, a drawer below 768px. In the Studio it is a 64px
  rail (`[data-rail]`) by default, with each place named in a tooltip. Places: Studio, Model tester,
  Deployments; Library — Everything, Agents, Tools, Functions, Prompts,
  Providers; System — Health and data. Backend status and Account at the foot.
- **Toolbar** (`Toolbar`, `.app-header`): 60px frosted band over the content.
  Leading: the sidebar button. Centre: the activity capsule. Trailing: glass
  capsules, then More (⋯). It never names the page.
- **Activity capsule** (`ActivityCapsule`): the open workflow's name (editable in
  the Studio, with a chevron listing saved workflows), then its state — running,
  empty, problems, warnings, or ready with a component count. Clicking the state
  opens Help when there are problems, otherwise the run timeline, which hangs
  from the capsule.
- **Studio toolbar**: Builder · Help · [Save | **Test**] · More (New, Import,
  Export, Copy, Auto-arrange, Validate, Run saved workflow, Appearance).

## Components

| Class | What it is |
|---|---|
| `.btn` `.btn-primary` `.btn-ghost` `.btn-danger` `.btn-sm` `.btn-lg` `.btn-icon` | Capsule push buttons |
| `.btn-toolbar` `.toolbar-group` `.liquid` | Liquid Glass toolbar capsules |
| `.input` `.select` `.textarea` `.search-field` `.field-label` | Fields; pop-ups draw the macOS chevrons |
| `.segmented` (`.is-wide`, `.is-dense`) | Segmented control; used for every tab strip |
| `.switch` | 38×20 switch, capsule knob |
| `.chip` `.chip-ok/-warn/-bad` | Tinted badges, never outlined |
| `.panel` `.well` `.rows` `.figures` | Grouped box, recessed well, row group, figure strip |
| `.mtable` `.table-box` `.inspector` `.split-layout` | macOS table + sticky inspector |
| `.glass-pane` `.glass-strong` `.menu` `.sheet` | Floating pane, popover glass, menu, sheet |
| `.node-card` (`.is-compact`, `.is-pill`) `.tile` | Canvas node and its kind tile |
| `.msg-user` `.msg-bot` `.trace` `.composer` | Test chat |
| `.page` `.display` `.lead` `.reading` | Scrolling pages, large title, lead, long-read text |

### Canvas nodes — n8n's shapes, drawn the Apple way

Every node is a flat surface (`--node-bg`) with a 1px hairline (`--node-line`),
its icon in the component's kind colour. Selected is a 2px ink ring, an error a
red ring, running a yellow ring; hover only darkens the hairline. A status glyph
appears in a small corner badge, and only when something needs saying.

- **Agent** — a 248px card: a 40px kind tile, a 14.5px semibold title, the model
  underneath, optional meta chips, and a foot that labels its three attachment
  ports: Tools, Memory, Knowledge. The ports are diamonds (filled when something
  is attached) so they read as a different connection from the round flow
  handles.
- **Tool, memory, knowledge** — a 60px round sub-node with the name and kind
  underneath; the diamond on top attaches it to an agent.
- **Trigger** — a 64px tile rounded on the side the flow starts from, title
  underneath; its run button appears on hover.
- **Router, answer** — 64px rounded squares with the title underneath.

## Landing page

A sticky frosted nav; one headline in SF Pro Display (clamp 40–78px, −0.045em);
the backend status as a capsule; one solid call to action; the install command
to copy; the real Studio (`public/studio-preview-{light,dark}.jpg`) in a window
on the one wallpaper the product shows outside the sidebar; three chapters
illustrated with real interface fragments; a hairline spec sheet; a closing call
to action.

Regenerate the preview images after a visible Studio change:

```sh
VITE_DEMO_MODE=true npx vite --port 5199 &   # the demo build's stub backend
npm run preview:images
```

## Departures from the Weft reference

- **A kind palette on the canvas.** Weft coloured four pipeline lanes; Delaxis
  colours eight component kinds (`--k-*`), drawn from the same no-blue,
  no-orange, no-brown family and used only on kind tiles.
- **Handles are visible at rest.** Weft hid handles until hover. Delaxis workflows
  are built by connecting typed handles (agents take tools, memory and knowledge
  on separate ports), so they stay visible: quiet rings for flow, diamonds for
  attachments.
- **n8n node shapes.** Weft drew every stage as the same card. Delaxis borrows
  n8n's vocabulary — cards for agents, round sub-nodes for what an agent uses,
  a D-shaped trigger, labels under the small shapes — because people who build
  agent workflows already read it, and draws it flat and in graphite.
- **Less lift.** The glass is flatter than Weft's: a fainter sheen and specular
  rim, 1–3px shadows, and no scale-on-hover on toolbar capsules.
- **The palette opens by default on an empty canvas** and closes when a workflow
  is opened; building from nothing needs it, reading a graph does not.
- **Chat-page themes are exempt.** The presets a deployed chatbot page can use
  (`midnight`, `ocean`, … — mirrored in `src/demo/mockApi.ts`) are product data the
  user chooses for their own page, not Studio chrome, and keep their own colours.

## Checking a change

```sh
npm run build && npm test && npm run lint
python3 ~/.claude/skills/macos27-glass-ui/scripts/check_palette.py src   # only demo chat themes may appear
DELAXIS_URL=http://localhost:5199 npm run audit:theme                     # contrast, both themes
```

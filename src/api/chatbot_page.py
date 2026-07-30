"""Shared chatbot page generation: theme presets, markdown support, config injection.

Single source of truth used by both the flash-deployment pipeline
(``src.api.routers.deployments``) and the AI frontend builder
(``src.api.routers.builder``). All colors are expressed as CSS variables so a
deployment's ``theme`` selects a preset instead of being silently ignored.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any

DEFAULT_THEME = "midnight"

# Each theme is a map of CSS variable name -> value, emitted as a :root block.
# Variable vocabulary mirrors workflow-editor/demo-assets/deployed-chat.html.
THEMES: dict[str, dict[str, str]] = {
    "midnight": {
        "bg": "#101820",
        "surface": "#121d29",
        "panel": "#0f1720",
        "border": "#263241",
        "text": "#e6edf3",
        "muted": "#9fb0c2",
        "accent": "#2f6fed",
        "accent-text": "#ffffff",
        "assistant-bubble": "#1b2a3a",
        "assistant-border": "#314257",
        "input-bg": "#111c28",
        "input-border": "#34465c",
        "code-bg": "#0b1220",
        "code-text": "#f8fafc",
        "link": "#93c5fd",
        "ok": "#74d99f",
        "shadow": "rgba(0,0,0,.28)",
    },
    "daylight": {
        "bg": "#f6f7fb",
        "surface": "#ffffff",
        "panel": "#eef1f7",
        "border": "#d8deea",
        "text": "#172033",
        "muted": "#5b6b83",
        "accent": "#2563eb",
        "accent-text": "#ffffff",
        "assistant-bubble": "#eef3ff",
        "assistant-border": "#dbe4f8",
        "input-bg": "#ffffff",
        "input-border": "#cbd5e1",
        "code-bg": "#111827",
        "code-text": "#f8fafc",
        "link": "#2563eb",
        "ok": "#16a34a",
        "shadow": "rgba(15,23,42,.12)",
    },
    "ocean": {
        "bg": "#04121b",
        "surface": "#072433",
        "panel": "#051a26",
        "border": "#12405a",
        "text": "#d8f0fa",
        "muted": "#86b3c7",
        "accent": "#06b6d4",
        "accent-text": "#04222d",
        "assistant-bubble": "#0a3346",
        "assistant-border": "#155a77",
        "input-bg": "#06202e",
        "input-border": "#17506c",
        "code-bg": "#021018",
        "code-text": "#e0f2fe",
        "link": "#67e8f9",
        "ok": "#5eead4",
        "shadow": "rgba(0,0,0,.35)",
    },
    "forest": {
        "bg": "#0c130d",
        "surface": "#131f15",
        "panel": "#0f1810",
        "border": "#28402b",
        "text": "#e7f0e7",
        "muted": "#9bb59d",
        "accent": "#22c55e",
        "accent-text": "#052e13",
        "assistant-bubble": "#1a2b1c",
        "assistant-border": "#2f4a33",
        "input-bg": "#122014",
        "input-border": "#33523a",
        "code-bg": "#081109",
        "code-text": "#ecfdf5",
        "link": "#86efac",
        "ok": "#4ade80",
        "shadow": "rgba(0,0,0,.32)",
    },
    "sunset": {
        "bg": "#1a1023",
        "surface": "#241531",
        "panel": "#1e1229",
        "border": "#3f2a52",
        "text": "#f4e8f7",
        "muted": "#bda3c9",
        "accent": "#f97316",
        "accent-text": "#331303",
        "assistant-bubble": "#2e1c3d",
        "assistant-border": "#4c3361",
        "input-bg": "#251733",
        "input-border": "#503a66",
        "code-bg": "#140b1c",
        "code-text": "#fdf4ff",
        "link": "#fdba74",
        "ok": "#86efac",
        "shadow": "rgba(0,0,0,.35)",
    },
    "mono": {
        "bg": "#ffffff",
        "surface": "#ffffff",
        "panel": "#f4f4f5",
        "border": "#d4d4d8",
        "text": "#111111",
        "muted": "#52525b",
        "accent": "#111111",
        "accent-text": "#ffffff",
        "assistant-bubble": "#f4f4f5",
        "assistant-border": "#d4d4d8",
        "input-bg": "#ffffff",
        "input-border": "#a1a1aa",
        "code-bg": "#18181b",
        "code-text": "#fafafa",
        "link": "#111111",
        "ok": "#16a34a",
        "shadow": "rgba(0,0,0,.10)",
    },
}

THEME_LABELS: dict[str, str] = {
    "midnight": "Midnight",
    "daylight": "Daylight",
    "ocean": "Ocean",
    "forest": "Forest",
    "sunset": "Sunset",
    "mono": "Mono",
}

# var() fallbacks keep this usable when injected into pages without a theme block.
MARKDOWN_STYLE = """
        .md-content p { margin: 0 0 8px; }
        .md-content p:last-child { margin-bottom: 0; }
        .md-content ul, .md-content ol { margin: 8px 0; padding-left: 20px; }
        .md-content li { margin: 3px 0; }
        .md-content code { background: rgba(148,163,184,.18); border-radius: 4px; padding: 2px 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: .92em; }
        .md-content pre { background: var(--code-bg, #0b1220); color: var(--code-text, #f8fafc); border-radius: 8px; padding: 12px; overflow: auto; white-space: pre; }
        .md-content pre code { background: transparent; padding: 0; color: inherit; }
        .md-content blockquote { margin: 8px 0; border-left: 3px solid var(--muted, #64748b); padding-left: 10px; color: var(--muted, #64748b); }
        .md-content a { color: var(--link, #2563eb); text-decoration: underline; }
        .md-content table { border-collapse: collapse; width: 100%; margin: 8px 0; }
        .md-content th, .md-content td { border: 1px solid rgba(148,163,184,.45); padding: 6px 8px; text-align: left; }
"""

MARKDOWN_SCRIPT = r"""
        function escapeHtml(value) {
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function inlineMarkdown(value) {
            let html = escapeHtml(value);
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
            return html;
        }
        function renderMarkdown(markdown) {
            const lines = String(markdown || '').split(/\r?\n/);
            const blocks = [];
            let list = null;
            let code = [];
            let inCode = false;
            function closeList() {
                if (!list) return;
                blocks.push('<' + list.type + '>' + list.items.map(item => '<li>' + inlineMarkdown(item) + '</li>').join('') + '</' + list.type + '>');
                list = null;
            }
            function closeCode() {
                if (!inCode) return;
                blocks.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
                code = [];
                inCode = false;
            }
            for (const line of lines) {
                if (line.trim().startsWith('```')) {
                    if (inCode) closeCode(); else { closeList(); inCode = true; code = []; }
                    continue;
                }
                if (inCode) { code.push(line); continue; }
                if (!line.trim()) { closeList(); continue; }
                const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
                const unordered = line.match(/^\s*[-*]\s+(.+)$/);
                if (ordered || unordered) {
                    const type = ordered ? 'ol' : 'ul';
                    if (!list || list.type !== type) { closeList(); list = { type, items: [] }; }
                    list.items.push((ordered || unordered)[1]);
                    continue;
                }
                closeList();
                if (line.startsWith('### ')) blocks.push('<h3>' + inlineMarkdown(line.slice(4)) + '</h3>');
                else if (line.startsWith('## ')) blocks.push('<h2>' + inlineMarkdown(line.slice(3)) + '</h2>');
                else if (line.startsWith('# ')) blocks.push('<h1>' + inlineMarkdown(line.slice(2)) + '</h1>');
                else if (line.startsWith('> ')) blocks.push('<blockquote>' + inlineMarkdown(line.slice(2)) + '</blockquote>');
                else blocks.push('<p>' + inlineMarkdown(line) + '</p>');
            }
            closeCode();
            closeList();
            return blocks.join('');
        }
"""

CONFIG_SNIPPET = "<script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script>"

_HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
_SCRIPT_OPEN_RE = re.compile(r"<script\b", re.IGNORECASE)


def normalize_theme(theme: str | None) -> str:
    """Map any theme value onto a known preset id."""
    if theme and theme.strip().lower() in THEMES:
        return theme.strip().lower()
    return DEFAULT_THEME


def theme_css(theme: str) -> str:
    """Emit the ``:root { --bg: ...; }`` block for a theme preset."""
    variables = THEMES[normalize_theme(theme)]
    lines = "\n".join(f"      --{name}: {value};" for name, value in variables.items())
    return f":root {{\n{lines}\n    }}"


def all_theme_css(theme: str) -> str:
    """The deployment's theme as ``:root``, plus every preset as an override block.

    Emitting all of them is what lets a visitor switch theme from the page's
    settings without a round trip — the picker only has to set
    ``data-delaxis-theme`` on <html>.
    """
    blocks = [theme_css(theme)]
    for theme_id, variables in THEMES.items():
        lines = "\n".join(f"      --{name}: {value};" for name, value in variables.items())
        blocks.append(f'[data-delaxis-theme="{theme_id}"] {{\n{lines}\n    }}')
    return "\n    ".join(blocks)


# Everything a generated design is allowed to change. Anything outside this set
# is ignored, so a design spec can restyle the page but never break its wiring.
BRAND_COLOR_KEYS = frozenset(THEMES[DEFAULT_THEME])
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|hsla?\([\d\s.,%/]+\)|[a-z]+)$")
_FONT_RE = re.compile(r"^[\w\s,\"'\-]{1,180}$")


def sanitize_brand(brand: dict[str, Any] | None) -> dict[str, str]:
    """Keep only the presentation values that are safe to inline as CSS.

    A generated design arrives as model output, so every value is treated as
    untrusted: anything that is not a plain colour, a font stack, or a small
    length is dropped rather than written into a stylesheet.
    """
    if not brand:
        return {}
    clean: dict[str, str] = {}
    for key, value in brand.items():
        text = str(value).strip()
        if not text or ";" in text or "}" in text or "<" in text:
            continue
        if key in BRAND_COLOR_KEYS and _COLOR_RE.match(text):
            clean[key] = text
        elif key == "font" and _FONT_RE.match(text):
            clean[key] = text
        elif key == "radius" and re.match(r"^\d{1,2}(px|rem)$", text):
            clean[key] = text
    return clean


def _parse_color(value: str) -> tuple[float, float, float] | None:
    """(r, g, b) in 0-255 for a hex or rgb() colour, or None if not parseable."""
    text = value.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits[:3])
        if len(digits) in (6, 8):
            try:
                return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            except ValueError:
                return None
        return None
    match = re.match(r"rgba?\(([^)]+)\)", text)
    if match:
        parts = [p.strip() for p in re.split(r"[,\s/]+", match.group(1)) if p.strip()]
        if len(parts) >= 3:
            try:
                return tuple(float(p.rstrip("%")) * (2.55 if p.endswith("%") else 1) for p in parts[:3])  # type: ignore[return-value]
            except ValueError:
                return None
    return None


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast between two colours; 0.0 when either cannot be parsed."""
    fg, bg = _parse_color(foreground), _parse_color(background)
    if fg is None or bg is None:
        return 0.0
    light, dark = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# (foreground var, background var, minimum ratio). Body copy needs 4.5:1;
# secondary text and large UI elements are held to 3:1, per WCAG AA.
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("text", "bg", 4.5),
    ("text", "surface", 4.5),
    ("text", "panel", 4.5),
    ("text", "assistant-bubble", 4.5),
    ("muted", "bg", 3.0),
    ("muted", "panel", 3.0),
    ("muted", "surface", 3.0),
    ("accent-text", "accent", 4.5),
    ("link", "assistant-bubble", 3.0),
)


def _shift(color: str, amount: float) -> str:
    """Nudge a colour toward white (positive) or black (negative)."""
    rgb = _parse_color(color)
    if rgb is None:
        return color
    target = 255.0 if amount > 0 else 0.0
    weight = abs(amount)
    return "#" + "".join(f"{int(round(c + (target - c) * weight)):02x}" for c in rgb)


# Surfaces that sit on the page background. When a design restyles `bg` without
# naming these, they are derived from it — leaving them at the theme's value is
# what produces a cream page with dark panels bolted onto it.
_BACKGROUND_FAMILY: tuple[tuple[str, float], ...] = (
    ("surface", 0.04),
    ("panel", 0.07),
    ("assistant-bubble", 0.05),
    ("input-bg", 0.02),
)


def _readable_on(background: str, minimum: float, preferred: str) -> str:
    """A foreground colour that clears ``minimum`` against ``background``.

    The preferred value wins when it already passes; otherwise this falls back
    to near-black or near-white, whichever has more contrast. Something legible
    is always returned, so a palette is never left unreadable.
    """
    if contrast_ratio(preferred, background) >= minimum:
        return preferred
    dark, light = "#111111", "#ffffff"
    return dark if contrast_ratio(dark, background) >= contrast_ratio(light, background) else light


def harmonize_brand(theme: str, brand: dict[str, Any] | None) -> tuple[dict[str, str], list[str]]:
    """Make a generated palette readable, keeping as much of it as possible.

    A generated palette regularly looks right in the abstract and fails in
    practice — pale grey on cream, or button text that vanishes on its own
    accent. Rather than trusting the model to check, each pair is measured here.

    Backgrounds are always kept, because they carry the design's intent; only
    the text colour on top is corrected, first to the theme's own value and then
    to black or white if that is still not enough. Returns the adjusted brand
    plus a note for every colour that had to change.
    """
    clean = sanitize_brand(brand)
    if not clean:
        return {}, []

    base = THEMES[normalize_theme(theme)]
    notes: list[str] = []

    def effective(name: str) -> str:
        return clean.get(name, base.get(name, "#000000"))

    # A design that changes the page background but not the panels on it would
    # otherwise inherit the theme's — a cream page with midnight panels. Derive
    # the unstated ones so the palette stays coherent.
    page_background = clean.get("bg")
    if page_background:
        going_lighter = _relative_luminance(_parse_color(page_background) or (0, 0, 0)) > 0.5
        for name, amount in _BACKGROUND_FAMILY:
            if name not in clean:
                clean[name] = _shift(page_background, -amount if going_lighter else amount)

    for foreground, background, minimum in CONTRAST_PAIRS:
        background_value = effective(background)
        if contrast_ratio(effective(foreground), background_value) >= minimum:
            continue
        replacement = _readable_on(background_value, minimum, base.get(foreground, "#111111"))
        if replacement == effective(foreground):
            continue
        clean[foreground] = replacement
        notes.append(f"{foreground} was unreadable on {background}, corrected to {replacement}")

    return clean, notes


def brand_css(brand: dict[str, Any] | None) -> str:
    """A ``:root`` override block for a generated design, or nothing."""
    clean = sanitize_brand(brand)
    if not clean:
        return ""
    lines = []
    for key, value in clean.items():
        name = "brand-font" if key == "font" else "brand-radius" if key == "radius" else key
        lines.append(f"      --{name}: {value};")
    # Placed after the theme blocks so it wins, but still under the visitor's
    # own theme choice if they pick one from the settings drawer.
    return ":root {\n" + "\n".join(lines) + "\n    }"


def theme_presets() -> list[dict[str, Any]]:
    """Theme list for the studio's deploy UI."""
    return [
        {"id": theme_id, "label": THEME_LABELS.get(theme_id, theme_id.title()), "vars": variables}
        for theme_id, variables in THEMES.items()
    ]


def safe_json(obj: Any) -> str:
    """JSON that is safe to embed inside a <script> block ('</' cannot close the tag)."""
    return json.dumps(obj).replace("</", "<\\/")


def ensure_config_contract(html: str) -> str:
    """Guarantee the page carries the __CHATBOT_CONFIG__ placeholder before any app script.

    The assignment must execute before the code that reads ``window.CHATBOT_CONFIG``,
    so it is inserted at the top of <head> (never appended at the end of <body>).
    """
    if "__CHATBOT_CONFIG__" in html:
        return html
    match = _HEAD_OPEN_RE.search(html)
    if match:
        return f"{html[:match.end()]}\n  {CONFIG_SNIPPET}{html[match.end():]}"
    match = _SCRIPT_OPEN_RE.search(html)
    if match:
        return f"{html[:match.start()]}{CONFIG_SNIPPET}\n{html[match.start():]}"
    return f"{CONFIG_SNIPPET}\n{html}"


def inject_runtime_config(html: str, config: dict[str, Any]) -> str:
    """Substitute the runtime config into the page, adding the contract if missing."""
    html = ensure_config_contract(html)
    return html.replace("__CHATBOT_CONFIG__", safe_json(config))


def ensure_markdown_support(html: str) -> str:
    """Add the markdown renderer (style + script) to pages that lack one.

    The script lands in <head> so ``renderMarkdown`` is defined before any body
    script runs. Every replacement is count=1 and has a fallback anchor, so the
    helpers never silently no-op on pages missing </style> or </body>.
    """
    if "function renderMarkdown" in html:
        return html
    if "</style>" in html:
        html = html.replace("</style>", f"{MARKDOWN_STYLE}\n  </style>", 1)
    elif "</head>" in html:
        html = html.replace("</head>", f"<style>{MARKDOWN_STYLE}</style>\n</head>", 1)
    else:
        html = f"<style>{MARKDOWN_STYLE}</style>\n{html}"

    script = f"<script>\n{MARKDOWN_SCRIPT}\n</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{script}\n</head>", 1)
    else:
        match = _SCRIPT_OPEN_RE.search(html)
        if match:
            html = f"{html[:match.start()]}{script}\n{html[match.start():]}"
        else:
            html = f"{html}\n{script}"
    return html


def page_defects(html: str) -> list[str]:
    """Structural problems that make a page not work as a chatbot.

    Checked separately from the cosmetic warnings because a generated page that
    hits any of these is not deployable — its buttons do nothing, or its chat
    never reaches the API. Catching them here is what stops a broken page from
    being published.
    """
    defects: list[str] = []
    lowered = html.lower()

    if "window.chatbot_config" not in lowered:
        defects.append("Never reads window.CHATBOT_CONFIG, so it does not know which workflow to talk to.")
    if "/api/v1/sessions" not in html:
        defects.append("Never calls /api/v1/sessions, so no conversation is ever created.")
    elif "/messages" not in html:
        defects.append("Creates a session but never posts to /messages, so nothing is ever sent.")

    # Something has to turn a user action into a request. Without any of these
    # the page renders and the buttons are inert.
    if not any(token in html for token in ("addEventListener", "onsubmit", "onclick", "onSubmit", "onClick")):
        defects.append("No event handlers, so nothing happens when the user presses send.")
    if "fetch(" not in html and "XMLHttpRequest" not in html:
        defects.append("Never makes an HTTP request.")

    # Somewhere to type and something to submit.
    if "<textarea" not in lowered and "<input" not in lowered:
        defects.append("No text input, so there is no way to send a message.")

    # Deployed pages are served from this app with no network egress guarantees;
    # a CDN reference is a blank screen for anyone behind a firewall.
    for pattern in ("src=\"http", "src='http", "href=\"http"):
        index = lowered.find(pattern.lower())
        while index != -1:
            snippet = html[index : index + 160]
            if any(host in snippet for host in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com", "cdnjs")):
                defects.append("Loads an external CDN asset, which will not resolve in an offline deployment.")
                break
            index = lowered.find(pattern.lower(), index + 1)

    if html.lstrip().startswith("```") or html.rstrip().endswith("```"):
        defects.append("Still wrapped in markdown code fences.")

    # De-duplicate while keeping order, so the CDN scan cannot report twice.
    seen: set[str] = set()
    return [d for d in defects if not (d in seen or seen.add(d))]


def validate_page(html: str) -> list[str]:
    """Warnings for a page about to be deployed (powers the deploy preview)."""
    warnings: list[str] = []
    lowered = html.lower()
    if "<!doctype" not in lowered:
        warnings.append("Missing <!doctype html> declaration.")
    if "<head" not in lowered:
        warnings.append("Missing <head> section.")
    if "<body" not in lowered:
        warnings.append("Missing <body> section.")
    if "function rendermarkdown" not in lowered:
        warnings.append("Markdown renderer missing — assistant replies will render as plain text.")
    warnings.extend(page_defects(html))
    return warnings


EMBED_TEMPLATE = r"""/* Delaxis embed widget for the "__DEPLOYMENT_ID__" deployment.
 *
 * Usage on any page:
 *   <script src="https://your-delaxis-host/d/__DEPLOYMENT_ID__/embed.js" defer></script>
 *
 * Options are read from the script tag's data- attributes:
 *   data-position="right|left"   which corner the launcher sits in
 *   data-label="Chat with us"    launcher tooltip and aria-label
 *   data-open="true"             open the panel on load
 *   data-width / data-height     panel size in px
 */
(function () {
  var script = document.currentScript
    || document.querySelector('script[src*="/d/__DEPLOYMENT_ID__/embed.js"]');
  var data = (script && script.dataset) || {};
  var origin = '__ORIGIN__';
  if (!origin && script) {
    try { origin = new URL(script.src).origin; } catch (e) { origin = ''; }
  }
  var src = origin + '/d/__DEPLOYMENT_ID__/';
  var side = data.position === 'left' ? 'left' : 'right';
  var label = data.label || '__TITLE__';
  var width = parseInt(data.width, 10) || 400;
  var height = parseInt(data.height, 10) || 620;
  var accent = data.accent || '__ACCENT__';

  // A single id keeps a double-included script from stacking two launchers.
  if (document.getElementById('delaxis-embed-__DEPLOYMENT_ID__')) return;

  var root = document.createElement('div');
  root.id = 'delaxis-embed-__DEPLOYMENT_ID__';

  var style = document.createElement('style');
  style.textContent = [
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-launcher{position:fixed;bottom:20px;' + side + ':20px;z-index:2147483000;',
    'width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;color:#fff;background:' + accent + ';',
    'box-shadow:0 10px 30px rgba(0,0,0,.28);display:grid;place-items:center;transition:transform .15s}',
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-launcher:hover{transform:scale(1.06)}',
    '#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-panel{position:fixed;bottom:88px;' + side + ':20px;z-index:2147483000;',
    'width:' + width + 'px;height:' + height + 'px;max-width:calc(100vw - 32px);max-height:calc(100vh - 120px);',
    'border:0;border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 24px 70px rgba(0,0,0,.35);display:none}',
    '#delaxis-embed-__DEPLOYMENT_ID__.delaxis-open .delaxis-panel{display:block}',
    '@media (max-width:520px){#delaxis-embed-__DEPLOYMENT_ID__ .delaxis-panel{',
    'inset:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0}}',
  ].join('');

  var frame = document.createElement('iframe');
  frame.className = 'delaxis-panel';
  frame.title = label;
  frame.setAttribute('loading', 'lazy');
  // The page needs storage for its conversation list, and forms for the composer.
  frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups');

  var button = document.createElement('button');
  button.className = 'delaxis-launcher';
  button.type = 'button';
  button.setAttribute('aria-label', label);
  button.title = label;
  button.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l2-4.9A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/></svg>';

  function toggle(open) {
    var isOpen = open === undefined ? !root.classList.contains('delaxis-open') : open;
    root.classList.toggle('delaxis-open', isOpen);
    button.setAttribute('aria-expanded', String(isOpen));
    // Loading on first open keeps the host page's initial render untouched.
    if (isOpen && !frame.src) frame.src = src;
  }

  button.addEventListener('click', function () { toggle(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') toggle(false);
  });

  root.appendChild(style);
  root.appendChild(frame);
  root.appendChild(button);
  document.body.appendChild(root);

  if (data.open === 'true') toggle(true);

  // Minimal programmatic control for host pages that want their own button.
  window.DelaxisChat = window.DelaxisChat || {};
  window.DelaxisChat['__DEPLOYMENT_ID__'] = {
    open: function () { toggle(true); },
    close: function () { toggle(false); },
    toggle: function () { toggle(); },
  };
  // Pre-rename alias: host pages already shipping window.OakChat keep working.
  window.OakChat = window.DelaxisChat;
})();
"""


def embed_script(*, deployment_id: str, title: str, theme: str, origin: str = "") -> str:
    """The one-line embed widget: a floating launcher that opens the chat in an iframe."""
    accent = THEMES[normalize_theme(theme)]["accent"]
    return (
        EMBED_TEMPLATE
        .replace("__DEPLOYMENT_ID__", deployment_id)
        .replace("__TITLE__", title.replace("\\", "\\\\").replace("'", "\\'"))
        .replace("__ACCENT__", accent)
        .replace("__ORIGIN__", origin.rstrip("/"))
    )


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script>
  <style>
    __THEME_CSS__
    __BRAND_CSS__
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0; background: var(--bg); color: var(--text);
      font-family: var(--brand-font, Inter), ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    button { font: inherit; cursor: pointer; }
    .app { display: grid; grid-template-columns: 264px 1fr; height: 100dvh; }

    /* ---- Sidebar: the visitor's own conversations ---- */
    .side {
      display: flex; flex-direction: column; min-height: 0;
      background: var(--panel); border-right: 1px solid var(--border);
    }
    .side-head { padding: 16px 14px 12px; border-bottom: 1px solid var(--border); }
    .brand { font-size: 15px; font-weight: 700; line-height: 1.3; margin: 0 0 10px; }
    .new-chat {
      width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px;
      padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--brand-radius, 8px);
      background: var(--surface); color: var(--text); font-size: 13px; font-weight: 600;
      transition: border-color .15s, background .15s;
    }
    .new-chat:hover { border-color: var(--accent); }
    .chats { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
    .chats-empty { padding: 12px 8px; font-size: 12px; color: var(--muted); line-height: 1.5; }
    .chat-item {
      display: flex; align-items: center; gap: 8px; width: 100%;
      padding: 8px 10px; border: 0; border-radius: 8px; background: transparent;
      color: var(--muted); font-size: 13px; text-align: left;
    }
    .chat-item:hover { background: var(--surface); color: var(--text); }
    .chat-item[aria-current="true"] { background: var(--surface); color: var(--text); font-weight: 600; }
    .chat-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .chat-del {
      border: 0; background: transparent; color: var(--muted); padding: 2px 4px;
      border-radius: 4px; opacity: 0; font-size: 15px; line-height: 1;
    }
    .chat-item:hover .chat-del, .chat-del:focus { opacity: 1; }
    .chat-del:hover { color: #ef4444; }
    .side-foot { padding: 10px 12px; border-top: 1px solid var(--border); }
    .side-foot button {
      width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 10px;
      border: 0; border-radius: 8px; background: transparent; color: var(--muted); font-size: 13px;
    }
    .side-foot button:hover { background: var(--surface); color: var(--text); }

    /* ---- Main chat column ---- */
    .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
    .top {
      display: flex; align-items: center; gap: 12px; padding: 12px 20px;
      border-bottom: 1px solid var(--border); background: var(--surface);
    }
    .burger { display: none; border: 0; background: transparent; color: var(--text); font-size: 18px; padding: 4px 6px; }
    .top h1 { font-size: 15px; font-weight: 700; margin: 0; }
    .status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
    .dot.err { background: #ef4444; }
    .spacer { flex: 1; }
    .icon-btn {
      border: 1px solid var(--border); background: transparent; color: var(--muted);
      border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 600;
    }
    .icon-btn:hover { color: var(--text); border-color: var(--accent); }

    .messages { flex: 1; overflow-y: auto; padding: 24px 20px; }
    .thread { max-width: 780px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
    .row { display: flex; gap: 12px; align-items: flex-start; }
    .row.user { flex-direction: row-reverse; }
    .avatar {
      flex: 0 0 28px; width: 28px; height: 28px; border-radius: 8px;
      display: grid; place-items: center; font-size: 11px; font-weight: 700;
      background: var(--assistant-bubble); border: 1px solid var(--assistant-border); color: var(--text);
    }
    .row.user .avatar { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
    .bubble-wrap { min-width: 0; max-width: 88%; }
    .bubble {
      padding: 11px 14px; border-radius: var(--brand-radius, 12px); font-size: 14px; line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .row.assistant .bubble { background: var(--assistant-bubble); border: 1px solid var(--assistant-border); }
    .row.user .bubble { background: var(--accent); color: var(--accent-text); white-space: pre-wrap; }
    .row.error .bubble { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.45); }
    .meta {
      display: flex; gap: 10px; align-items: center; margin-top: 5px;
      font-size: 11px; color: var(--muted); opacity: 0; transition: opacity .15s;
    }
    .row:hover .meta, .meta:focus-within { opacity: 1; }
    .row.user .meta { justify-content: flex-end; }
    .meta button { border: 0; background: transparent; color: inherit; padding: 0; font-size: 11px; text-decoration: underline; }
    .typing { display: inline-flex; gap: 4px; padding: 4px 0; }
    .typing i {
      width: 6px; height: 6px; border-radius: 50%; background: var(--muted);
      animation: blink 1.2s infinite ease-in-out;
    }
    .typing i:nth-child(2) { animation-delay: .18s; }
    .typing i:nth-child(3) { animation-delay: .36s; }
    @keyframes blink { 0%, 60%, 100% { opacity: .25 } 30% { opacity: 1 } }

    .suggestions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
    .suggestions button {
      border: 1px solid var(--border); background: var(--surface); color: var(--muted);
      border-radius: 999px; padding: 7px 13px; font-size: 12.5px;
    }
    .suggestions button:hover { color: var(--text); border-color: var(--accent); }

    .composer { border-top: 1px solid var(--border); background: var(--surface); padding: 14px 20px 18px; }
    .composer form { max-width: 780px; margin: 0 auto; display: flex; gap: 10px; align-items: flex-end; }
    .composer textarea {
      flex: 1; resize: none; min-height: 44px; max-height: 180px; padding: 12px 14px;
      background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text);
      border-radius: 10px; font: inherit; font-size: 14px; line-height: 1.45;
    }
    .composer textarea:focus { outline: none; border-color: var(--accent); }
    .send {
      border: 0; background: var(--accent); color: var(--accent-text);
      border-radius: var(--brand-radius, 10px); padding: 0 18px; height: 44px; font-weight: 700;
    }
    .send:disabled { opacity: .5; cursor: not-allowed; }
    .hint { max-width: 780px; margin: 8px auto 0; font-size: 11px; color: var(--muted); }

    /* ---- Settings drawer ---- */
    .scrim { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 40; }
    .drawer {
      position: fixed; top: 0; right: 0; bottom: 0; width: min(360px, 100%); z-index: 50;
      background: var(--panel); border-left: 1px solid var(--border);
      display: flex; flex-direction: column; box-shadow: -18px 0 50px var(--shadow);
    }
    /* A class selector beats the user-agent [hidden] rule, so display:none has
       to be restated or the drawer would render open on load. */
    .drawer[hidden], .scrim[hidden] { display: none; }
    .drawer header {
      display: flex; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--border);
    }
    .drawer header h2 { margin: 0; font-size: 14px; font-weight: 700; }
    .drawer .body { padding: 18px; overflow-y: auto; display: flex; flex-direction: column; gap: 20px; }
    .field { display: flex; flex-direction: column; gap: 6px; }
    .field label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
    .field select {
      background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text);
      border-radius: 8px; padding: 9px 10px; font: inherit; font-size: 13px;
    }
    .check { display: flex; align-items: center; gap: 9px; font-size: 13px; }
    .facts { font-size: 12px; color: var(--muted); line-height: 1.9; }
    .facts code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text); }
    .danger {
      border: 1px solid rgba(239,68,68,.5); background: transparent; color: #ef4444;
      border-radius: 8px; padding: 9px 12px; font-size: 13px; font-weight: 600;
    }
    .danger:hover { background: rgba(239,68,68,.1); }

    __MARKDOWN_STYLE__

    @media (max-width: 860px) {
      .app { grid-template-columns: 1fr; }
      .side {
        position: fixed; inset: 0 auto 0 0; width: 264px; z-index: 45;
        transform: translateX(-100%); transition: transform .2s ease;
      }
      body.nav-open .side { transform: none; }
      .burger { display: block; }
      .messages { padding: 18px 14px; }
      .composer { padding: 12px 14px 16px; }
    }
    @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  </style>
</head>
<body>
  <div class="app">
    <aside class="side" id="side">
      <div class="side-head">
        <p class="brand">__TITLE__</p>
        <button class="new-chat" id="new-chat" type="button"><span aria-hidden="true">+</span> New chat</button>
      </div>
      <nav class="chats" id="chats" aria-label="Your conversations"></nav>
      <div class="side-foot">
        <button id="open-settings" type="button"><span aria-hidden="true">⚙</span> Settings</button>
      </div>
    </aside>

    <main class="main">
      <div class="top">
        <button class="burger" id="burger" type="button" aria-label="Show conversations">☰</button>
        <h1>__TITLE__</h1>
        <span class="status"><span class="dot" id="status-dot"></span><span id="status-text">Ready</span></span>
        <span class="spacer"></span>
        <button class="icon-btn" id="top-new" type="button">New chat</button>
      </div>

      <div class="messages" id="messages"><div class="thread" id="thread"></div></div>

      <div class="composer">
        <form id="form">
          <textarea id="input" rows="1" placeholder="Ask anything…" autocomplete="off"></textarea>
          <button class="send" id="send" type="submit">Send</button>
        </form>
        <p class="hint" id="hint">Enter to send · Shift + Enter for a new line</p>
      </div>
    </main>
  </div>

  <div class="scrim" id="scrim" hidden></div>
  <aside class="drawer" id="drawer" hidden aria-label="Settings">
    <header>
      <h2>Settings</h2>
      <span class="spacer"></span>
      <button class="icon-btn" id="close-settings" type="button">Close</button>
    </header>
    <div class="body">
      <div class="field">
        <label for="theme-select">Appearance</label>
        <select id="theme-select">__THEME_OPTIONS__</select>
      </div>
      <label class="check"><input type="checkbox" id="enter-sends" checked /> Enter sends the message</label>
      <label class="check"><input type="checkbox" id="keep-history" checked /> Remember my conversations on this device</label>
      <div class="field">
        <label>Connected to</label>
        <p class="facts">
          Workflow <code>__WORKFLOW_ID__</code><br />
          Provider <code>__PROVIDER_ID__</code><br />
          Model <code>__MODEL_ID__</code>
        </p>
      </div>
      <button class="danger" id="clear-all" type="button">Delete all conversations</button>
    </div>
  </aside>

  <script>
    __MARKDOWN_SCRIPT__

    const cfg = window.CHATBOT_CONFIG || {};
    // Empty api_url = same origin: the app serving this page also serves the API.
    const apiBase = cfg.api_url || '';
    const deployment = cfg.name || cfg.workflow_id || 'chatbot';
    const greeting = cfg.greeting || 'Hi, how can I help?';
    const suggestions = Array.isArray(cfg.suggestions) ? cfg.suggestions.slice(0, 4) : [];

    // --- Local persistence -------------------------------------------------
    // Only ids and titles live here; the messages themselves come from the API,
    // which stays the single source of truth across devices and reloads.
    const KEY = (name) => 'delaxis:' + deployment + ':' + name;
    const store = {
      read(name, fallback) {
        try { const raw = localStorage.getItem(KEY(name)); return raw ? JSON.parse(raw) : fallback; }
        catch (_) { return fallback; }
      },
      write(name, value) {
        try { localStorage.setItem(KEY(name), JSON.stringify(value)); } catch (_) { /* private mode */ }
      },
      drop(name) { try { localStorage.removeItem(KEY(name)); } catch (_) { /* ignore */ } },
    };

    const settings = Object.assign(
      { theme: cfg.theme || '', enterSends: true, keepHistory: true },
      store.read('settings', {}),
    );

    function visitorId() {
      let id = store.read('visitor', null);
      if (!id) {
        id = 'visitor-' + (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(16).slice(2));
        store.write('visitor', id);
      }
      return id;
    }

    let chats = settings.keepHistory ? store.read('chats', []) : [];
    let activeId = settings.keepHistory ? store.read('active', null) : null;
    let messages = [];
    let busy = false;

    const el = {
      thread: document.getElementById('thread'),
      messages: document.getElementById('messages'),
      chats: document.getElementById('chats'),
      input: document.getElementById('input'),
      send: document.getElementById('send'),
      form: document.getElementById('form'),
      hint: document.getElementById('hint'),
      statusDot: document.getElementById('status-dot'),
      statusText: document.getElementById('status-text'),
      drawer: document.getElementById('drawer'),
      scrim: document.getElementById('scrim'),
    };

    function persist() {
      if (!settings.keepHistory) return;
      store.write('chats', chats);
      store.write('active', activeId);
    }

    function setStatus(text, isError) {
      el.statusText.textContent = text;
      el.statusDot.classList.toggle('err', Boolean(isError));
    }

    // --- Rendering ---------------------------------------------------------
    function messageRow(message) {
      const row = document.createElement('div');
      row.className = 'row ' + (message.error ? 'error' : message.role);

      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.setAttribute('aria-hidden', 'true');
      avatar.textContent = message.role === 'user' ? 'You' : 'AI';

      const wrap = document.createElement('div');
      wrap.className = 'bubble-wrap';

      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      if (message.role === 'user') {
        bubble.textContent = message.content;
      } else {
        bubble.classList.add('md-content');
        bubble.innerHTML = renderMarkdown(message.content);
      }
      wrap.appendChild(bubble);

      const meta = document.createElement('div');
      meta.className = 'meta';
      if (message.timestamp) {
        const time = document.createElement('span');
        time.textContent = new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        meta.appendChild(time);
      }
      if (message.role !== 'user') {
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.textContent = 'Copy';
        copy.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(message.content);
            copy.textContent = 'Copied';
            setTimeout(() => { copy.textContent = 'Copy'; }, 1400);
          } catch (_) { copy.textContent = 'Press ⌘C'; }
        });
        meta.appendChild(copy);
      }
      if (message.retry) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = 'Retry';
        retry.addEventListener('click', () => send(message.retry));
        meta.appendChild(retry);
      }
      wrap.appendChild(meta);

      row.appendChild(avatar);
      row.appendChild(wrap);
      return row;
    }

    function render() {
      el.thread.replaceChildren();
      const shown = messages.length ? messages : [{ role: 'assistant', content: greeting }];
      shown.forEach((message) => el.thread.appendChild(messageRow(message)));

      if (!messages.length && suggestions.length) {
        const row = document.createElement('div');
        row.className = 'suggestions';
        suggestions.forEach((text) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = text;
          button.addEventListener('click', () => send(text));
          row.appendChild(button);
        });
        el.thread.appendChild(row);
      }

      if (busy) {
        const row = document.createElement('div');
        row.className = 'row assistant';
        row.innerHTML = '<div class="avatar" aria-hidden="true">AI</div>'
          + '<div class="bubble-wrap"><div class="bubble"><span class="typing" role="status" aria-label="Thinking">'
          + '<i></i><i></i><i></i></span></div></div>';
        el.thread.appendChild(row);
      }

      el.messages.scrollTop = el.messages.scrollHeight;
    }

    function renderChats() {
      el.chats.replaceChildren();
      if (!chats.length) {
        const empty = document.createElement('p');
        empty.className = 'chats-empty';
        empty.textContent = settings.keepHistory
          ? 'No conversations yet. Send a message to start one.'
          : 'History is off, so conversations are not kept on this device.';
        el.chats.appendChild(empty);
        return;
      }
      chats.forEach((chat) => {
        const item = document.createElement('button');
        item.className = 'chat-item';
        item.type = 'button';
        item.setAttribute('aria-current', String(chat.id === activeId));

        const title = document.createElement('span');
        title.className = 'chat-title';
        title.textContent = chat.title || 'New conversation';
        item.appendChild(title);

        const del = document.createElement('span');
        del.className = 'chat-del';
        del.setAttribute('role', 'button');
        del.setAttribute('aria-label', 'Delete conversation');
        del.textContent = '×';
        del.addEventListener('click', (event) => { event.stopPropagation(); removeChat(chat.id); });
        item.appendChild(del);

        item.addEventListener('click', () => openChat(chat.id));
        el.chats.appendChild(item);
      });
    }

    // --- API ---------------------------------------------------------------
    async function api(path, options) {
      const response = await fetch(apiBase + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options));
      if (!response.ok) {
        let detail = await response.text();
        try { detail = JSON.parse(detail).detail || detail; } catch (_) { /* plain text */ }
        const error = new Error(detail || ('Request failed with ' + response.status));
        error.status = response.status;
        throw error;
      }
      return response.json();
    }

    async function ensureSession() {
      if (activeId) return activeId;
      const data = await api('/api/v1/sessions', {
        method: 'POST',
        body: JSON.stringify({
          workflow_id: cfg.workflow_id,
          user_id: visitorId(),
          metadata: { deployment: cfg.name },
        }),
      });
      activeId = data.session_id;
      chats = [{ id: activeId, title: 'New conversation', updatedAt: Date.now() }].concat(chats);
      persist();
      renderChats();
      return activeId;
    }

    async function loadHistory(sessionId) {
      // The server owns the transcript; a session it no longer knows about is
      // dropped from the local list rather than left as a dead entry.
      try {
        const data = await api('/api/v1/sessions/' + sessionId + '/history');
        messages = (data.messages || [])
          .filter((message) => message.role === 'user' || message.role === 'assistant')
          .map((message) => ({ role: message.role, content: message.content, timestamp: message.timestamp }));
        return true;
      } catch (error) {
        if (error.status === 404) {
          chats = chats.filter((chat) => chat.id !== sessionId);
          if (activeId === sessionId) activeId = null;
          persist();
          renderChats();
        }
        messages = [];
        return false;
      }
    }

    async function openChat(sessionId) {
      activeId = sessionId;
      persist();
      renderChats();
      setStatus('Loading…');
      await loadHistory(sessionId);
      setStatus('Ready');
      render();
      document.body.classList.remove('nav-open');
    }

    function newChat() {
      activeId = null;
      messages = [];
      persist();
      renderChats();
      render();
      setStatus('Ready');
      el.input.focus();
      document.body.classList.remove('nav-open');
    }

    function removeChat(sessionId) {
      chats = chats.filter((chat) => chat.id !== sessionId);
      // Best effort: the local list is authoritative for this visitor either way.
      fetch(apiBase + '/api/v1/sessions/' + sessionId, { method: 'DELETE' }).catch(() => {});
      if (activeId === sessionId) { activeId = null; messages = []; render(); }
      persist();
      renderChats();
    }

    async function send(text) {
      const content = String(text || '').trim();
      if (!content || busy) return;

      busy = true;
      el.send.disabled = true;
      messages.push({ role: 'user', content, timestamp: Date.now() });
      render();
      setStatus('Thinking…');

      try {
        const sessionId = await ensureSession();
        const data = await api('/api/v1/sessions/' + sessionId + '/messages', {
          method: 'POST',
          body: JSON.stringify({
            message: content,
            max_turns: cfg.max_turns || 10,
            metadata: { provider_id: cfg.provider_id, model_id: cfg.model_id },
          }),
        });
        messages.push({
          role: 'assistant',
          content: data.response || 'No response was produced.',
          timestamp: Date.now(),
        });
        const chat = chats.find((item) => item.id === sessionId);
        if (chat) {
          if (chat.title === 'New conversation') chat.title = content.slice(0, 48);
          chat.updatedAt = Date.now();
          persist();
          renderChats();
        }
        setStatus('Ready');
      } catch (error) {
        messages.push({
          role: 'assistant',
          error: true,
          content: 'Could not get a reply: ' + error.message,
          retry: content,
          timestamp: Date.now(),
        });
        setStatus('Connection problem', true);
      } finally {
        busy = false;
        el.send.disabled = false;
        render();
        el.input.focus();
      }
    }

    // --- Settings ----------------------------------------------------------
    function applySettings() {
      if (settings.theme) document.documentElement.setAttribute('data-delaxis-theme', settings.theme);
      el.hint.textContent = settings.enterSends
        ? 'Enter to send · Shift + Enter for a new line'
        : 'Shift + Enter to send';
      store.write('settings', settings);
    }

    function openSettings(open) {
      el.drawer.hidden = !open;
      el.scrim.hidden = !open;
    }

    const themeSelect = document.getElementById('theme-select');
    themeSelect.value = settings.theme || (cfg.theme || 'midnight');
    themeSelect.addEventListener('change', () => {
      settings.theme = themeSelect.value;
      applySettings();
    });

    const enterSends = document.getElementById('enter-sends');
    enterSends.checked = settings.enterSends;
    enterSends.addEventListener('change', () => {
      settings.enterSends = enterSends.checked;
      applySettings();
    });

    const keepHistory = document.getElementById('keep-history');
    keepHistory.checked = settings.keepHistory;
    keepHistory.addEventListener('change', () => {
      settings.keepHistory = keepHistory.checked;
      if (!settings.keepHistory) { store.drop('chats'); store.drop('active'); }
      applySettings();
      persist();
      renderChats();
    });

    document.getElementById('clear-all').addEventListener('click', () => {
      chats.slice().forEach((chat) => removeChat(chat.id));
      newChat();
    });

    document.getElementById('open-settings').addEventListener('click', () => openSettings(true));
    document.getElementById('close-settings').addEventListener('click', () => openSettings(false));
    el.scrim.addEventListener('click', () => { openSettings(false); document.body.classList.remove('nav-open'); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') openSettings(false); });

    document.getElementById('new-chat').addEventListener('click', newChat);
    document.getElementById('top-new').addEventListener('click', newChat);
    document.getElementById('burger').addEventListener('click', () => {
      document.body.classList.toggle('nav-open');
      el.scrim.hidden = !document.body.classList.contains('nav-open');
    });

    // --- Composer ----------------------------------------------------------
    function autoGrow() {
      el.input.style.height = 'auto';
      el.input.style.height = Math.min(el.input.scrollHeight, 180) + 'px';
    }
    el.input.addEventListener('input', autoGrow);
    el.input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      const shouldSend = settings.enterSends ? !event.shiftKey : event.shiftKey;
      if (!shouldSend) return;
      event.preventDefault();
      el.form.requestSubmit();
    });
    el.form.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = el.input.value;
      el.input.value = '';
      autoGrow();
      send(text);
    });

    // --- Boot --------------------------------------------------------------
    applySettings();
    renderChats();
    render();
    if (activeId) { openChat(activeId); } else { el.input.focus(); }
  </script>
</body>
</html>
"""


def default_chatbot_html(
    *,
    title: str,
    greeting: str,
    workflow_id: str,
    provider_id: str,
    model_id: str,
    theme: str,
    config: dict[str, Any],
    brand: dict[str, Any] | None = None,
) -> str:
    """The default deployable chat page.

    Substitution is done with ``str.replace`` rather than an f-string so the CSS
    and JS below can be written normally instead of with every brace doubled.

    ``brand`` restyles the page (colours, font, corner radius) without touching
    its wiring — that is what a generated design gets to change.
    """
    return (
        PAGE_TEMPLATE
        .replace("__BRAND_CSS__", brand_css(brand))
        .replace("__TITLE__", escape(title))
        .replace("__GREETING__", escape(greeting))
        .replace("__WORKFLOW_ID__", escape(workflow_id))
        .replace("__PROVIDER_ID__", escape(provider_id))
        .replace("__MODEL_ID__", escape(model_id))
        .replace("__THEME_CSS__", all_theme_css(theme))
        .replace("__MARKDOWN_STYLE__", MARKDOWN_STYLE)
        .replace("__MARKDOWN_SCRIPT__", MARKDOWN_SCRIPT)
        .replace("__THEME_OPTIONS__", "".join(
            f'<option value="{theme_id}">{escape(THEME_LABELS.get(theme_id, theme_id.title()))}</option>'
            for theme_id in THEMES
        ))
        # Last: the config JSON must not be scanned for other placeholders.
        .replace("__CHATBOT_CONFIG__", safe_json(config))
    )

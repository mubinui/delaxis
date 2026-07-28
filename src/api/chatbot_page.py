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


def validate_page(html: str) -> list[str]:
    """Sanity warnings for a page about to be deployed (powers deploy preview)."""
    warnings: list[str] = []
    lowered = html.lower()
    if "<!doctype" not in lowered:
        warnings.append("Missing <!doctype html> declaration.")
    if "<head" not in lowered:
        warnings.append("Missing <head> section.")
    if "<body" not in lowered:
        warnings.append("Missing <body> section.")
    if "window.chatbot_config" not in lowered:
        warnings.append("Page never reads window.CHATBOT_CONFIG — the chat cannot reach the workflow API.")
    if "function rendermarkdown" not in lowered:
        warnings.append("Markdown renderer missing — assistant replies will render as plain text.")
    return warnings


def default_chatbot_html(
    *,
    title: str,
    greeting: str,
    workflow_id: str,
    provider_id: str,
    model_id: str,
    theme: str,
    config: dict[str, Any],
) -> str:
    """The default deployable chat page: theme-aware, escaped, config in <head>."""
    safe_title = escape(title)
    safe_greeting = escape(greeting)
    safe_workflow = escape(workflow_id)
    safe_provider = escape(provider_id)
    safe_model = escape(model_id)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <script>window.CHATBOT_CONFIG = {safe_json(config)};</script>
  <style>
    {theme_css(theme)}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    main {{ min-height: 100vh; display: grid; grid-template-columns: minmax(280px, 420px) 1fr; }}
    aside {{ padding: 32px; background: var(--panel); border-right: 1px solid var(--border); display: flex; flex-direction: column; justify-content: space-between; }}
    h1 {{ font-size: 34px; margin: 0 0 14px; line-height: 1; letter-spacing: 0; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .status {{ display: inline-flex; align-items: center; gap: 8px; color: var(--ok); font-size: 13px; margin-top: 24px; }}
    .dot {{ width: 8px; height: 8px; background: var(--ok); border-radius: 50%; }}
    section {{ display: flex; align-items: center; justify-content: center; padding: 28px; }}
    .chat {{ width: min(780px, 100%); height: min(760px, calc(100vh - 56px)); border: 1px solid var(--border); background: var(--surface); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 24px 70px var(--shadow); }}
    .messages {{ flex: 1; padding: 22px; overflow: auto; display: flex; flex-direction: column; gap: 14px; }}
    .msg {{ max-width: 82%; padding: 12px 14px; border-radius: 8px; white-space: pre-wrap; line-height: 1.45; font-size: 14px; }}
    .user {{ align-self: flex-end; background: var(--accent); color: var(--accent-text); }}
    .assistant {{ align-self: flex-start; background: var(--assistant-bubble); border: 1px solid var(--assistant-border); }}
{MARKDOWN_STYLE}
    form {{ display: flex; gap: 10px; padding: 16px; border-top: 1px solid var(--border); background: var(--panel); }}
    input {{ flex: 1; background: var(--input-bg); border: 1px solid var(--input-border); color: var(--text); border-radius: 6px; padding: 12px; font-size: 14px; }}
    button {{ border: 0; background: var(--accent); color: var(--accent-text); border-radius: 6px; padding: 0 18px; font-weight: 700; cursor: pointer; }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    @media (max-width: 820px) {{ main {{ grid-template-columns: 1fr; }} aside {{ display: none; }} section {{ padding: 12px; }} .chat {{ height: calc(100vh - 24px); }} }}
  </style>
</head>
<body>
  <main>
    <aside>
      <div>
        <h1>{safe_title}</h1>
        <p>{safe_greeting}</p>
        <div class="status"><span class="dot"></span> Live on workflow <strong>{safe_workflow}</strong></div>
      </div>
      <p>Provider: {safe_provider}<br/>Model: {safe_model}</p>
    </aside>
    <section>
      <div class="chat">
        <div id="messages" class="messages"></div>
        <form id="form">
          <input id="input" autocomplete="off" placeholder="Ask anything..." />
          <button id="send" type="submit">Send</button>
        </form>
      </div>
    </section>
  </main>
  <script>
    const cfg = window.CHATBOT_CONFIG;
    // Empty api_url = same origin: the app serving this page also serves the API
    const apiBase = cfg.api_url || '';
    const messages = document.getElementById('messages');
    const input = document.getElementById('input');
    const send = document.getElementById('send');
    let sessionId = null;
{MARKDOWN_SCRIPT}
    function add(role, text) {{
      const div = document.createElement('div');
      div.className = 'msg ' + role;
            if (role === 'assistant') {{
                div.classList.add('md-content');
                div.innerHTML = renderMarkdown(text);
            }} else {{
                div.textContent = text;
            }}
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }}
    async function ensureSession() {{
      if (sessionId) return sessionId;
      const res = await fetch(apiBase + '/api/v1/sessions', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ workflow_id: cfg.workflow_id, user_id: 'flash-user', metadata: {{ deployment: cfg.name }} }})
      }});
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      sessionId = data.session_id;
      return sessionId;
    }}
    add('assistant', cfg.greeting);
    document.getElementById('form').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      add('user', text);
      send.disabled = true;
      try {{
        const sid = await ensureSession();
        const res = await fetch(apiBase + '/api/v1/sessions/' + sid + '/messages', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ message: text, max_turns: 10, metadata: {{ provider_id: cfg.provider_id, model_id: cfg.model_id }} }})
        }});
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        add('assistant', data.response || 'No response');
      }} catch (error) {{
        add('assistant', 'Error: ' + error.message);
      }} finally {{
        send.disabled = false;
        input.focus();
      }}
    }});
  </script>
</body>
</html>
"""

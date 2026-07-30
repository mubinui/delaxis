# Integrating a deployed chatbot

Every workflow can be published as a chat page at `/d/<name>/`, served by the same
application that runs the API. This page covers the three ways to put that chatbot in
front of users, what the session model guarantees, and what to configure before going
to production.

- [Pick an integration](#pick-an-integration)
- [1. Floating widget](#1-floating-widget-one-script-tag)
- [2. Inline iframe](#2-inline-iframe)
- [3. Direct API](#3-direct-api)
- [How sessions work](#how-sessions-work)
- [Configuring the page](#configuring-the-page)
- [Auth](#auth)
- [Serving from another domain](#serving-from-another-domain)
- [Going to production](#going-to-production)

---

## Pick an integration

| You want | Use | Effort |
|---|---|---|
| A support bubble in the corner of an existing site | [Floating widget](#1-floating-widget-one-script-tag) | one script tag |
| The chat inside your own page layout | [Inline iframe](#2-inline-iframe) | one iframe |
| Your own UI, or a non-browser client | [Direct API](#3-direct-api) | two endpoints |

The Studio's **Deployments** panel shows these snippets pre-filled for each deployment,
and the same values are available from the API:

```bash
curl http://localhost:8000/api/v1/deployments/<id>/integration
```

---

## 1. Floating widget (one script tag)

```html
<script src="https://delaxis.example.com/d/support-chat/embed.js" defer></script>
```

That injects a launcher button in the bottom-right corner; clicking it opens the chat in
an iframe. The iframe is only loaded on first open, so the host page's initial render is
untouched.

Options go on the script tag:

```html
<script src="https://delaxis.example.com/d/support-chat/embed.js" defer
        data-position="left"
        data-label="Ask us anything"
        data-width="420" data-height="640"
        data-open="false"></script>
```

| Attribute | Default | Meaning |
|---|---|---|
| `data-position` | `right` | Which corner the launcher sits in (`left` or `right`) |
| `data-label` | the deployment title | Tooltip and accessible name |
| `data-width` / `data-height` | `400` / `620` | Panel size in px; it goes full-screen under 520px wide |
| `data-open` | `false` | Open the panel on load |
| `data-accent` | the theme's accent | Launcher colour, if you need to match your brand |

To drive it from your own button:

```html
<button onclick="DelaxisChat['support-chat'].open()">Talk to us</button>
```

`open()`, `close()` and `toggle()` are available on `window.DelaxisChat['<deployment-id>']`.

---

## 2. Inline iframe

```html
<iframe src="https://delaxis.example.com/d/support-chat/"
        title="Support chatbot"
        style="width:100%;height:640px;border:0;border-radius:12px"
        allow="clipboard-write"></iframe>
```

Give it at least ~520px of height; below that the composer and the conversation list
compete for space. `allow="clipboard-write"` is what makes the per-message **Copy**
button work.

---

## 3. Direct API

The chat page is a thin client over two endpoints. Anything that can make HTTP requests
can do the same.

```bash
BASE=https://delaxis.example.com

# 1. Open a session, once per conversation
SESSION=$(curl -s -X POST $BASE/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id": "support_triage", "user_id": "alice"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# 2. Send a message, once per turn
curl -s -X POST $BASE/api/v1/sessions/$SESSION/messages \
  -H 'Content-Type: application/json' \
  -d '{"message": "How do I reset my password?"}'
```

The reply looks like:

```json
{
  "session_id": "…",
  "response": "…the assistant's answer…",
  "turn_count": 1,
  "cost": { "cost_usd": 0.0004, "usage": { "total_tokens": 812 } },
  "metadata": { "runtime": "crewai", "agents_called": ["TriageAgent"], "trace_steps": [] }
}
```

Other endpoints the page uses:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/sessions/{id}/history` | Full transcript — how a reloaded page restores a conversation |
| `DELETE /api/v1/sessions/{id}` | Delete a conversation |
| `POST /api/v1/chat/stream` | Server-sent events, if you want tokens as they arrive |

> **Do not pass model settings from the client.** The page sends `provider_id` and
> `model_id` in its message metadata, but the server ignores them and uses the
> deployment record instead — that JS is editable by anyone who opens a public page.
> Change the model on the deployment, not the caller.

---

## How sessions work

A **session** is one conversation. The server owns the transcript; the browser only
remembers which sessions belong to this visitor.

- `localStorage` holds the session ids, their titles, and a generated visitor id —
  never the messages.
- On load the page re-fetches the active session's transcript from
  `GET /sessions/{id}/history`, so a reload, a second tab, or a restored browser session
  all show the same conversation.
- A session the server no longer knows about (a restart with a cleared store) is dropped
  from the visitor's list instead of lingering as a dead entry.
- **New chat** starts a fresh session; the previous one stays in the list.
- Turning off *Remember my conversations on this device* in the page's settings clears
  the local list and stops writing it. The server-side transcript is unaffected.

Sessions are persisted to `${CREWAI_STORAGE_DIR}/sessions.json` and survive an API
restart. There is no automatic expiry — see [Going to production](#going-to-production).

---

## Configuring the page

Set these when you deploy, from the Studio or `POST /api/v1/deployments/flash`:

| Field | Effect |
|---|---|
| `title` | Browser tab, sidebar heading and widget tooltip |
| `greeting` | The first assistant message on an empty conversation |
| `suggestions` | Up to four starter prompts shown as chips (great for discoverability) |
| `theme` | One of `midnight`, `daylight`, `ocean`, `forest`, `sunset`, `mono` |
| `provider_id` / `model_id` | Which model actually answers — enforced server-side |
| `auth_mode` | `public` or `private` |

Visitors can override the theme, the Enter-to-send behaviour and local history from the
page's own settings drawer; those choices are per-device and never change the deployment.

For a completely custom look, pass your own `frontend_html`. Two contracts apply:

1. Read `window.CHATBOT_CONFIG` for `workflow_id`, `api_url`, `greeting` and the rest.
   The placeholder is injected into `<head>` automatically if you leave it out.
2. Define `renderMarkdown(text)` or one will be injected for you, so replies do not
   render as raw markdown.

`POST /api/v1/deployments/preview` returns the rendered HTML plus warnings for a page
that breaks either contract, before you publish it.

---

## Auth

`auth_mode: "public"` means anyone with the URL can chat, and every request costs you
model tokens. Before exposing a public deployment:

- Tighten the rate limits — `REQUESTS_PER_MINUTE` (default 60) and `REQUESTS_PER_HOUR`
  (default 1000). They are keyed per user, and every anonymous visitor of a public page
  shares the same bucket.
- Pin a cheap model on the deployment.
- Cap `max_turns` so one visitor cannot run an unbounded conversation.

`auth_mode: "private"` expects the session endpoints to be authenticated. With API-key
auth enabled, an embedded page cannot authenticate on its own — proxy the two session
endpoints through your own backend, attach the key there, and point the deployment's
`api_url` at your proxy.

---

## Serving from another domain

`api_url: ""` (the default) means same origin: the app serving the page also serves the
API, and nothing else is needed. The widget and iframe both work cross-origin because
the browser only ever talks to the Delaxis origin from inside the frame.

Set `api_url` only when the API lives somewhere else. Then the browser makes
cross-origin calls, so the API must allow your page's origin — that is `FRONTEND_URL`,
a comma-separated allowlist (`*` by default):

```bash
FRONTEND_URL=https://app.example.com,https://www.example.com
```

`embed.js` itself is served with `Access-Control-Allow-Origin: *` and a five-minute
cache, since it is meant to be loaded by third-party pages.

---

## Going to production

- **Rate limiting** — on, before anything public.
- **Session growth** — `sessions.json` grows without bound; prune it or move to a
  database-backed store if you expect real traffic.
- **Model cost** — the deployment pins the model, so put the cheap one there and keep
  the expensive one for internal workflows.
- **Content Security Policy** — if your site sets one, allow the Delaxis origin in
  `frame-src` (iframe/widget) and `script-src` (widget).
- **The transcript is not private to the visitor.** Anyone who knows a session id can
  read it through `GET /sessions/{id}/history`. Ids are UUID4, but do not treat a public
  deployment as a confidential channel.

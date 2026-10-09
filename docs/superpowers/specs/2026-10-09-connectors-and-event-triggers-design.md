# Connectors and event triggers

**Status:** draft for review · **Date:** 2026-10-09

## What this is for

Delaxis workflows can call the web, databases, files and Gmail. They cannot
touch the systems most teams run their work in: Jira, GitLab, GitHub, Slack,
Confluence. Adding one of those today means writing an `api` tool by hand, URL
and auth header included, or wiring up an MCP server. Neither is "drop it on
the canvas and pick what it may do".

This design adds **connectors**: ready-made integrations that appear in the
palette, connect to an account once, expose a chosen set of actions to agents,
and can start a workflow when something happens in the remote system. Jira and
GitLab ship first. The framework is built so that the next connector is one
Python module and no frontend change.

### Intent, as agreed

- Said: Jira, GitLab, and more ready-made tools, so that complex workflows are
  easy to design.
- Assumed, and to be corrected if wrong: "ready-made" means no URLs, headers
  or env vars to type; "complex" means workflows that read from and write to
  several systems and are started by events in them, not only by chat.
- Success looks like: a user with a GitLab personal access token builds a
  merge-request review workflow in the Studio in under ten minutes, without
  reading the GitLab API docs, and sees its runs in the Runs page.

### The first use

The first workflows built on this will be a support desk: requests arrive by
email and chat, become tickets in Jira, pass through people who decide and
act, and end with a reply to the requester, with periodic reports on the
side. The desk's own steps belong to the operator and are not described
here. What it needs from the platform is: triggers for mail, chat messages,
ticket events and a schedule; actions that create, classify, assign,
comment on and close tickets; and a way to follow one ticket across many
short runs.

A ticket lives for days and waits on people. A run is one message in and one
answer out, and this design keeps it that way rather than holding a run open
for days. **The ticket is the state.** Each event starts a short run that
reads the ticket and does the next step; humans keep the decisions. Three
things make that workable: a trigger for every kind of event, an **entity
key** on every run (the ticket key) so the Runs page shows a ticket's full
history in order, and message templates that put the ticket's current state
in front of the agent.

## Where the frontend stands today

- The palette is a hardcoded list of about twenty tiles in seven groups. The
  **Connect** group has two: MCP server and Gmail.
- Gmail is the only real connector. It has an OAuth flow
  (`/api/v1/integrations/gmail/*`), an `integration_credentials` table with
  Fernet-encrypted tokens, a palette tile, a hand-written inspector form, and a
  runtime factory that turns one node into send/search/read tools. This is the
  pattern to generalise.
- `api` tools wrap any REST endpoint but take their credentials from an
  environment variable, which is a server-admin job, not a Studio user's.
- The inspector (`PropertiesPanel.tsx`) is 1,400 lines with one form per tool
  kind. Every new kind grows it.
- Triggers are `chat`, `webhook` and `manual`. A webhook has a secret and an
  `input_mapping`, but knows nothing about the payload it receives.
- Run history exists (`workflow_runs`), so anything new that runs a workflow
  is recorded and replayable for free.

## Approaches considered

**A. Native connectors (recommended).** Each connector is a Python module:
an httpx client, a table of actions with typed parameters, a table of events
with a normaliser, and a verifier for the connection. A generic runtime factory
turns the chosen actions into CrewAI tools. The Studio renders palette tiles
and inspector forms from a catalogue endpoint.
*For:* works in the Docker image with no extra processes; credentials stay in
our encrypted store; actions are typed, documented and unit-testable with a
mock transport; read and write actions can be separated so a node is read-only
until the user ticks a write. *Against:* each connector is code we maintain.

**B. MCP presets.** Ship palette tiles that preconfigure the MCP node for the
Atlassian and GitLab MCP servers. *For:* little code. *Against:* the servers
run as separate processes (Node or a remote service), need their own auth
flows, their tool lists change under us, and the inspector cannot show what an
action does before the server is reachable. This is still the right answer for
the long tail: an MCP preset tile is cheap to add once the catalogue exists.

**C. Generated `api` tools.** Extend the Swagger importer to pull the Jira and
GitLab OpenAPI specs. *Against:* hundreds of operations, credentials still
from env vars, no events. Rejected.

Choice: **A for Jira and GitLab, with B available as "MCP preset" entries in
the same catalogue later.**

## Design

### 1. Connector catalogue (backend)

A connector is a module under `src/connectors/<id>.py` registering a
`Connector` object:

```python
Connector(
    id="gitlab", name="GitLab", icon="gitlab",
    auth=AuthSpec(kinds=["token"], base_url=True, base_url_default="https://gitlab.com",
                  token_label="Personal access token", token_help="api scope; read_api for read-only"),
    options=[Field("project", "Default project", help="group/name; actions default to it")],
    actions=[Action("list_merge_requests", kind="read", params=[...], run=...), ...],
    events=[Event("merge_request.opened", ...), ...],
    verify=verify_connection,          # GET /api/v4/user -> account label
    sample_payloads={...},             # one per event, for the Test tab
    signature=verify_gitlab_token,     # X-Gitlab-Token == secret
    normalize=normalize_event,         # payload -> NormalizedEvent
)
```

`Action.params` are pydantic fields, so the CrewAI tool gets a real schema and
a docstring from `Action.description`. `Action.kind` is `read` or `write`.

**Catalogue endpoint:** `GET /api/v1/integrations/connectors` returns every
connector's id, name, icon, auth spec, options, actions (id, name, kind,
description, params) and events (id, name, description). The Studio renders
from this; it has no per-connector code.

**Gmail** is registered in the catalogue too, with `auth.kinds=["oauth"]`, so
it gets the same palette tile and form. Saved workflows with `type: "gmail"`
keep working: the factory map keeps the `gmail` alias.

### 2. Connections (accounts)

`integration_credentials` becomes the connections table. Added columns:
`base_url`, `account_label` (what the verifier returned: a GitLab username, a
Jira display name), `auth_kind`, `options` (JSON). `account_email` stays for
Gmail and becomes nullable. One Alembic migration.

Endpoints, replacing the Gmail-specific ones over time:

| Method and path | Purpose |
|---|---|
| `GET /integrations/connections` | every connection, token never returned |
| `POST /integrations/connections` | `{connector, base_url?, username?, token}`; the connector's verifier runs; on success the connection is stored and returned, otherwise 400 with the remote's reason |
| `POST /integrations/connections/{id}/test` | run the verifier again |
| `DELETE /integrations/connections/{id}` | remove; workflows referencing it get a diagnostic |
| `GET /integrations/connections/{id}/oauth-url`, `GET .../oauth/callback` | the existing Gmail flow, generalised by connector id |

Tokens are stored with the existing Fernet `SecretManager`. Auth per
connector, first version:

- **Jira Cloud:** email plus API token, sent as Basic auth. Verifier:
  `GET /rest/api/3/myself`.
- **Jira Data Center / Server:** personal access token, Bearer. Same verifier
  on `/rest/api/2/myself`. The connector picks the API version from the first
  successful probe and stores it in `options`.
- **GitLab (gitlab.com or self-hosted):** personal access token in
  `PRIVATE-TOKEN`. Verifier: `GET /api/v4/user`.

- **Google Calendar:** the Gmail OAuth flow with the calendar scopes added.
  One Google connection serves both connectors; connecting Gmail asks for
  the calendar scopes too.
- **WhatsApp (Meta Cloud API):** a permanent system-user token, the phone
  number id, and the app secret (for verifying inbound webhook signatures).
  Verifier: `GET /{phone_number_id}`. Twilio's WhatsApp API is the
  alternative if that is what the account uses; same connector shape,
  different client.

OAuth 2.0 for Jira Cloud and GitLab is a later step: it needs an app
registration per installation, which is the same burden Gmail has today.

### 3. Runtime: the connector tool factory

A new tool kind, `connector`, with settings:

```json
{"type": "connector", "connector": "jira", "connection_id": "…",
 "actions": ["search_issues", "get_issue", "add_comment"],
 "options": {"project": "OPS"}}
```

`ConnectorToolFactory` (in `runtime_tool_factories.py`, next to Gmail's)
builds one CrewAI tool per listed action: `{node_name}_{action_id}`, with the
action's parameter model and description, calling the connector module with
the connection's decrypted token and the node's options. Its
`sandbox_function` takes `action` plus parameters, for the inspector's Test
tab. A missing or deleted connection fails the run with a message that names
the node and the connection, not a 401 from the remote.

Every action call is logged as a `tool_call_start` / `tool_call_result`
event, so it shows on the canvas, in the timeline and in run history, like
every other tool.

### 4. Actions shipped first

Read actions are on by default when a node is dropped; writes are off until
ticked. The inspector shows them in two groups.

**Jira**

| Action | Kind | Notes |
|---|---|---|
| `search_issues` | read | JQL, with `max_results` capped by the node |
| `get_issue` | read | fields, status, assignee, comments |
| `list_projects` | read | |
| `list_transitions` | read | what `transition_issue` may do |
| `create_issue` | write | project defaults to the node option |
| `update_issue` | write | summary, description, priority, labels, custom fields by id |
| `add_comment` | write | |
| `transition_issue` | write | by transition name or id |
| `assign_issue` | write | by account id or email |

**GitLab**

| Action | Kind | Notes |
|---|---|---|
| `search_projects` | read | |
| `list_merge_requests` | read | state, author, labels filters |
| `get_merge_request` | read | includes description and approval state |
| `get_merge_request_changes` | read | the diff, size-capped |
| `list_issues` | read | |
| `get_file` | read | a file at a ref |
| `list_pipelines` | read | plus the latest job statuses |
| `create_issue` | write | |
| `update_issue` | write | |
| `add_merge_request_note` | write | comment on an MR |
| `add_issue_note` | write | |
| `set_merge_request_labels` | write | |

Approving or merging an MR, and triggering pipelines, are deliberately left
out of the first version; they are the actions whose mistakes cost most.

**Gmail** keeps `send_email`, `search_emails` and `read_email`, and gains
`reply_to_thread` (so a resolution mail lands in the user's original thread)
and `list_new_messages(since)`, which the Email received trigger polls.

**Google Calendar**

| Action | Kind | Notes |
|---|---|---|
| `find_free_slots` | read | attendees, window, duration; uses the free/busy API |
| `list_events` | read | |
| `create_event` | write | attendees, Meet link optional |
| `update_event` | write | |

**WhatsApp**

| Action | Kind | Notes |
|---|---|---|
| `send_message` | write | free-form text, allowed within 24 hours of the user's last message |
| `send_template` | write | an approved message template, for messages outside that window |
| `get_media` | read | download an attachment from an inbound message |

The 24-hour rule and template approval are Meta's, not ours; the connector
reports the remote's reason when a send is refused.

### 5. Event triggers

A new trigger type, `event`, beside `chat`, `webhook` and `manual`:

```json
{"type": "event", "connector": "gitlab", "connection_id": "…",
 "events": ["merge_request.opened", "merge_request.updated"],
 "filters": {"project": "group/name"}, "secret": "…",
 "input_mapping": {"message": "Review this merge request:\n{{summary}}\n\n{{description}}"}}
```

Delivery: the remote posts to the existing `POST /api/v1/webhooks/{slug}`.
For an `event` trigger the handler calls the connector's `signature` check
(GitLab: `X-Gitlab-Token`; Jira: the secret as a query parameter, since Jira
Cloud webhooks do not sign), then `normalize`, which returns a
`NormalizedEvent` with `event`, `summary`, `description`, `url`, `actor`,
`entity` (`{kind, id, project}`) and `raw`. Events not in the trigger's list,
or not matching its filters, are acknowledged with 202 and ignored. A
matching event renders `input_mapping.message` (a small `{{field}}` template
over the normalised event) and runs the workflow through the session manager
with metadata `{source: "event:gitlab", event: …, entity: …}`. The run
appears in run history with that source; the Runs page filter gets the new
sources.

Each event trigger has its own secret and slug, as webhooks do now. The
inspector shows the URL and secret to paste into GitLab or Jira. For GitLab,
a **Register webhook** button creates the project hook through the API with
the connection's token (`POST /projects/:id/hooks`); Jira Cloud webhook
registration needs admin rights, so it stays manual with step-by-step text.

Events shipped first: GitLab `push`, `merge_request.{opened,updated,merged,
closed}`, `issue.{opened,closed,reopened}`, `pipeline.{success,failed}`,
`note.created`; Jira `issue.created`, `issue.updated`, `issue.transitioned`,
`comment.created`; WhatsApp `message.received`.

**Polled events.** Gmail has no webhook without Google Pub/Sub, so a
connector may declare a polled event: `poll(connection, cursor)` returns new
events and the next cursor. A poller in the API process runs every event
trigger that uses one at its interval (default two minutes, configurable per
trigger), stores the cursor on the trigger, and delivers each event exactly
as a webhook would. First polled event: Gmail `message.received`, with
filters for label, sender and subject. The poller runs in one process only;
on Kubernetes that is the single replica the deployment already uses.

**Scheduled triggers.** A `schedule` trigger has a cron expression and a
timezone, and runs the workflow with a fixed message (the template rendered
with the date). The same poller drives it. Missed schedules while the server
was down are skipped, not replayed, and logged.

**The entity key.** `NormalizedEvent.entity` (`{kind, key, url}`: a Jira
issue key, a GitLab MR, an email thread, a WhatsApp conversation) is stored
on the run as `entity_key`. An agent action that creates an entity sets it
too (`create_issue` returns the key, and the factory records it). The Runs
page gains an **Entity** filter and shows one ticket's runs in order; the
run response and the `done` frame carry `entity_key`.

### 6. Studio

**Palette.** The **Connect** group is built from the catalogue: one tile per
connector, plus MCP server. Tiles the catalogue adds later appear with no
Studio release. A **Start** tile per connector with events ("GitLab event",
"Jira event", "Email received", "WhatsApp message") appears beside Manual,
Chat and Webhook, plus a **Schedule** tile.

**Inspector.** Two new components, in a new `src/components/inspector/`
folder rather than inside `PropertiesPanel.tsx`:

- `ConnectorForm`: connection picker (existing connections for this
  connector, plus **Connect…**), the connector's options as fields, actions as
  two checklists (Read, Write) with each action's description, and a Test tab
  that runs one action with typed parameters and shows the result.
- `EventTriggerForm`: connection picker, event checklist, filters, the
  webhook URL and secret with copy buttons, **Register webhook** where the
  connector supports it, the message template with a live preview against the
  connector's sample payload, and a Test tab that posts a sample payload
  through the real webhook endpoint and links to the resulting run.

The Gmail form is replaced by `ConnectorForm`; `renderGmailConfig` and
`fetchGmailStatus` go.

**Connections page.** A new place in the sidebar's Library group:
**Connections**. A table of connected accounts (connector, account, base URL,
added, status from the last test) with an inspector offering Test and Remove,
and an **Add connection** sheet: pick a connector, fill the fields the
catalogue declares, and it verifies before saving. The inspector's
**Connect…** opens the same sheet.

**Diagnostics.** New codes: `connection_missing` (node or trigger references
a connection that no longer exists), `connector_no_actions`,
`event_trigger_without_events`. Shown where diagnostics show today.

**Templates.** Three starter workflows that use the connectors, shipped in
`configs/workflows.json` like the existing six, each with `metadata.setup`
naming the connection it needs:

- *Merge request reviewer* — GitLab `merge_request.opened` → an agent reads
  the diff and description → posts a review note.
- *Jira triage* — chat or Jira `issue.created` → triage agent classifies,
  sets labels and priority, assigns, and comments with its reasoning.
- *Incident digest* — GitLab `pipeline.failed` → an agent reads the job logs,
  searches Jira for a matching open issue, and creates or comments on one.

They run end to end against the fake forge below, and against real accounts
once a connection exists. The support-desk workflow itself is not shipped as
a template: it is the user's to build, and the templates exist to show the
building blocks working.

**Demo mode.** The Pages demo mocks `/integrations/connectors` and
`/connections` with the shipped catalogue and two canned connections, so the
tiles and forms work in the static demo.

### 7. Test strategy

- **Connector clients:** unit tests with an `httpx.MockTransport` per action,
  including the error mapping (401 → "token rejected", 404 → "not found",
  429 → retried once with backoff, then reported).
- **Fake forge:** `scripts/fake_forge.py`, a small FastAPI app that imitates
  the GitLab, Jira, WhatsApp and Google Calendar endpoints the actions and
  verifiers use, with a seeded project, issues, merge requests and a calendar.
  Gmail keeps its existing mocked client. The e2e server (`serve.sh`) starts it
  and points the test connections at it; the backend integration tests mount
  it in-process. It is the only way the e2e suite and CI can exercise
  connectors without secrets.
- **API tests:** connections CRUD and verification, catalogue shape, the
  `connector` tool factory building the right tools, event trigger delivery
  (signature accepted and refused, event filtered, run recorded with the
  event source).
- **Studio:** vitest for the template renderer and the catalogue-to-palette
  mapping; Playwright for: add a GitLab connection on the Connections page,
  drop a GitLab node, pick actions, run the Test tab; create an event trigger,
  post a sample payload, see the run in Runs.
- **Live check (manual, optional):** one real GitLab PAT and one Jira Cloud
  token, supplied by you at the time; the three templates run against them.

### 8. Delivery order

Ordered by what a support desk needs first; GitLab rides along in slice 1
because two connectors prove the framework is generic.

1. **Connector framework, Jira, GitLab, Connections page, inspector form,
   palette from the catalogue, Gmail migrated with its new actions.** Useful
   on its own: agents can create, classify, assign and close tickets and
   send mail.
2. **Event triggers**: webhook events (Jira, GitLab), the poller with the
   Email received trigger, the Schedule trigger, the entity key and the Runs
   page filter. After this the whole ticket lifecycle can be built.
3. **WhatsApp and Google Calendar connectors**, with their trigger and
   actions.
4. **Templates, the fake forge in e2e, the demo-mode mocks.**
5. **Next connectors** by the same recipe, one module each: GitHub (same
   shape as GitLab), Slack, Confluence (shares the Jira connection). MCP
   preset tiles for anything else.

### Out of scope for this design

- OAuth for Jira and GitLab (token auth first; OAuth reuses the Gmail flow
  when an installation registers an app).
- Approving or merging merge requests, triggering pipelines, deleting
  anything.
- New canvas semantics: loops, fan-out, per-field data mapping between nodes.
  The runtime is agent-led; an agent that has the right actions decides what
  to call. If a template turns out to need a construct the canvas lacks, that
  is its own design.
- Runs that stay open waiting for a person. The ticket-as-state pattern above
  covers a support desk without it.
- Per-user connections. Connections belong to the installation, as Gmail
  accounts do today; the audit trail records who added one.
- Providing a WhatsApp number. The connector needs a WhatsApp Business
  account with the Cloud API enabled (or a Twilio account); the platform
  cannot stand one up.

### Open questions for you

- Which Jira do you run: Cloud (`*.atlassian.net`) or Data Center? Both are
  designed for; the one you have is the one that gets the live check.
- Is gitlab.com or a self-hosted GitLab the target? Same reason.
- WhatsApp: Meta's Cloud API directly, or through Twilio? The design assumes
  Meta; Twilio is the same connector with a different client.
- Is the support mailbox a Google Workspace account? The
  Email received trigger and Calendar connector assume Gmail; Microsoft 365
  would be a separate connector (Graph API) by the same recipe.
- Should write actions be allowed at all for workflows started by a public
  chat trigger? The default in this design is yes if the node ticks them; a
  per-deployment "read-only" switch is easy to add if you want it.

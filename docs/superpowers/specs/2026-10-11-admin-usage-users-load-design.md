# Admin panel: users, usage, live load and load tests

**Status:** draft for review · **Date:** 2026-10-11

## What this is for

An administrator wants to see who is using Delaxis and what it costs them:
which users and deployed pages are active, how many tokens and how much
money each one spends, what is running right now and how loaded the server
is, and how the system behaves when many requests arrive at once.

### Intent, as agreed

- Said: a token and resource consumption monitor; concurrency testing; a
  user monitor in an admin panel.
- Assumed, and to be corrected if wrong: "user" means every identity that
  causes a run: a signed-in Studio user, an API key, and a visitor of a
  deployed chat page. "Resource" means tokens, cost, run time and the server's
  CPU and memory. "Concurrency testing" means pushing a chosen number of
  simultaneous requests through a workflow and measuring what happens.
- Success looks like: an admin opens the panel and can answer, without
  leaving it, "who spent the most this month, on which workflow and model;
  who is running something now; how long do replies take with 20 people at
  once, and where does it start queueing".

## Where it stands today

- **Users.** A `users` table with roles `admin`, `user` and `readonly`;
  API keys belong to users; `POST /auth/users` is admin-only; there is no
  endpoint that lists users. In development mode a request without
  credentials is treated as a built-in "development" user, which is how the
  Studio works locally without signing in.
- **Attribution is client-supplied.** `POST /sessions` takes `user_id` from
  the request body and the run inherits it. A deployed page sends a visitor
  id it generated itself. Nothing ties a run to the authenticated caller, so
  a per-user report would be whatever callers chose to write.
- **Tokens** are recorded per run (prompt, completion, total) from CrewAI.
- **Cost is a guess.** Every model is priced at one flat rate ($1.50 per
  million input tokens, $6 per million output) whatever model ran. The config
  has a `pricing` field per model; none of the 47 shipped models fills it.
  The run does not record which model ran.
- **Dashboard counters** for tokens and cost exist (Prometheus) but the
  runtime never increments them, so they read zero.
- **Concurrency** is limited per workflow (`DELAXIS_MAX_CONCURRENT_RUNS`,
  default 10) and the API can report active and waiting runs. There is no
  way to generate load or to see the server's CPU or memory.

## Design

### 1. Every run has a principal, decided by the server

A **principal** is who caused a run: `{kind, id, label}` with `kind` one of
`user`, `api_key`, `visitor`, `development`, `system`.

| Request | Principal |
|---|---|
| JWT for a user in the `users` table | `user:<user id>`, label = username |
| API key | `api_key:<key id>`, label = key name, owner = the key's user |
| Deployed page (public trigger) | `visitor:<deployment id>:<visitor id>`, label = `Visitor <first 6 chars>`; the visitor id the page sends is kept but typed as a visitor and scoped to its deployment, so it can never collide with a user |
| Development mode, no credentials | `development:local`, label = "development" |
| Event, schedule, test case, replay, load test | `system:<source>`, e.g. `system:replay` |

The principal is set in the session when it is created, from the
authenticated request, and copied to every run of that session. The
`user_id` the client sends stays as a free-text label (the chat widget's
display name, the API caller's own reference) and no longer counts as
identity. `workflow_runs` gains `principal_kind`, `principal_id`,
`principal_label`, `deployment_id`, `provider`, `model`. The Runs page shows
the principal and gets a **User** filter.

This closes the hole that let any caller write any user id: reports are
about who authenticated, not who they said they were.

### 2. Real cost, or none

- The run records the provider and model that actually ran (after any
  per-agent or deployment override). When agents use different models, the
  run records the entry agent's and lists the rest in `usage.models`.
- A **price table** gives `(input, output)` per million tokens per model.
  Sources, in order: the model's `pricing` in `api_providers.json` (the field
  exists); for OpenRouter, the prices its `/models` endpoint publishes,
  fetched once a day and cached in `data/model_prices.json`; nothing else.
- `cost_usd` = prompt × input price + completion × output price, computed at
  the end of the run. **Unknown price → `cost_usd` is null**, and the run is
  counted as "unpriced" wherever totals are shown. The flat guess is removed
  everywhere, including the trace step that reports it.
- The runtime feeds the existing Prometheus counters
  (`llm_tokens_total`, `llm_cost_total`, `workflow_executions_active`,
  `workflow_executions_queued`), so `/metrics` and the Health page say
  something true.
- The provider editor in the Studio shows and edits each model's prices.

### 3. Admin API

All under `/api/v1/admin`, admin-only (`require_admin`; the development
principal counts as admin in development mode, as it does today).

| Endpoint | Returns |
|---|---|
| `GET /users?window=30d` | one row per principal seen in the window, plus every registered user even if idle: kind, label, role and status (for users), API key count, last seen, sessions active now, runs, failures, tokens, cost and unpriced runs for today and for the window |
| `GET /users/{principal}` | the row plus a daily series (runs, tokens, cost) for the window and the ten most recent runs |
| `POST /users/{user id}/deactivate`, `/reactivate` | flips `users.active`; the auth check must refuse an inactive user's tokens and API keys from the next request (the plan verifies this and adds it if missing) |
| `GET /usage?from&to&group_by=day|user|workflow|model|deployment&exclude_load_tests=true` | aggregates over `workflow_runs`: runs, failures, prompt/completion/total tokens, cost, unpriced runs, mean and p95 duration |
| `GET /usage/top-runs?from&to&limit=20` | the most expensive runs, linking into run history |
| `GET /live` | runs active and waiting per workflow (from the session manager), principals running now, sessions open, process CPU % and resident memory (`psutil`, a new dependency), uptime, rate-limit rejections in the last minute, the concurrency limit |

Aggregation runs in SQL on `workflow_runs` and works on SQLite and
PostgreSQL. With the default history limit of 5,000 runs this is a single
indexed query; a daily rollup table is not needed yet and is named as the
first thing to add if it becomes slow.

### 4. Load tests

`POST /admin/load-tests`:

```json
{"workflow_id": "support_triage", "concurrency": 20, "total_requests": 100,
 "mode": "dry_run", "dry_run_latency_ms": 800, "dry_run_failure_rate": 0.0,
 "message": "What is the weather in Berlin?", "test_case_ids": [],
 "confirm_live": false}
```

- The test runs as a background job inside the API process. It sends
  requests through the session manager, so it exercises the real
  per-workflow concurrency limit, queueing, session persistence and run
  recording. It does **not** go through HTTP, so the per-client rate limiter
  is not part of it; the page says so. For HTTP-level load from outside,
  `scripts/load_test.py` fires real requests at a URL and prints the same
  report.
- **Dry run** swaps in a stand-in runtime for the job's own requests only
  (a configurable latency and failure rate, no model), so it measures the
  platform's overhead, queueing and limits at no cost. Live traffic during
  the test is unaffected except for sharing the concurrency limit.
- **Live** calls the real model. It requires `confirm_live: true`, is
  capped at `DELAXIS_LOAD_TEST_MAX_REQUESTS` (default 500), and the response
  to a preview call (`POST /admin/load-tests/preview`) gives the estimated
  cost: the workflow's average cost over its last 20 priced runs times
  `total_requests`. Its runs are recorded with source `load_test` so the
  Usage page can exclude them.
- Each request is timed in three parts: queue wait (time blocked on the
  concurrency limit), run time, total. The result holds a summary (requests,
  ok, failed, throughput per second, latency p50/p95/max, queue wait
  p50/p95, tokens, cost) and up to 2,000 per-request samples.
- `GET /admin/load-tests/{id}/stream` sends progress as SSE (completed count,
  running latency percentiles) while it runs; `POST /admin/load-tests/{id}/stop`
  cancels; `GET /admin/load-tests?workflow_id=` lists past tests, so the page
  can show the previous one beside the current.
- Stored in a `load_tests` table: id, workflow, mode, parameters, status,
  started/finished, summary JSON, samples JSON, principal who started it.

### 5. Studio: the Admin place

A new **Admin** place in the sidebar's System group, shown only to admins
(the role comes from `GET /auth/users/me`). Four tabs:

- **Users.** A table: principal, kind, role and status, last seen, active
  now, runs, tokens, cost for today and the window, with a window picker
  (today, 7 days, 30 days). Visitors are grouped under their deployed page
  and can be expanded. The inspector shows the daily series as a small
  chart, the last ten runs (linking to Runs), the user's API keys, and
  Deactivate or Reactivate for registered users.
- **Usage.** Tiles: tokens, cost, runs, failures, unpriced runs for the
  window. Charts: tokens and cost per day; cost by workflow; cost by model.
  The most expensive runs. A notice when runs are unpriced, linking to the
  provider editor. A switch to exclude load tests. Charts follow the
  project's dataviz guidance: one system, legible in light and dark.
- **Live.** Active and waiting runs per workflow against the limit, who is
  running now, open sessions, CPU and memory, refreshed every five seconds
  while the tab is open.
- **Load tests.** The form (workflow, message or test cases, concurrency,
  total, mode, dry-run latency and failure rate), the live preview of cost
  for live mode with a confirmation step, a live chart of latency and
  completed requests while it runs, the summary, and a comparison with the
  previous test of the same workflow.

The Health page's figures (tokens, cost) become real because the counters
are fed; nothing else there changes.

### 6. Test strategy

- **Principal derivation:** unit tests for every row of the table in §1,
  including a client that sends someone else's user id and gets its own
  principal anyway, and a visitor id that matches a username and stays a
  visitor.
- **Pricing:** unit tests for the price table precedence, the OpenRouter
  fetch (mocked) and cache, the cost formula, and null cost for an unknown
  model. A regression test that no run is ever priced by the old flat rate.
- **Aggregation:** tests over a seeded `workflow_runs` table for each
  `group_by`, the time window, `exclude_load_tests`, and p95.
- **Admin gating:** every admin endpoint returns 403 for the `user` role and
  200 for `admin`; the deactivated user's token is refused.
- **Load tests:** the job with the dry-run runtime at fixed latency gives
  deterministic p50/p95; concurrency above the limit shows queue wait;
  stop cancels; the cap and `confirm_live` are enforced; SSE progress frames
  arrive in order.
- **Studio:** vitest for the number formatting, the window picker maths and
  the chart data shaping; Playwright for: the Admin place is visible to the
  admin and absent for a `user`; the Users table lists the test admin with
  the run the test just made; a 5-at-once, 10-request dry-run load test
  completes and shows p95 and a stored result.
- **Docker smoke:** `GET /api/v1/admin/live` returns 200 with CPU and memory.

### 7. Delivery order

1. **Principals, model on the run, real pricing, counters fed.** Backend
   only; makes every later number true.
2. **Admin API and the Users, Usage and Live tabs.**
3. **Load tests**: job, API, SSE, the tab, and the CLI.

### Out of scope

- Enforced quotas or budgets (a per-user monthly cap that refuses runs) and
  alerting. The data this design produces is what a quota would need; the
  enforcement is its own small design once there is something to cap.
- Invoices, currencies other than USD, or prices for providers that do not
  publish them (those models stay unpriced until someone fills `pricing`).
- Per-user rate limits (limits stay per client address).
- Organisations or tenants; one installation is one tenant.
- HTTP-level load generation from inside the server (the CLI does it from
  outside).

### Open questions for you

- Should deployed-page visitors appear in the Users tab by default, or only
  under their page? The design shows them grouped under the page, collapsed.
- May a **live** load test run when `ENVIRONMENT=production`? The design
  allows it for admins with the cap and the confirmation; say so if it
  should be dry-run only there.
- Which window should the Users tab open on: today, 7 days or 30 days? The
  design opens on 30 days.

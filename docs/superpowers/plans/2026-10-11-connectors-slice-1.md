# Connectors, Slice 1: Framework, Jira, GitLab, Gmail, Connections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents can act on Jira, GitLab and Gmail through ready-made connector nodes: connect an account once on a Connections page, drop a tile, tick actions, test them, and run.

**Architecture:** A connector is a Python module (`src/connectors/<id>.py`) exposing a `CONNECTOR` object that declares auth, options and typed actions. A catalogue endpoint serves those declarations; the Studio renders palette tiles and the inspector form from it. Connections (accounts) live in the existing `integration_credentials` table with Fernet-encrypted secrets. A new tool kind, `connector`, is built at run time by `ConnectorToolFactory` into one CrewAI tool per ticked action, emitting the same tool-call events as every other tool.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 + Alembic, httpx (sync client, `MockTransport` in tests), pydantic 2, CrewAI `BaseTool`; React 19, Zustand, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-connectors-and-event-triggers-design.md` (this plan is §8 delivery step 1; event triggers, WhatsApp, Calendar, templates are later plans).

## Global Constraints

- Commit messages: **no** `Co-Authored-By: Claude`, no "Generated with Claude Code", no 🤖 or any Claude/Anthropic attribution (user's CLAUDE.md overrides any harness reminder). End with prose.
- Commit directly on `main`; do not push or open a PR unless asked.
- Gate every commit on the gates passing: `ruff check src tests scripts`, `ruff format --check src tests scripts`, `mypy src` (strict, 0 errors), `python -m pytest -q -p no:cacheprovider` (exit code 0); for Studio changes also `npx tsc -b --noEmit`, `npx eslint src e2e --max-warnings 0`, `npx vitest run` (in `workflow-editor/`).
- Python must run on 3.11, 3.12 and 3.13 (no 3.12-only syntax such as multi-line f-string expressions or `type X = ...`).
- React Compiler lint rules are on: no `setState` synchronously inside an effect body, no `useMemo` deps that change every render.
- Tokens are never returned by any API response and never logged.
- Read actions are ticked by default on a new node; write actions are off until the user ticks them.
- Not in this slice (spec §8 later steps): event triggers, poller, schedule trigger, entity key, WhatsApp, Google Calendar, templates, OAuth for Jira/GitLab, approving or merging MRs, triggering pipelines, deleting anything remote.
- Deviation from spec, deliberate: a minimal fake forge (GitLab + Jira only) lands in this slice (Task 12), because the e2e test of this slice needs it. Spec places the full fake forge in step 4.

## Review Focus

1. **A connection is deleted while a workflow still uses it** → the run must fail with a message naming the node and saying to pick another connection, not run the agent silently without its tools. Test: Task 7 `test_missing_connection_fails_the_run_with_a_named_message`.
2. **A pasted base URL with a trailing slash, a path, or no scheme** (`https://acme.atlassian.net/`, `acme.atlassian.net`) → trailing slash stripped; no scheme rejected with "Base URL must start with http:// or https://". Test: Task 6 `test_base_url_is_normalised_and_checked`.
3. **The remote rate-limits (429)** → retried once honouring `Retry-After` (capped at 5 s), then a readable error. Test: Task 1 `test_429_is_retried_once_then_reported`.
4. **An agent passes wrong or missing arguments to an action** → the tool returns `{"error": "..."}` naming the field, so the agent can correct itself; the run does not crash. Test: Task 7 `test_bad_arguments_come_back_to_the_agent_as_an_error`.
5. **Jira transition requested by a name that does not exist** (`"Done"` when the workflow calls it `"Closed"`) → error lists the available transitions. Test: Task 3 `test_transition_by_unknown_name_lists_the_choices`.

---

## File Structure

**Backend — new**
- `src/connectors/__init__.py` — package marker, re-exports `ConnectorError`.
- `src/connectors/base.py` — declarations (`Param`, `Action`, `AuthSpec`, `OptionField`, `Connector`, `ConnectionSecrets`, `ConnectorContext`, `VerifyResult`, `ConnectorError`) and helpers `args_model`, `validate_args`, `catalogue_entry`.
- `src/connectors/http.py` — one `request()` for every connector: auth headers, timeouts, 429 retry, error mapping.
- `src/connectors/registry.py` — `get_connector`, `all_connectors`, `connector_ids`.
- `src/connectors/gitlab.py`, `src/connectors/jira.py`, `src/connectors/gmail.py` — one `CONNECTOR` each.
- `src/connectors/store.py` — `ConnectionStore`: connections CRUD over `integration_credentials`.
- `src/connectors/tool_factory.py` — `ConnectorToolFactory`, `ConnectorActionTool`.
- `src/api/routers/connections.py` — catalogue, connections, test, run-action endpoints.
- `alembic/versions/c4f1a8e2b6d0_connections.py` — new columns on `integration_credentials`.
- `scripts/fake_forge.py` — fake GitLab/Jira for e2e.
- Tests: `tests/unit/connectors/test_base.py`, `test_http.py`, `test_gitlab.py`, `test_jira.py`, `test_gmail.py`, `test_store.py`, `test_tool_factory.py`; `tests/integration/test_connections_api.py`.

**Backend — modified**
- `src/infrastructure/database/schema.py` — `IntegrationCredential` columns.
- `src/tools/gmail_tool.py` — `reply_to_thread`, `list_new_messages`.
- `src/tools/runtime_tool_factories.py` — register `connector` factory type.
- `src/config/tool_models.py` — `connector` tool type + validation.
- `src/crewai_runtime/runtime.py` — pass emitter to factories that accept it; let `ConnectorError` fail the run.
- `src/api/router_registry.py` — include the router.

**Studio — new**
- `workflow-editor/src/api/connectors.ts` — types and API calls.
- `workflow-editor/src/stores/connectorStore.ts` — catalogue + connections state.
- `workflow-editor/src/utils/connectorPalette.ts` (+ `.test.ts`) — catalogue → palette tiles, icons, default node config, legacy Gmail upgrade.
- `workflow-editor/src/components/connections/AddConnectionSheet.tsx` — add-a-connection sheet.
- `workflow-editor/src/components/ConnectionsPage.tsx` — the Connections place.
- `workflow-editor/src/components/inspector/ConnectorForm.tsx` — node inspector form with Test.
- `workflow-editor/e2e/connectors.spec.ts`.

**Studio — modified**
- `src/components/Sidebar.tsx` (palette), `src/components/PropertiesPanel.tsx` (form, remove Gmail form), `src/stores/uiStore.ts` + `src/App.tsx` + `src/components/shell/AppSidebar.tsx` (new place), `src/utils/graphDiagnostics.ts` (+ test) and its two callers, `src/demo/mockApi.ts` (empty catalogue), `playwright.config.ts` (second web server), `README.md`.

---

### Task 1: Connector core — declarations, argument models, HTTP client

**Files:**
- Create: `src/connectors/__init__.py`, `src/connectors/base.py`, `src/connectors/http.py`
- Test: `tests/unit/connectors/__init__.py` (empty), `tests/unit/connectors/test_base.py`, `tests/unit/connectors/test_http.py`

**Interfaces:**
- Produces (used by every later backend task):
  - `ConnectorError(message: str, status: int | None = None)` with `.status`
  - `Param(name, type, description, required=True, default=None, enum=None)`
  - `Action(id, name, kind: "read"|"write", description, params: tuple[Param, ...], run: Callable[[ConnectorContext, dict[str, Any]], Any])`
  - `AuthSpec(kind: "token"|"oauth", base_url=False, base_url_default=None, base_url_label="Base URL", username_label=None, username_required=False, token_label="Token", token_help="", oauth_start=None)`
  - `OptionField(key, label, help="")`
  - `VerifyResult(account_label: str, options: dict[str, Any] = {})`
  - `ConnectionSecrets(base_url: str | None, username: str | None, token: str, account_label: str | None = None, options: dict = {})`
  - `ConnectorContext(secrets, options: dict, transport: httpx.BaseTransport | None = None)` with `.option(key, default=None)`
  - `Connector(id, name, icon, description, auth, actions, options=(), verify=None)` with `.action(action_id) -> Action` (raises `KeyError`)
  - `args_model(connector_id: str, action: Action) -> type[BaseModel]`
  - `validate_args(connector_id: str, action: Action, args: dict) -> dict` (raises `ConnectorError`)
  - `catalogue_entry(connector: Connector) -> dict`
  - `request(ctx, method, url, *, service, headers=None, auth=None, params=None, json_body=None, raw=False, timeout=30.0) -> Any`

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_base.py`:
```python
"""Connector declarations: argument models, validation, and the catalogue shape."""

from __future__ import annotations

from typing import Any

import pytest

from src.connectors.base import (
    Action,
    AuthSpec,
    ConnectionSecrets,
    Connector,
    ConnectorContext,
    ConnectorError,
    OptionField,
    Param,
    args_model,
    catalogue_entry,
    validate_args,
)


def _noop(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return args


SEARCH = Action(
    id="search",
    name="Search",
    kind="read",
    description="Search things.",
    params=(
        Param("query", "string", "What to look for"),
        Param("max_results", "integer", "How many", required=False, default=10),
        Param("labels", "array", "Labels", required=False),
        Param("state", "string", "State", required=False, enum=("open", "closed")),
    ),
    run=_noop,
)
CONNECTOR = Connector(
    id="demo",
    name="Demo",
    icon="plug",
    description="A demo connector",
    auth=AuthSpec(kind="token", base_url=True, base_url_default="https://demo.test"),
    actions=(SEARCH,),
    options=(OptionField("project", "Default project", "Used when an action names none"),),
)


def test_args_model_has_the_declared_fields_and_types() -> None:
    model = args_model("demo", SEARCH)
    schema = model.model_json_schema()
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["description"] == "What to look for"
    assert model(query="x").model_dump()["max_results"] == 10


def test_validate_args_coerces_and_drops_unset_optionals() -> None:
    assert validate_args("demo", SEARCH, {"query": "bug", "max_results": "5"}) == {
        "query": "bug",
        "max_results": 5,
    }


def test_validate_args_names_the_bad_field() -> None:
    with pytest.raises(ConnectorError, match="query"):
        validate_args("demo", SEARCH, {"max_results": 5})
    with pytest.raises(ConnectorError, match="state"):
        validate_args("demo", SEARCH, {"query": "x", "state": "merged"})


def test_catalogue_entry_describes_everything_the_studio_renders() -> None:
    entry = catalogue_entry(CONNECTOR)
    assert entry["id"] == "demo"
    assert entry["auth"]["kind"] == "token"
    assert entry["auth"]["base_url_default"] == "https://demo.test"
    assert entry["options"] == [
        {"key": "project", "label": "Default project", "help": "Used when an action names none"}
    ]
    action = entry["actions"][0]
    assert action["id"] == "search" and action["kind"] == "read"
    assert action["params"][0] == {
        "name": "query",
        "type": "string",
        "description": "What to look for",
        "required": True,
        "default": None,
        "enum": None,
    }
    assert action["params"][3]["enum"] == ["open", "closed"]


def test_unknown_action_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        CONNECTOR.action("nope")


def test_context_option_prefers_the_node_then_the_connection() -> None:
    secrets = ConnectionSecrets(base_url=None, username=None, token="t", options={"project": "A"})
    assert ConnectorContext(secrets, {"project": "B"}).option("project") == "B"
    assert ConnectorContext(secrets, {}).option("project") == "A"
    assert ConnectorContext(secrets, {"project": ""}).option("project", "C") == "A"
    empty = ConnectionSecrets(base_url=None, username=None, token="t")
    assert ConnectorContext(empty, {}).option("project", "C") == "C"
```

`tests/unit/connectors/test_http.py`:
```python
"""The shared HTTP call: auth, error mapping, and the single 429 retry."""

from __future__ import annotations

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.http import request


def ctx_for(handler: object) -> ConnectorContext:
    secrets = ConnectionSecrets(base_url="https://x.test", username=None, token="t")
    return ConnectorContext(secrets, {}, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_json_is_returned_and_headers_are_sent() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json={"ok": True})

    result = request(ctx_for(handler), "GET", "https://x.test/a", service="X", headers={"PRIVATE-TOKEN": "t"})
    assert result == {"ok": True}
    assert seen["private-token"] == "t"


def test_raw_returns_text() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="file body")

    assert request(ctx_for(handler), "GET", "https://x.test/f", service="X", raw=True) == "file body"


def test_empty_body_is_an_empty_dict() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    assert request(ctx_for(handler), "PUT", "https://x.test/a", service="X") == {}


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "rejected the token"), (403, "permission"), (404, "not found")],
)
def test_common_failures_read_as_sentences(status: int, words: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    with pytest.raises(ConnectorError, match=words) as info:
        request(ctx_for(handler), "GET", "https://x.test/a", service="GitLab")
    assert info.value.status == status
    assert "GitLab" in str(info.value)


def test_remote_message_is_passed_through_for_other_errors() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": ["Field 'summary' is required"]})

    with pytest.raises(ConnectorError, match="Field 'summary' is required"):
        request(ctx_for(handler), "POST", "https://x.test/a", service="Jira")


def test_429_is_retried_once_then_reported() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"})

    with pytest.raises(ConnectorError, match="rate"):
        request(ctx_for(handler), "GET", "https://x.test/a", service="X")
    assert calls["n"] == 2


def test_429_then_success_returns_the_success() -> None:
    responses = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=[1])]

    def handler(req: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    assert request(ctx_for(handler), "GET", "https://x.test/a", service="X") == [1]


def test_unreachable_host_names_the_address() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ConnectorError, match="Could not reach https://x.test/a"):
        request(ctx_for(handler), "GET", "https://x.test/a", service="X")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.connectors'`

- [ ] **Step 3: Write the implementation**

`src/connectors/__init__.py`:
```python
"""Ready-made integrations: each module here declares one connector."""

from src.connectors.base import ConnectorError

__all__ = ["ConnectorError"]
```

`src/connectors/base.py`:
```python
"""What a connector declares, and what one of its actions receives.

A connector is data: its auth, its options and its actions. The catalogue
endpoint serves these declarations so the Studio can render a connector's
palette tile and inspector form without knowing it; the tool factory turns
the actions a node ticks into agent tools with real argument schemas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, Field, ValidationError, create_model

ParamType = Literal["string", "integer", "boolean", "array", "object"]
ActionKind = Literal["read", "write"]
AuthKind = Literal["token", "oauth"]

_PY_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


class ConnectorError(Exception):
    """A failure to show as is: the remote's reason, or what the user should fix."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Param:
    name: str
    type: ParamType
    description: str
    required: bool = True
    default: Any = None
    enum: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ConnectionSecrets:
    """A connection as an action needs it: where to call and with what."""

    base_url: str | None
    username: str | None
    token: str
    account_label: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorContext:
    """Everything one action call gets: the connection, the node's options, a transport."""

    secrets: ConnectionSecrets
    options: dict[str, Any]
    # Tests pass an httpx.MockTransport; production leaves it None.
    transport: httpx.BaseTransport | None = None

    def option(self, key: str, default: Any = None) -> Any:
        """The node's value, else the connection's, else ``default``. Empty counts as unset."""
        for source in (self.options, self.secrets.options):
            value = source.get(key)
            if value not in (None, ""):
                return value
        return default


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    kind: ActionKind
    description: str
    params: tuple[Param, ...]
    run: Callable[[ConnectorContext, dict[str, Any]], Any]


@dataclass(frozen=True)
class AuthSpec:
    kind: AuthKind
    base_url: bool = False
    base_url_default: str | None = None
    base_url_label: str = "Base URL"
    # Shown as a field when not None (Jira Cloud's account email).
    username_label: str | None = None
    username_required: bool = False
    token_label: str = "Token"
    token_help: str = ""
    # For kind == "oauth": the API path that returns {"auth_url": ...}.
    oauth_start: str | None = None


@dataclass(frozen=True)
class OptionField:
    key: str
    label: str
    help: str = ""


@dataclass(frozen=True)
class VerifyResult:
    account_label: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Connector:
    id: str
    name: str
    icon: str
    description: str
    auth: AuthSpec
    actions: tuple[Action, ...]
    options: tuple[OptionField, ...] = ()
    verify: Callable[[ConnectorContext], VerifyResult] | None = None

    def action(self, action_id: str) -> Action:
        for action in self.actions:
            if action.id == action_id:
                return action
        raise KeyError(f"{self.name} has no action '{action_id}'")


def args_model(connector_id: str, action: Action) -> type[BaseModel]:
    """A pydantic model for an action's parameters: the agent tool's argument schema."""
    fields: dict[str, Any] = {}
    for param in action.params:
        py_type: Any = _PY_TYPES[param.type]
        if param.enum:
            py_type = Literal[param.enum]
        if param.required:
            fields[param.name] = (py_type, Field(description=param.description))
        else:
            fields[param.name] = (
                py_type | None,
                Field(default=param.default, description=param.description),
            )
    model = create_model(f"{connector_id}_{action.id}_args", **fields)
    return cast(type[BaseModel], model)


def validate_args(connector_id: str, action: Action, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce an action's arguments, or say which field is wrong."""
    try:
        parsed = args_model(connector_id, action).model_validate(args)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConnectorError(f"Invalid arguments for {action.id}: {problems}") from exc
    return parsed.model_dump(exclude_none=True)


def catalogue_entry(connector: Connector) -> dict[str, Any]:
    """The connector as the Studio sees it. No callables, no secrets."""
    auth = connector.auth
    return {
        "id": connector.id,
        "name": connector.name,
        "icon": connector.icon,
        "description": connector.description,
        "auth": {
            "kind": auth.kind,
            "base_url": auth.base_url,
            "base_url_default": auth.base_url_default,
            "base_url_label": auth.base_url_label,
            "username_label": auth.username_label,
            "username_required": auth.username_required,
            "token_label": auth.token_label,
            "token_help": auth.token_help,
            "oauth_start": auth.oauth_start,
        },
        "options": [
            {"key": option.key, "label": option.label, "help": option.help}
            for option in connector.options
        ],
        "actions": [
            {
                "id": action.id,
                "name": action.name,
                "kind": action.kind,
                "description": action.description,
                "params": [
                    {
                        "name": param.name,
                        "type": param.type,
                        "description": param.description,
                        "required": param.required,
                        "default": param.default,
                        "enum": list(param.enum) if param.enum else None,
                    }
                    for param in action.params
                ],
            }
            for action in connector.actions
        ],
    }
```

`src/connectors/http.py`:
```python
"""The one HTTP call every connector makes.

Errors become sentences a user can act on ("GitLab rejected the token")
instead of status codes, and a 429 is retried once, honouring Retry-After up
to five seconds, before it is reported.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.connectors.base import ConnectorContext, ConnectorError

_MAX_RETRY_WAIT_SECONDS = 5.0


def _remote_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip()
    if isinstance(body, dict):
        for key in ("errorMessages", "message", "error", "errors", "error_description"):
            value = body.get(key)
            if isinstance(value, list) and value:
                return "; ".join(str(item) for item in value)
            if isinstance(value, dict) and value:
                return "; ".join(f"{k}: {v}" for k, v in value.items())
            if value:
                return str(value)
    return str(body)[:300]


def _raise_for(response: httpx.Response, service: str) -> None:
    status = response.status_code
    remote = _remote_message(response)
    if status == 401:
        raise ConnectorError(
            f"{service} rejected the token (401). Check the connection on the Connections page.",
            status,
        )
    if status == 403:
        raise ConnectorError(
            f"The {service} account lacks permission for this ({remote or '403'}).", status
        )
    if status == 404:
        raise ConnectorError(f"{service}: not found ({remote or response.request.url}).", status)
    if status == 429:
        raise ConnectorError(f"{service} is rate limiting requests; try again shortly.", status)
    raise ConnectorError(f"{service} returned {status}: {remote or 'no detail'}", status)


def request(
    ctx: ConnectorContext,
    method: str,
    url: str,
    *,
    service: str,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    raw: bool = False,
    timeout: float = 30.0,
) -> Any:
    """Call ``url`` and return its JSON (or text when ``raw``), or raise ConnectorError."""
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    with httpx.Client(transport=ctx.transport, timeout=timeout, auth=auth) as client:
        response: httpx.Response | None = None
        for attempt in (1, 2):
            try:
                response = client.request(
                    method,
                    url,
                    headers={"Accept": "application/json", **(headers or {})},
                    params=clean_params,
                    json=json_body,
                )
            except httpx.TransportError as exc:
                raise ConnectorError(f"Could not reach {url}: {exc}") from exc
            if response.status_code == 429 and attempt == 1:
                try:
                    wait = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1.0
                time.sleep(min(max(wait, 0.0), _MAX_RETRY_WAIT_SECONDS))
                continue
            break
    assert response is not None
    if response.status_code >= 400:
        _raise_for(response, service)
    if raw:
        return response.text
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text
```

Create `tests/unit/connectors/__init__.py` as an empty file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/ && mypy src/connectors && ruff check src/connectors tests/unit/connectors`
Expected: all PASS, mypy "Success", ruff "All checks passed!". If mypy rejects `Literal[param.enum]`, keep the runtime behaviour and annotate that line with `# type: ignore[valid-type]` — the enum test proves it works.

- [ ] **Step 5: Commit**

```bash
git add src/connectors tests/unit/connectors
git commit -m "feat(connectors): declarations, typed action arguments, and one HTTP call

A connector declares its auth, options and actions as data; actions get a
pydantic argument model the agent tool schema comes from. The shared request
turns 401/403/404 into sentences and retries one 429."
```

---

### Task 2: GitLab connector

**Files:**
- Create: `src/connectors/gitlab.py`
- Test: `tests/unit/connectors/test_gitlab.py`

**Interfaces:**
- Consumes: Task 1 (`Action`, `Param`, `AuthSpec`, `OptionField`, `Connector`, `ConnectorContext`, `ConnectorError`, `VerifyResult`, `request`).
- Produces: `src.connectors.gitlab.CONNECTOR` with id `gitlab` and actions `search_projects`, `list_merge_requests`, `get_merge_request`, `get_merge_request_changes`, `list_issues`, `get_file`, `list_pipelines` (read), `create_issue`, `update_issue`, `add_merge_request_note`, `add_issue_note`, `set_merge_request_labels` (write). `verify(ctx) -> VerifyResult(account_label=<username>)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_gitlab.py`:
```python
"""GitLab actions against a mocked API: the right calls, the right shapes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.gitlab import CONNECTOR

Handler = Callable[[httpx.Request], httpx.Response]


def ctx(handler: Handler, options: dict[str, Any] | None = None) -> ConnectorContext:
    secrets = ConnectionSecrets(base_url="https://gitlab.test", username=None, token="glpat-x")
    return ConnectorContext(secrets, options or {}, transport=httpx.MockTransport(handler))


def run(action_id: str, handler: Handler, args: dict[str, Any], options: dict[str, Any] | None = None) -> Any:
    return CONNECTOR.action(action_id).run(ctx(handler, options), args)


def test_verify_returns_the_username_and_sends_the_token() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v4/user"
        assert req.headers["PRIVATE-TOKEN"] == "glpat-x"
        return httpx.Response(200, json={"username": "alice", "id": 3})

    assert CONNECTOR.verify is not None
    assert CONNECTOR.verify(ctx(handler)).account_label == "alice"


def test_default_base_url_is_gitlab_com() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"username": "a"})

    secrets = ConnectionSecrets(base_url=None, username=None, token="t")
    assert CONNECTOR.verify is not None
    CONNECTOR.verify(ConnectorContext(secrets, {}, transport=httpx.MockTransport(handler)))
    assert seen == ["https://gitlab.com/api/v4/user"]


def test_project_path_is_url_encoded_and_falls_back_to_the_node_option() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.raw_path.startswith(b"/api/v4/projects/group%2Fapp/merge_requests")
        assert req.url.params["state"] == "opened"
        return httpx.Response(
            200,
            json=[
                {
                    "iid": 7,
                    "title": "Fix login",
                    "state": "opened",
                    "author": {"username": "bob"},
                    "source_branch": "fix",
                    "target_branch": "main",
                    "web_url": "https://gitlab.test/mr/7",
                    "labels": ["bug"],
                    "updated_at": "2026-10-01T00:00:00Z",
                }
            ],
        )

    result = run("list_merge_requests", handler, {}, {"project": "group/app"})
    assert result == [
        {
            "iid": 7,
            "title": "Fix login",
            "state": "opened",
            "author": "bob",
            "source_branch": "fix",
            "target_branch": "main",
            "labels": ["bug"],
            "updated_at": "2026-10-01T00:00:00Z",
            "url": "https://gitlab.test/mr/7",
        }
    ]


def test_an_action_without_a_project_says_so() -> None:
    with pytest.raises(ConnectorError, match="project"):
        run("list_issues", lambda req: httpx.Response(200, json=[]), {})


def test_merge_request_changes_are_capped() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/merge_requests/7/diffs")
        return httpx.Response(200, json=[{"new_path": "a.py", "diff": "+" * 5000}] * 3)

    result = run("get_merge_request_changes", handler, {"project": "g/a", "iid": 7, "max_chars": 6000})
    assert result["truncated"] is True
    assert sum(len(f["diff"]) for f in result["files"]) <= 6000


def test_create_issue_posts_labels_as_a_comma_list() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        body = json.loads(req.content)
        assert body == {"title": "Crash", "description": "Steps", "labels": "bug,urgent"}
        return httpx.Response(201, json={"iid": 12, "web_url": "https://gitlab.test/i/12", "title": "Crash"})

    result = run("create_issue", handler, {"project": "g/a", "title": "Crash", "description": "Steps", "labels": ["bug", "urgent"]})
    assert result == {"iid": 12, "title": "Crash", "url": "https://gitlab.test/i/12"}


def test_add_merge_request_note_posts_the_body() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/merge_requests/7/notes")
        assert json.loads(req.content) == {"body": "Looks good"}
        return httpx.Response(201, json={"id": 99})

    assert run("add_merge_request_note", handler, {"project": "g/a", "iid": 7, "body": "Looks good"}) == {"note_id": 99}


def test_get_file_returns_text_at_a_ref() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.raw_path.startswith(b"/api/v4/projects/g%2Fa/repository/files/src%2Fmain.py/raw")
        assert req.url.params["ref"] == "main"
        return httpx.Response(200, text="print('hi')")

    assert run("get_file", handler, {"project": "g/a", "file_path": "src/main.py", "ref": "main"}) == "print('hi')"


def test_reads_are_read_and_writes_are_writes() -> None:
    kinds = {action.id: action.kind for action in CONNECTOR.actions}
    assert kinds["list_merge_requests"] == "read"
    assert kinds["create_issue"] == "write"
    assert not any(word in action_id for action_id in kinds for word in ("merge_merge", "approve", "delete"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_gitlab.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.connectors.gitlab'`

- [ ] **Step 3: Write the implementation**

`src/connectors/gitlab.py`:
```python
"""GitLab: projects, merge requests, issues, files and pipelines.

Works with gitlab.com and self-hosted GitLab. Auth is a personal access token
sent in PRIVATE-TOKEN; ``api`` scope for writes, ``read_api`` for read-only.
Approving, merging, triggering pipelines and deleting are deliberately absent.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.connectors.base import (
    Action,
    AuthSpec,
    Connector,
    ConnectorContext,
    ConnectorError,
    OptionField,
    Param,
    VerifyResult,
)
from src.connectors.http import request

SERVICE = "GitLab"
DEFAULT_BASE_URL = "https://gitlab.com"


def _api(ctx: ConnectorContext) -> str:
    return (ctx.secrets.base_url or DEFAULT_BASE_URL).rstrip("/") + "/api/v4"


def _headers(ctx: ConnectorContext) -> dict[str, str]:
    return {"PRIVATE-TOKEN": ctx.secrets.token}


def _call(ctx: ConnectorContext, method: str, path: str, **kwargs: Any) -> Any:
    return request(ctx, method, _api(ctx) + path, service=SERVICE, headers=_headers(ctx), **kwargs)


def _project(ctx: ConnectorContext, args: dict[str, Any]) -> str:
    project = args.get("project") or ctx.option("project")
    if not project:
        raise ConnectorError(
            "No GitLab project given. Pass 'project' (group/name or id), or set the node's Default project."
        )
    return quote(str(project), safe="")


def _labels(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def _mr(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "iid": item.get("iid"),
        "title": item.get("title"),
        "state": item.get("state"),
        "author": (item.get("author") or {}).get("username"),
        "source_branch": item.get("source_branch"),
        "target_branch": item.get("target_branch"),
        "labels": item.get("labels") or [],
        "updated_at": item.get("updated_at"),
        "url": item.get("web_url"),
    }


def _issue(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "iid": item.get("iid"),
        "title": item.get("title"),
        "state": item.get("state"),
        "author": (item.get("author") or {}).get("username"),
        "assignees": [a.get("username") for a in item.get("assignees") or []],
        "labels": item.get("labels") or [],
        "updated_at": item.get("updated_at"),
        "url": item.get("web_url"),
    }


def verify(ctx: ConnectorContext) -> VerifyResult:
    user = _call(ctx, "GET", "/user")
    return VerifyResult(account_label=str(user.get("username") or user.get("name") or "GitLab user"))


def search_projects(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    items = _call(
        ctx,
        "GET",
        "/projects",
        params={"search": args.get("search"), "membership": "true", "per_page": args.get("max_results", 20)},
    )
    return [
        {
            "id": p.get("id"),
            "path": p.get("path_with_namespace"),
            "description": p.get("description"),
            "url": p.get("web_url"),
        }
        for p in items
    ]


def list_merge_requests(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    items = _call(
        ctx,
        "GET",
        f"/projects/{_project(ctx, args)}/merge_requests",
        params={
            "state": args.get("state", "opened"),
            "labels": _labels(args.get("labels")),
            "author_username": args.get("author_username"),
            "per_page": args.get("max_results", 20),
        },
    )
    return [_mr(item) for item in items]


def get_merge_request(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    base = f"/projects/{_project(ctx, args)}/merge_requests/{args['iid']}"
    item = _call(ctx, "GET", base)
    try:
        approvals = _call(ctx, "GET", base + "/approvals")
        approval = {
            "approved": approvals.get("approved"),
            "approved_by": [a.get("user", {}).get("username") for a in approvals.get("approved_by") or []],
        }
    except ConnectorError:
        approval = None
    return {**_mr(item), "description": item.get("description") or "", "approvals": approval}


def get_merge_request_changes(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    limit = int(args.get("max_chars", 20000))
    files = _call(
        ctx,
        "GET",
        f"/projects/{_project(ctx, args)}/merge_requests/{args['iid']}/diffs",
        params={"per_page": 100},
    )
    out: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for item in files:
        diff = str(item.get("diff") or "")
        room = limit - used
        if room <= 0:
            truncated = True
            break
        if len(diff) > room:
            diff = diff[:room]
            truncated = True
        used += len(diff)
        out.append({"path": item.get("new_path") or item.get("old_path"), "diff": diff})
    return {"files": out, "truncated": truncated}


def list_issues(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    items = _call(
        ctx,
        "GET",
        f"/projects/{_project(ctx, args)}/issues",
        params={
            "state": args.get("state", "opened"),
            "labels": _labels(args.get("labels")),
            "search": args.get("search"),
            "per_page": args.get("max_results", 20),
        },
    )
    return [_issue(item) for item in items]


def get_file(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    path = quote(str(args["file_path"]), safe="")
    return _call(
        ctx,
        "GET",
        f"/projects/{_project(ctx, args)}/repository/files/{path}/raw",
        params={"ref": args.get("ref", "HEAD")},
        raw=True,
    )


def list_pipelines(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    project = _project(ctx, args)
    pipelines = _call(
        ctx,
        "GET",
        f"/projects/{project}/pipelines",
        params={"ref": args.get("ref"), "status": args.get("status"), "per_page": args.get("max_results", 10)},
    )
    out = [
        {"id": p.get("id"), "status": p.get("status"), "ref": p.get("ref"), "updated_at": p.get("updated_at"), "url": p.get("web_url")}
        for p in pipelines
    ]
    if out:
        jobs = _call(ctx, "GET", f"/projects/{project}/pipelines/{out[0]['id']}/jobs", params={"per_page": 100})
        out[0]["jobs"] = [{"name": j.get("name"), "stage": j.get("stage"), "status": j.get("status")} for j in jobs]
    return out


def create_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    body: dict[str, Any] = {"title": args["title"]}
    if args.get("description"):
        body["description"] = args["description"]
    labels = _labels(args.get("labels"))
    if labels:
        body["labels"] = labels
    item = _call(ctx, "POST", f"/projects/{_project(ctx, args)}/issues", json_body=body)
    return {"iid": item.get("iid"), "title": item.get("title"), "url": item.get("web_url")}


def update_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    body: dict[str, Any] = {}
    for key in ("title", "description", "state_event"):
        if args.get(key) is not None:
            body[key] = args[key]
    if args.get("labels") is not None:
        body["labels"] = _labels(args["labels"])
    if not body:
        raise ConnectorError("Nothing to update: pass title, description, labels or state_event.")
    item = _call(ctx, "PUT", f"/projects/{_project(ctx, args)}/issues/{args['iid']}", json_body=body)
    return _issue(item)


def add_merge_request_note(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    note = _call(
        ctx,
        "POST",
        f"/projects/{_project(ctx, args)}/merge_requests/{args['iid']}/notes",
        json_body={"body": args["body"]},
    )
    return {"note_id": note.get("id")}


def add_issue_note(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    note = _call(
        ctx,
        "POST",
        f"/projects/{_project(ctx, args)}/issues/{args['iid']}/notes",
        json_body={"body": args["body"]},
    )
    return {"note_id": note.get("id")}


def set_merge_request_labels(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    item = _call(
        ctx,
        "PUT",
        f"/projects/{_project(ctx, args)}/merge_requests/{args['iid']}",
        json_body={"labels": _labels(args["labels"]) or ""},
    )
    return _mr(item)


_PROJECT = Param("project", "string", "Project path (group/name) or id; defaults to the node's Default project", required=False)
_IID = Param("iid", "integer", "The merge request or issue number inside the project")
_MAX = Param("max_results", "integer", "Most items to return", required=False, default=20)

CONNECTOR = Connector(
    id="gitlab",
    name="GitLab",
    icon="gitlab",
    description="Merge requests, issues, files and pipelines on gitlab.com or your own GitLab",
    auth=AuthSpec(
        kind="token",
        base_url=True,
        base_url_default=DEFAULT_BASE_URL,
        token_label="Personal access token",
        token_help="Create one under User settings → Access tokens. Scope 'api' to allow writes, 'read_api' for read-only.",
    ),
    options=(OptionField("project", "Default project", "group/name; actions use it when they name no project"),),
    verify=verify,
    actions=(
        Action("search_projects", "Search projects", "read", "Find projects you are a member of by name.", (Param("search", "string", "Text in the project name"), _MAX), search_projects),
        Action("list_merge_requests", "List merge requests", "read", "List merge requests in a project, newest first.", (_PROJECT, Param("state", "string", "opened, merged, closed or all", required=False, default="opened", enum=("opened", "merged", "closed", "all")), Param("labels", "array", "Only these labels", required=False), Param("author_username", "string", "Only by this author", required=False), _MAX), list_merge_requests),
        Action("get_merge_request", "Get a merge request", "read", "One merge request with its description and approval state.", (_PROJECT, _IID), get_merge_request),
        Action("get_merge_request_changes", "Get merge request changes", "read", "The diff of a merge request, file by file, capped in size.", (_PROJECT, _IID, Param("max_chars", "integer", "Most diff characters to return", required=False, default=20000)), get_merge_request_changes),
        Action("list_issues", "List issues", "read", "List issues in a project.", (_PROJECT, Param("state", "string", "opened, closed or all", required=False, default="opened", enum=("opened", "closed", "all")), Param("labels", "array", "Only these labels", required=False), Param("search", "string", "Text in the title or description", required=False), _MAX), list_issues),
        Action("get_file", "Get a file", "read", "A file's content at a branch, tag or commit.", (_PROJECT, Param("file_path", "string", "Path in the repository, e.g. src/app.py"), Param("ref", "string", "Branch, tag or commit; default HEAD", required=False, default="HEAD")), get_file),
        Action("list_pipelines", "List pipelines", "read", "Recent pipelines, with the jobs of the newest one.", (_PROJECT, Param("ref", "string", "Only this branch or tag", required=False), Param("status", "string", "Only this status, e.g. failed", required=False), Param("max_results", "integer", "Most pipelines to return", required=False, default=10)), list_pipelines),
        Action("create_issue", "Create an issue", "write", "Open a new issue in a project.", (_PROJECT, Param("title", "string", "Issue title"), Param("description", "string", "Issue body in Markdown", required=False), Param("labels", "array", "Labels to set", required=False)), create_issue),
        Action("update_issue", "Update an issue", "write", "Change an issue's title, description or labels, or close/reopen it.", (_PROJECT, _IID, Param("title", "string", "New title", required=False), Param("description", "string", "New body", required=False), Param("labels", "array", "Replace the labels", required=False), Param("state_event", "string", "close or reopen", required=False, enum=("close", "reopen"))), update_issue),
        Action("add_merge_request_note", "Comment on a merge request", "write", "Post a comment on a merge request.", (_PROJECT, _IID, Param("body", "string", "Comment in Markdown")), add_merge_request_note),
        Action("add_issue_note", "Comment on an issue", "write", "Post a comment on an issue.", (_PROJECT, _IID, Param("body", "string", "Comment in Markdown")), add_issue_note),
        Action("set_merge_request_labels", "Set merge request labels", "write", "Replace a merge request's labels.", (_PROJECT, _IID, Param("labels", "array", "The labels to keep")), set_merge_request_labels),
    ),
)
```

Run `ruff format src/connectors/gitlab.py` after writing; the long `Action(...)` lines are reformatted.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_gitlab.py && mypy src/connectors`
Expected: PASS, mypy Success.

- [ ] **Step 5: Commit**

```bash
git add src/connectors/gitlab.py tests/unit/connectors/test_gitlab.py
git commit -m "feat(connectors): GitLab — merge requests, issues, files, pipelines

Personal access token auth against gitlab.com or a self-hosted GitLab. Seven
read actions and five write actions; nothing that approves, merges, triggers
a pipeline or deletes."
```

---

### Task 3: Jira connector

**Files:**
- Create: `src/connectors/jira.py`
- Test: `tests/unit/connectors/test_jira.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `src.connectors.jira.CONNECTOR` (id `jira`) with actions `search_issues`, `get_issue`, `list_projects`, `list_transitions` (read), `create_issue`, `update_issue`, `add_comment`, `transition_issue`, `assign_issue` (write). `verify()` returns `VerifyResult(account_label, options={"api_version": "3"|"2"})`. Helpers `to_adf(text) -> dict`, `adf_to_text(node) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_jira.py`:
```python
"""Jira actions against a mocked API, for Cloud (v3, ADF) and Data Center (v2)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.jira import CONNECTOR, adf_to_text, to_adf

Handler = Callable[[httpx.Request], httpx.Response]


def ctx(handler: Handler, *, version: str = "3", username: str | None = "ops@acme.test", options: dict[str, Any] | None = None) -> ConnectorContext:
    secrets = ConnectionSecrets(
        base_url="https://acme.atlassian.net",
        username=username,
        token="tok",
        options={"api_version": version},
    )
    return ConnectorContext(secrets, options or {}, transport=httpx.MockTransport(handler))


def run(action_id: str, handler: Handler, args: dict[str, Any], **kw: Any) -> Any:
    return CONNECTOR.action(action_id).run(ctx(handler, **kw), args)


def test_cloud_verify_uses_basic_auth_and_records_v3() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/3/myself"
        expected = base64.b64encode(b"ops@acme.test:tok").decode()
        assert req.headers["Authorization"] == f"Basic {expected}"
        return httpx.Response(200, json={"displayName": "Ops Bot", "emailAddress": "ops@acme.test"})

    assert CONNECTOR.verify is not None
    result = CONNECTOR.verify(ctx(handler, version=""))
    assert result.account_label == "Ops Bot (ops@acme.test)"
    assert result.options == {"api_version": "3"}


def test_data_center_verify_falls_back_to_v2_with_a_bearer_token() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        if req.url.path == "/rest/api/3/myself":
            return httpx.Response(404, json={"message": "no v3"})
        return httpx.Response(200, json={"displayName": "Ops", "name": "ops"})

    assert CONNECTOR.verify is not None
    result = CONNECTOR.verify(ctx(handler, version="", username=None))
    assert result.options == {"api_version": "2"}


def test_adf_round_trip_keeps_paragraphs_and_lines() -> None:
    text = "First line\nsecond line\n\nNew paragraph"
    assert adf_to_text(to_adf(text)) == text


def test_search_uses_the_jql_endpoint_on_cloud() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/3/search/jql"
        assert req.url.params["jql"] == "project = OPS"
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "OPS-1",
                        "fields": {
                            "summary": "Login fails",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Ann"},
                            "priority": {"name": "High"},
                            "labels": ["bug"],
                            "issuetype": {"name": "Bug"},
                            "updated": "2026-10-01",
                        },
                    }
                ]
            },
        )

    assert run("search_issues", handler, {"jql": "project = OPS"}) == [
        {
            "key": "OPS-1",
            "summary": "Login fails",
            "status": "To Do",
            "assignee": "Ann",
            "priority": "High",
            "labels": ["bug"],
            "type": "Bug",
            "updated": "2026-10-01",
            "url": "https://acme.atlassian.net/browse/OPS-1",
        }
    ]


def test_search_uses_the_old_endpoint_on_data_center() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/2/search"
        return httpx.Response(200, json={"issues": []})

    assert run("search_issues", handler, {"jql": "x"}, version="2", username=None) == []


def test_create_issue_sends_adf_on_cloud_and_defaults_the_project() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        fields = json.loads(req.content)["fields"]
        assert fields["project"] == {"key": "OPS"}
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["description"]["type"] == "doc"
        return httpx.Response(201, json={"key": "OPS-9", "id": "10009"})

    result = run("create_issue", handler, {"summary": "Crash", "description": "Steps", "issue_type": "Bug"}, options={"project": "OPS"})
    assert result == {"key": "OPS-9", "id": "10009", "url": "https://acme.atlassian.net/browse/OPS-9"}


def test_create_issue_sends_plain_text_on_data_center() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["fields"]["description"] == "Steps"
        return httpx.Response(201, json={"key": "OPS-9", "id": "1"})

    run("create_issue", handler, {"summary": "Crash", "description": "Steps", "project": "OPS"}, version="2", username=None)


def test_get_issue_flattens_description_and_comments() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "key": "OPS-1",
                "fields": {
                    "summary": "S",
                    "description": to_adf("Body"),
                    "status": {"name": "Open"},
                    "reporter": {"displayName": "Rae"},
                    "comment": {"comments": [{"author": {"displayName": "Ann"}, "created": "t", "body": to_adf("Hi")}]},
                },
            },
        )

    issue = run("get_issue", handler, {"key": "OPS-1"})
    assert issue["description"] == "Body"
    assert issue["comments"] == [{"author": "Ann", "created": "t", "body": "Hi"}]
    assert issue["reporter"] == "Rae"


def test_transition_matches_by_name_case_insensitively() -> None:
    posted: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Done", "to": {"name": "Closed"}}]})
        posted.append(json.loads(req.content))
        return httpx.Response(204)

    assert run("transition_issue", handler, {"key": "OPS-1", "transition": "done"}) == {"key": "OPS-1", "transitioned_to": "Closed"}
    assert posted == [{"transition": {"id": "31"}}]


def test_transition_by_unknown_name_lists_the_choices() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transitions": [{"id": "1", "name": "Start", "to": {"name": "In Progress"}}, {"id": "2", "name": "Close", "to": {"name": "Closed"}}]})

    with pytest.raises(ConnectorError, match="Start, Close"):
        run("transition_issue", handler, {"key": "OPS-1", "transition": "Done"})


def test_assign_by_email_looks_up_the_account_on_cloud() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/rest/api/3/user/search":
            assert req.url.params["query"] == "dev@acme.test"
            return httpx.Response(200, json=[{"accountId": "acc-1", "displayName": "Dev"}])
        assert req.url.path == "/rest/api/3/issue/OPS-1/assignee"
        assert json.loads(req.content) == {"accountId": "acc-1"}
        return httpx.Response(204)

    assert run("assign_issue", handler, {"key": "OPS-1", "assignee": "dev@acme.test"}) == {"key": "OPS-1", "assignee": "Dev"}


def test_assign_to_an_unknown_email_says_so() -> None:
    with pytest.raises(ConnectorError, match="No Jira user"):
        run("assign_issue", lambda req: httpx.Response(200, json=[]), {"key": "OPS-1", "assignee": "who@acme.test"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_jira.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.connectors.jira'`

- [ ] **Step 3: Write the implementation**

`src/connectors/jira.py`:
```python
"""Jira Cloud and Jira Data Center: search, read, create, comment, transition, assign.

Cloud uses REST v3 with an account email and API token (Basic auth) and
Atlassian Document Format for rich text. Data Center uses REST v2 with a
personal access token (Bearer) and plain text. Which one a connection talks
to is found when it is verified and stored as the ``api_version`` option.
"""

from __future__ import annotations

from typing import Any

from src.connectors.base import (
    Action,
    AuthSpec,
    Connector,
    ConnectorContext,
    ConnectorError,
    OptionField,
    Param,
    VerifyResult,
)
from src.connectors.http import request

SERVICE = "Jira"
_ISSUE_FIELDS = "summary,status,assignee,priority,labels,issuetype,updated"


def _version(ctx: ConnectorContext) -> str:
    return str(ctx.secrets.options.get("api_version") or "3")


def _base(ctx: ConnectorContext) -> str:
    if not ctx.secrets.base_url:
        raise ConnectorError("This Jira connection has no base URL.")
    return ctx.secrets.base_url.rstrip("/")


def _auth(ctx: ConnectorContext) -> tuple[dict[str, str], tuple[str, str] | None]:
    if ctx.secrets.username:
        return {}, (ctx.secrets.username, ctx.secrets.token)
    return {"Authorization": f"Bearer {ctx.secrets.token}"}, None


def _call(ctx: ConnectorContext, method: str, path: str, *, version: str | None = None, **kwargs: Any) -> Any:
    headers, basic = _auth(ctx)
    url = f"{_base(ctx)}/rest/api/{version or _version(ctx)}{path}"
    return request(ctx, method, url, service=SERVICE, headers=headers, auth=basic, **kwargs)


def to_adf(text: str) -> dict[str, Any]:
    """Plain text as an Atlassian Document: blank lines split paragraphs, newlines break lines."""
    paragraphs: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        content: list[dict[str, Any]] = []
        for index, line in enumerate(block.split("\n")):
            if index:
                content.append({"type": "hardBreak"})
            if line:
                content.append({"type": "text", "text": line})
        paragraphs.append({"type": "paragraph", "content": content})
    return {"type": "doc", "version": 1, "content": paragraphs}


def adf_to_text(node: Any) -> str:
    """An Atlassian Document (or plain text from v2) as plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    children = "".join(adf_to_text(child) for child in node.get("content") or [])
    if kind == "doc":
        return "\n\n".join(adf_to_text(child) for child in node.get("content") or [])
    return children


def _rich(ctx: ConnectorContext, text: str) -> Any:
    return to_adf(text) if _version(ctx) == "3" else text


def _url(ctx: ConnectorContext, key: str) -> str:
    return f"{_base(ctx)}/browse/{key}"


def _name(person: Any) -> str | None:
    return person.get("displayName") if isinstance(person, dict) else None


def _summary(ctx: ConnectorContext, issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": (fields.get("status") or {}).get("name"),
        "assignee": _name(fields.get("assignee")),
        "priority": (fields.get("priority") or {}).get("name"),
        "labels": fields.get("labels") or [],
        "type": (fields.get("issuetype") or {}).get("name"),
        "updated": fields.get("updated"),
        "url": _url(ctx, str(issue.get("key"))),
    }


def verify(ctx: ConnectorContext) -> VerifyResult:
    try:
        me = _call(ctx, "GET", "/myself", version="3")
        version = "3"
    except ConnectorError as exc:
        if exc.status != 404:
            raise
        me = _call(ctx, "GET", "/myself", version="2")
        version = "2"
    label = str(me.get("displayName") or me.get("name") or "Jira user")
    email = me.get("emailAddress")
    return VerifyResult(account_label=f"{label} ({email})" if email else label, options={"api_version": version})


def search_issues(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    params = {"jql": args["jql"], "maxResults": args.get("max_results", 20), "fields": _ISSUE_FIELDS}
    path = "/search/jql" if _version(ctx) == "3" else "/search"
    result = _call(ctx, "GET", path, params=params)
    return [_summary(ctx, issue) for issue in result.get("issues") or []]


def get_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    issue = _call(
        ctx,
        "GET",
        f"/issue/{args['key']}",
        params={"fields": _ISSUE_FIELDS + ",description,reporter,created,comment"},
    )
    fields = issue.get("fields") or {}
    comments = (fields.get("comment") or {}).get("comments") or []
    return {
        **_summary(ctx, issue),
        "description": adf_to_text(fields.get("description")),
        "reporter": _name(fields.get("reporter")),
        "created": fields.get("created"),
        "comments": [
            {"author": _name(c.get("author")), "created": c.get("created"), "body": adf_to_text(c.get("body"))}
            for c in comments[-20:]
        ],
    }


def list_projects(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    if _version(ctx) == "3":
        projects = _call(ctx, "GET", "/project/search", params={"maxResults": 50}).get("values") or []
    else:
        projects = _call(ctx, "GET", "/project")
    return [{"key": p.get("key"), "name": p.get("name")} for p in projects]


def list_transitions(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    result = _call(ctx, "GET", f"/issue/{args['key']}/transitions")
    return [
        {"id": t.get("id"), "name": t.get("name"), "to": (t.get("to") or {}).get("name")}
        for t in result.get("transitions") or []
    ]


def create_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    project = args.get("project") or ctx.option("project")
    if not project:
        raise ConnectorError("No Jira project given. Pass 'project' (its key), or set the node's Default project.")
    fields: dict[str, Any] = {
        "project": {"key": project},
        "summary": args["summary"],
        "issuetype": {"name": args.get("issue_type", "Task")},
    }
    if args.get("description"):
        fields["description"] = _rich(ctx, args["description"])
    if args.get("labels"):
        fields["labels"] = list(args["labels"])
    if args.get("priority"):
        fields["priority"] = {"name": args["priority"]}
    created = _call(ctx, "POST", "/issue", json_body={"fields": fields})
    key = str(created.get("key"))
    return {"key": key, "id": created.get("id"), "url": _url(ctx, key)}


def update_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    fields: dict[str, Any] = dict(args.get("fields") or {})
    if args.get("summary"):
        fields["summary"] = args["summary"]
    if args.get("description") is not None:
        fields["description"] = _rich(ctx, args["description"])
    if args.get("labels") is not None:
        fields["labels"] = list(args["labels"])
    if args.get("priority"):
        fields["priority"] = {"name": args["priority"]}
    if not fields:
        raise ConnectorError("Nothing to update: pass summary, description, labels, priority or fields.")
    _call(ctx, "PUT", f"/issue/{args['key']}", json_body={"fields": fields})
    return {"key": args["key"], "updated": sorted(fields)}


def add_comment(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    comment = _call(ctx, "POST", f"/issue/{args['key']}/comment", json_body={"body": _rich(ctx, args["body"])})
    return {"key": args["key"], "comment_id": comment.get("id")}


def transition_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    wanted = str(args["transition"]).strip().lower()
    choices = list_transitions(ctx, {"key": args["key"]})
    match = next(
        (t for t in choices if wanted in (str(t["id"]).lower(), str(t["name"]).lower(), str(t["to"]).lower())),
        None,
    )
    if match is None:
        names = ", ".join(str(t["name"]) for t in choices) or "none"
        raise ConnectorError(f"{args['key']} has no transition '{args['transition']}'. Available: {names}.")
    _call(ctx, "POST", f"/issue/{args['key']}/transitions", json_body={"transition": {"id": match["id"]}})
    return {"key": args["key"], "transitioned_to": match["to"] or match["name"]}


def assign_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    who = str(args.get("assignee") or "").strip()
    cloud = _version(ctx) == "3"
    if who.lower() in ("", "none", "unassigned"):
        _call(ctx, "PUT", f"/issue/{args['key']}/assignee", json_body={"accountId": None} if cloud else {"name": None})
        return {"key": args["key"], "assignee": None}
    display = who
    if "@" in who:
        users = _call(ctx, "GET", "/user/search", params={"query": who} if cloud else {"username": who})
        if not users:
            raise ConnectorError(f"No Jira user matches {who}.")
        who = str(users[0].get("accountId") if cloud else users[0].get("name"))
        display = str(users[0].get("displayName") or who)
    _call(ctx, "PUT", f"/issue/{args['key']}/assignee", json_body={"accountId": who} if cloud else {"name": who})
    return {"key": args["key"], "assignee": display}


_KEY = Param("key", "string", "Issue key, e.g. OPS-123")

CONNECTOR = Connector(
    id="jira",
    name="Jira",
    icon="jira",
    description="Search, create, comment on, transition and assign Jira issues (Cloud or Data Center)",
    auth=AuthSpec(
        kind="token",
        base_url=True,
        base_url_label="Jira site URL",
        username_label="Account email (Jira Cloud only)",
        token_label="API token (Cloud) or personal access token (Data Center)",
        token_help="Cloud: id.atlassian.com → Security → API tokens, and fill in the account email. Data Center: Profile → Personal access tokens, and leave the email empty.",
    ),
    options=(OptionField("project", "Default project", "Project key, e.g. OPS; used when an action names none"),),
    verify=verify,
    actions=(
        Action("search_issues", "Search issues", "read", "Find issues with JQL, e.g. 'project = OPS AND status != Done ORDER BY created DESC'.", (Param("jql", "string", "A JQL query"), Param("max_results", "integer", "Most issues to return", required=False, default=20)), search_issues),
        Action("get_issue", "Get an issue", "read", "One issue with its description and latest comments.", (_KEY,), get_issue),
        Action("list_projects", "List projects", "read", "The projects this account can see.", (), list_projects),
        Action("list_transitions", "List transitions", "read", "The status changes an issue allows right now.", (_KEY,), list_transitions),
        Action("create_issue", "Create an issue", "write", "Create an issue; returns its key and link.", (Param("summary", "string", "One-line title"), Param("description", "string", "Body text", required=False), Param("issue_type", "string", "Task, Bug, Story, …", required=False, default="Task"), Param("project", "string", "Project key; defaults to the node's Default project", required=False), Param("priority", "string", "Priority name, e.g. High", required=False), Param("labels", "array", "Labels to set", required=False)), create_issue),
        Action("update_issue", "Update an issue", "write", "Change an issue's summary, description, labels, priority, or other fields by id.", (_KEY, Param("summary", "string", "New summary", required=False), Param("description", "string", "New description", required=False), Param("labels", "array", "Replace the labels", required=False), Param("priority", "string", "Priority name", required=False), Param("fields", "object", "Other fields by id, e.g. {\"customfield_10010\": \"x\"}", required=False)), update_issue),
        Action("add_comment", "Comment on an issue", "write", "Add a comment to an issue.", (_KEY, Param("body", "string", "Comment text")), add_comment),
        Action("transition_issue", "Transition an issue", "write", "Move an issue to another status by transition name, id, or target status.", (_KEY, Param("transition", "string", "Transition name or id, or the status to move to")), transition_issue),
        Action("assign_issue", "Assign an issue", "write", "Assign an issue by email or account id; 'none' unassigns.", (_KEY, Param("assignee", "string", "Email, account id (Cloud) or username (Data Center), or 'none'")), assign_issue),
    ),
)
```

Run `ruff format src/connectors/jira.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_jira.py && mypy src/connectors`
Expected: PASS, Success.

- [ ] **Step 5: Commit**

```bash
git add src/connectors/jira.py tests/unit/connectors/test_jira.py
git commit -m "feat(connectors): Jira Cloud and Data Center

Basic auth with an account email and API token on Cloud (REST v3, Atlassian
Document Format), a bearer personal access token on Data Center (REST v2).
The version is found on verify. Transitions match by name, id or target
status and list the choices when none match."
```

---

### Task 4: Gmail connector, with reply-to-thread and new-message listing

**Files:**
- Modify: `src/tools/gmail_tool.py` (add two functions after `read_email`)
- Create: `src/connectors/gmail.py`, `src/connectors/registry.py`
- Test: `tests/unit/connectors/test_gmail.py`, `tests/unit/connectors/test_registry.py`

**Interfaces:**
- Consumes: Task 1; existing `gmail_tool.send_email/search_emails/read_email/_gmail_service/_header`.
- Produces:
  - `gmail_tool.reply_to_thread(account_email: str, message_id: str, body: str, cc: str = "") -> str` (JSON)
  - `gmail_tool.list_new_messages(account_email: str, since_epoch: int, query: str = "", max_results: int = 20) -> str` (JSON)
  - `src.connectors.gmail.CONNECTOR` (id `gmail`, `auth.kind == "oauth"`, `auth.oauth_start == "/api/v1/integrations/gmail/auth-url"`) with actions `search_emails`, `read_email`, `list_new_messages` (read), `send_email`, `reply_to_thread` (write). Actions use `ctx.secrets.account_label` as the mailbox.
  - `src.connectors.registry`: `get_connector(connector_id: str) -> Connector | None`, `all_connectors() -> list[Connector]`, `connector_ids() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_gmail.py`:
```python
"""Gmail as a connector, and the two new mailbox calls behind it."""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from typing import Any

import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext
from src.connectors.gmail import CONNECTOR
from src.tools import gmail_tool


class _Call:
    def __init__(self, result: Any, sink: list[Any] | None = None, payload: Any = None) -> None:
        self._result = result
        if sink is not None:
            sink.append(payload)

    def execute(self) -> Any:
        return self._result


class FakeMessages:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.listed: list[Any] = []

    def get(self, userId: str, id: str, format: str = "full", metadataHeaders: Any = None) -> _Call:  # noqa: A002, N803
        return _Call(
            {
                "id": id,
                "threadId": "thr-1",
                "snippet": "My login fails",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "User <user@acme.test>"},
                        {"name": "Subject", "value": "Login fails"},
                        {"name": "Message-ID", "value": "<orig@acme.test>"},
                        {"name": "Date", "value": "Mon, 6 Oct 2026 10:00:00 +0000"},
                    ]
                },
            }
        )

    def send(self, userId: str, body: dict[str, Any]) -> _Call:  # noqa: N803
        return _Call({"id": "sent-1", "threadId": body.get("threadId")}, self.sent, body)

    def list(self, userId: str, q: str, maxResults: int) -> _Call:  # noqa: N803
        return _Call({"messages": [{"id": "m1"}]}, self.listed, q)


class FakeService:
    def __init__(self) -> None:
        self.messages_api = FakeMessages()

    def users(self) -> FakeService:
        return self

    def messages(self) -> FakeMessages:
        return self.messages_api


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    fake = FakeService()
    monkeypatch.setattr(gmail_tool, "_gmail_service", lambda account_email: fake)
    return fake


def test_reply_stays_in_the_thread_and_quotes_the_subject(service: FakeService) -> None:
    result = json.loads(gmail_tool.reply_to_thread("ops@acme.test", "m1", "Fixed now."))
    assert result["status"] == "sent" and result["thread_id"] == "thr-1"
    sent = service.messages_api.sent[0]
    assert sent["threadId"] == "thr-1"
    mail = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
    assert mail["To"] == "User <user@acme.test>"
    assert mail["Subject"] == "Re: Login fails"
    assert mail["In-Reply-To"] == "<orig@acme.test>"
    assert "<orig@acme.test>" in mail["References"]


def test_list_new_messages_queries_after_the_cursor(service: FakeService) -> None:
    result = json.loads(gmail_tool.list_new_messages("ops@acme.test", since_epoch=1760000000, query="label:support"))
    assert service.messages_api.listed == ["after:1760000000 label:support"]
    assert result[0]["subject"] == "Login fails"


def test_gmail_connector_uses_the_connection_mailbox(service: FakeService) -> None:
    secrets = ConnectionSecrets(base_url=None, username=None, token="", account_label="ops@acme.test")
    ctx = ConnectorContext(secrets, {})
    out = CONNECTOR.action("reply_to_thread").run(ctx, {"message_id": "m1", "body": "Done"})
    assert out["status"] == "sent"


def test_gmail_connector_is_oauth_with_a_start_path() -> None:
    assert CONNECTOR.auth.kind == "oauth"
    assert CONNECTOR.auth.oauth_start == "/api/v1/integrations/gmail/auth-url"
    assert {a.id: a.kind for a in CONNECTOR.actions} == {
        "search_emails": "read",
        "read_email": "read",
        "list_new_messages": "read",
        "send_email": "write",
        "reply_to_thread": "write",
    }
```

`tests/unit/connectors/test_registry.py`:
```python
from src.connectors.registry import all_connectors, connector_ids, get_connector


def test_builtin_connectors_are_registered_in_a_stable_order() -> None:
    assert connector_ids() == ["jira", "gitlab", "gmail"]
    assert [c.id for c in all_connectors()] == ["jira", "gitlab", "gmail"]


def test_unknown_connector_is_none() -> None:
    assert get_connector("nope") is None
    jira = get_connector("jira")
    assert jira is not None and jira.name == "Jira"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_gmail.py tests/unit/connectors/test_registry.py`
Expected: FAIL — `AttributeError: module 'src.tools.gmail_tool' has no attribute 'reply_to_thread'` / `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

Append to `src/tools/gmail_tool.py` (after `read_email`; `EmailMessage`, `base64`, `json`, `logger`, `_gmail_service`, `_header` already exist in the module):
```python
def reply_to_thread(account_email: str, message_id: str, body: str, cc: str = "") -> str:
    """Reply to a message in its own thread, to its sender (or Reply-To)."""
    service = _gmail_service(account_email)
    original = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"],
        )
        .execute()
    )
    headers = original.get("payload", {}).get("headers", [])
    recipient = _header(headers, "Reply-To") or _header(headers, "From")
    if not recipient:
        return json.dumps({"error": f"Message {message_id} has no sender to reply to."})
    subject = _header(headers, "Subject")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()
    original_id = _header(headers, "Message-ID")
    references = " ".join(part for part in (_header(headers, "References"), original_id) if part)

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = account_email
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if original_id:
        message["In-Reply-To"] = original_id
        message["References"] = references
    message.set_content(body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    thread_id = original.get("threadId")
    result = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )
    logger.info("gmail_reply_sent", account_email=account_email, thread_id=thread_id)
    return json.dumps(
        {"status": "sent", "message_id": result.get("id"), "thread_id": thread_id, "to": recipient}
    )


def list_new_messages(
    account_email: str, since_epoch: int, query: str = "", max_results: int = 20
) -> str:
    """Messages received after ``since_epoch`` (seconds), optionally narrowed by a Gmail query."""
    full_query = f"after:{int(since_epoch)} {query}".strip()
    return search_emails(account_email, query=full_query, max_results=max_results)
```

Check the existing `search_emails` calls `messages().list(userId="me", q=..., maxResults=...)` and then `messages().get(...)` per id; the test's `FakeMessages` mirrors that. If `search_emails` uses different keyword names, adjust the fake's method signatures to match — not the production code.

`src/connectors/gmail.py`:
```python
"""Gmail: search, read, send, reply in thread, and list what arrived since a time.

Connections are made by Google sign-in (OAuth), not a pasted token; the
connection's account label is the mailbox address the actions use.
"""

from __future__ import annotations

import json
from typing import Any

from src.connectors.base import Action, AuthSpec, Connector, ConnectorContext, ConnectorError, Param
from src.tools import gmail_tool


def _mailbox(ctx: ConnectorContext) -> str:
    if not ctx.secrets.account_label:
        raise ConnectorError("This Gmail connection has no mailbox address; reconnect it.")
    return ctx.secrets.account_label


def _parsed(text: str) -> Any:
    try:
        result = json.loads(text)
    except ValueError:
        return text
    if isinstance(result, dict) and result.get("error"):
        raise ConnectorError(str(result["error"]))
    return result


def search_emails(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(gmail_tool.search_emails(_mailbox(ctx), query=args["query"], max_results=args.get("max_results", 10)))


def read_email(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(gmail_tool.read_email(_mailbox(ctx), message_id=args["message_id"]))


def list_new_messages(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.list_new_messages(
            _mailbox(ctx),
            since_epoch=args["since_epoch"],
            query=args.get("query", ""),
            max_results=args.get("max_results", 20),
        )
    )


def send_email(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.send_email(
            _mailbox(ctx),
            to=args["to"],
            subject=args["subject"],
            body=args["body"],
            cc=args.get("cc", ""),
            bcc=args.get("bcc", ""),
        )
    )


def reply_to_thread(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.reply_to_thread(_mailbox(ctx), message_id=args["message_id"], body=args["body"], cc=args.get("cc", ""))
    )


CONNECTOR = Connector(
    id="gmail",
    name="Gmail",
    icon="gmail",
    description="Search, read, send and reply to email from a connected Google account",
    auth=AuthSpec(kind="oauth", oauth_start="/api/v1/integrations/gmail/auth-url"),
    actions=(
        Action("search_emails", "Search mail", "read", "Search the mailbox with Gmail query syntax, e.g. 'from:alice is:unread newer_than:7d'.", (Param("query", "string", "Gmail search query"), Param("max_results", "integer", "Most messages to return", required=False, default=10)), search_emails),
        Action("read_email", "Read a message", "read", "One message in full, by the id a search returned.", (Param("message_id", "string", "Gmail message id"),), read_email),
        Action("list_new_messages", "List new mail", "read", "Messages received after a time (seconds since 1970), optionally filtered by a Gmail query.", (Param("since_epoch", "integer", "Only mail after this Unix time"), Param("query", "string", "Extra Gmail query, e.g. 'label:support'", required=False, default=""), Param("max_results", "integer", "Most messages to return", required=False, default=20)), list_new_messages),
        Action("send_email", "Send mail", "write", "Send a new email. 'to', 'cc' and 'bcc' take comma-separated addresses.", (Param("to", "string", "Recipients"), Param("subject", "string", "Subject"), Param("body", "string", "Plain-text body"), Param("cc", "string", "Cc", required=False, default=""), Param("bcc", "string", "Bcc", required=False, default="")), send_email),
        Action("reply_to_thread", "Reply in thread", "write", "Reply to a message in its own thread, to its sender.", (Param("message_id", "string", "The message to reply to"), Param("body", "string", "Plain-text reply"), Param("cc", "string", "Cc", required=False, default="")), reply_to_thread),
    ),
)
```

`src/connectors/registry.py`:
```python
"""The connectors this installation offers, in the order the Studio shows them."""

from __future__ import annotations

import importlib
from functools import cache

from src.connectors.base import Connector

_BUILTIN = ("jira", "gitlab", "gmail")


@cache
def _load() -> dict[str, Connector]:
    loaded: dict[str, Connector] = {}
    for module_name in _BUILTIN:
        connector: Connector = importlib.import_module(f"src.connectors.{module_name}").CONNECTOR
        loaded[connector.id] = connector
    return loaded


def all_connectors() -> list[Connector]:
    return list(_load().values())


def connector_ids() -> list[str]:
    return list(_load())


def get_connector(connector_id: str) -> Connector | None:
    return _load().get(connector_id)
```

Run `ruff format src/connectors src/tools/gmail_tool.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/ tests -k gmail && mypy src/connectors src/tools/gmail_tool.py`
Expected: PASS (including existing Gmail tests), Success.

- [ ] **Step 5: Commit**

```bash
git add src/tools/gmail_tool.py src/connectors/gmail.py src/connectors/registry.py tests/unit/connectors/test_gmail.py tests/unit/connectors/test_registry.py
git commit -m "feat(connectors): Gmail as a connector, with reply in thread and new mail

Replies keep the user's thread (threadId, In-Reply-To, References) so a
resolution lands where the issue was reported. list_new_messages returns mail
after a time, the call the email trigger will poll. The registry lists Jira,
GitLab and Gmail."
```

---

### Task 5: Connections storage

**Files:**
- Modify: `src/infrastructure/database/schema.py` (`IntegrationCredential`)
- Create: `alembic/versions/c4f1a8e2b6d0_connections.py`, `src/connectors/store.py`
- Test: `tests/unit/connectors/test_store.py`, and extend `tests/unit/test_migration_target.py`'s table check is unaffected (no change needed).

**Interfaces:**
- Consumes: Task 1 (`ConnectionSecrets`), existing `get_db_manager()`, `get_global_credential_manager()`.
- Produces:
  - `@dataclass Connection(id: str, connector: str, account_label: str | None, base_url: str | None, auth_kind: str, options: dict[str, Any], created_at: str | None, last_status: str | None, last_error: str | None, last_verified_at: str | None)` with `to_dict()`.
  - `ConnectionStore()` with `list_connections(connector: str | None = None) -> list[Connection]`, `get(connection_id: str) -> Connection | None`, `create(*, connector: str, base_url: str | None, username: str | None, token: str, account_label: str, options: dict[str, Any]) -> Connection`, `secrets(connection_id: str) -> ConnectionSecrets | None`, `record_test(connection_id: str, *, ok: bool, error: str | None = None, account_label: str | None = None) -> None`, `delete(connection_id: str) -> bool`.
  - Gmail rows (written by the existing OAuth callback, `provider="gmail"`) appear as connections with `auth_kind="oauth"` and `account_label=account_email`; `secrets()` for them returns `token=""`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_store.py`:
```python
"""Connections persist encrypted, list without secrets, and include Gmail accounts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.connectors.store import ConnectionStore
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential


@pytest.fixture(autouse=True)
def empty_table() -> Iterator[None]:
    with get_db_manager().get_session() as session:
        session.query(IntegrationCredential).delete()
    yield


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import src.infrastructure.secrets as secrets_module

    for name in ("_global_credential_manager", "_credential_manager", "_secret_manager"):
        if hasattr(secrets_module, name):
            monkeypatch.setattr(secrets_module, name, None)


def make(store: ConnectionStore, **overrides: object) -> str:
    data: dict[str, object] = {
        "connector": "gitlab",
        "base_url": "https://gitlab.test",
        "username": None,
        "token": "glpat-secret",
        "account_label": "alice",
        "options": {},
    }
    data.update(overrides)
    return store.create(**data).id  # type: ignore[arg-type]


def test_a_connection_round_trips_and_its_token_is_encrypted() -> None:
    store = ConnectionStore()
    connection_id = make(store, username="ops@acme.test", options={"api_version": "3"}, connector="jira")
    listed = store.list_connections()
    assert [c.connector for c in listed] == ["jira"]
    assert "token" not in listed[0].to_dict()
    secrets = store.secrets(connection_id)
    assert secrets is not None
    assert (secrets.token, secrets.username, secrets.options) == ("glpat-secret", "ops@acme.test", {"api_version": "3"})
    with get_db_manager().get_session() as session:
        row = session.query(IntegrationCredential).one()
        assert "glpat-secret" not in row.encrypted_token


def test_list_filters_by_connector() -> None:
    store = ConnectionStore()
    make(store)
    make(store, connector="jira")
    assert [c.connector for c in store.list_connections("jira")] == ["jira"]


def test_gmail_accounts_show_up_as_oauth_connections() -> None:
    with get_db_manager().get_session() as session:
        session.add(IntegrationCredential(provider="gmail", account_email="ops@acme.test", encrypted_token="x", scopes=[]))
    connection = ConnectionStore().list_connections("gmail")[0]
    assert (connection.auth_kind, connection.account_label) == ("oauth", "ops@acme.test")
    secrets = ConnectionStore().secrets(connection.id)
    assert secrets is not None and secrets.account_label == "ops@acme.test" and secrets.token == ""


def test_record_test_and_delete() -> None:
    store = ConnectionStore()
    connection_id = make(store)
    store.record_test(connection_id, ok=False, error="401")
    connection = store.get(connection_id)
    assert connection is not None and (connection.last_status, connection.last_error) == ("failed", "401")
    store.record_test(connection_id, ok=True, account_label="alice2")
    connection = store.get(connection_id)
    assert connection is not None and (connection.last_status, connection.last_error, connection.account_label) == ("ok", None, "alice2")
    assert store.delete(connection_id) is True
    assert store.get(connection_id) is None
    assert store.delete(connection_id) is False


def test_unknown_or_malformed_ids_are_none() -> None:
    store = ConnectionStore()
    assert store.get("00000000-0000-0000-0000-000000000000") is None
    assert store.get("not-a-uuid") is None
    assert store.secrets("not-a-uuid") is None
```

Before writing the store, open `src/infrastructure/secrets.py` lines 380–400 and confirm the module-level cache variable names used by `get_global_credential_manager()`; correct the tuple in the `encryption_key` fixture to the real names.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.connectors.store'`

- [ ] **Step 3: Write the implementation**

In `src/infrastructure/database/schema.py`, `class IntegrationCredential`: make `account_email` optional and add columns (keep everything else):
```python
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A connection's display name: the GitLab username, the Jira display name,
    # the Gmail address. account_email stays for Gmail rows.
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="oauth")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```
Then run `mypy src` and fix any Gmail code that now sees `account_email: str | None` (e.g. `str(row.account_email or "")` where it builds responses).

`alembic/versions/c4f1a8e2b6d0_connections.py`:
```python
"""integration_credentials become connections

Revision ID: c4f1a8e2b6d0
Revises: b7e4c2d91f03
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a8e2b6d0'
down_revision: Union[str, Sequence[str], None] = 'b7e4c2d91f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('integration_credentials') as batch:
        batch.alter_column('account_email', existing_type=sa.String(length=255), nullable=True)
        batch.add_column(sa.Column('account_label', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('base_url', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('auth_kind', sa.String(length=20), nullable=False, server_default='oauth'))
        batch.add_column(sa.Column('options', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('last_status', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('last_error', sa.Text(), nullable=True))
        batch.add_column(sa.Column('last_verified_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE integration_credentials SET account_label = account_email WHERE account_label IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM integration_credentials WHERE account_email IS NULL")
    with op.batch_alter_table('integration_credentials') as batch:
        batch.drop_column('last_verified_at')
        batch.drop_column('last_error')
        batch.drop_column('last_status')
        batch.drop_column('options')
        batch.drop_column('auth_kind')
        batch.drop_column('base_url')
        batch.drop_column('account_label')
        batch.alter_column('account_email', existing_type=sa.String(length=255), nullable=False)
```
Do **not** run `ruff format` over `alembic/versions` (older migrations must stay byte-identical; format only this new file if at all).

`src/connectors/store.py`:
```python
"""Connections: accounts on remote systems, stored with their secrets encrypted.

A connection is a row of integration_credentials. Token connections (Jira,
GitLab) keep {"token", "username"} Fernet-encrypted; Gmail rows come from the
Google sign-in flow and are listed here as OAuth connections. Nothing this
module returns to callers outside the runtime contains a secret.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from src.connectors.base import ConnectionSecrets
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential
from src.infrastructure.secrets import get_global_credential_manager
from src.utils.time import as_utc, utc_now_naive


@dataclass
class Connection:
    id: str
    connector: str
    account_label: str | None
    base_url: str | None
    auth_kind: str
    options: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_verified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: Any) -> str | None:
    aware = as_utc(value)
    return aware.isoformat() if aware else None


def _connection(row: IntegrationCredential) -> Connection:
    return Connection(
        id=str(row.id),
        connector=row.provider,
        account_label=row.account_label or row.account_email,
        base_url=row.base_url,
        auth_kind=row.auth_kind or "oauth",
        options=dict(row.options or {}),
        created_at=_iso(row.created_at),
        last_status=row.last_status,
        last_error=row.last_error,
        last_verified_at=_iso(row.last_verified_at),
    )


def _uuid(connection_id: str) -> UUID | None:
    try:
        return UUID(str(connection_id))
    except ValueError:
        return None


class ConnectionStore:
    def __init__(self) -> None:
        self._db = get_db_manager()

    def list_connections(self, connector: str | None = None) -> list[Connection]:
        with self._db.get_session() as session:
            query = session.query(IntegrationCredential)
            if connector:
                query = query.filter(IntegrationCredential.provider == connector)
            rows = query.order_by(IntegrationCredential.created_at).all()
            return [_connection(row) for row in rows]

    def get(self, connection_id: str) -> Connection | None:
        key = _uuid(connection_id)
        if key is None:
            return None
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            return _connection(row) if row else None

    def create(
        self,
        *,
        connector: str,
        base_url: str | None,
        username: str | None,
        token: str,
        account_label: str,
        options: dict[str, Any],
    ) -> Connection:
        encrypted = get_global_credential_manager().encrypt_credential(
            json.dumps({"token": token, "username": username})
        )
        with self._db.get_session() as session:
            row = IntegrationCredential(
                provider=connector,
                account_email=None,
                account_label=account_label,
                base_url=base_url,
                auth_kind="token",
                options=options,
                encrypted_token=encrypted,
                scopes=[],
                last_status="ok",
                last_verified_at=utc_now_naive(),
            )
            session.add(row)
            session.flush()
            return _connection(row)

    def secrets(self, connection_id: str) -> ConnectionSecrets | None:
        key = _uuid(connection_id)
        if key is None:
            return None
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return None
            label = row.account_label or row.account_email
            if (row.auth_kind or "oauth") == "oauth":
                return ConnectionSecrets(base_url=row.base_url, username=None, token="", account_label=label, options=dict(row.options or {}))
            payload = json.loads(get_global_credential_manager().decrypt_credential(row.encrypted_token))
            return ConnectionSecrets(
                base_url=row.base_url,
                username=payload.get("username"),
                token=str(payload.get("token") or ""),
                account_label=label,
                options=dict(row.options or {}),
            )

    def record_test(
        self, connection_id: str, *, ok: bool, error: str | None = None, account_label: str | None = None
    ) -> None:
        key = _uuid(connection_id)
        if key is None:
            return
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return
            row.last_status = "ok" if ok else "failed"
            row.last_error = None if ok else error
            row.last_verified_at = utc_now_naive()
            if ok and account_label:
                row.account_label = account_label

    def delete(self, connection_id: str) -> bool:
        key = _uuid(connection_id)
        if key is None:
            return False
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return False
            session.delete(row)
            return True
```

- [ ] **Step 4: Run the tests and migration check**

Run:
```bash
python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_store.py tests/unit/test_migration_target.py
D=$(mktemp -d); DATABASE_URL=sqlite:///$D/m.db python - <<'EOF'
import os
from alembic.config import Config
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from src.infrastructure.database.schema import Base
url = os.environ["DATABASE_URL"]
cfg = Config("alembic.ini"); cfg.set_main_option("script_location", "alembic"); cfg.attributes["database_url"] = url
command.upgrade(cfg, "head")
with create_engine(url).connect() as c:
    print([d for d in compare_metadata(MigrationContext.configure(c), Base.metadata) if "integration_credentials" in str(d)])
command.downgrade(cfg, "b7e4c2d91f03"); command.upgrade(cfg, "head"); print("down/up ok")
EOF
```
Expected: tests PASS; the diff list prints `[]` (server defaults may appear as a `modify_default` diff — acceptable); `down/up ok`.

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/database/schema.py alembic/versions/c4f1a8e2b6d0_connections.py src/connectors/store.py tests/unit/connectors/test_store.py
git commit -m "feat(connectors): connections stored with encrypted secrets

integration_credentials gains a label, base URL, auth kind, options and the
last test's outcome. Token connections keep their token and username
Fernet-encrypted; Gmail accounts from the sign-in flow list as OAuth
connections. Nothing listed carries a secret."
```

---

### Task 6: Connections API

**Files:**
- Create: `src/api/routers/connections.py`
- Modify: `src/api/router_registry.py` (import `connections`, `app.include_router(connections.router)` after `integrations`)
- Test: `tests/integration/test_connections_api.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces (HTTP, all under `/api/v1/integrations`):
  - `GET /connectors` → `{"connectors": [catalogue_entry, ...]}`
  - `GET /connections?connector=` → `{"connections": [Connection.to_dict(), ...]}`
  - `POST /connections` body `{"connector", "base_url"?, "username"?, "token", "options"?}` → `201` Connection dict; `400` with the verifier's message; `404` unknown connector.
  - `POST /connections/{id}/test` → `{"ok": bool, "account_label": str | None, "error": str | None}`
  - `DELETE /connections/{id}` → `204` / `404`
  - `POST /connections/{id}/actions/{action_id}` body `{"args": {}, "options": {}}` → `{"result": ...}`; `400` ConnectorError message; `404` unknown connection/action.
  - Module function `normalise_base_url(value: str | None, default: str | None, required: bool) -> str | None` (raises `ValueError`).

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_connections_api.py`:
```python
"""The connections API: catalogue, verified create, test, run an action, delete."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from src.connectors import http as connector_http
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import src.infrastructure.secrets as secrets_module

    for name in ("_global_credential_manager", "_credential_manager", "_secret_manager"):
        if hasattr(secrets_module, name):
            monkeypatch.setattr(secrets_module, name, None)
    with get_db_manager().get_session() as session:
        session.query(IntegrationCredential).delete()
    yield


@pytest.fixture
def fake_gitlab(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Route every connector HTTP call to a fake GitLab."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("PRIVATE-TOKEN") != "good":
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        if req.url.path == "/api/v4/user":
            return httpx.Response(200, json={"username": "alice"})
        if req.url.path.endswith("/merge_requests"):
            return httpx.Response(200, json=[{"iid": 7, "title": "Fix login", "web_url": "u"}])
        return httpx.Response(404, json={"message": "404 Not Found"})

    real_client = httpx.Client

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(connector_http.httpx, "Client", client)
    return seen


async def create(client: AsyncClient, **body: Any) -> httpx.Response:
    payload = {"connector": "gitlab", "base_url": "https://gitlab.test", "token": "good", **body}
    return await client.post("/api/v1/integrations/connections", json=payload)


async def test_catalogue_lists_jira_gitlab_and_gmail(async_client: AsyncClient) -> None:
    body = (await async_client.get("/api/v1/integrations/connectors")).json()
    assert [c["id"] for c in body["connectors"]] == ["jira", "gitlab", "gmail"]
    gitlab = body["connectors"][1]
    assert gitlab["auth"]["base_url_default"] == "https://gitlab.com"
    assert {a["kind"] for a in gitlab["actions"]} == {"read", "write"}


async def test_create_verifies_and_never_returns_the_token(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    response = await create(async_client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_label"] == "alice" and body["connector"] == "gitlab"
    assert "good" not in response.text
    listed = (await async_client.get("/api/v1/integrations/connections")).json()["connections"]
    assert [c["id"] for c in listed] == [body["id"]]
    assert "good" not in str(listed)


async def test_a_rejected_token_is_not_saved(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    response = await create(async_client, token="bad")
    assert response.status_code == 400
    assert "rejected the token" in response.json()["detail"]
    assert (await async_client.get("/api/v1/integrations/connections")).json()["connections"] == []


async def test_base_url_is_normalised_and_checked(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    response = await create(async_client, base_url="https://gitlab.test/")
    assert response.json()["base_url"] == "https://gitlab.test"
    bad = await create(async_client, base_url="gitlab.test")
    assert bad.status_code == 400 and "http://" in bad.json()["detail"]
    jira_without_url = await async_client.post(
        "/api/v1/integrations/connections", json={"connector": "jira", "token": "t"}
    )
    assert jira_without_url.status_code == 400 and "Jira site URL" in jira_without_url.json()["detail"]


async def test_default_base_url_is_used_when_omitted(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    response = await create(async_client, base_url=None)
    assert response.json()["base_url"] == "https://gitlab.com"


async def test_unknown_connector_and_oauth_connector(async_client: AsyncClient) -> None:
    assert (await create(async_client, connector="nope")).status_code == 404
    gmail = await create(async_client, connector="gmail")
    assert gmail.status_code == 400 and "sign" in gmail.json()["detail"].lower()


async def test_test_endpoint_records_the_outcome(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    connection_id = (await create(async_client)).json()["id"]
    result = (await async_client.post(f"/api/v1/integrations/connections/{connection_id}/test")).json()
    assert result == {"ok": True, "account_label": "alice", "error": None}


async def test_run_action_returns_the_result_and_errors_readably(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    connection_id = (await create(async_client)).json()["id"]
    url = f"/api/v1/integrations/connections/{connection_id}/actions/list_merge_requests"
    ok = await async_client.post(url, json={"args": {}, "options": {"project": "g/a"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"][0]["title"] == "Fix login"
    missing = await async_client.post(url, json={"args": {}, "options": {}})
    assert missing.status_code == 400 and "project" in missing.json()["detail"]
    unknown = await async_client.post(f"/api/v1/integrations/connections/{connection_id}/actions/nope", json={})
    assert unknown.status_code == 404


async def test_delete(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    connection_id = (await create(async_client)).json()["id"]
    assert (await async_client.delete(f"/api/v1/integrations/connections/{connection_id}")).status_code == 204
    assert (await async_client.delete(f"/api/v1/integrations/connections/{connection_id}")).status_code == 404
    assert (await async_client.post(f"/api/v1/integrations/connections/{connection_id}/test")).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/integration/test_connections_api.py`
Expected: FAIL — 404s on `/api/v1/integrations/connectors`.

- [ ] **Step 3: Write the implementation**

`src/api/routers/connections.py`:
```python
"""Connectors and connections: the catalogue, accounts, and running one action.

The catalogue is what the Studio renders palette tiles and inspector forms
from. A connection is only saved after the connector's verifier accepted its
credentials, so a saved connection is known to have worked at least once.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.audit_logging import get_logger
from src.connectors.base import (
    ConnectionSecrets,
    ConnectorContext,
    ConnectorError,
    catalogue_entry,
    validate_args,
)
from src.connectors.registry import all_connectors, get_connector
from src.connectors.store import ConnectionStore

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class ConnectionCreate(BaseModel):
    connector: str
    base_url: str | None = None
    username: str | None = None
    token: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class ActionRun(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


def normalise_base_url(value: str | None, default: str | None, required: bool, label: str = "Base URL") -> str | None:
    """Trim a pasted URL, fall back to the default, and insist on a scheme."""
    url = (value or "").strip() or (default or "")
    if not url:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"{label} must start with http:// or https:// (got {url}).")
    return url.rstrip("/")


def _audit(action: str, resource: str, detail: dict[str, Any]) -> None:
    try:
        from src.tools.audit_trail import append_audit_entry

        append_audit_entry(action=action, category="config", resource=resource, detail=detail)
    except Exception as exc:  # noqa: BLE001 - auditing must not block the change
        logger.warning("connection_audit_failed", action=action, error=str(exc))


@router.get("/connectors")
async def list_connectors() -> dict[str, Any]:
    return {"connectors": [catalogue_entry(connector) for connector in all_connectors()]}


@router.get("/connections")
async def list_connections(connector: str | None = None) -> dict[str, Any]:
    connections = await asyncio.to_thread(ConnectionStore().list_connections, connector)
    return {"connections": [connection.to_dict() for connection in connections]}


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionCreate) -> dict[str, Any]:
    connector = get_connector(body.connector)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {body.connector}")
    if connector.auth.kind == "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"Connect {connector.name} through its sign-in button, not a pasted token.",
        )
    try:
        base_url = normalise_base_url(
            body.base_url,
            connector.auth.base_url_default,
            required=connector.auth.base_url,
            label=connector.auth.base_url_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    username = (body.username or "").strip() or None
    if connector.auth.username_required and not username:
        raise HTTPException(status_code=400, detail=f"{connector.auth.username_label} is required.")

    secrets = ConnectionSecrets(base_url=base_url, username=username, token=body.token.strip(), options=dict(body.options))
    account_label = connector.name
    options = dict(body.options)
    if connector.verify is not None:
        try:
            verified = await asyncio.to_thread(connector.verify, ConnectorContext(secrets, {}))
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        account_label = verified.account_label
        options.update(verified.options)

    connection = await asyncio.to_thread(
        ConnectionStore().create,
        connector=connector.id,
        base_url=base_url,
        username=username,
        token=secrets.token,
        account_label=account_label,
        options=options,
    )
    _audit("connection.created", f"connection:{connection.id}", {"connector": connector.id, "account": account_label})
    return connection.to_dict()


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str) -> dict[str, Any]:
    store = ConnectionStore()
    connection = await asyncio.to_thread(store.get, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    connector = get_connector(connection.connector)
    secrets = await asyncio.to_thread(store.secrets, connection_id)
    if connector is None or secrets is None or connector.verify is None:
        return {"ok": True, "account_label": connection.account_label, "error": None}
    try:
        verified = await asyncio.to_thread(connector.verify, ConnectorContext(secrets, {}))
    except ConnectorError as exc:
        await asyncio.to_thread(store.record_test, connection_id, ok=False, error=str(exc))
        return {"ok": False, "account_label": connection.account_label, "error": str(exc)}
    await asyncio.to_thread(store.record_test, connection_id, ok=True, account_label=verified.account_label)
    return {"ok": True, "account_label": verified.account_label, "error": None}


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: str) -> Response:
    if not await asyncio.to_thread(ConnectionStore().delete, connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    _audit("connection.deleted", f"connection:{connection_id}", {})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{connection_id}/actions/{action_id}")
async def run_action(connection_id: str, action_id: str, body: ActionRun | None = None) -> dict[str, Any]:
    """Run one action now, for the inspector's Test. Writes act on the real system."""
    store = ConnectionStore()
    connection = await asyncio.to_thread(store.get, connection_id)
    secrets = await asyncio.to_thread(store.secrets, connection_id) if connection else None
    connector = get_connector(connection.connector) if connection else None
    if connection is None or secrets is None or connector is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        action = connector.action(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    request_body = body or ActionRun()
    try:
        args = validate_args(connector.id, action, request_body.args)
        result = await asyncio.to_thread(action.run, ConnectorContext(secrets, request_body.options), args)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"result": result}
```

In `src/api/router_registry.py`: add `connections,` to the import list (alphabetical, after `configs,`) and `app.include_router(connections.router)` immediately after `app.include_router(integrations.router)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/integration/test_connections_api.py && mypy src`
Expected: PASS, Success.

- [ ] **Step 5: Commit**

```bash
git add src/api/routers/connections.py src/api/router_registry.py tests/integration/test_connections_api.py
git commit -m "feat(api): connector catalogue and verified connections

GET /integrations/connectors serves what the Studio renders. A connection is
saved only after its connector accepted the credentials; base URLs are
trimmed and must carry a scheme. Test re-verifies, and an action can be run
on its own for the inspector's Test. Creating and removing are audited."
```

---

### Task 7: The `connector` tool kind at run time

**Files:**
- Create: `src/connectors/tool_factory.py`
- Modify: `src/tools/runtime_tool_factories.py` (`_database_factories` → add connector), `src/config/tool_models.py` (type + validation), `src/crewai_runtime/runtime.py` (≈ line 923–934)
- Test: `tests/unit/connectors/test_tool_factory.py`

**Interfaces:**
- Consumes: Tasks 1, 4 (registry), 5 (`ConnectionStore.secrets`); `RuntimeToolFactory` base; `ExecutionEventEmitter.tool_started(tool_id, name, kwargs)` / `tool_finished(tool_id, name, result=None, error=None, duration_ms=None)`.
- Produces:
  - Tool settings shape: `{"type": "connector", "connector": str, "connection_id": str, "actions": list[str], "options": dict}`
  - `ConnectorToolFactory(tool_id, name, description, settings)` with `accepts_emitter = True`, `build(stack, emitter=None) -> list[BaseTool]`, `sandbox_function() -> Callable`.
  - Tool names: `f"{factory.name}_{action.id}"`.
  - Tool results: JSON text; on `ConnectorError` the text `{"error": "..."}`.
  - A missing connection raises `ConnectorError` from `build`, and the runtime lets it fail the run.

- [ ] **Step 1: Write the failing tests**

`tests/unit/connectors/test_tool_factory.py`:
```python
"""Connector nodes become agent tools with real schemas, events, and honest failures."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import pytest

from src.config.tool_models import ToolConfig
from src.connectors import tool_factory as tf
from src.connectors.base import ConnectionSecrets, ConnectorError
from src.tools.runtime_tool_factories import create_runtime_factory, is_factory_tool_type


class Emitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, Any]] = []

    def tool_started(self, tool_id: str, name: str, kwargs: dict[str, Any]) -> None:
        self.events.append(("start", name, kwargs))

    def tool_finished(self, tool_id: str, name: str, result: Any = None, error: str | None = None, duration_ms: int | None = None) -> None:
        self.events.append(("finish", name, error or result))


SETTINGS = {"type": "connector", "connector": "jira", "connection_id": "c1", "actions": ["search_issues", "add_comment"], "options": {"project": "OPS"}}


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        def secrets(self, connection_id: str) -> ConnectionSecrets | None:
            if connection_id != "c1":
                return None
            return ConnectionSecrets(base_url="https://acme.atlassian.net", username="a@b.c", token="t", options={"api_version": "3"})

    monkeypatch.setattr(tf, "ConnectionStore", Store)


def factory(settings: dict[str, Any] | None = None) -> Any:
    return create_runtime_factory("connector", "ops_jira", "ops_jira", "Jira for ops", settings or SETTINGS)


def test_connector_is_a_factory_type() -> None:
    assert is_factory_tool_type("connector")


def test_one_tool_per_ticked_action_with_the_action_schema(secrets: None) -> None:
    tools = factory().build(contextlib.ExitStack(), emitter=None)
    assert [t.name for t in tools] == ["ops_jira_search_issues", "ops_jira_add_comment"]
    schema = tools[0].args_schema.model_json_schema()
    assert schema["required"] == ["jql"]


def test_a_call_runs_the_action_and_emits_events(secrets: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def fake_run(ctx: Any, args: dict[str, Any]) -> Any:
        seen.append((ctx.option("project"), args))
        return [{"key": "OPS-1"}]

    from src.connectors.jira import CONNECTOR

    monkeypatch.setattr(tf, "get_connector", lambda cid: _with_action(CONNECTOR, "search_issues", fake_run))
    emitter = Emitter()
    tool = factory().build(contextlib.ExitStack(), emitter=emitter)[0]
    out = tool.run(jql="project = OPS")
    assert json.loads(out) == [{"key": "OPS-1"}]
    assert seen == [("OPS", {"jql": "project = OPS", "max_results": 20})]
    assert [e[0] for e in emitter.events] == ["start", "finish"]


def test_bad_arguments_come_back_to_the_agent_as_an_error(secrets: None) -> None:
    emitter = Emitter()
    tool = factory().build(contextlib.ExitStack(), emitter=emitter)[0]
    out = json.loads(tool._run(max_results=5))
    assert "jql" in out["error"]
    assert emitter.events[-1][0] == "finish" and "jql" in emitter.events[-1][2]


def test_missing_connection_fails_the_run_with_a_named_message(secrets: None) -> None:
    with pytest.raises(ConnectorError, match="ops_jira.*no longer exists"):
        factory({**SETTINGS, "connection_id": "gone"}).build(contextlib.ExitStack(), emitter=None)


def test_tool_config_validates_connector_settings() -> None:
    ToolConfig(id="ops_jira", name="ops_jira", description="d", settings=SETTINGS)
    with pytest.raises(ValueError, match="unknown connector"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "connector": "nope"})
    with pytest.raises(ValueError, match="connection"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "connection_id": ""})
    with pytest.raises(ValueError, match="at least one action"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "actions": []})
    with pytest.raises(ValueError, match="merge_all"):
        ToolConfig(id="x", name="x", description="d", settings={**SETTINGS, "actions": ["merge_all"]})


def _with_action(connector: Any, action_id: str, run: Any) -> Any:
    from dataclasses import replace

    actions = tuple(replace(a, run=run) if a.id == action_id else a for a in connector.actions)
    return replace(connector, actions=actions)
```

Add to the existing runtime tests file `tests/unit/test_runtime_manager_crew.py` is **not** needed; instead add this test at the end of `tests/unit/connectors/test_tool_factory.py`:
```python
def test_runtime_lets_a_connector_error_fail_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    class Broken:
        accepts_emitter = True

        def build(self, stack: Any, emitter: Any = None) -> list[Any]:
            raise ConnectorError("node 'ops_jira' uses a connection that no longer exists")

    registry = SimpleNamespace(get_tool=lambda tool_id: SimpleNamespace(factory=Broken(), tool_id=tool_id, name=tool_id))
    monkeypatch.setattr("src.crewai_runtime.runtime.get_tool_registry", lambda: registry)
    runtime = CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")
    with pytest.raises(ConnectorError, match="no longer exists"):
        runtime._get_crewai_tools(["ops_jira"], contextlib.ExitStack())
```
Before writing it, open `src/crewai_runtime/runtime.py` around line 900 and confirm the method name and positional order (`_get_crewai_tools(tool_ids, stack, run_tool_cache=None, emitter=None)` per `tests/unit/test_runtime_manager_crew.py`'s monkeypatch of `_get_crewai_tools`). Adjust the call in the test to the real signature.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/test_tool_factory.py`
Expected: FAIL — `ImportError: cannot import name 'tool_factory'`.

- [ ] **Step 3: Write the implementation**

`src/connectors/tool_factory.py`:
```python
"""A connector node at run time: one agent tool per ticked action.

Factory-built tools bypass the runtime's tool wrapper, so each tool reports
its own tool_call_start / tool_call_result events; connector calls then show
on the canvas, in the timeline and in run history like any other tool. A
failed call returns {"error": ...} to the agent so it can correct itself; a
connection that no longer exists fails the run, because an agent that silently
lost its tools gives answers nobody should trust.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from typing import Any

from crewai.tools import BaseTool

from src.connectors.base import Connector, ConnectorContext, ConnectorError, args_model, validate_args
from src.connectors.registry import get_connector
from src.connectors.store import ConnectionStore
from src.tools.runtime_tool_factories import RuntimeToolFactory


class ConnectorActionTool(BaseTool):
    """One connector action as a CrewAI tool."""

    runner: Callable[..., str]

    def _run(self, **kwargs: Any) -> str:
        return self.runner(**kwargs)


def _as_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, default=str)


class ConnectorToolFactory(RuntimeToolFactory):
    accepts_emitter = True

    def _connector(self) -> Connector:
        connector = get_connector(str(self.settings.get("connector", "")))
        if connector is None:
            raise ConnectorError(f"Tool '{self.name}' names an unknown connector '{self.settings.get('connector')}'.")
        return connector

    def _context(self, connector: Connector) -> ConnectorContext:
        connection_id = str(self.settings.get("connection_id") or "")
        secrets = ConnectionStore().secrets(connection_id) if connection_id else None
        if secrets is None:
            raise ConnectorError(
                f"The {connector.name} node '{self.name}' uses a connection that no longer exists "
                f"({connection_id or 'none chosen'}). Pick another in its inspector."
            )
        return ConnectorContext(secrets, dict(self.settings.get("options") or {}))

    def build(self, stack: contextlib.ExitStack, emitter: Any = None) -> list[Any]:
        connector = self._connector()
        ctx = self._context(connector)
        tools: list[Any] = []
        for action_id in self.settings.get("actions") or []:
            action = connector.action(str(action_id))
            tool_name = f"{self.name}_{action.id}"

            def runner(_action: Any = action, _tool_name: str = tool_name, **kwargs: Any) -> str:
                if emitter is not None:
                    emitter.tool_started(self.tool_id, _tool_name, kwargs)
                started = time.perf_counter()
                try:
                    args = validate_args(connector.id, _action, kwargs)
                    text = _as_text(_action.run(ctx, args))
                except ConnectorError as exc:
                    if emitter is not None:
                        emitter.tool_finished(self.tool_id, _tool_name, error=str(exc), duration_ms=int((time.perf_counter() - started) * 1000))
                    return json.dumps({"error": str(exc)})
                if emitter is not None:
                    emitter.tool_finished(self.tool_id, _tool_name, result=text, duration_ms=int((time.perf_counter() - started) * 1000))
                return text

            tools.append(
                ConnectorActionTool(
                    name=tool_name,
                    description=f"{connector.name}: {action.description}",
                    args_schema=args_model(connector.id, action),
                    runner=runner,
                )
            )
        return tools

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def connector_action(action: str = "", **kwargs: Any) -> Any:
            """Run one of this node's actions: pass its id as 'action' and its arguments."""
            connector = factory._connector()
            if action not in (factory.settings.get("actions") or []):
                return {"error": f"'{action}' is not ticked on this node."}
            chosen = connector.action(action)
            try:
                return chosen.run(factory._context(connector), validate_args(connector.id, chosen, kwargs))
            except ConnectorError as exc:
                return {"error": str(exc)}

        connector_action.__name__ = self.name
        return connector_action
```

In `src/tools/runtime_tool_factories.py`, replace `_database_factories`:
```python
def _database_factories() -> dict[str, type[RuntimeToolFactory]]:
    """Imported lazily: these modules import this one for the base class."""
    from src.connectors.tool_factory import ConnectorToolFactory
    from src.tools.database_factories import MongoToolFactory, SqlToolFactory

    return {"sql": SqlToolFactory, "mongodb": MongoToolFactory, "connector": ConnectorToolFactory}
```

In `src/config/tool_models.py`: change `VALID_TOOL_TYPES` to include `"connector"`; in `validate_tool_type`, add a branch `elif tool_type == "connector": self._validate_connector_settings()` alongside the others; add the method:
```python
    def _validate_connector_settings(self) -> None:
        from src.connectors.registry import connector_ids, get_connector

        name = str(self.settings.get("connector", ""))
        connector = get_connector(name)
        if connector is None:
            raise ValueError(
                f"Tool '{self.id}': unknown connector '{name}'. Known: {', '.join(connector_ids())}"
            )
        if not str(self.settings.get("connection_id") or "").strip():
            raise ValueError(
                f"Tool '{self.id}': pick a {connector.name} connection (settings.connection_id)."
            )
        actions = self.settings.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError(f"Tool '{self.id}': tick at least one {connector.name} action.")
        known = {action.id for action in connector.actions}
        unknown = [str(action) for action in actions if action not in known]
        if unknown:
            raise ValueError(
                f"Tool '{self.id}': {connector.name} has no action {', '.join(unknown)}."
            )
```

In `src/crewai_runtime/runtime.py` (the factory branch of `_get_crewai_tools`), replace
```python
                if tool_id not in cache:
                    try:
                        cache[tool_id] = factory.build(stack)
                    except Exception as e:
```
with
```python
                if tool_id not in cache:
                    try:
                        if getattr(factory, "accepts_emitter", False):
                            cache[tool_id] = factory.build(stack, emitter=emitter)
                        else:
                            cache[tool_id] = factory.build(stack)
                    except ConnectorError:
                        # A connector without its connection must fail the run,
                        # not leave the agent silently without its tools.
                        raise
                    except Exception as e:
```
and add `from src.connectors.base import ConnectorError` to the module imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider tests/unit/connectors/ && python -m pytest -q -p no:cacheprovider && mypy src`
Expected: all PASS (full suite too), Success.

- [ ] **Step 5: Commit**

```bash
git add src/connectors/tool_factory.py src/tools/runtime_tool_factories.py src/config/tool_models.py src/crewai_runtime/runtime.py tests/unit/connectors/test_tool_factory.py
git commit -m "feat(runtime): connector nodes become agent tools

A connector tool's settings name the connector, connection and ticked
actions; each action becomes a CrewAI tool with its real argument schema and
reports tool-call events like any other tool. Bad arguments return an error
the agent can act on; a missing connection fails the run with the node's
name instead of running the agent without its tools."
```

---

### Task 8: Studio — connector API client, store, palette from the catalogue

**Files:**
- Create: `workflow-editor/src/api/connectors.ts`, `workflow-editor/src/stores/connectorStore.ts`, `workflow-editor/src/utils/connectorPalette.ts`, `workflow-editor/src/utils/connectorPalette.test.ts`
- Modify: `workflow-editor/src/components/Sidebar.tsx` (Connect group), `workflow-editor/src/demo/mockApi.ts` (two empty routes)

**Interfaces:**
- Consumes: Task 6 HTTP endpoints.
- Produces (TypeScript):
  - Types `ConnectorParam`, `ConnectorAction`, `ConnectorAuth`, `ConnectorInfo`, `Connection`, `ConnectionTest`.
  - `listConnectors(): Promise<ConnectorInfo[]>`, `listConnections(): Promise<Connection[]>`, `createConnection(body): Promise<Connection>`, `testConnection(id): Promise<ConnectionTest>`, `deleteConnection(id): Promise<void>`, `runConnectorAction(connectionId, actionId, args, options): Promise<unknown>`, `apiDetail(error: unknown): string`.
  - `useConnectorStore` with `connectors`, `connections`, `loaded`, `error`, `refresh()`, `add(body)`, `remove(id)`, `test(id)`.
  - `connectorIcon(icon: string): LucideIcon`, `connectorNodeConfig(connector: ConnectorInfo): JsonObject`, `connectorTiles(connectors: ConnectorInfo[]): ConnectorTile[]`, `upgradeLegacyGmail(config: JsonObject, connections: Connection[]): JsonObject`.

- [ ] **Step 1: Write the failing test**

`workflow-editor/src/utils/connectorPalette.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { connectorNodeConfig, connectorTiles, upgradeLegacyGmail } from './connectorPalette';
import type { Connection, ConnectorInfo } from '../api/connectors';

const auth = { kind: 'token', base_url: true, base_url_default: null, base_url_label: 'URL', username_label: null, username_required: false, token_label: 'Token', token_help: '', oauth_start: null } as const;

const jira: ConnectorInfo = {
    id: 'jira', name: 'Jira', icon: 'jira', description: 'Issues', auth, options: [],
    actions: [
        { id: 'search_issues', name: 'Search', kind: 'read', description: '', params: [] },
        { id: 'add_comment', name: 'Comment', kind: 'write', description: '', params: [] },
    ],
};

describe('connector palette', () => {
    it('ticks read actions only on a new node', () => {
        expect(connectorNodeConfig(jira)).toEqual({ type: 'connector', connector: 'jira', connection_id: '', actions: ['search_issues'], options: {} });
    });

    it('makes one tool tile per connector', () => {
        const [tile] = connectorTiles([jira]);
        expect(tile.label).toBe('Jira');
        expect(tile.type).toBe('tool');
        expect(tile.tone).toBe('connect');
        expect(tile.config.connector).toBe('jira');
        expect(tile.icon).toBeTruthy();
    });

    it('upgrades a legacy Gmail node onto its connection', () => {
        const connections: Connection[] = [{ id: 'c9', connector: 'gmail', account_label: 'ops@acme.test', base_url: null, auth_kind: 'oauth', options: {}, created_at: null, last_status: null, last_error: null, last_verified_at: null }];
        expect(upgradeLegacyGmail({ type: 'gmail', account_email: 'ops@acme.test', capabilities: ['send', 'read'], name: 'mail' }, connections)).toEqual({
            type: 'connector', connector: 'gmail', connection_id: 'c9', actions: ['send_email', 'read_email'], options: {}, name: 'mail',
        });
        expect(upgradeLegacyGmail({ type: 'gmail', account_email: 'other@acme.test' }, connections).connection_id).toBe('');
        expect(upgradeLegacyGmail({ type: 'gmail' }, []).actions).toEqual(['send_email', 'search_emails', 'read_email']);
    });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (in `workflow-editor/`): `npx vitest run src/utils/connectorPalette.test.ts`
Expected: FAIL — cannot resolve `./connectorPalette`.

- [ ] **Step 3: Write the implementation**

`workflow-editor/src/api/connectors.ts`:
```ts
import { api } from './client';
import type { JsonObject } from '../types/json';

export interface ConnectorParam {
    name: string;
    type: 'string' | 'integer' | 'boolean' | 'array' | 'object';
    description: string;
    required: boolean;
    default: unknown;
    enum: string[] | null;
}

export interface ConnectorAction {
    id: string;
    name: string;
    kind: 'read' | 'write';
    description: string;
    params: ConnectorParam[];
}

export interface ConnectorAuth {
    kind: 'token' | 'oauth';
    base_url: boolean;
    base_url_default: string | null;
    base_url_label: string;
    username_label: string | null;
    username_required: boolean;
    token_label: string;
    token_help: string;
    oauth_start: string | null;
}

export interface ConnectorInfo {
    id: string;
    name: string;
    icon: string;
    description: string;
    auth: ConnectorAuth;
    options: Array<{ key: string; label: string; help: string }>;
    actions: ConnectorAction[];
}

export interface Connection {
    id: string;
    connector: string;
    account_label: string | null;
    base_url: string | null;
    auth_kind: string;
    options: JsonObject;
    created_at: string | null;
    last_status: 'ok' | 'failed' | null;
    last_error: string | null;
    last_verified_at: string | null;
}

export interface ConnectionTest {
    ok: boolean;
    account_label: string | null;
    error: string | null;
}

export interface ConnectionCreate {
    connector: string;
    base_url?: string;
    username?: string;
    token: string;
    options?: JsonObject;
}

const BASE = '/api/v1/integrations';

/** The API's `detail` out of a thrown `api()` error, or the error's own message. */
export const apiDetail = (error: unknown): string => {
    const message = error instanceof Error ? error.message : String(error);
    const match = /^API \d+: ([\s\S]*)$/.exec(message);
    if (!match) return message;
    try {
        const body = JSON.parse(match[1]) as { detail?: unknown };
        return typeof body.detail === 'string' ? body.detail : match[1];
    } catch {
        return match[1];
    }
};

export const listConnectors = async () => (await api<{ connectors: ConnectorInfo[] }>(`${BASE}/connectors`)).connectors;

export const listConnections = async () => (await api<{ connections: Connection[] }>(`${BASE}/connections`)).connections;

export const createConnection = (body: ConnectionCreate) =>
    api<Connection>(`${BASE}/connections`, { method: 'POST', body: JSON.stringify(body) });

export const testConnection = (id: string) =>
    api<ConnectionTest>(`${BASE}/connections/${encodeURIComponent(id)}/test`, { method: 'POST' });

export const deleteConnection = (id: string) =>
    api<void>(`${BASE}/connections/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const runConnectorAction = async (connectionId: string, actionId: string, args: JsonObject, options: JsonObject) =>
    (await api<{ result: unknown }>(
        `${BASE}/connections/${encodeURIComponent(connectionId)}/actions/${encodeURIComponent(actionId)}`,
        { method: 'POST', body: JSON.stringify({ args, options }) },
    )).result;
```

`workflow-editor/src/stores/connectorStore.ts`:
```ts
import { create } from 'zustand';
import {
    apiDetail, createConnection, deleteConnection, listConnections, listConnectors, testConnection,
} from '../api/connectors';
import type { Connection, ConnectionCreate, ConnectionTest, ConnectorInfo } from '../api/connectors';

interface ConnectorState {
    connectors: ConnectorInfo[];
    connections: Connection[];
    loaded: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    add: (body: ConnectionCreate) => Promise<Connection>;
    remove: (id: string) => Promise<void>;
    test: (id: string) => Promise<ConnectionTest>;
}

/** The connector catalogue and this installation's connections, shared by the palette, inspector and Connections page. */
export const useConnectorStore = create<ConnectorState>((set, get) => ({
    connectors: [],
    connections: [],
    loaded: false,
    error: null,

    refresh: async () => {
        try {
            const [connectors, connections] = await Promise.all([listConnectors(), listConnections()]);
            set({ connectors, connections, loaded: true, error: null });
        } catch (error) {
            set({ loaded: true, error: apiDetail(error) });
        }
    },

    add: async (body) => {
        const connection = await createConnection(body);
        set({ connections: [...get().connections, connection] });
        return connection;
    },

    remove: async (id) => {
        await deleteConnection(id);
        set({ connections: get().connections.filter((connection) => connection.id !== id) });
    },

    test: async (id) => {
        const result = await testConnection(id);
        await get().refresh();
        return result;
    },
}));
```

`workflow-editor/src/utils/connectorPalette.ts`:
```ts
import type { LucideIcon } from 'lucide-react';
import { GitMerge, Mail, Plug, SquareKanban } from 'lucide-react';
import type { Connection, ConnectorInfo } from '../api/connectors';
import type { JsonObject } from '../types/json';

// lucide ships no brand marks, so each connector gets a generic glyph that reads as its job.
const ICONS: Record<string, LucideIcon> = { gitlab: GitMerge, jira: SquareKanban, gmail: Mail };

export const connectorIcon = (icon: string): LucideIcon => ICONS[icon] ?? Plug;

/** A freshly dropped connector node: no connection yet, read actions ticked, writes off. */
export const connectorNodeConfig = (connector: ConnectorInfo): JsonObject => ({
    type: 'connector',
    connector: connector.id,
    connection_id: '',
    actions: connector.actions.filter((action) => action.kind === 'read').map((action) => action.id),
    options: {},
});

export interface ConnectorTile {
    type: 'tool';
    label: string;
    icon: LucideIcon;
    tone: 'connect';
    hint: string;
    config: JsonObject;
}

export const connectorTiles = (connectors: ConnectorInfo[]): ConnectorTile[] =>
    connectors.map((connector) => ({
        type: 'tool',
        label: connector.name,
        icon: connectorIcon(connector.icon),
        tone: 'connect',
        hint: connector.description,
        config: connectorNodeConfig(connector),
    }));

const GMAIL_ACTIONS: Record<string, string> = { send: 'send_email', search: 'search_emails', read: 'read_email' };

/** A node saved with the old Gmail tool shape, as a Gmail connector node on the same account. */
export const upgradeLegacyGmail = (config: JsonObject, connections: Connection[]): JsonObject => {
    const capabilities: string[] = Array.isArray(config.capabilities) && config.capabilities.length
        ? config.capabilities
        : ['send', 'search', 'read'];
    const match = connections.find((connection) => connection.connector === 'gmail' && connection.account_label === config.account_email);
    const upgraded: JsonObject = {
        type: 'connector',
        connector: 'gmail',
        connection_id: match?.id ?? '',
        actions: capabilities.map((capability) => GMAIL_ACTIONS[capability]).filter(Boolean),
        options: {},
    };
    if (config.name) upgraded.name = config.name;
    return upgraded;
};
```
If `SquareKanban` is not exported by the installed lucide version, use `KanbanSquare`; check with `grep -c "SquareKanban" node_modules/lucide-react/dist/lucide-react.d.ts`.

`workflow-editor/src/components/Sidebar.tsx`:
1. In `PALETTE_GROUPS`, remove the Gmail item from the `integrations` group (keep MCP server). Remove `Mail` from the lucide import if now unused.
2. Inside the component, before `visibleGroups`, add:
```tsx
    const connectors = useConnectorStore((state) => state.connectors);
    const connectorsLoaded = useConnectorStore((state) => state.loaded);
    const refreshConnectors = useConnectorStore((state) => state.refresh);
    useEffect(() => {
        if (!connectorsLoaded) void refreshConnectors();
    }, [connectorsLoaded, refreshConnectors]);

    // The Connect group is MCP plus one tile per connector the server offers,
    // so a connector added on the server appears without a Studio release.
    const paletteGroups = useMemo<PaletteGroup[]>(
        () => PALETTE_GROUPS.map((group) => (
            group.id === 'integrations' ? { ...group, items: [...group.items, ...connectorTiles(connectors)] } : group
        )),
        [connectors],
    );
```
3. Replace both uses of `PALETTE_GROUPS` inside `visibleGroups` with `paletteGroups`, and add `paletteGroups` to its dependency list.
4. Imports: `import { useConnectorStore } from '../stores/connectorStore';` and `import { connectorTiles } from '../utils/connectorPalette';`.

`workflow-editor/src/demo/mockApi.ts`: in `routes`, before `// ---- sessions / chat ----`, add
```ts
    // ---- connectors (the demo offers none; the palette shows MCP only) ----
    ['GET', /^\/integrations\/connectors$/, () => json({ connectors: [] })],
    ['GET', /^\/integrations\/connections$/, () => json({ connections: [] })],
```

- [ ] **Step 4: Run tests and checks**

Run (in `workflow-editor/`): `npx vitest run && npx tsc -b --noEmit && npx eslint src --max-warnings 0`
Expected: all pass, no output from tsc/eslint.

- [ ] **Step 5: Commit**

```bash
git add workflow-editor/src/api/connectors.ts workflow-editor/src/stores/connectorStore.ts workflow-editor/src/utils/connectorPalette.ts workflow-editor/src/utils/connectorPalette.test.ts workflow-editor/src/components/Sidebar.tsx workflow-editor/src/demo/mockApi.ts
git commit -m "feat(studio): connector tiles come from the server's catalogue

The Connect group is MCP plus a tile per connector the API offers; a dropped
connector node starts with its read actions ticked and its writes off. The
old Gmail tile is gone; Gmail is a connector like the others."
```

---

### Task 9: Studio — Connections page and the Add connection sheet

**Files:**
- Create: `workflow-editor/src/components/connections/AddConnectionSheet.tsx`, `workflow-editor/src/components/ConnectionsPage.tsx`
- Modify: `workflow-editor/src/stores/uiStore.ts` (`Screen` gains `'connections'`), `workflow-editor/src/App.tsx` (route), `workflow-editor/src/components/shell/AppSidebar.tsx` (Library place)

**Interfaces:**
- Consumes: Task 8 (`useConnectorStore`, `apiDetail`, types); existing `api` client, `Toolbar`, `MoreMenu`, `ActivityCapsule`, `StatusGlyph`, CSS classes `.sheet`, `.sheet-backdrop`, `.page`, `.split-layout`, `.table-box`, `.mtable`, `.inspector`, `.rows`, `.input`, `.select`, `.field-label`.
- Produces: `<AddConnectionSheet open connectorId? onClose onAdded? />` (exported, used again in Task 10); `<ConnectionsPage />`.

- [ ] **Step 1: Write the sheet**

`workflow-editor/src/components/connections/AddConnectionSheet.tsx`:
```tsx
import { useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { api } from '../../api/client';
import { apiDetail } from '../../api/connectors';
import type { Connection } from '../../api/connectors';
import { useConnectorStore } from '../../stores/connectorStore';

const POLL_MS = 2000;
const POLL_LIMIT = 60;

/**
 * Add a connection: pick a connector, fill in what it asks for, and the server
 * verifies the credentials before saving. OAuth connectors (Gmail) open their
 * sign-in in a new window instead and the sheet waits for the account to appear.
 */
export const AddConnectionSheet = ({
    open, connectorId, onClose, onAdded,
}: { open: boolean; connectorId?: string; onClose: () => void; onAdded?: (connection: Connection) => void }) => {
    const { connectors, connections, add, refresh } = useConnectorStore();
    const [chosen, setChosen] = useState(connectorId ?? '');
    const [baseUrl, setBaseUrl] = useState('');
    const [username, setUsername] = useState('');
    const [token, setToken] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    if (!open) return null;
    const connector = connectors.find((item) => item.id === (chosen || connectors[0]?.id));

    const save = async () => {
        if (!connector) return;
        setBusy(true);
        setError(null);
        try {
            const connection = await add({
                connector: connector.id,
                base_url: baseUrl.trim() || undefined,
                username: username.trim() || undefined,
                token: token.trim(),
            });
            setToken('');
            onAdded?.(connection);
            onClose();
        } catch (failure) {
            setError(apiDetail(failure));
        } finally {
            setBusy(false);
        }
    };

    const signIn = async () => {
        if (!connector?.auth.oauth_start) return;
        setBusy(true);
        setError(null);
        const before = new Set(connections.filter((item) => item.connector === connector.id).map((item) => item.id));
        try {
            const { auth_url: authUrl } = await api<{ auth_url: string }>(connector.auth.oauth_start);
            window.open(authUrl, '_blank', 'noopener,width=520,height=680');
            for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
                await new Promise((resolve) => setTimeout(resolve, POLL_MS));
                await refresh();
                const added = useConnectorStore.getState().connections.find((item) => item.connector === connector.id && !before.has(item.id));
                if (added) {
                    onAdded?.(added);
                    onClose();
                    return;
                }
            }
            setError('No account appeared. Finish the sign-in in the window that opened, then try again.');
        } catch (failure) {
            setError(apiDetail(failure));
        } finally {
            setBusy(false);
        }
    };

    return (
        <>
            <div className="sheet-backdrop" onClick={onClose} aria-hidden="true" />
            <div className="sheet" role="dialog" aria-label="Add a connection">
                <div className="flex items-center gap-2">
                    <h2 className="title-2 flex-1">Add a connection</h2>
                    <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><X size={14} /></button>
                </div>
                <label className="flex flex-col gap-1">
                    <span className="field-label">Connector</span>
                    <select className="select" value={connector?.id ?? ''} onChange={(event) => { setChosen(event.target.value); setError(null); }} aria-label="Connector">
                        {connectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                </label>
                {connector && <p className="hint">{connector.description}</p>}
                {connector?.auth.kind === 'oauth' ? (
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void signIn()}>
                        <ExternalLink size={13} /> {busy ? 'Waiting for sign-in…' : `Sign in to ${connector.name}`}
                    </button>
                ) : connector && (
                    <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void save(); }}>
                        {connector.auth.base_url && (
                            <label className="flex flex-col gap-1">
                                <span className="field-label">{connector.auth.base_url_label}</span>
                                <input className="input" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder={connector.auth.base_url_default ?? 'https://'} aria-label={connector.auth.base_url_label} />
                            </label>
                        )}
                        {connector.auth.username_label && (
                            <label className="flex flex-col gap-1">
                                <span className="field-label">{connector.auth.username_label}</span>
                                <input className="input" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" aria-label={connector.auth.username_label} />
                            </label>
                        )}
                        <label className="flex flex-col gap-1">
                            <span className="field-label">{connector.auth.token_label}</span>
                            <input className="input" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" aria-label={connector.auth.token_label} />
                            {connector.auth.token_help && <span className="hint">{connector.auth.token_help}</span>}
                        </label>
                        <button type="submit" className="btn btn-primary" disabled={busy || !token.trim()}>
                            {busy ? 'Checking…' : 'Connect'}
                        </button>
                    </form>
                )}
                {error && <p className="text-[12.5px]" role="alert" style={{ color: 'var(--clay)' }}>{error}</p>}
            </div>
        </>
    );
};
```

- [ ] **Step 2: Write the page**

`workflow-editor/src/components/ConnectionsPage.tsx`:
```tsx
import { useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { Toolbar, MoreMenu } from './shell/Toolbar';
import { ActivityCapsule } from './shell/ActivityCapsule';
import { StatusGlyph } from './shell/StatusGlyph';
import { AddConnectionSheet } from './connections/AddConnectionSheet';
import { useUiStore } from '../stores/uiStore';
import { useConnectorStore } from '../stores/connectorStore';
import { apiDetail } from '../api/connectors';
import type { ConnectionTest } from '../api/connectors';

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—');

/** The accounts this installation can act as: add, check and remove them. */
export const ConnectionsPage = () => {
    const go = useUiStore((state) => state.go);
    const { connectors, connections, loaded, error, refresh, remove, test } = useConnectorStore();
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [adding, setAdding] = useState(false);
    const [testResult, setTestResult] = useState<{ id: string; result: ConnectionTest } | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    const selected = connections.find((connection) => connection.id === selectedId) ?? connections[0];
    const nameOf = (id: string) => connectors.find((connector) => connector.id === id)?.name ?? id;
    const shownTest = testResult && selected && testResult.id === selected.id ? testResult.result : null;

    const runTest = async (id: string) => {
        setActionError(null);
        try {
            setTestResult({ id, result: await test(id) });
        } catch (failure) {
            setActionError(apiDetail(failure));
        }
    };

    const removeSelected = async () => {
        if (!selected) return;
        if (!confirm(`Remove the ${nameOf(selected.connector)} connection ${selected.account_label ?? ''}? Workflows using it will stop until you pick another.`)) return;
        setActionError(null);
        try {
            await remove(selected.id);
            setSelectedId(null);
        } catch (failure) {
            setActionError(apiDetail(failure));
        }
    };

    return (
        <>
            <div className="page">
                <div className="page-inner">
                    <div className="page-head">
                        <div>
                            <h1 className="display">Connections</h1>
                            <p className="lead mt-1 max-w-[680px]">
                                Accounts your workflows act as in Jira, GitLab and Gmail. Connect one once; every connector node can use it.
                                Tokens are checked before they are saved and stored encrypted.
                            </p>
                        </div>
                        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
                            <Plus size={13} /> Add connection
                        </button>
                    </div>

                    {error && <p className="mt-4 text-[12.5px]" role="alert" style={{ color: 'var(--clay)' }}>Could not load connections: {error}</p>}

                    {loaded && connections.length === 0 && !error && (
                        <div className="panel empty-state mt-5">
                            <div className="headline">No connections yet</div>
                            <p className="hint max-w-[380px]">Add a Jira or GitLab token, or sign in to Gmail, and connector nodes can use it.</p>
                            <button type="button" className="btn mt-2" onClick={() => setAdding(true)}>Add connection</button>
                        </div>
                    )}

                    {connections.length > 0 && (
                        <div className="split-layout">
                            <div className="table-box">
                                <table className="mtable" aria-label="Connections">
                                    <thead><tr><th>Account</th><th>Connector</th><th className="hide-narrow">Added</th><th>Status</th></tr></thead>
                                    <tbody>
                                        {connections.map((connection) => (
                                            <tr key={connection.id} aria-selected={connection.id === selected?.id} onClick={() => setSelectedId(connection.id)}>
                                                <td style={{ maxWidth: 0, width: '40%' }}>
                                                    <button type="button" className="row-title" onFocus={() => setSelectedId(connection.id)}>{connection.account_label ?? nameOf(connection.connector)}</button>
                                                    {connection.base_url && <span className="row-sub mono">{connection.base_url}</span>}
                                                </td>
                                                <td>{nameOf(connection.connector)}</td>
                                                <td className="hide-narrow">{when(connection.created_at)}</td>
                                                <td>
                                                    <span className="row-status">
                                                        <StatusGlyph shape={connection.last_status === 'failed' ? 'bad' : connection.last_status === 'ok' ? 'ok' : 'idle'} />
                                                        {connection.last_status === 'failed' ? 'Failing' : connection.last_status === 'ok' ? 'Working' : 'Not checked'}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            {selected && (
                                <aside className="inspector" aria-label="Connection details">
                                    <div>
                                        <h2 className="title-2">{selected.account_label ?? nameOf(selected.connector)}</h2>
                                        <div className="text-dim mt-0.5">{nameOf(selected.connector)}</div>
                                    </div>
                                    <div className="rows">
                                        {selected.base_url && <div><span className="row-k">Site</span><span className="row-v mono">{selected.base_url}</span></div>}
                                        <div><span className="row-k">Sign-in</span><span className="row-v">{selected.auth_kind === 'oauth' ? 'Google sign-in' : 'Token'}</span></div>
                                        <div><span className="row-k">Added</span><span className="row-v">{when(selected.created_at)}</span></div>
                                        <div><span className="row-k">Last checked</span><span className="row-v">{when(selected.last_verified_at)}</span></div>
                                    </div>
                                    {selected.last_error && <p className="text-[12px]" style={{ color: 'var(--clay)' }}>{selected.last_error}</p>}
                                    {shownTest && (
                                        <p className="text-[12.5px]" role="status" style={{ color: shownTest.ok ? 'var(--ok, inherit)' : 'var(--clay)' }}>
                                            {shownTest.ok ? `Working — signed in as ${shownTest.account_label}` : shownTest.error}
                                        </p>
                                    )}
                                    {actionError && <p className="text-[12px]" role="alert" style={{ color: 'var(--clay)' }}>{actionError}</p>}
                                    <div className="flex items-center gap-1.5">
                                        <button type="button" className="btn btn-sm" onClick={() => void runTest(selected.id)}>Test</button>
                                        <span className="flex-1" />
                                        <button type="button" className="btn btn-danger btn-sm" onClick={() => void removeSelected()}>Remove</button>
                                    </div>
                                </aside>
                            )}
                        </div>
                    )}
                </div>
            </div>
            <AddConnectionSheet open={adding} onClose={() => setAdding(false)} onAdded={(connection) => setSelectedId(connection.id)} />
            <Toolbar
                center={<ActivityCapsule onStatusClick={() => go('studio')} />}
                actions={
                    <>
                        <button type="button" className="btn btn-toolbar btn-icon" onClick={() => void refresh()} aria-label="Refresh" title="Refresh">
                            <RefreshCw size={15} strokeWidth={1.8} />
                        </button>
                        <MoreMenu />
                    </>
                }
            />
        </>
    );
};
```
Note: `useEffect(() => { void refresh(); }, [refresh])` calls a Zustand action, not a `useState` setter, so the set-state-in-effect rule does not apply. If eslint flags it anyway, move the call into the store as `refresh` already does and keep the effect; do not add `// eslint-disable`.

- [ ] **Step 3: Wire the place**

- `uiStore.ts`: `export type Screen = 'landing' | 'studio' | 'tester' | 'deploy' | 'runs' | 'connections' | 'library';`
- `App.tsx`: import `ConnectionsPage` and render `{screen === 'connections' && <ConnectionsPage />}` after the `runs` line.
- `AppSidebar.tsx`: import `Plug` from lucide; in the `Library` group, after `providers`, add
  `{ id: 'connections', label: 'Connections', icon: Plug, hue: 'var(--hue-2)', screen: 'connections', count: connections.length || undefined },`
  with `const connections = useConnectorStore((state) => state.connections);` near the other store reads (import `useConnectorStore`).

- [ ] **Step 4: Check**

Run (in `workflow-editor/`): `npx tsc -b --noEmit && npx eslint src --max-warnings 0 && npx vitest run`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add workflow-editor/src/components/connections/AddConnectionSheet.tsx workflow-editor/src/components/ConnectionsPage.tsx workflow-editor/src/stores/uiStore.ts workflow-editor/src/App.tsx workflow-editor/src/components/shell/AppSidebar.tsx
git commit -m "feat(studio): a Connections page to add, check and remove accounts

Pick a connector and paste what it asks for; the server checks the token
before saving. Gmail opens Google sign-in and the sheet waits for the
account to arrive. Each connection shows whether its last check worked."
```

---

### Task 10: Studio — the connector inspector form, and Gmail moved onto it

**Files:**
- Create: `workflow-editor/src/components/inspector/ConnectorForm.tsx`
- Modify: `workflow-editor/src/components/PropertiesPanel.tsx`

**Interfaces:**
- Consumes: Tasks 8–9 (`useConnectorStore`, `runConnectorAction`, `apiDetail`, `AddConnectionSheet`, `upgradeLegacyGmail`); PropertiesPanel's `updateConfig(key, value)` and `updateNodeData` (confirm names at lines ~60–120 before editing).
- Produces: `<ConnectorForm config={config} onChange={(key, value) => void} />`.

- [ ] **Step 1: Write the form**

`workflow-editor/src/components/inspector/ConnectorForm.tsx`:
```tsx
import { useState } from 'react';
import { Play, Plus } from 'lucide-react';
import { apiDetail, runConnectorAction } from '../../api/connectors';
import type { ConnectorAction, ConnectorParam } from '../../api/connectors';
import { useConnectorStore } from '../../stores/connectorStore';
import { AddConnectionSheet } from '../connections/AddConnectionSheet';
import type { JsonObject } from '../../types/json';

type Values = Record<string, string | boolean>;

const parseArg = (param: ConnectorParam, raw: string | boolean): unknown => {
    if (param.type === 'boolean') return Boolean(raw);
    const text = String(raw).trim();
    if (text === '') return undefined;
    if (param.type === 'integer') return Number(text);
    if (param.type === 'array') return text.split(',').map((item) => item.trim()).filter(Boolean);
    if (param.type === 'object') return JSON.parse(text);
    return text;
};

/**
 * A connector node: which account it acts as, its defaults, the actions its
 * agent may call, and a Test that runs one action for real.
 */
export const ConnectorForm = ({ config, onChange }: { config: JsonObject; onChange: (key: string, value: unknown) => void }) => {
    const { connectors, connections } = useConnectorStore();
    const connector = connectors.find((item) => item.id === config.connector);
    const [adding, setAdding] = useState(false);
    const [testAction, setTestAction] = useState('');
    const [values, setValues] = useState<Values>({});
    const [running, setRunning] = useState(false);
    const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);

    if (!connector) {
        return <p className="hint">Unknown connector “{String(config.connector ?? '')}”. It may have been removed from this server.</p>;
    }

    const ticked: string[] = Array.isArray(config.actions) ? config.actions : [];
    const options: JsonObject = (config.options ?? {}) as JsonObject;
    const mine = connections.filter((connection) => connection.connector === connector.id);
    const toggle = (action: ConnectorAction) => {
        const next = ticked.includes(action.id) ? ticked.filter((id) => id !== action.id) : [...ticked, action.id];
        onChange('actions', next);
    };
    const chosen = connector.actions.find((action) => action.id === (testAction || ticked[0]));

    const runTest = async () => {
        if (!chosen || !config.connection_id) return;
        setRunning(true);
        setOutcome(null);
        try {
            const args: JsonObject = {};
            for (const param of chosen.params) {
                const parsed = parseArg(param, values[param.name] ?? '');
                if (parsed !== undefined) args[param.name] = parsed;
            }
            const result = await runConnectorAction(String(config.connection_id), chosen.id, args, options);
            setOutcome({ ok: true, text: typeof result === 'string' ? result : JSON.stringify(result, null, 2) });
        } catch (failure) {
            setOutcome({ ok: false, text: failure instanceof SyntaxError ? `Invalid JSON: ${failure.message}` : apiDetail(failure) });
        } finally {
            setRunning(false);
        }
    };

    const actionGroup = (kind: 'read' | 'write', title: string, hint: string) => (
        <fieldset className="flex flex-col gap-1">
            <legend className="field-label">{title}</legend>
            <span className="hint">{hint}</span>
            {connector.actions.filter((action) => action.kind === kind).map((action) => (
                <label key={action.id} className="flex cursor-pointer items-start gap-2 py-0.5">
                    <input type="checkbox" checked={ticked.includes(action.id)} onChange={() => toggle(action)} aria-label={action.name} className="mt-0.5" />
                    <span className="min-w-0">
                        <span className="block text-[12.5px]">{action.name}</span>
                        <span className="hint block">{action.description}</span>
                    </span>
                </label>
            ))}
        </fieldset>
    );

    return (
        <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1">
                <span className="field-label">Connection</span>
                <div className="flex items-center gap-1.5">
                    <select className="select" value={String(config.connection_id ?? '')} onChange={(event) => onChange('connection_id', event.target.value)} aria-label="Connection">
                        <option value="">Choose an account…</option>
                        {mine.map((connection) => (
                            <option key={connection.id} value={connection.id}>{connection.account_label ?? connection.id}{connection.base_url ? ` · ${connection.base_url}` : ''}</option>
                        ))}
                    </select>
                    <button type="button" className="btn btn-sm" onClick={() => setAdding(true)}><Plus size={12} /> Connect…</button>
                </div>
                {!config.connection_id && <span className="hint" style={{ color: 'var(--clay)' }}>Pick the account this node acts as.</span>}
            </label>

            {connector.options.map((option) => (
                <label key={option.key} className="flex flex-col gap-1">
                    <span className="field-label">{option.label}</span>
                    <input
                        className="input"
                        value={String(options[option.key] ?? '')}
                        onChange={(event) => onChange('options', { ...options, [option.key]: event.target.value })}
                        aria-label={option.label}
                    />
                    {option.help && <span className="hint">{option.help}</span>}
                </label>
            ))}

            {actionGroup('read', 'Read', 'What the agent may look up.')}
            {actionGroup('write', 'Write', `What the agent may change in ${connector.name}. Off until you tick it.`)}
            {ticked.length === 0 && <span className="hint" style={{ color: 'var(--clay)' }}>Tick at least one action.</span>}

            <div className="flex flex-col gap-2">
                <span className="h-section">Test</span>
                <select className="select" value={chosen?.id ?? ''} onChange={(event) => { setTestAction(event.target.value); setValues({}); setOutcome(null); }} aria-label="Action to test">
                    {connector.actions.filter((action) => ticked.includes(action.id)).map((action) => <option key={action.id} value={action.id}>{action.name}</option>)}
                </select>
                {chosen?.params.map((param) => (
                    <label key={param.name} className="flex flex-col gap-1">
                        <span className="field-label">{param.name}{param.required ? ' *' : ''}</span>
                        {param.type === 'boolean' ? (
                            <input type="checkbox" checked={Boolean(values[param.name])} onChange={(event) => setValues({ ...values, [param.name]: event.target.checked })} aria-label={param.name} />
                        ) : param.type === 'object' ? (
                            <textarea className="textarea mono" rows={3} value={String(values[param.name] ?? '')} onChange={(event) => setValues({ ...values, [param.name]: event.target.value })} aria-label={param.name} placeholder="{}" />
                        ) : (
                            <input className="input" value={String(values[param.name] ?? '')} onChange={(event) => setValues({ ...values, [param.name]: event.target.value })} aria-label={param.name} placeholder={param.type === 'array' ? 'comma, separated' : param.default !== null && param.default !== undefined ? String(param.default) : ''} />
                        )}
                        <span className="hint">{param.description}</span>
                    </label>
                ))}
                {chosen?.kind === 'write' && <span className="hint" style={{ color: 'var(--clay)' }}>This changes the real {connector.name}.</span>}
                <button type="button" className="btn btn-sm self-start" disabled={running || !chosen || !config.connection_id} onClick={() => void runTest()}>
                    <Play size={10} fill="currentColor" /> {running ? 'Running…' : 'Run'}
                </button>
                {outcome && (
                    <pre className="well mono max-h-64 overflow-auto whitespace-pre-wrap p-2 text-[11px]" role={outcome.ok ? 'status' : 'alert'} style={{ color: outcome.ok ? 'var(--muted)' : 'var(--clay)' }}>{outcome.text}</pre>
                )}
            </div>

            <AddConnectionSheet open={adding} connectorId={connector.id} onClose={() => setAdding(false)} onAdded={(connection) => onChange('connection_id', connection.id)} />
        </div>
    );
};
```

- [ ] **Step 2: Wire it into the inspector and remove the old Gmail form**

In `workflow-editor/src/components/PropertiesPanel.tsx`:
1. Import `ConnectorForm`, `useConnectorStore`, `upgradeLegacyGmail`.
2. Next to `{config.type === 'gmail' && renderGmailConfig()}` (≈ line 983) render `{config.type === 'connector' && <ConnectorForm config={config} onChange={updateConfig} />}`, then delete the Gmail line.
3. Delete `fetchGmailStatus` (≈ line 27), the `GmailStatus` type and every Gmail-only state/effect/handler, and `renderGmailConfig` (≈ lines 1145–1200). Search the file for `gmail` afterwards: the only remaining reference must be the upgrade in step 4.
4. Upgrade legacy Gmail nodes when one is selected:
```tsx
    const connectorsLoaded = useConnectorStore((state) => state.loaded);
    const connections = useConnectorStore((state) => state.connections);
    const refreshConnectors = useConnectorStore((state) => state.refresh);
    useEffect(() => {
        if (!connectorsLoaded) void refreshConnectors();
    }, [connectorsLoaded, refreshConnectors]);
    // A node saved with the old Gmail tool becomes a Gmail connector node on the
    // same account the first time it is opened; the next save stores the new shape.
    const legacyGmail = selectedNode?.type === 'tool' && config.type === 'gmail';
    useEffect(() => {
        if (!legacyGmail || !connectorsLoaded || !selectedNode) return;
        updateNodeData(selectedNode.id, { config: upgradeLegacyGmail(config, connections) });
    }, [legacyGmail, connectorsLoaded, connections, selectedNode, config, updateNodeData]);
```
Use the PropertiesPanel's actual node-update function name (search for how `updateConfig` writes to the store) in place of `updateNodeData` if it differs. Place these hooks with the component's other hooks, before any early return.
5. Exclude connector nodes from the generic tool Test tab (the form has its own): where the test tab is gated with `!['memory', 'knowledge'].includes(config.type)` (≈ lines 1307 and 1350), use `['memory', 'knowledge', 'connector']`.
6. `kindLabel` (≈ line 1259): for `config.type === 'connector'`, show the connector's name: `selectedNode.type === 'tool' && config.type === 'connector' ? \`Connector · ${connectors.find((c) => c.id === config.connector)?.name ?? config.connector}\`` ahead of the generic `Tool · …` branch (read `connectors` from `useConnectorStore`).

- [ ] **Step 3: Check**

Run (in `workflow-editor/`): `npx tsc -b --noEmit && npx eslint src --max-warnings 0 && npx vitest run && grep -n "gmail" src/components/PropertiesPanel.tsx`
Expected: pass; the grep shows only the legacy-upgrade lines.

- [ ] **Step 4: Commit**

```bash
git add workflow-editor/src/components/inspector/ConnectorForm.tsx workflow-editor/src/components/PropertiesPanel.tsx
git commit -m "feat(studio): one inspector form for every connector

Pick the account, set the defaults, tick what the agent may read and what it
may change, and run any ticked action for real from the Test section. The
Gmail-only form is gone; a node saved with the old Gmail tool is moved onto
its connection the first time it is opened."
```

---

### Task 11: Studio — diagnostics for connector nodes

**Files:**
- Modify: `workflow-editor/src/utils/graphDiagnostics.ts`, `workflow-editor/src/components/HelpPanel.tsx` (line ~72), `workflow-editor/src/components/shell/ActivityCapsule.tsx` (line ~49)
- Test: `workflow-editor/src/utils/graphDiagnostics.test.ts` (exists — add cases; create it if it does not)

**Interfaces:**
- Consumes: `Connection` type.
- Produces: `DiagnosticsInput.connections?: Connection[]`; diagnostics codes `connection_missing` (severity `error`) and `connector_no_actions` (severity `error`).

- [ ] **Step 1: Write the failing tests**

Add to `workflow-editor/src/utils/graphDiagnostics.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { diagnoseWorkflow } from './graphDiagnostics';
import type { VisualNode } from '../types/workflow';
import type { Connection } from '../api/connectors';

const connectorNode = (config: Record<string, unknown>): VisualNode => ({
    id: 'jira-1', type: 'tool', position: { x: 0, y: 0 }, data: { label: 'Jira', config: { type: 'connector', connector: 'jira', ...config } },
});
const connection: Connection = { id: 'c1', connector: 'jira', account_label: 'Ops', base_url: null, auth_kind: 'token', options: {}, created_at: null, last_status: 'ok', last_error: null, last_verified_at: null };
const codes = (node: VisualNode, connections?: Connection[]) =>
    diagnoseWorkflow({ nodes: [node], edges: [], connections }).map((d) => d.code);

describe('connector diagnostics', () => {
    it('flags a node with no connection chosen', () => {
        expect(codes(connectorNode({ connection_id: '', actions: ['search_issues'] }), [connection])).toContain('connection_missing');
    });

    it('flags a node whose connection was removed', () => {
        const found = diagnoseWorkflow({ nodes: [connectorNode({ connection_id: 'gone', actions: ['x'] })], edges: [], connections: [connection] })
            .find((d) => d.code === 'connection_missing');
        expect(found?.detail).toMatch(/no longer exists/);
    });

    it('flags a node with no actions ticked', () => {
        expect(codes(connectorNode({ connection_id: 'c1', actions: [] }), [connection])).toContain('connector_no_actions');
    });

    it('is quiet when the node is complete, and skips the connection check when connections are unknown', () => {
        const complete = codes(connectorNode({ connection_id: 'c1', actions: ['search_issues'] }), [connection]);
        expect(complete).not.toContain('connection_missing');
        expect(complete).not.toContain('connector_no_actions');
        expect(codes(connectorNode({ connection_id: 'gone', actions: ['x'] }))).not.toContain('connection_missing');
    });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/utils/graphDiagnostics.test.ts`
Expected: FAIL — `connection_missing` not produced (and a TS error on `connections` in `DiagnosticsInput`).

- [ ] **Step 3: Implement**

In `graphDiagnostics.ts`: `import type { Connection } from '../api/connectors';`, add `connections?: Connection[];` to `DiagnosticsInput`, and inside `diagnoseWorkflow`, with the other per-node checks, add:
```ts
    for (const node of input.nodes) {
        const config = (node.data?.config ?? {}) as JsonObject;
        if (node.type !== 'tool' || config.type !== 'connector') continue;
        const actions = Array.isArray(config.actions) ? config.actions : [];
        if (actions.length === 0) {
            diagnostics.push({
                id: `connector_no_actions:${node.id}`,
                code: 'connector_no_actions',
                severity: 'error',
                title: 'No actions ticked',
                detail: `${label(node)} lets its agent do nothing. Tick at least one action in its inspector.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'tool',
            });
        }
        if (!input.connections) continue;
        const chosen = String(config.connection_id ?? '');
        if (!chosen || !input.connections.some((connection) => connection.id === chosen)) {
            diagnostics.push({
                id: `connection_missing:${node.id}`,
                code: 'connection_missing',
                severity: 'error',
                title: chosen ? 'Connection removed' : 'No connection chosen',
                detail: chosen
                    ? `${label(node)} uses a connection that no longer exists. Pick another account in its inspector.`
                    : `${label(node)} has no account to act as. Pick one in its inspector, or add one on the Connections page.`,
                nodeId: node.id,
                nodeLabel: label(node),
                component: 'tool',
            });
        }
    }
```
Use the function's existing accumulator name in place of `diagnostics` if it differs.

In `HelpPanel.tsx` and `ActivityCapsule.tsx`, read `const connections = useConnectorStore((state) => state.connections);` and `const connectorsLoaded = useConnectorStore((state) => state.loaded);`, pass `connections: connectorsLoaded ? connections : undefined` into `diagnoseWorkflow`, and add both to the memo dependency arrays.

- [ ] **Step 4: Check**

Run: `npx vitest run && npx tsc -b --noEmit && npx eslint src --max-warnings 0`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add workflow-editor/src/utils/graphDiagnostics.ts workflow-editor/src/utils/graphDiagnostics.test.ts workflow-editor/src/components/HelpPanel.tsx workflow-editor/src/components/shell/ActivityCapsule.tsx
git commit -m "feat(studio): diagnostics for connector nodes

A connector node with no account, a removed account, or no actions ticked
shows as an error in Help and the activity capsule before anything runs."
```

---

### Task 12: End to end with a fake forge, docs, and the full gate run

**Files:**
- Create: `scripts/fake_forge.py`, `workflow-editor/e2e/connectors.spec.ts`
- Modify: `workflow-editor/playwright.config.ts` (second web server), `README.md` (a Connectors section; the API block), `.env.example` (nothing new — confirm `ENCRYPTION_KEY` is documented as required for connections)

**Interfaces:**
- Consumes: everything above.
- Produces: fake forge on `http://127.0.0.1:8797` accepting token `fake-token`: `GET /health`, `GET /api/v4/user`, `GET /api/v4/projects/{project}/merge_requests`, `GET /rest/api/3/myself`, `GET /rest/api/3/search/jql`.

- [ ] **Step 1: Write the fake forge**

`scripts/fake_forge.py`:
```python
"""A stand-in for GitLab and Jira, so the e2e suite exercises connectors without secrets.

Run: uv run uvicorn --app-dir scripts fake_forge:app --port 8797
Accepts the token 'fake-token' (GitLab PRIVATE-TOKEN; Jira Basic with any email).
"""

from __future__ import annotations

import base64

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="fake forge")
TOKEN = "fake-token"

MERGE_REQUESTS = [
    {
        "iid": 7,
        "title": "Fix login redirect",
        "state": "opened",
        "author": {"username": "alice"},
        "source_branch": "fix-login",
        "target_branch": "main",
        "web_url": "http://127.0.0.1:8797/group/app/-/merge_requests/7",
        "labels": ["bug"],
        "updated_at": "2026-10-01T10:00:00Z",
    }
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v4/user")
def gitlab_user(private_token: str | None = Header(default=None, alias="PRIVATE-TOKEN")) -> dict[str, object]:
    if private_token != TOKEN:
        raise HTTPException(status_code=401, detail="401 Unauthorized")
    return {"id": 1, "username": "forge-bot"}


@app.get("/api/v4/projects/{project:path}/merge_requests")
def gitlab_merge_requests(project: str, private_token: str | None = Header(default=None, alias="PRIVATE-TOKEN")) -> list[dict[str, object]]:
    if private_token != TOKEN:
        raise HTTPException(status_code=401, detail="401 Unauthorized")
    return MERGE_REQUESTS


def _jira_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _, _, token = base64.b64decode(authorization[6:]).decode().partition(":")
    if token != TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/rest/api/3/myself")
def jira_myself(authorization: str | None = Header(default=None)) -> dict[str, str]:
    _jira_auth(authorization)
    return {"displayName": "Forge Jira", "emailAddress": "ops@example.com", "accountId": "acc-1"}


@app.get("/rest/api/3/search/jql")
def jira_search(jql: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    _jira_auth(authorization)
    return {
        "issues": [
            {
                "key": "OPS-1",
                "fields": {
                    "summary": "Users cannot log in",
                    "status": {"name": "To Do"},
                    "assignee": None,
                    "priority": {"name": "High"},
                    "labels": ["login"],
                    "issuetype": {"name": "Bug"},
                    "updated": "2026-10-01T10:00:00.000+0000",
                },
            }
        ]
    }
```

In `workflow-editor/playwright.config.ts`, change `webServer` to an array: the existing entry first, and
```ts
        {
            command: 'uv run --project .. --no-sync uvicorn --app-dir ../scripts fake_forge:app --host 127.0.0.1 --port 8797',
            url: 'http://127.0.0.1:8797/health',
            reuseExistingServer: !process.env.CI,
            timeout: 60_000,
        },
```
In `workflow-editor/e2e/serve.sh`, export a fixed `ENCRYPTION_KEY` for the run so connections can be stored:
```bash
# Connections are stored encrypted; a throwaway key for a throwaway database.
export ENCRYPTION_KEY="$(uv run --project "$REPO" --no-sync python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```
(place it before the `exec` line).

- [ ] **Step 2: Write the e2e spec**

`workflow-editor/e2e/connectors.spec.ts`:
```ts
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

const FORGE = 'http://127.0.0.1:8797';

const openPlace = async (page: Page, name: string) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Studio' }).first().click();
    await page.getByRole('button', { name, exact: true }).click();
};

const addGitLab = async (page: Page, token: string) => {
    await page.getByRole('button', { name: 'Add connection' }).first().click();
    const sheet = page.getByRole('dialog', { name: 'Add a connection' });
    await sheet.getByLabel('Connector').selectOption('gitlab');
    await sheet.getByLabel('Base URL').fill(FORGE);
    await sheet.getByLabel('Personal access token').fill(token);
    await sheet.getByRole('button', { name: 'Connect' }).click();
    return sheet;
};

/** Drop a palette tile on the canvas the way a mouse drag does: a real DataTransfer through the real handlers. */
const dropTile = async (page: Page, label: string) => {
    const tile = page.getByTitle(new RegExp(`^${label}`)).first();
    const pane = page.locator('.react-flow__pane');
    const transfer = await page.evaluateHandle(() => new DataTransfer());
    await tile.dispatchEvent('dragstart', { dataTransfer: transfer });
    const box = await pane.boundingBox();
    if (!box) throw new Error('canvas not visible');
    const at = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
    await pane.dispatchEvent('dragover', { dataTransfer: transfer, ...at });
    await pane.dispatchEvent('drop', { dataTransfer: transfer, ...at });
};

test('a wrong token is refused and nothing is saved', async ({ page }) => {
    await openPlace(page, 'Connections');
    const sheet = await addGitLab(page, 'wrong-token');
    await expect(sheet.getByRole('alert')).toContainText('rejected the token');
    await sheet.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('table', { name: 'Connections' })).toHaveCount(0);
});

test('a GitLab connection is verified, used by a node, and its action runs', async ({ page }) => {
    await openPlace(page, 'Connections');
    await addGitLab(page, 'fake-token');
    const table = page.getByRole('table', { name: 'Connections' });
    await expect(table).toContainText('forge-bot');
    await page.getByRole('button', { name: 'Test' }).click();
    await expect(page.getByRole('status')).toContainText('Working — signed in as forge-bot');

    await page.getByRole('button', { name: 'Studio', exact: true }).click();
    await dropTile(page, 'GitLab');
    await page.locator('.react-flow__node').filter({ hasText: 'GitLab' }).first().click();

    await page.getByLabel('Connection').selectOption({ label: `forge-bot · ${FORGE}` });
    await page.getByLabel('Default project').fill('group/app');
    await expect(page.getByLabel('Create an issue')).not.toBeChecked();
    await expect(page.getByLabel('List merge requests')).toBeChecked();

    await page.getByLabel('Action to test').selectOption('list_merge_requests');
    await page.getByRole('button', { name: 'Run' }).click();
    await expect(page.getByRole('status').last()).toContainText('Fix login redirect');
});
```
If `getByTitle` does not find the palette tile, inspect `ResourceCard` for its accessible name (`title` or `aria-label`) and use that locator; the drop mechanics stay the same.

- [ ] **Step 3: Run the e2e suite**

Run (in `workflow-editor/`): `npx playwright test`
Expected: all specs pass (27 existing + 2 new). If the drop fails, check `WorkflowCanvas.onDrop` reads `application/reactflow` and `application/reactflow-config` from the event's `dataTransfer` — the dispatched `dragstart` on the tile populates the shared `DataTransfer` through `ResourceCard`'s real `onDragStart`.

- [ ] **Step 4: Document**

In `README.md`, add after the `### Trust tools` section:
```markdown
### Connectors

Ready-made integrations for **Jira** (Cloud and Data Center), **GitLab**
(gitlab.com or self-hosted) and **Gmail**. Add an account once on the
**Connections** page: paste a token (Jira, GitLab) or sign in (Gmail). The
token is checked against the service before it is saved, and stored encrypted
with `ENCRYPTION_KEY`.

Drop a connector tile from the palette's **Connect** group onto the canvas,
choose the account, and tick what the agent may do. Read actions start ticked;
write actions — create, comment, transition, assign, label — stay off until
you tick them. The inspector's **Test** runs any ticked action for real.

| Connector | Read | Write |
|---|---|---|
| Jira | search (JQL), get issue, projects, transitions | create, update, comment, transition, assign |
| GitLab | projects, merge requests, MR diff, issues, files, pipelines | create/update issue, comment on MR or issue, set MR labels |
| Gmail | search, read, new mail since a time | send, reply in thread |

Nothing approves or merges a merge request, triggers a pipeline, or deletes
anything. A workflow whose connection has been removed fails with the node's
name rather than running without its tools.
```
Add to the README API block:
```bash
# Connectors and connections
curl localhost:8000/api/v1/integrations/connectors
curl -X POST localhost:8000/api/v1/integrations/connections \
  -H 'Content-Type: application/json' \
  -d '{"connector": "gitlab", "token": "glpat-…"}'
```
Confirm `.env.example` documents `ENCRYPTION_KEY` (it is needed for Gmail already); if its comment mentions only Gmail, extend it to "Gmail and connector tokens".

- [ ] **Step 5: Full gate run**

Run, from the repository root:
```bash
ruff check src tests scripts && ruff format --check src tests scripts && mypy src && python scripts/check_configs.py && python -m pytest -q -p no:cacheprovider
cd workflow-editor && npx tsc -b --noEmit && npx eslint src e2e --max-warnings 0 && npx vitest run && npx playwright test && npm run build:demo
```
Expected: every command succeeds; pytest exit code 0; Playwright all passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/fake_forge.py workflow-editor/e2e/connectors.spec.ts workflow-editor/playwright.config.ts workflow-editor/e2e/serve.sh README.md .env.example
git commit -m "test(e2e): connectors end to end against a fake forge; document them

A small fake GitLab and Jira lets the suite add a connection, see a wrong
token refused, drop a GitLab node, pick its account and run an action, with
no real account or secret. The README describes connectors and their API."
```

---

## Self-Review Notes

- **Spec coverage (slice 1 of §8):** catalogue (T1, T6), Jira/GitLab/Gmail modules (T2–T4), connections table and endpoints including test and delete (T5–T6), OAuth for Gmail through the generalised sheet (T9), `connector` tool kind and factory with events and named failure (T7), palette from the catalogue (T8), inspector form with Test (T10), Connections page (T9), diagnostics `connection_missing` and `connector_no_actions` (T11), Gmail migrated with `reply_to_thread` and `list_new_messages` (T4, T10), demo mode not broken (T8). `event_trigger_without_events` belongs to slice 2. "Register webhook", event tiles and the Runs entity filter belong to slice 2.
- **Deviation:** minimal fake forge moved into this slice (T12) — stated in Global Constraints.
- **Names used across tasks:** `ConnectorError`, `ConnectorContext.option`, `args_model`, `validate_args`, `catalogue_entry`, `request`, `get_connector`/`all_connectors`/`connector_ids`, `ConnectionStore.secrets/create/record_test/delete/get/list_connections`, `Connection.to_dict`, `ConnectorToolFactory.accepts_emitter`, TS `useConnectorStore`, `apiDetail`, `runConnectorAction`, `connectorTiles`, `connectorNodeConfig`, `upgradeLegacyGmail`, `AddConnectionSheet` — consistent across T1–T12.

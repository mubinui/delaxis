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


def _call(
    ctx: ConnectorContext, method: str, path: str, *, version: str | None = None, **kwargs: Any
) -> Any:
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
    if kind == "doc":
        return "\n\n".join(adf_to_text(child) for child in node.get("content") or [])
    return "".join(adf_to_text(child) for child in node.get("content") or [])


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
    return VerifyResult(
        account_label=f"{label} ({email})" if email else label,
        options={"api_version": version},
    )


def search_issues(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    params = {
        "jql": args["jql"],
        "maxResults": args.get("max_results", 20),
        "fields": _ISSUE_FIELDS,
    }
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
            {
                "author": _name(c.get("author")),
                "created": c.get("created"),
                "body": adf_to_text(c.get("body")),
            }
            for c in comments[-20:]
        ],
    }


def list_projects(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    if _version(ctx) == "3":
        projects = _call(ctx, "GET", "/project/search", params={"maxResults": 50}).get("values")
    else:
        projects = _call(ctx, "GET", "/project")
    return [{"key": p.get("key"), "name": p.get("name")} for p in projects or []]


def list_transitions(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    result = _call(ctx, "GET", f"/issue/{args['key']}/transitions")
    return [
        {"id": t.get("id"), "name": t.get("name"), "to": (t.get("to") or {}).get("name")}
        for t in result.get("transitions") or []
    ]


def create_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    project = args.get("project") or ctx.option("project")
    if not project:
        raise ConnectorError(
            "No Jira project given. Pass 'project' (its key), or set the node's Default project."
        )
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
        raise ConnectorError(
            "Nothing to update: pass summary, description, labels, priority or fields."
        )
    _call(ctx, "PUT", f"/issue/{args['key']}", json_body={"fields": fields})
    return {"key": args["key"], "updated": sorted(fields)}


def add_comment(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    comment = _call(
        ctx,
        "POST",
        f"/issue/{args['key']}/comment",
        json_body={"body": _rich(ctx, args["body"])},
    )
    return {"key": args["key"], "comment_id": comment.get("id")}


def transition_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    wanted = str(args["transition"]).strip().lower()
    choices = list_transitions(ctx, {"key": args["key"]})
    match = next(
        (
            t
            for t in choices
            if wanted in (str(t["id"]).lower(), str(t["name"]).lower(), str(t["to"]).lower())
        ),
        None,
    )
    if match is None:
        names = ", ".join(str(t["name"]) for t in choices) or "none"
        raise ConnectorError(
            f"{args['key']} has no transition '{args['transition']}'. Available: {names}."
        )
    _call(
        ctx,
        "POST",
        f"/issue/{args['key']}/transitions",
        json_body={"transition": {"id": match["id"]}},
    )
    return {"key": args["key"], "transitioned_to": match["to"] or match["name"]}


def assign_issue(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    who = str(args.get("assignee") or "").strip()
    cloud = _version(ctx) == "3"
    if who.lower() in ("", "none", "unassigned"):
        _call(
            ctx,
            "PUT",
            f"/issue/{args['key']}/assignee",
            json_body={"accountId": None} if cloud else {"name": None},
        )
        return {"key": args["key"], "assignee": None}
    display = who
    if "@" in who:
        users = _call(
            ctx, "GET", "/user/search", params={"query": who} if cloud else {"username": who}
        )
        if not users:
            raise ConnectorError(f"No Jira user matches {who}.")
        who = str(users[0].get("accountId") if cloud else users[0].get("name"))
        display = str(users[0].get("displayName") or who)
    _call(
        ctx,
        "PUT",
        f"/issue/{args['key']}/assignee",
        json_body={"accountId": who} if cloud else {"name": who},
    )
    return {"key": args["key"], "assignee": display}


_KEY = Param("key", "string", "Issue key, e.g. OPS-123")

CONNECTOR = Connector(
    id="jira",
    name="Jira",
    icon="jira",
    description=(
        "Search, create, comment on, transition and assign Jira issues (Cloud or Data Center)"
    ),
    auth=AuthSpec(
        kind="token",
        base_url=True,
        base_url_label="Jira site URL",
        username_label="Account email (Jira Cloud only)",
        token_label="API token (Cloud) or personal access token (Data Center)",
        token_help=(
            "Cloud: id.atlassian.com → Security → API tokens, and fill in the account email. "
            "Data Center: Profile → Personal access tokens, and leave the email empty."
        ),
    ),
    options=(
        OptionField(
            "project", "Default project", "Project key, e.g. OPS; used when an action names none"
        ),
    ),
    verify=verify,
    actions=(
        Action(
            "search_issues",
            "Search issues",
            "read",
            "Find issues with JQL, e.g. 'project = OPS AND status != Done ORDER BY created DESC'.",
            (
                Param("jql", "string", "A JQL query"),
                Param(
                    "max_results", "integer", "Most issues to return", required=False, default=20
                ),
            ),
            search_issues,
        ),
        Action(
            "get_issue",
            "Get an issue",
            "read",
            "One issue with its description and latest comments.",
            (_KEY,),
            get_issue,
        ),
        Action(
            "list_projects",
            "List projects",
            "read",
            "The projects this account can see.",
            (),
            list_projects,
        ),
        Action(
            "list_transitions",
            "List transitions",
            "read",
            "The status changes an issue allows right now.",
            (_KEY,),
            list_transitions,
        ),
        Action(
            "create_issue",
            "Create an issue",
            "write",
            "Create an issue; returns its key and link.",
            (
                Param("summary", "string", "One-line title"),
                Param("description", "string", "Body text", required=False),
                Param(
                    "issue_type", "string", "Task, Bug, Story, …", required=False, default="Task"
                ),
                Param(
                    "project",
                    "string",
                    "Project key; defaults to the node's Default project",
                    required=False,
                ),
                Param("priority", "string", "Priority name, e.g. High", required=False),
                Param("labels", "array", "Labels to set", required=False),
            ),
            create_issue,
        ),
        Action(
            "update_issue",
            "Update an issue",
            "write",
            "Change an issue's summary, description, labels, priority, or other fields by id.",
            (
                _KEY,
                Param("summary", "string", "New summary", required=False),
                Param("description", "string", "New description", required=False),
                Param("labels", "array", "Replace the labels", required=False),
                Param("priority", "string", "Priority name", required=False),
                Param(
                    "fields",
                    "object",
                    'Other fields by id, e.g. {"customfield_10010": "x"}',
                    required=False,
                ),
            ),
            update_issue,
        ),
        Action(
            "add_comment",
            "Comment on an issue",
            "write",
            "Add a comment to an issue.",
            (_KEY, Param("body", "string", "Comment text")),
            add_comment,
        ),
        Action(
            "transition_issue",
            "Transition an issue",
            "write",
            "Move an issue to another status by transition name, id, or target status.",
            (
                _KEY,
                Param("transition", "string", "Transition name or id, or the status to move to"),
            ),
            transition_issue,
        ),
        Action(
            "assign_issue",
            "Assign an issue",
            "write",
            "Assign an issue by email or account id; 'none' unassigns.",
            (
                _KEY,
                Param(
                    "assignee",
                    "string",
                    "Email, account id (Cloud) or username (Data Center), or 'none'",
                ),
            ),
            assign_issue,
        ),
    ),
)

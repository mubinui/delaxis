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
            "No GitLab project given. Pass 'project' (group/name or id), "
            "or set the node's Default project."
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
    return VerifyResult(
        account_label=str(user.get("username") or user.get("name") or "GitLab user")
    )


def search_projects(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    items = _call(
        ctx,
        "GET",
        "/projects",
        params={
            "search": args.get("search"),
            "membership": "true",
            "per_page": args.get("max_results", 20),
        },
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
        approval: dict[str, Any] | None = {
            "approved": approvals.get("approved"),
            "approved_by": [
                a.get("user", {}).get("username") for a in approvals.get("approved_by") or []
            ],
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
        params={
            "ref": args.get("ref"),
            "status": args.get("status"),
            "per_page": args.get("max_results", 10),
        },
    )
    out = [
        {
            "id": p.get("id"),
            "status": p.get("status"),
            "ref": p.get("ref"),
            "updated_at": p.get("updated_at"),
            "url": p.get("web_url"),
        }
        for p in pipelines
    ]
    if out:
        jobs = _call(
            ctx,
            "GET",
            f"/projects/{project}/pipelines/{out[0]['id']}/jobs",
            params={"per_page": 100},
        )
        out[0]["jobs"] = [
            {"name": j.get("name"), "stage": j.get("stage"), "status": j.get("status")}
            for j in jobs
        ]
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
    item = _call(
        ctx, "PUT", f"/projects/{_project(ctx, args)}/issues/{args['iid']}", json_body=body
    )
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


_PROJECT = Param(
    "project",
    "string",
    "Project path (group/name) or id; defaults to the node's Default project",
    required=False,
)
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
        token_help=(
            "Create one under User settings → Access tokens. "
            "Scope 'api' to allow writes, 'read_api' for read-only."
        ),
    ),
    options=(
        OptionField(
            "project", "Default project", "group/name; actions use it when they name no project"
        ),
    ),
    verify=verify,
    actions=(
        Action(
            "search_projects",
            "Search projects",
            "read",
            "Find projects you are a member of by name.",
            (Param("search", "string", "Text in the project name"), _MAX),
            search_projects,
        ),
        Action(
            "list_merge_requests",
            "List merge requests",
            "read",
            "List merge requests in a project, newest first.",
            (
                _PROJECT,
                Param(
                    "state",
                    "string",
                    "opened, merged, closed or all",
                    required=False,
                    default="opened",
                    enum=("opened", "merged", "closed", "all"),
                ),
                Param("labels", "array", "Only these labels", required=False),
                Param("author_username", "string", "Only by this author", required=False),
                _MAX,
            ),
            list_merge_requests,
        ),
        Action(
            "get_merge_request",
            "Get a merge request",
            "read",
            "One merge request with its description and approval state.",
            (_PROJECT, _IID),
            get_merge_request,
        ),
        Action(
            "get_merge_request_changes",
            "Get merge request changes",
            "read",
            "The diff of a merge request, file by file, capped in size.",
            (
                _PROJECT,
                _IID,
                Param(
                    "max_chars",
                    "integer",
                    "Most diff characters to return",
                    required=False,
                    default=20000,
                ),
            ),
            get_merge_request_changes,
        ),
        Action(
            "list_issues",
            "List issues",
            "read",
            "List issues in a project.",
            (
                _PROJECT,
                Param(
                    "state",
                    "string",
                    "opened, closed or all",
                    required=False,
                    default="opened",
                    enum=("opened", "closed", "all"),
                ),
                Param("labels", "array", "Only these labels", required=False),
                Param("search", "string", "Text in the title or description", required=False),
                _MAX,
            ),
            list_issues,
        ),
        Action(
            "get_file",
            "Get a file",
            "read",
            "A file's content at a branch, tag or commit.",
            (
                _PROJECT,
                Param("file_path", "string", "Path in the repository, e.g. src/app.py"),
                Param(
                    "ref",
                    "string",
                    "Branch, tag or commit; default HEAD",
                    required=False,
                    default="HEAD",
                ),
            ),
            get_file,
        ),
        Action(
            "list_pipelines",
            "List pipelines",
            "read",
            "Recent pipelines, with the jobs of the newest one.",
            (
                _PROJECT,
                Param("ref", "string", "Only this branch or tag", required=False),
                Param("status", "string", "Only this status, e.g. failed", required=False),
                Param(
                    "max_results",
                    "integer",
                    "Most pipelines to return",
                    required=False,
                    default=10,
                ),
            ),
            list_pipelines,
        ),
        Action(
            "create_issue",
            "Create an issue",
            "write",
            "Open a new issue in a project.",
            (
                _PROJECT,
                Param("title", "string", "Issue title"),
                Param("description", "string", "Issue body in Markdown", required=False),
                Param("labels", "array", "Labels to set", required=False),
            ),
            create_issue,
        ),
        Action(
            "update_issue",
            "Update an issue",
            "write",
            "Change an issue's title, description or labels, or close/reopen it.",
            (
                _PROJECT,
                _IID,
                Param("title", "string", "New title", required=False),
                Param("description", "string", "New body", required=False),
                Param("labels", "array", "Replace the labels", required=False),
                Param(
                    "state_event",
                    "string",
                    "close or reopen",
                    required=False,
                    enum=("close", "reopen"),
                ),
            ),
            update_issue,
        ),
        Action(
            "add_merge_request_note",
            "Comment on a merge request",
            "write",
            "Post a comment on a merge request.",
            (_PROJECT, _IID, Param("body", "string", "Comment in Markdown")),
            add_merge_request_note,
        ),
        Action(
            "add_issue_note",
            "Comment on an issue",
            "write",
            "Post a comment on an issue.",
            (_PROJECT, _IID, Param("body", "string", "Comment in Markdown")),
            add_issue_note,
        ),
        Action(
            "set_merge_request_labels",
            "Set merge request labels",
            "write",
            "Replace a merge request's labels.",
            (_PROJECT, _IID, Param("labels", "array", "The labels to keep")),
            set_merge_request_labels,
        ),
    ),
)

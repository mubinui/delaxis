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
def gitlab_user(
    private_token: str | None = Header(default=None, alias="PRIVATE-TOKEN"),
) -> dict[str, object]:
    if private_token != TOKEN:
        raise HTTPException(status_code=401, detail="401 Unauthorized")
    return {"id": 1, "username": "forge-bot"}


@app.get("/api/v4/projects/{project:path}/merge_requests")
def gitlab_merge_requests(
    project: str,
    private_token: str | None = Header(default=None, alias="PRIVATE-TOKEN"),
) -> list[dict[str, object]]:
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

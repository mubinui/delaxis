"""The graph digest sent to a third-party model must never carry a secret.

WorkflowCanvas.normalizeConfig writes a raw api_key into each agent node's
model_config, so a digest built by spreading node config would ship the user's
key to whichever provider answers the "explain this" request.
"""

import pytest

from src.api.routers.builder import (
    DiagnosticExplainRequest,
    GraphDigest,
    GraphDigestNode,
    _digest_text,
)

SECRET = "sk-DO-NOT-LEAK-abcdef123456"


class TestDigestIsAllowlisted:
    def test_extra_config_keys_are_rejected_not_carried(self):
        """The node model declares only safe fields, so a key cannot ride along."""
        node = GraphDigestNode(
            id="a1",
            label="Researcher",
            provider_id="gemini",
            model="gemini-3.5-flash",
            **{"api_key": SECRET, "base_url": "http://internal"},
        )
        dumped = node.model_dump()
        assert "api_key" not in dumped
        assert SECRET not in str(dumped)

    def test_rendered_prompt_contains_no_secret(self):
        digest = GraphDigest(
            nodes=[
                GraphDigestNode(
                    id="a1", label="Researcher", provider_id="gemini",
                    model="gemini-3.5-flash", tools=["web_search"],
                    **{"api_key": SECRET},
                )
            ],
            edges=[{"source": "t1", "target": "a1"}],
            pattern="sequential",
        )
        text = _digest_text(digest)
        assert SECRET not in text
        # ...while still describing the graph usefully
        assert "Researcher" in text
        assert "gemini-3.5-flash" in text
        assert "web_search" in text

    def test_whole_request_payload_is_clean(self):
        body = DiagnosticExplainRequest(
            mode="fix",
            diagnostic={"code": "provider_key_missing", "title": "no key", "detail": "d"},
            graph=GraphDigest(
                nodes=[GraphDigestNode(id="a1", label="A", **{"api_key": SECRET})]
            ),
        )
        assert SECRET not in str(body.model_dump())

    def test_empty_graph_is_described_not_crashed(self):
        assert "empty" in _digest_text(GraphDigest()).lower()


class TestExplainEndpointGuards:
    def test_unknown_provider_is_rejected(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.routers import builder as builder_router

        app = FastAPI()
        app.include_router(builder_router.router)
        response = TestClient(app).post(
            "/api/v1/builder/explain-diagnostic",
            json={"mode": "explain", "provider_id": "ghost-provider", "graph": {"nodes": []}},
        )
        assert response.status_code == 400

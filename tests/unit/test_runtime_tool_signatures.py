"""Plain-function tools keep their typed argument schema when wrapped for CrewAI.

`src.tools.rag_pipeline` uses `from __future__ import annotations`, so its hints
are strings like "Optional[str]". Copied verbatim onto the runtime's wrapper,
they were resolved in the runtime's module — which never imports `Optional` —
and every workflow using `rag_query` failed with
"`Rag_Query` is not fully defined; you should define `Optional`".
"""
from types import SimpleNamespace

from crewai.tools import tool

from src.crewai_runtime.runtime import CrewAIWorkflowRuntime
from src.tools.rag_pipeline import query_rag


def make_runtime() -> CrewAIWorkflowRuntime:
    return CrewAIWorkflowRuntime(memory_enabled=False, storage_dir="./.crewai-test")


def test_wrapped_tool_with_postponed_annotations_builds_its_schema() -> None:
    tool_def = SimpleNamespace(
        tool_id="rag_query",
        name="rag_query",
        description="Search indexed documents.",
        function=query_rag,
    )
    wrapped = make_runtime()._wrap_tool(tool, tool_def)

    schema = wrapped.args_schema.model_json_schema()
    assert set(schema["properties"]) >= {"query", "collection", "top_k", "rerank"}
    assert schema["properties"]["top_k"]["type"] == "integer"


def test_knowledge_embedder_needs_no_openai_key(monkeypatch) -> None:
    """Crew knowledge embeds with the retrieval service's embedder, not OpenAI.

    Left to crewai's default, knowledge was embedded with OpenAI using
    OPENAI_API_KEY, and every workflow with knowledge failed with a 401 when that
    key belonged to another provider.
    """
    from crewai.rag.embeddings.factory import build_embedder_from_dict

    from src.crewai_runtime.runtime import knowledge_embedder

    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-v1-not-an-openai-key")
    embed = build_embedder_from_dict(knowledge_embedder())
    vectors = embed(["refund window for annual plans", "deploy a chatbot"])

    assert len(vectors) == 2
    assert len(vectors[0]) == len(vectors[1]) > 0
    assert any(value != 0 for value in vectors[0])


def test_agents_and_crews_accept_the_knowledge_embedder() -> None:
    """crewai validates the spec on Agent and Crew more strictly than its factory."""
    from crewai import Agent

    from src.crewai_runtime.runtime import knowledge_embedder

    agent = Agent(role="Support", goal="Answer", backstory="Helpful", embedder=knowledge_embedder())
    assert agent.embedder is not None

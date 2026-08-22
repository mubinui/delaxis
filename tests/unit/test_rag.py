"""Tests for the retrieval pipeline.

The previous implementation was an HTTP client for a service nothing started,
so there was nothing to test and nothing was. These cover the parts most likely
to be wrong in a hand-rolled RAG system: chunk boundaries, the weighting inside
the local embedder, whether the stores actually agree with each other, and
whether re-ingesting a document leaves the old one behind.
"""

from __future__ import annotations

import importlib.util

import pytest

from src.rag.chunking import chunk_text
from src.rag.embeddings import LocalEmbeddings, create_embedder
from src.rag.service import RagConfig, RagService
from src.rag.stores import normalise_collection
from src.rag.stores.base import Record, VectorStoreError, cosine, matches
from src.rag.stores.sqlite_store import SqliteVectorStore

HANDBOOK = [
    ("deploy.md", "Deployments are served at /d/<name> by the same app, so there are no extra ports."),
    ("audit.md", "The audit trail is append only and hash chained, so a quiet edit is detectable."),
    ("sql.md", "Read-only enforcement rejects INSERT, UPDATE, DELETE and DDL before the query runs."),
]


def installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


@pytest.fixture
def embedder() -> LocalEmbeddings:
    return LocalEmbeddings()


def records(embedder: LocalEmbeddings) -> list[Record]:
    return [
        Record(id=f"c{index}", text=text, embedding=embedder.embed([text])[0],
               metadata={"source": source, "kind": "doc"})
        for index, (source, text) in enumerate(HANDBOOK)
    ]


# --------------------------------------------------------------------------- #


class TestChunking:
    def test_short_text_is_one_chunk(self):
        chunks = chunk_text("A single short sentence.")
        assert len(chunks) == 1
        assert chunks[0].text == "A single short sentence."

    def test_empty_text_yields_nothing(self):
        assert chunk_text("   \n\n  ") == []

    def test_chunks_overlap_so_a_straddling_fact_survives(self):
        body = " ".join(f"Sentence number {n} carries a fact." for n in range(120))
        chunks = chunk_text(body, chunk_chars=400, overlap_chars=100)
        assert len(chunks) > 3
        assert all(chunks[i].end > chunks[i + 1].start for i in range(len(chunks) - 1))

    def test_no_chunk_begins_mid_word(self):
        # The overlap step-back originally landed on an arbitrary character, so
        # chunks began like "tection." and embedded as nonsense.
        body = " ".join(f"Deployment number {n} is configured and running." for n in range(80))
        for chunk in chunk_text(body, chunk_chars=300, overlap_chars=80):
            assert chunk.text[0].isalnum() or chunk.text[0] in "\"'(["

    def test_whole_document_is_covered(self):
        body = " ".join(f"Fact {n}." for n in range(200))
        chunks = chunk_text(body, chunk_chars=250, overlap_chars=50)
        assert chunks[0].start == 0
        assert chunks[-1].end >= len(body.strip()) - 2

    def test_text_without_whitespace_still_terminates(self):
        chunks = chunk_text("x" * 5000, chunk_chars=300, overlap_chars=50)
        assert len(chunks) > 1
        assert all(chunk.characters <= 300 for chunk in chunks)

    def test_metadata_travels_to_every_chunk(self):
        chunks = chunk_text("word " * 400, chunk_chars=300, metadata={"source": "a.md"})
        assert len(chunks) > 1
        assert all(chunk.metadata["source"] == "a.md" for chunk in chunks)

    def test_overlap_must_be_smaller_than_the_chunk(self):
        with pytest.raises(ValueError):
            chunk_text("hello", chunk_chars=200, overlap_chars=200)


class TestLocalEmbeddings:
    def test_is_deterministic(self, embedder):
        assert embedder.embed(["repeatable"]) == embedder.embed(["repeatable"])

    def test_vectors_are_unit_length(self, embedder):
        vector = embedder.embed(["some ordinary text"])[0]
        assert cosine(vector, vector) == pytest.approx(1.0, abs=1e-6)

    def test_empty_text_does_not_explode(self, embedder):
        assert embedder.embed([""])[0] == [0.0] * embedder.dimensions

    def test_trigrams_survive_the_weighting(self, embedder):
        # Regression: weights were folded in before the sub-linear term, so
        # 1 + log(0.35) made every trigram contribute a negative amount and
        # morphological matches scored zero.
        assert cosine(embedder.embed_query("deploy"), embedder.embed_query("deploys")) > 0.2

    def test_retrieves_the_right_document(self, embedder):
        vectors = embedder.embed([text for _, text in HANDBOOK])
        for query, expected in (
            ("how are chatbots served", 0),
            ("can someone quietly edit the log", 1),
            ("blocking write statements in sql", 2),
        ):
            scores = [cosine(embedder.embed_query(query), vector) for vector in vectors]
            assert scores.index(max(scores)) == expected, query

    def test_unrelated_text_scores_near_zero(self, embedder):
        assert cosine(
            embedder.embed_query("photosynthesis in coastal mangroves"),
            embedder.embed(["Read-only enforcement rejects INSERT and UPDATE."])[0],
        ) < 0.1

    def test_missing_key_falls_back_rather_than_failing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert create_embedder("gemini").name == "local"

    def test_unknown_provider_is_refused(self):
        from src.rag.embeddings import EmbeddingError

        with pytest.raises(EmbeddingError):
            create_embedder("telepathy")


class TestFiltering:
    def test_no_filter_matches_everything(self):
        assert matches({"a": 1}, None)

    def test_all_keys_must_match(self):
        assert matches({"a": 1, "b": 2}, {"a": 1})
        assert not matches({"a": 1, "b": 2}, {"a": 1, "b": 3})
        assert not matches({}, {"a": 1})


class TestSqliteStore:
    @pytest.fixture
    def store(self):
        return SqliteVectorStore(":memory:")

    def test_upsert_then_search(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        hits = store.search("knowledge", embedder.embed_query("quietly edit the log"), top_k=1)
        assert hits[0].source == "audit.md"

    def test_search_on_empty_collection(self, store, embedder):
        assert store.search("nothing", embedder.embed_query("anything")) == []

    def test_upsert_is_idempotent(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        store.upsert("knowledge", records(embedder))
        assert store.stats("knowledge")["chunks"] == len(HANDBOOK)

    def test_filter_restricts_to_one_source(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        hits = store.search("knowledge", embedder.embed_query("anything"),
                            top_k=5, where={"source": "sql.md"})
        assert {hit.source for hit in hits} == {"sql.md"}

    def test_filter_on_other_metadata(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        assert len(store.search("knowledge", embedder.embed_query("a"), top_k=9,
                                where={"kind": "doc"})) == len(HANDBOOK)
        assert store.search("knowledge", embedder.embed_query("a"), top_k=9,
                            where={"kind": "other"}) == []

    def test_delete_by_source(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        assert store.delete("knowledge", where={"source": "audit.md"}) == 1
        assert store.stats("knowledge")["chunks"] == len(HANDBOOK) - 1

    def test_delete_by_id(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        assert store.delete("knowledge", ids=["c0", "c1"]) == 2

    def test_drop_removes_the_collection(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        assert store.drop("knowledge")
        assert "knowledge" not in store.collections()

    def test_sources_are_grouped(self, store, embedder):
        store.upsert("knowledge", records(embedder))
        assert {item["source"] for item in store.sources("knowledge")} == \
            {source for source, _ in HANDBOOK}

    def test_dimension_mismatch_says_what_to_do(self, store, embedder):
        # Changing embedding provider against an existing collection is a real
        # mistake, and numpy's own error names nothing actionable.
        store.upsert("knowledge", records(embedder))
        with pytest.raises(VectorStoreError, match="re-ingest"):
            store.search("knowledge", [0.1] * 99)

    def test_collections_are_isolated(self, store, embedder):
        store.upsert("first", records(embedder))
        store.upsert("second", records(embedder)[:1])
        assert store.stats("first")["chunks"] == len(HANDBOOK)
        assert store.stats("second")["chunks"] == 1


class TestCollectionNames:
    @pytest.mark.parametrize("raw,expected", [
        ("knowledge", "knowledge"),
        ("kb", "kb-collection"),          # Chroma rejects names under three characters
        ("My Docs!", "My-Docs"),
        ("", "default"),
        ("--weird--", "weird"),
        ("session/abc 123", "session-abc-123"),
    ])
    def test_normalises_to_a_portable_name(self, raw, expected):
        assert normalise_collection(raw) == expected

    def test_is_stable(self):
        once = normalise_collection("My Docs!")
        assert normalise_collection(once) == once


class TestBackendParity:
    """Every store must rank the same corpus the same way.

    Retrieval quality should not change because someone switched databases, and
    a backend whose scores mean something different is a bug that only shows up
    as worse answers.
    """

    def stores(self, tmp_path):
        built = [("sqlite", SqliteVectorStore(":memory:"))]
        if installed("faiss"):
            from src.rag.stores.faiss_store import FaissVectorStore
            built.append(("faiss", FaissVectorStore(path=str(tmp_path / "faiss"))))
        if installed("qdrant_client"):
            from src.rag.stores.qdrant_store import QdrantVectorStore
            built.append(("qdrant", QdrantVectorStore(path=":memory:")))
        if installed("chromadb"):
            from src.rag.stores.chroma_store import ChromaVectorStore
            built.append(("chromadb", ChromaVectorStore(persist_directory=str(tmp_path / "chroma"))))
        return built

    def test_every_backend_ranks_alike(self, tmp_path, embedder):
        query = embedder.embed_query("can someone quietly edit the log")
        ranking: dict[str, list[str]] = {}
        scores: dict[str, float] = {}

        for name, store in self.stores(tmp_path):
            store.upsert("knowledge", records(embedder))
            hits = store.search("knowledge", query, top_k=3)
            assert hits, name
            assert hits[0].source == "audit.md", name
            ranking[name] = [hit.source for hit in hits]
            scores[name] = hits[0].score

        if len(ranking) < 2:
            pytest.skip("only one backend installed; nothing to compare against")

        # Compared against each other rather than a constant: the property that
        # matters is that switching databases does not change the answer, and a
        # hard-coded score would only pin the corpus in place.
        reference = next(iter(ranking))
        for name, order in ranking.items():
            assert order == ranking[reference], f"{name} ordered differently to {reference}"
            assert scores[name] == pytest.approx(scores[reference], abs=0.01), name

    def test_every_backend_filters_and_deletes(self, tmp_path, embedder):
        for name, store in self.stores(tmp_path):
            store.upsert("knowledge", records(embedder))
            hits = store.search("knowledge", embedder.embed_query("statements"),
                                top_k=5, where={"source": "sql.md"})
            assert {hit.source for hit in hits} == {"sql.md"}, name
            assert store.delete("knowledge", where={"source": "audit.md"}) == 1, name
            assert store.stats("knowledge")["chunks"] == len(HANDBOOK) - 1, name


class TestService:
    @pytest.fixture
    def service(self):
        return RagService(RagConfig(backend="sqlite"), store=SqliteVectorStore(":memory:"))

    def test_ingest_then_retrieve(self, service):
        service.ingest_text(HANDBOOK[1][1], source="audit.md", collection="handbook")
        hits = service.query("quiet edit of the log", collection="handbook")
        assert hits and hits[0]["source"] == "audit.md"

    def test_reingest_replaces_rather_than_duplicating(self, service):
        body = " ".join(f"Paragraph {n} of the handbook explains a rule." for n in range(60))
        first = service.ingest_text(body, source="handbook.md", collection="handbook")
        assert first.chunks > 1
        second = service.ingest_text(body, source="handbook.md", collection="handbook")
        assert second.replaced == first.chunks
        assert service.stats("handbook")["chunks"] == second.chunks

    def test_a_document_that_shrank_leaves_no_orphans(self, service):
        long_body = " ".join(f"Rule {n} applies to deployments." for n in range(80))
        service.ingest_text(long_body, source="rules.md", collection="handbook")
        service.ingest_text("Rule 1 applies.", source="rules.md", collection="handbook")
        # Upserting by id alone would leave the tail of the longer version behind,
        # still answering questions from text the document no longer contains.
        assert service.stats("handbook")["chunks"] == 1

    def test_empty_document_is_reported_not_raised(self, service):
        result = service.ingest_text("   ", source="blank.md")
        assert result.chunks == 0 and result.note

    def test_query_before_anything_is_ingested(self, service):
        assert service.query("anything", collection="empty") == []

    def test_blank_query_returns_nothing(self, service):
        service.ingest_text(HANDBOOK[0][1], source="deploy.md")
        assert service.query("   ") == []

    def test_delete_document(self, service):
        service.ingest_text(HANDBOOK[0][1], source="deploy.md", collection="handbook")
        assert service.delete_document("deploy.md", "handbook") == 1
        assert service.stats("handbook")["chunks"] == 0

    def test_collection_names_are_normalised_consistently(self, service):
        service.ingest_text(HANDBOOK[0][1], source="deploy.md", collection="My Docs!")
        assert service.query("deployments", collection="My Docs!")
        assert "My-Docs" in service.collections()

    def test_chunk_ids_are_stable_across_runs(self, service):
        assert RagService._chunk_id("a.md", 3) == RagService._chunk_id("a.md", 3)
        assert RagService._chunk_id("a.md", 3) != RagService._chunk_id("b.md", 3)


class TestTools:
    """The contract the CrewAI runtime and configs/tools.json depend on."""

    @pytest.fixture(autouse=True)
    def isolated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))
        from src.rag import service as service_module

        service_module.reset_rag_service()
        yield
        service_module.reset_rag_service()

    @pytest.mark.asyncio
    async def test_query_returns_the_runtime_contract(self):
        from src.tools.rag_pipeline import ingest_text, query_rag

        await ingest_text(HANDBOOK[1][1], source="audit.md", collection="handbook")
        result = await query_rag(query="quiet edit", collection="handbook", top_k=3)
        assert result["success"] is True
        assert result["error"] is None
        assert isinstance(result["results"], list)
        assert result["total_results"] == len(result["results"])
        assert {"text", "score", "source"} <= set(result["results"][0])

    @pytest.mark.asyncio
    async def test_query_without_a_query(self):
        from src.tools.rag_pipeline import query_rag

        result = await query_rag(query="")
        assert result["success"] is False and result["results"] == []

    @pytest.mark.asyncio
    async def test_ingest_missing_file_is_reported_not_raised(self):
        from src.tools.rag_pipeline import ingest_file

        result = await ingest_file(collection="handbook", file_path="/nope/missing.pdf")
        assert result["success"] is False and result["documents_processed"] == 0

    @pytest.mark.asyncio
    async def test_ingest_file_round_trip(self, tmp_path):
        from src.tools.rag_pipeline import ingest_file, list_files, query_rag

        document = tmp_path / "handbook.md"
        document.write_text("\n\n".join(text for _, text in HANDBOOK))

        ingested = await ingest_file(collection="handbook", file_path=str(document))
        assert ingested["success"] and ingested["documents_processed"] >= 1

        listed = await list_files(collection="handbook")
        assert "handbook.md" in listed["files"]

        found = await query_rag(query="read only sql", collection="handbook")
        assert found["success"] and found["results"]

    @pytest.mark.asyncio
    async def test_delete_missing_document_is_honest(self):
        from src.tools.rag_pipeline import delete_file

        result = await delete_file("never-existed.md", collection="handbook")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_disabled_reports_rather_than_hanging(self, monkeypatch):
        from src.config import settings as settings_module
        from src.tools import rag_pipeline

        monkeypatch.setattr(
            settings_module.get_settings().external_services, "rag_pipeline_enabled", False
        )
        result = await rag_pipeline.query_rag(query="anything")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

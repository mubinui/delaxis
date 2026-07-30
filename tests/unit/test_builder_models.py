"""Builder tasks route to the strongest model that is actually reachable.

Before this, each endpoint carried a literal default, so a fresh install planned
whole chatbots and generated frontends on ``gpt-oss-20b``. The properties that
matter: an unpinned request escalates, a pinned one never does, and a provider
without a key is never escalated to (which would turn a working build into an
authentication error).
"""

import json

import pytest

from src.api.builder_models import choose_model, ranked_models


def _providers_file(tmp_path, providers):
    path = tmp_path / "api_providers.json"
    path.write_text(json.dumps({"version": "1.0", "providers": providers}))
    return path


def _provider(provider_id, models, *, env_var="KEY", required=True, enabled=True):
    return {
        "id": provider_id,
        "name": provider_id,
        "type": "llm",
        "base_url": f"https://{provider_id}.test/v1",
        "enabled": enabled,
        "auth": {"scheme": "bearer", "env_var": env_var, "required": required},
        "models": [{"name": m} for m in models],
    }


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A provider set where the frontier models live behind a keyed provider."""
    providers = [
        _provider("openrouter", ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5",
                                 "google/gemini-3.6-flash", "openai/gpt-oss-20b"],
                  env_var="OPENROUTER_API_KEY"),
        _provider("local", ["some-local-model"], required=False),
    ]
    path = _providers_file(tmp_path, providers)
    monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return path


class TestEscalation:
    @pytest.mark.parametrize(
        "task,expected",
        [
            ("plan", "anthropic/claude-opus-5"),
            ("config", "anthropic/claude-opus-5"),
            ("tool", "anthropic/claude-opus-5"),
            ("frontend", "anthropic/claude-opus-5"),
            # Small JSON and interactive work go to a faster model on purpose.
            ("design", "anthropic/claude-sonnet-5"),
            ("chat", "anthropic/claude-sonnet-5"),
            ("explain", "google/gemini-3.6-flash"),
        ],
    )
    def test_task_gets_its_ranked_best(self, catalog, task, expected):
        choice = choose_model(task)
        assert choice.model_id == expected
        assert choice.escalated is True

    def test_never_lands_on_the_old_cheap_default(self, catalog):
        # The regression this whole module exists to prevent.
        for task in ("plan", "config", "tool", "frontend"):
            assert choose_model(task).model_id != "openai/gpt-oss-20b"


class TestPinning:
    def test_explicit_model_is_honoured(self, catalog):
        choice = choose_model(
            "frontend", requested_provider="openrouter", requested_model="openai/gpt-oss-20b"
        )
        assert choice.model_id == "openai/gpt-oss-20b"
        assert choice.provider_id == "openrouter"
        assert choice.escalated is False

    def test_pinning_survives_even_for_an_unlisted_model(self, catalog):
        # A deliberate choice must not be second-guessed.
        choice = choose_model("plan", requested_provider="custom", requested_model="my-model")
        assert (choice.provider_id, choice.model_id) == ("custom", "my-model")
        assert choice.escalated is False


class TestProviderScoping:
    """A named provider is respected even when a better model lives elsewhere.

    Silently relocating the request would swallow a typo'd or unconfigured
    provider id that the caller needs to see as a 400.
    """

    def test_escalates_only_within_the_named_provider(self, tmp_path, monkeypatch):
        providers = [
            _provider("strong", ["anthropic/claude-opus-5"], required=False),
            _provider("weak", ["google/gemini-3.6-flash", "openai/gpt-oss-20b"], required=False),
        ]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)

        choice = choose_model("plan", requested_provider="weak")
        assert choice.provider_id == "weak"
        # Best *within* weak, not the globally best model.
        assert choice.model_id == "google/gemini-3.6-flash"
        assert choice.escalated is True

    def test_unknown_provider_is_handed_back_untouched(self, catalog):
        choice = choose_model("plan", requested_provider="ghost")
        assert choice.provider_id == "ghost"
        assert choice.model_id == ""
        assert choice.escalated is False

    def test_keyless_named_provider_is_handed_back_untouched(self, tmp_path, monkeypatch):
        providers = [_provider("needs_key", ["anthropic/claude-opus-5"], env_var="NEEDS_KEY")]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.delenv("NEEDS_KEY", raising=False)
        choice = choose_model("frontend", requested_provider="needs_key")
        assert (choice.provider_id, choice.model_id) == ("needs_key", "")


class TestKeyAwareness:
    def test_provider_without_a_key_is_skipped(self, tmp_path, monkeypatch):
        providers = [
            _provider("anthropic", ["anthropic/claude-opus-5"], env_var="ANTHROPIC_API_KEY"),
            _provider("openrouter", ["google/gemini-3.6-flash"], env_var="OPENROUTER_API_KEY"),
        ]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        # Opus ranks first for planning but has no key, so it must be passed over
        # rather than escalated to.
        choice = choose_model("plan")
        assert choice.model_id == "google/gemini-3.6-flash"
        assert choice.provider_id == "openrouter"

    def test_keyless_provider_is_usable_when_auth_not_required(self, tmp_path, monkeypatch):
        providers = [_provider("local", ["local-llama"], required=False)]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        assert choose_model("plan").model_id == "local-llama"

    def test_disabled_provider_is_ignored(self, tmp_path, monkeypatch):
        providers = [
            _provider("openrouter", ["anthropic/claude-opus-5"],
                      env_var="OPENROUTER_API_KEY", enabled=False),
            _provider("local", ["local-llama"], required=False),
        ]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert choose_model("plan").model_id == "local-llama"


class TestFallbacks:
    def test_unranked_model_is_used_rather_than_failing(self, tmp_path, monkeypatch):
        # A working build on an unranked model beats no build.
        providers = [_provider("local", ["some-unknown-model"], required=False)]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        choice = choose_model("plan")
        assert choice.model_id == "some-unknown-model"
        assert "no preferred model" in choice.reason

    def test_no_usable_provider_returns_empty_for_the_caller_to_report(self, tmp_path, monkeypatch):
        providers = [_provider("anthropic", ["anthropic/claude-opus-5"], env_var="ANTHROPIC_API_KEY")]
        path = _providers_file(tmp_path, providers)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        choice = choose_model("plan")
        assert choice.model_id == ""
        assert choice.escalated is False

    def test_unknown_task_falls_back_to_the_config_ranking(self, catalog):
        assert choose_model("not-a-task").model_id == "anthropic/claude-opus-5"  # type: ignore[arg-type]


class TestRankings:
    def test_every_task_declares_a_ranking(self):
        for task in ("plan", "config", "tool", "frontend", "design", "chat", "explain"):
            assert ranked_models(task), f"{task} has no ranked models"

    def test_reasoning_tasks_rank_a_frontier_model_first(self):
        for task in ("plan", "config", "tool"):
            assert ranked_models(task)[0] == "anthropic/claude-opus-5"

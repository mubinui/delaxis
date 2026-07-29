"""Keys pasted in the studio must never reach the git-tracked config file."""

import json
import os
import stat

import pytest

from src.config import provider_registry, provider_secrets


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OAK_DATA_DIR", str(tmp_path))
    yield tmp_path / "provider_secrets.json"


@pytest.fixture
def providers_file(tmp_path, monkeypatch):
    def _write(providers):
        path = tmp_path / "api_providers.json"
        path.write_text(json.dumps({"version": "2.0", "providers": providers}), encoding="utf-8")
        monkeypatch.setattr(provider_registry, "_providers_path", lambda: path)
        return path

    return _write


class TestStore:
    def test_round_trip(self, store):
        assert provider_secrets.get_secret("p1") is None
        provider_secrets.set_secret("p1", "sk-abc")
        assert provider_secrets.get_secret("p1") == "sk-abc"
        assert provider_secrets.has_secret("p1") is True

    def test_file_is_owner_only(self, store):
        provider_secrets.set_secret("p1", "sk-abc")
        mode = stat.S_IMODE(os.stat(store).st_mode)
        assert mode == 0o600, f"secret store is {oct(mode)}, expected 0o600"

    def test_delete(self, store):
        provider_secrets.set_secret("p1", "sk-abc")
        assert provider_secrets.delete_secret("p1") is True
        assert provider_secrets.get_secret("p1") is None
        assert provider_secrets.delete_secret("p1") is False

    def test_corrupt_file_does_not_crash_callers(self, store):
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("{not json", encoding="utf-8")
        assert provider_secrets.get_secret("p1") is None

    def test_empty_key_rejected(self, store):
        with pytest.raises(ValueError):
            provider_secrets.set_secret("p1", "")

    def test_listing(self, store):
        provider_secrets.set_secret("b", "k")
        provider_secrets.set_secret("a", "k")
        assert provider_secrets.list_secret_ids() == ["a", "b"]


class TestPrecedence:
    """inline (legacy) -> secret store -> environment."""

    def _provider(self):
        return [
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ]

    def test_env_used_when_nothing_stored(self, store, providers_file, monkeypatch):
        providers_file(self._provider())
        monkeypatch.setenv("P1_KEY", "env-key")
        assert provider_registry.resolve_api_key("p1") == "env-key"
        assert provider_registry.key_source("p1") == "env"

    def test_store_beats_env(self, store, providers_file, monkeypatch):
        providers_file(self._provider())
        monkeypatch.setenv("P1_KEY", "env-key")
        provider_secrets.set_secret("p1", "stored-key")
        assert provider_registry.resolve_api_key("p1") == "stored-key"
        assert provider_registry.key_source("p1") == "secret_store"

    def test_inline_legacy_key_still_wins(self, store, providers_file, monkeypatch):
        providers = self._provider()
        providers[0]["api_key"] = "inline-key"
        providers_file(providers)
        monkeypatch.setenv("P1_KEY", "env-key")
        provider_secrets.set_secret("p1", "stored-key")
        assert provider_registry.resolve_api_key("p1") == "inline-key"
        assert provider_registry.key_source("p1") == "inline"

    def test_deployments_get_the_env_key_when_nothing_is_pasted(self, store, providers_file, monkeypatch):
        """Deployments run in-process against the same registry, so this is the
        whole mechanism behind 'deployments use the key from the environment'."""
        providers_file(self._provider())
        monkeypatch.setenv("P1_KEY", "env-key")
        resolved = provider_registry.resolve_llm("p1", "some-model")
        assert resolved.api_key == "env-key"

    def test_no_key_anywhere(self, store, providers_file, monkeypatch):
        providers_file(self._provider())
        monkeypatch.delenv("P1_KEY", raising=False)
        assert provider_registry.resolve_api_key("p1") is None
        assert provider_registry.key_source("p1") == "none"

    def test_unknown_provider_is_not_an_error(self, store, providers_file):
        providers_file(self._provider())
        assert provider_registry.resolve_api_key("ghost") is None
        assert provider_registry.key_source("ghost") == "none"

"""Property-based tests for API provider management."""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.api_provider_models import mask_api_key


# **Feature: config-management-ui, Property 12: API key masking**
@given(
    api_key=st.one_of(
        st.none(),
        st.text(min_size=0, max_size=100),
    )
)
@settings(max_examples=100)
def test_api_key_masking(api_key):
    """
    Test that API key masking shows only last 4 characters.
    
    For any API provider response, the api_key field should be masked
    showing only the last 4 characters.
    
    Validates: Requirements 3.3
    """
    masked = mask_api_key(api_key)
    
    if api_key is None or len(api_key) == 0:
        # None or empty string should return None
        assert masked is None
    elif len(api_key) <= 4:
        # Short keys should be fully masked
        assert masked == "*" * len(api_key)
        # The mask must not leak the key. A key that is itself all asterisks is
        # equal to its own mask, which leaks nothing — so it is not a violation,
        # and the earlier `api_key not in masked` form failed on inputs like "*".
        assert set(masked) <= {"*"}
    else:
        # Keys longer than 4 chars should show last 4
        assert masked is not None
        assert len(masked) == len(api_key)
        assert masked.endswith(api_key[-4:])
        assert masked.startswith("*")
        # Everything except the last 4 characters must be masked out
        assert masked == "*" * (len(api_key) - 4) + api_key[-4:]


# **Feature: config-management-ui, Property 1: Configuration CRUD consistency**
@given(
    provider_id=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=20,
    ).filter(lambda x: x and x[0].isalpha()),
    name=st.text(min_size=1, max_size=100),
    provider_type=st.sampled_from(["llm", "tool", "api"]),
    description=st.text(min_size=1, max_size=500),
    base_url=st.one_of(
        st.none(),
        st.text(min_size=10, max_size=200).filter(lambda x: "://" in x)
    ),
    api_key=st.one_of(st.none(), st.text(min_size=10, max_size=100)),
    enabled=st.booleans(),
)
@settings(max_examples=100)
def test_api_provider_crud_consistency(
    provider_id, name, provider_type, description, base_url, api_key, enabled
):
    """
    Test that creating an API provider and then retrieving it returns the same data.
    
    For any API provider configuration, creating it and then reading it back should
    return the exact same data that was created.
    
    Validates: Requirements 3.2
    """
    # Create a temporary config file
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "api_providers.json"
        
        # Initialize empty config
        initial_config = {"version": "1.0", "providers": []}
        with open(config_path, "w") as f:
            json.dump(initial_config, f)
        
        # Create provider data
        provider_data = {
            "id": provider_id,
            "name": name,
            "type": provider_type,
            "description": description,
            "enabled": enabled,
            "config": {},
        }
        
        if base_url:
            provider_data["base_url"] = base_url
        
        if api_key:
            provider_data["api_key"] = api_key
        
        # Write provider to config (CREATE)
        config = initial_config.copy()
        config["providers"].append(provider_data)
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        # Read provider from config (READ)
        with open(config_path, "r") as f:
            loaded_config = json.load(f)
        
        retrieved_provider = next(
            (p for p in loaded_config["providers"] if p["id"] == provider_id),
            None
        )
        
        # Assert CRUD consistency
        assert retrieved_provider is not None, "Provider should be retrievable after creation"
        assert retrieved_provider["id"] == provider_id
        assert retrieved_provider["name"] == name
        assert retrieved_provider["type"] == provider_type
        assert retrieved_provider["description"] == description
        assert retrieved_provider["enabled"] == enabled
        
        if base_url:
            assert retrieved_provider.get("base_url") == base_url
        
        if api_key:
            assert retrieved_provider.get("api_key") == api_key


def test_api_key_masking_specific_examples():
    """Test API key masking with specific examples."""
    # Empty string
    assert mask_api_key("") is None
    
    # None
    assert mask_api_key(None) is None
    
    # Short keys (4 or fewer characters)
    assert mask_api_key("a") == "*"
    assert mask_api_key("ab") == "**"
    assert mask_api_key("abc") == "***"
    assert mask_api_key("abcd") == "****"
    
    # Longer keys
    assert mask_api_key("abcde") == "*bcde"
    assert mask_api_key("sk-1234567890") == "*********7890"  # 14 chars: 10 asterisks + "7890"
    assert mask_api_key("very_long_api_key_12345") == "*******************2345"  # 23 chars: 19 asterisks + "2345"


def test_api_provider_crud_with_minimal_fields():
    """Test CRUD with minimal required fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "api_providers.json"
        
        initial_config = {"version": "1.0", "providers": []}
        with open(config_path, "w") as f:
            json.dump(initial_config, f)
        
        provider_data = {
            "id": "test_provider",
            "name": "Test Provider",
            "type": "api",
            "description": "A test provider",
            "enabled": True,
            "config": {},
        }
        
        config = initial_config.copy()
        config["providers"].append(provider_data)
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        with open(config_path, "r") as f:
            loaded_config = json.load(f)
        
        retrieved = next(
            (p for p in loaded_config["providers"] if p["id"] == "test_provider"),
            None
        )
        
        assert retrieved is not None
        assert retrieved["id"] == "test_provider"
        assert retrieved["name"] == "Test Provider"


def test_api_provider_crud_with_all_fields():
    """Test CRUD with all optional fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "api_providers.json"
        
        initial_config = {"version": "1.0", "providers": []}
        with open(config_path, "w") as f:
            json.dump(initial_config, f)
        
        provider_data = {
            "id": "full_provider",
            "name": "Full Provider",
            "type": "llm",
            "description": "A provider with all fields",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key-12345",
            "enabled": False,
            "config": {"timeout": 30, "max_retries": 3},
        }
        
        config = initial_config.copy()
        config["providers"].append(provider_data)
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        with open(config_path, "r") as f:
            loaded_config = json.load(f)
        
        retrieved = next(
            (p for p in loaded_config["providers"] if p["id"] == "full_provider"),
            None
        )
        
        assert retrieved is not None
        assert retrieved["id"] == "full_provider"
        assert retrieved["base_url"] == "https://api.example.com/v1"
        assert retrieved["api_key"] == "sk-test-key-12345"
        assert retrieved["enabled"] is False
        assert retrieved["config"]["timeout"] == 30

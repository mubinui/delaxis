"""Property-based tests for configuration validation rejection."""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from src.config.prompt_models import PromptTemplateConfig
from src.config.api_provider_models import APIProviderCreateRequest


# **Feature: config-management-ui, Property 5: Validation rejection**
@given(
    # Generate invalid prompt configurations
    id_field=st.one_of(
        st.none(),  # Missing ID
        st.just(""),  # Empty ID
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ-!@#$%", min_size=1, max_size=20),  # Invalid characters
    ),
    name=st.one_of(st.none(), st.just("")),  # Missing or empty name
    description=st.one_of(st.none(), st.just("")),  # Missing or empty description
    template=st.one_of(
        st.none(),  # Missing template
        st.just(""),  # Empty template
        st.just("   "),  # Whitespace only
        st.just("Hello {unclosed"),  # Unclosed brace
        st.just("Hello {name}}"),  # Extra closing brace
        st.just("Hello {{nested}}"),  # Nested braces (technically valid but we'll test)
        st.just("Hello {123invalid}"),  # Invalid variable name starting with number
        st.just("Hello {-invalid}"),  # Invalid variable name with special char
    ),
)
@settings(max_examples=100)
def test_prompt_validation_rejection(id_field, name, description, template):
    """
    Test that invalid prompt configurations are rejected with specific error messages.
    
    For any invalid configuration (missing required fields, invalid references),
    the system should reject the save operation and return specific error messages.
    
    Validates: Requirements 8.1, 8.4
    """
    # Skip if all fields are valid (we want to test invalid cases)
    if all([
        id_field and isinstance(id_field, str) and id_field.strip() and 
        all(c.islower() or c.isdigit() or c == '_' for c in id_field),
        name and isinstance(name, str) and name.strip(),
        description and isinstance(description, str) and description.strip(),
        template and isinstance(template, str) and template.strip() and
        '{' not in template  # No variables to validate
    ]):
        assume(False)  # Skip valid configurations
    
    # Attempt to create prompt configuration
    with pytest.raises((ValidationError, ValueError, TypeError)) as exc_info:
        config_data = {}
        
        if id_field is not None:
            config_data["id"] = id_field
        if name is not None:
            config_data["name"] = name
        if description is not None:
            config_data["description"] = description
        if template is not None:
            config_data["template"] = template
        
        # Add variables list (empty for now)
        config_data["variables"] = []
        
        PromptTemplateConfig(**config_data)
    
    # Assert that an error was raised (validation rejection occurred)
    assert exc_info.value is not None
    
    # Assert that error message is specific and informative
    error_message = str(exc_info.value).lower()
    
    # Check that error message contains relevant information
    if id_field is None or (isinstance(id_field, str) and not id_field.strip()):
        assert any(keyword in error_message for keyword in ["id", "required", "field", "missing"])
    elif id_field and any(c.isupper() or c in "-!@#$%" for c in id_field):
        assert any(keyword in error_message for keyword in ["id", "pattern", "invalid", "match"])
    
    if name is None or (isinstance(name, str) and not name.strip()):
        assert any(keyword in error_message for keyword in ["name", "required", "field", "missing"])
    
    if description is None or (isinstance(description, str) and not description.strip()):
        assert any(keyword in error_message for keyword in ["description", "required", "field", "missing"])
    
    if template is not None:
        if not template.strip():
            assert any(keyword in error_message for keyword in ["template", "empty", "cannot"])
        elif "unclosed" in template or template.count("{") != template.count("}"):
            assert any(keyword in error_message for keyword in ["brace", "mismatch", "template"])
        elif "123invalid" in template or "-invalid" in template:
            assert any(keyword in error_message for keyword in ["variable", "invalid", "name"])


# **Feature: config-management-ui, Property 5: Validation rejection**
@given(
    # Generate invalid API provider configurations
    id_field=st.one_of(
        st.none(),  # Missing ID
        st.just(""),  # Empty ID
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ-!@#$%", min_size=1, max_size=20),  # Invalid characters
    ),
    name=st.one_of(st.none(), st.just("")),  # Missing or empty name
    provider_type=st.one_of(
        st.none(),  # Missing type
        st.just(""),  # Empty type
        st.just("invalid_type"),  # Invalid type value
        st.just("LLM"),  # Wrong case
    ),
    description=st.one_of(st.none(), st.just("")),  # Missing or empty description
)
@settings(max_examples=100)
def test_api_provider_validation_rejection(id_field, name, provider_type, description):
    """
    Test that invalid API provider configurations are rejected with specific error messages.
    
    For any invalid configuration (missing required fields, invalid type values),
    the system should reject the save operation and return specific error messages.
    
    Validates: Requirements 8.1, 8.4
    """
    # Skip if all fields are valid
    if all([
        id_field and isinstance(id_field, str) and id_field.strip() and 
        all(c.islower() or c.isdigit() or c == '_' for c in id_field),
        name and isinstance(name, str) and name.strip(),
        provider_type in ["llm", "tool", "api"],
        description and isinstance(description, str) and description.strip(),
    ]):
        assume(False)  # Skip valid configurations
    
    # Attempt to create API provider configuration
    with pytest.raises((ValidationError, ValueError, TypeError)) as exc_info:
        config_data = {}
        
        if id_field is not None:
            config_data["id"] = id_field
        if name is not None:
            config_data["name"] = name
        if provider_type is not None:
            config_data["type"] = provider_type
        if description is not None:
            config_data["description"] = description
        
        APIProviderCreateRequest(**config_data)
    
    # Assert that an error was raised (validation rejection occurred)
    assert exc_info.value is not None
    
    # Assert that error message is specific and informative
    error_message = str(exc_info.value).lower()
    
    # Check that error message contains relevant information
    if id_field is None or (isinstance(id_field, str) and not id_field.strip()):
        assert any(keyword in error_message for keyword in ["id", "required", "field", "missing"])
    elif id_field and any(c.isupper() or c in "-!@#$%" for c in id_field):
        assert any(keyword in error_message for keyword in ["id", "pattern", "invalid", "match"])
    
    if name is None or (isinstance(name, str) and not name.strip()):
        assert any(keyword in error_message for keyword in ["name", "required", "field", "missing"])
    
    if provider_type is None or (isinstance(provider_type, str) and not provider_type.strip()):
        assert any(keyword in error_message for keyword in ["type", "required", "field", "missing"])
    elif provider_type and provider_type not in ["llm", "tool", "api"]:
        assert any(keyword in error_message for keyword in ["type", "must be one of", "llm", "tool", "api"])
    
    if description is None or (isinstance(description, str) and not description.strip()):
        assert any(keyword in error_message for keyword in ["description", "required", "field", "missing"])


def test_prompt_missing_required_fields():
    """Test that prompts with missing required fields are rejected."""
    # Missing ID
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            name="Test",
            description="Test description",
            template="Hello {name}",
            variables=["name"]
        )
    assert "id" in str(exc_info.value).lower()
    
    # Missing name
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            description="Test description",
            template="Hello {name}",
            variables=["name"]
        )
    assert "name" in str(exc_info.value).lower()
    
    # Missing description
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            template="Hello {name}",
            variables=["name"]
        )
    assert "description" in str(exc_info.value).lower()
    
    # Missing template
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            variables=["name"]
        )
    assert "template" in str(exc_info.value).lower()


def test_prompt_invalid_id_format():
    """Test that prompts with invalid ID format are rejected."""
    # ID with uppercase letters
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            id="TestPrompt",
            name="Test",
            description="Test description",
            template="Hello",
            variables=[]
        )
    assert "id" in str(exc_info.value).lower()
    
    # ID with special characters
    with pytest.raises(ValidationError) as exc_info:
        PromptTemplateConfig(
            id="test-prompt",
            name="Test",
            description="Test description",
            template="Hello",
            variables=[]
        )
    assert "id" in str(exc_info.value).lower()


def test_prompt_invalid_template_syntax():
    """Test that prompts with invalid template syntax are rejected."""
    # Unclosed brace
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {name",
            variables=["name"]
        )
    assert "brace" in str(exc_info.value).lower()
    
    # Extra closing brace
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {name}}",
            variables=["name"]
        )
    assert "brace" in str(exc_info.value).lower()
    
    # Invalid variable name
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {123invalid}",
            variables=["123invalid"]
        )
    assert "variable" in str(exc_info.value).lower()


def test_prompt_empty_template():
    """Test that prompts with empty template are rejected."""
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="",
            variables=[]
        )
    assert "empty" in str(exc_info.value).lower()
    
    # Whitespace only
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="   ",
            variables=[]
        )
    assert "empty" in str(exc_info.value).lower()


def test_prompt_variable_mismatch():
    """Test that prompts with mismatched variables are rejected."""
    # Variables in template but not in list
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {name} and {age}",
            variables=["name"]  # Missing 'age'
        )
    error_msg = str(exc_info.value).lower()
    assert "variable" in error_msg
    assert "age" in error_msg
    
    # Variables in list but not in template
    with pytest.raises(ValueError) as exc_info:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {name}",
            variables=["name", "age"]  # Extra 'age'
        )
    error_msg = str(exc_info.value).lower()
    assert "variable" in error_msg
    assert "age" in error_msg


def test_api_provider_missing_required_fields():
    """Test that API providers with missing required fields are rejected."""
    # Missing ID
    with pytest.raises(ValidationError) as exc_info:
        APIProviderCreateRequest(
            name="Test Provider",
            type="llm",
            description="Test description"
        )
    assert "id" in str(exc_info.value).lower()
    
    # Missing name
    with pytest.raises(ValidationError) as exc_info:
        APIProviderCreateRequest(
            id="test_provider",
            type="llm",
            description="Test description"
        )
    assert "name" in str(exc_info.value).lower()
    
    # Missing type
    with pytest.raises(ValidationError) as exc_info:
        APIProviderCreateRequest(
            id="test_provider",
            name="Test Provider",
            description="Test description"
        )
    assert "type" in str(exc_info.value).lower()
    
    # Missing description
    with pytest.raises(ValidationError) as exc_info:
        APIProviderCreateRequest(
            id="test_provider",
            name="Test Provider",
            type="llm"
        )
    assert "description" in str(exc_info.value).lower()


def test_api_provider_invalid_type():
    """Test that API providers with invalid type are rejected."""
    with pytest.raises(ValueError) as exc_info:
        APIProviderCreateRequest(
            id="test_provider",
            name="Test Provider",
            type="invalid_type",
            description="Test description"
        )
    error_msg = str(exc_info.value).lower()
    assert "type" in error_msg
    assert any(keyword in error_msg for keyword in ["llm", "tool", "api"])


def test_api_provider_invalid_id_format():
    """Test that API providers with invalid ID format are rejected."""
    for invalid_id in ["TestProvider", "test provider", "test.provider", "-test", "test/provider"]:
        with pytest.raises(ValidationError) as exc_info:
            APIProviderCreateRequest(
                id=invalid_id,
                name="Test Provider",
                type="llm",
                description="Test description"
            )
        assert "id" in str(exc_info.value).lower()


def test_api_provider_hyphenated_id_is_accepted():
    """Hyphens are needed for real provider ids like lm-studio and zhipu-ai."""
    provider = APIProviderCreateRequest(
        id="lm-studio",
        name="LM Studio",
        type="llm",
        description="Local OpenAI-compatible server"
    )
    assert provider.id == "lm-studio"


def test_validation_error_messages_are_specific():
    """Test that validation errors provide specific, actionable messages."""
    # Test prompt validation error specificity
    try:
        PromptTemplateConfig(
            id="test_prompt",
            name="Test",
            description="Test description",
            template="Hello {invalid-var}",
            variables=["invalid-var"]
        )
        pytest.fail("Should have raised ValueError")
    except ValueError as e:
        error_msg = str(e)
        # Error should mention the specific problem
        assert "variable" in error_msg.lower()
        assert "invalid" in error_msg.lower() or "name" in error_msg.lower()
    
    # Test API provider validation error specificity
    try:
        APIProviderCreateRequest(
            id="test_provider",
            name="Test",
            type="database",  # Invalid type
            description="Test"
        )
        pytest.fail("Should have raised ValueError")
    except ValueError as e:
        error_msg = str(e)
        # Error should mention valid types
        assert "llm" in error_msg.lower() or "tool" in error_msg.lower() or "api" in error_msg.lower()

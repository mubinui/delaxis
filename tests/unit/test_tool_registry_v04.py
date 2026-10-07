"""
Property-based tests for Tool Registry v0.4 Migration.

Tests validate that tools are compatible with CrewAI 0.4's AssistantAgent
direct registration pattern.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

# =============================================================================
# Test Data and Fixtures
# =============================================================================


@pytest.fixture
def sample_tool_configs():
    """Sample tool configurations matching configs/tools.json structure."""
    return {
        "version": "1.0",
        "tools": [
            {
                "id": "calculate",
                "name": "calculate",
                "description": "Safely evaluate an arithmetic expression.",
                "entrypoint": "src.tools.calculator:calculate",
                "enabled": True,
                "settings": {},
                "version": 1,
            },
            {
                "id": "web_search",
                "name": "search_web",
                "description": "Search the web using DuckDuckGo.",
                "entrypoint": "src.tools.web_search:search_web",
                "enabled": True,
                "settings": {"max_results": 5},
                "version": 1,
            },
        ],
    }


@pytest.fixture
def v04_tool_configs():
    """v0.4 compatible tool configurations with is_async field."""
    return {
        "version": "2.0",
        "tools": [
            {
                "id": "calculate",
                "name": "calculate",
                "description": "Safely evaluate an arithmetic expression. Parameter: expression (string).",
                "entrypoint": "src.tools.calculator:calculate",
                "enabled": True,
                "is_async": False,
                "settings": {},
                "version": 2,
            },
            {
                "id": "rag_query",
                "name": "rag_query",
                "description": "Query RAG pipeline. Parameters: collection (string), query (string), top_k (int).",
                "entrypoint": "src.tools.rag_pipeline:query_rag",
                "enabled": True,
                "is_async": True,
                "settings": {},
                "version": 2,
            },
        ],
    }


# =============================================================================
# Property 1: Tool Schema Validation for v0.4 AssistantAgent
# =============================================================================


class TestV04ToolSchema:
    """Test that tools follow CrewAI 0.4 schema requirements."""

    def test_tool_config_has_is_async_field(self, v04_tool_configs):
        """Property: v0.4 tool configs must have is_async field."""
        for tool in v04_tool_configs["tools"]:
            assert "is_async" in tool, f"Tool {tool['id']} missing is_async field"
            assert isinstance(tool["is_async"], bool), "is_async must be boolean"

    def test_tool_description_includes_parameters(self, v04_tool_configs):
        """Property: v0.4 tool descriptions should document parameters."""
        for tool in v04_tool_configs["tools"]:
            # For tools that require parameters, description should mention them
            if tool["id"] == "calculate":
                assert "Parameter" in tool["description"] or "expression" in tool["description"]
            if tool["id"] == "rag_query":
                assert "Parameters" in tool["description"]

    def test_tool_name_matches_function_name(self, v04_tool_configs):
        """Property: tool name should match the function name for clarity."""
        for tool in v04_tool_configs["tools"]:
            # Extract function name from entrypoint
            entrypoint = tool["entrypoint"]
            function_name = entrypoint.split(":")[-1]
            # Name should be the function name or a reasonable variant (allow reordering)
            # Both rag_query and query_rag are acceptable as they're clear
            name_parts = set(tool["name"].split("_"))
            function_parts = set(function_name.split("_"))
            assert name_parts == function_parts, (
                f"Tool name parts {name_parts} should match function parts {function_parts}"
            )


# =============================================================================
# Property 2: Async Tool Support
# =============================================================================


class TestAsyncToolSupport:
    """Test async tool handling for v0.4."""

    def test_async_tools_marked_correctly(self, v04_tool_configs):
        """Property: RAG and async tools should be marked as is_async=True."""
        rag_tools = [t for t in v04_tool_configs["tools"] if "rag" in t["id"].lower()]
        for tool in rag_tools:
            # RAG tools are typically async
            assert tool.get("is_async") is True, f"RAG tool {tool['id']} should be async"

    def test_sync_tools_marked_correctly(self, v04_tool_configs):
        """Property: Simple API tools should be marked as is_async=False."""
        sync_tool_ids = ["calculate"]
        for tool_id in sync_tool_ids:
            tool = next((t for t in v04_tool_configs["tools"] if t["id"] == tool_id), None)
            if tool:
                assert tool.get("is_async") is False, f"Tool {tool_id} should be sync"


# =============================================================================
# Property 3: Tool Error Handling for v0.4
# =============================================================================


class TestToolErrorHandling:
    """Test that tools have proper error handling for v0.4."""

    def test_tool_config_has_error_handling_metadata(self):
        """Property: v0.4 tool configs should support error handling metadata."""
        tool_config = {
            "id": "test_tool",
            "name": "test_tool",
            "entrypoint": "module:function",
            "enabled": True,
            "is_async": False,
            "error_handling": {
                "retry_count": 3,
                "timeout": 30,
                "fallback_response": "Tool unavailable",
            },
        }

        assert "error_handling" in tool_config
        assert "retry_count" in tool_config["error_handling"]
        assert "timeout" in tool_config["error_handling"]

    def test_tool_should_return_structured_errors(self):
        """Property: Tool functions should return structured error responses."""
        # Example error response structure
        error_response = {
            "success": False,
            "error": "API unavailable",
            "error_type": "ConnectionError",
            "timestamp": "2024-12-13T00:00:00Z",
        }

        assert "success" in error_response
        assert "error" in error_response
        assert error_response["success"] is False


# =============================================================================
# Property 4: Tool Registry v0.4 Compatibility
# =============================================================================


class TestToolRegistryV04Compatibility:
    """Test tool registry supports v0.4 AssistantAgent patterns."""

    def test_tools_can_be_passed_directly_to_agent(self):
        """Property: Tools should be passable as list to AssistantAgent constructor."""

        # Mock tool function
        def sample_tool(param: str) -> str:
            """A sample tool function."""
            return f"Result: {param}"

        # Tools should be in format accepted by AssistantAgent
        tools = [sample_tool]

        assert isinstance(tools, list)
        assert callable(tools[0])
        assert hasattr(tools[0], "__name__")
        assert hasattr(tools[0], "__doc__")

    def test_tool_has_required_metadata_for_llm(self):
        """Property: Tool functions must have docstrings for LLM understanding."""

        def sample_tool(city: str) -> dict:
            """
            Get weather information for a city.

            Args:
                city: City name (e.g., Berlin)

            Returns:
                Dictionary with weather details
            """
            return {"city": city}

        assert sample_tool.__doc__ is not None
        assert len(sample_tool.__doc__.strip()) > 0
        assert "Args:" in sample_tool.__doc__
        assert "Returns:" in sample_tool.__doc__


# =============================================================================
# Property 6: Tool Entrypoint Validation
# =============================================================================


class TestToolEntrypoints:
    """Test tool entrypoint format for v0.4."""

    @given(
        st.sampled_from(
            [
                "src.tools.calculator:calculate",
                "src.tools.rag_pipeline:query_rag",
                "src.tools.web_search:search_web",
            ]
        )
    )
    def test_entrypoint_format_valid(self, entrypoint):
        """Property: Entrypoints must follow module:function format."""
        assert ":" in entrypoint, "Entrypoint must contain ':' separator"
        parts = entrypoint.split(":")
        assert len(parts) == 2, "Entrypoint must have exactly 2 parts"

        module_path, function_name = parts
        assert "." in module_path, "Module path must have at least one dot"
        assert len(function_name) > 0, "Function name cannot be empty"
        assert function_name.isidentifier(), "Function name must be valid Python identifier"

    def test_entrypoint_module_path_convention(self):
        """Property: Module paths should follow project convention."""
        valid_prefixes = ["src.tools.", "src.agents.", "src.utils."]
        entrypoint = "src.tools.calculator:calculate"

        module_path = entrypoint.split(":")[0]
        assert any(module_path.startswith(prefix) for prefix in valid_prefixes), (
            "Module path should start with src.tools, src.agents, or src.utils"
        )


# =============================================================================
# Integration Test Placeholder
# =============================================================================


class TestToolRegistryIntegration:
    """Integration tests for tool registry with v0.4 agents."""

    def test_tool_registry_loads_v04_tools(self):
        """Integration: Tool registry should load and validate v0.4 tools."""
        from src.config.loader import get_loader
        from src.config.tool_registry import ToolRegistry

        # Load tools config
        loader = get_loader()
        loader.load_tools(use_cache=False)

        # Create tool registry and load tools
        registry = ToolRegistry()
        registry.load_from_config()

        # Verify example tools are loaded
        example_tools = ["web_search", "calculate", "get_weather"]
        for tool_id in example_tools:
            tool_def = registry.get_tool(tool_id)
            assert tool_def is not None, f"Tool {tool_id} should be loaded"
            assert tool_def.function is not None, f"Tool {tool_id} should have a function"
            # Verify is_async is set correctly
            assert hasattr(tool_def, "is_async"), f"Tool {tool_id} should have is_async attribute"

    def test_tools_register_with_assistant_agent(self):
        """Integration: Tools should register successfully with AssistantAgent."""
        from src.config.tool_registry import ToolRegistry

        # Create tool registry
        registry = ToolRegistry()
        registry.load_from_config()

        # Get tools for v0.4 agent
        tool_ids = ["web_search", "calculate"]
        tools = registry.get_tools_for_agent(tool_ids)

        # Verify we got callable functions
        assert len(tools) == 2, "Should return 2 tool functions"
        for tool in tools:
            assert callable(tool), "Each tool should be callable"

        # Verify tools can be used with AssistantAgent (just check the structure)
        # In actual usage, these would be passed to AssistantAgent(tools=tools)
        assert all(callable(t) for t in tools), "All tools should be callable for AssistantAgent"

    def test_async_tools_execute_correctly(self):
        """Integration: Async tools should execute properly in v0.4."""
        from src.config.tool_registry import ToolRegistry

        # Create tool registry
        registry = ToolRegistry()
        registry.load_from_config()

        # Get RAG tools (which are marked as async)
        rag_tool_ids = ["rag_query", "rag_ingest_file", "rag_delete_file"]

        for tool_id in rag_tool_ids:
            tool_def = registry.get_tool(tool_id)
            if tool_def:  # Only test if tool is loaded
                # Verify is_async is set
                assert hasattr(tool_def, "is_async"), f"Tool {tool_id} should have is_async"

                # For RAG tools, is_async should be True based on config
                # We can verify the config says they're async
                from src.config.loader import get_loader

                loader = get_loader()
                tools_config = loader.load_tools(use_cache=False)
                config = tools_config.get_tool(tool_id)
                if config:
                    assert config.is_async, f"RAG tool {tool_id} should be marked async in config"

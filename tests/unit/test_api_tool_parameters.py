"""Regression tests for API-tool function signatures.

An API tool's description is the contract the model reads before calling it. If
the generated function does not accept the parameters that description names,
every well-behaved call fails with a TypeError — and the model has no way to
discover that from the description alone. These tests pin the signature to the
declared parameters.
"""

import inspect

import pytest

from src.tools.api_tool_executor import create_api_tool_function


def parameter_names(function) -> list[str]:
    return list(inspect.signature(function).parameters)


WEATHER_PARAMETERS = [
    {"name": "latitude", "in": "query", "required": True,
     "description": "Latitude", "schema": {"type": "number"}},
    {"name": "longitude", "in": "query", "required": True,
     "description": "Longitude", "schema": {"type": "number"}},
    {"name": "current_weather", "in": "query", "required": False,
     "description": "Include current conditions", "schema": {"type": "boolean", "default": True}},
]


class TestHandDeclaredParameters:
    """Parameters written directly in settings, with no Swagger import."""

    def test_signature_matches_declared_parameters(self):
        function = create_api_tool_function(
            "get_weather",
            {"type": "api", "api_url": "https://example.test", "parameters": WEATHER_PARAMETERS},
            "Get the weather.",
        )
        assert parameter_names(function) == ["latitude", "longitude", "current_weather"]

    def test_required_parameters_have_no_default(self):
        function = create_api_tool_function(
            "get_weather",
            {"type": "api", "api_url": "https://example.test", "parameters": WEATHER_PARAMETERS},
        )
        signature = inspect.signature(function)
        assert signature.parameters["latitude"].default is inspect.Parameter.empty
        assert signature.parameters["current_weather"].default is True

    def test_types_are_annotated_for_the_model(self):
        function = create_api_tool_function(
            "get_weather",
            {"type": "api", "api_url": "https://example.test", "parameters": WEATHER_PARAMETERS},
        )
        assert "latitude" in function.__annotations__

    def test_header_parameters_are_excluded(self):
        # Headers are applied automatically, so exposing them to the model would
        # invite it to set authentication itself.
        function = create_api_tool_function(
            "thing",
            {
                "type": "api",
                "api_url": "https://example.test",
                "parameters": [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "Authorization", "in": "header", "required": True, "schema": {"type": "string"}},
                ],
            },
        )
        assert parameter_names(function) == ["q"]


class TestSwaggerParameters:
    """The imported path must keep working, and must win over the hand-written one."""

    def test_swagger_metadata_is_used(self):
        function = create_api_tool_function(
            "search",
            {
                "type": "api",
                "api_url": "https://example.test",
                "_swagger_metadata": {
                    "parameters": [
                        {"name": "term", "in": "query", "required": True, "schema": {"type": "string"}}
                    ]
                },
            },
        )
        assert parameter_names(function) == ["term"]

    def test_swagger_metadata_takes_precedence(self):
        function = create_api_tool_function(
            "search",
            {
                "type": "api",
                "api_url": "https://example.test",
                "_swagger_metadata": {
                    "parameters": [
                        {"name": "from_swagger", "in": "query", "required": True, "schema": {"type": "string"}}
                    ]
                },
                "parameters": [
                    {"name": "from_settings", "in": "query", "required": True, "schema": {"type": "string"}}
                ],
            },
        )
        assert parameter_names(function) == ["from_swagger"]


class TestUndeclaredParameters:
    def test_a_tool_with_no_parameters_still_accepts_kwargs(self):
        # Degrading to "untyped" is acceptable; degrading to "uncallable" is not.
        function = create_api_tool_function("ping", {"type": "api", "api_url": "https://example.test"})
        signature = inspect.signature(function)
        kinds = {parameter.kind for parameter in signature.parameters.values()}
        assert inspect.Parameter.VAR_KEYWORD in kinds

    def test_calling_with_arguments_does_not_raise_typeerror(self):
        import asyncio

        function = create_api_tool_function("ping", {"type": "api", "api_url": "http://127.0.0.1:1/none"})
        # The request itself will fail (nothing is listening); what matters is
        # that the failure is an HTTP error the tool reports, not a TypeError
        # from the signature rejecting a documented argument.
        result = asyncio.run(function(anything="value"))
        assert isinstance(result, dict)


class TestShippedConfig:
    def test_get_weather_declares_the_parameters_it_documents(self):
        import json
        from pathlib import Path

        config = json.loads((Path(__file__).resolve().parents[2] / "configs" / "tools.json").read_text())
        weather = next(tool for tool in config["tools"] if tool["id"] == "get_weather")

        function = create_api_tool_function("get_weather", weather["settings"], weather["description"])
        for documented in ("latitude", "longitude", "current_weather"):
            assert documented in parameter_names(function), (
                f"'{documented}' is documented in the description but the generated "
                "function does not accept it"
            )

    @pytest.mark.parametrize("tool_id", ["get_weather"])
    def test_every_api_tool_in_config_is_callable_as_documented(self, tool_id):
        import json
        import re
        from pathlib import Path

        config = json.loads((Path(__file__).resolve().parents[2] / "configs" / "tools.json").read_text())
        tool = next(item for item in config["tools"] if item["id"] == tool_id)
        function = create_api_tool_function(tool_id, tool["settings"], tool["description"])
        accepted = set(parameter_names(function))

        # Parameters the description promises, in the "  - name (required):" form
        # the shipped tools use.
        documented = set(re.findall(r"^\s*-\s+(\w+)\s*\(", tool["description"], re.MULTILINE))
        assert documented <= accepted, f"documented but not accepted: {sorted(documented - accepted)}"

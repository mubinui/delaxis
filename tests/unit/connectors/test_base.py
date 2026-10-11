"""Connector declarations: argument models, validation, and the catalogue shape."""

from __future__ import annotations

from typing import Any

import pytest

from src.connectors.base import (
    Action,
    AuthSpec,
    ConnectionSecrets,
    Connector,
    ConnectorContext,
    ConnectorError,
    OptionField,
    Param,
    args_model,
    catalogue_entry,
    validate_args,
)


def _noop(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return args


SEARCH = Action(
    id="search",
    name="Search",
    kind="read",
    description="Search things.",
    params=(
        Param("query", "string", "What to look for"),
        Param("max_results", "integer", "How many", required=False, default=10),
        Param("labels", "array", "Labels", required=False),
        Param("state", "string", "State", required=False, enum=("open", "closed")),
    ),
    run=_noop,
)
CONNECTOR = Connector(
    id="demo",
    name="Demo",
    icon="plug",
    description="A demo connector",
    auth=AuthSpec(kind="token", base_url=True, base_url_default="https://demo.test"),
    actions=(SEARCH,),
    options=(OptionField("project", "Default project", "Used when an action names none"),),
)


def test_args_model_has_the_declared_fields_and_types() -> None:
    model = args_model("demo", SEARCH)
    schema = model.model_json_schema()
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["description"] == "What to look for"
    assert model(query="x").model_dump()["max_results"] == 10


def test_validate_args_coerces_and_drops_unset_optionals() -> None:
    assert validate_args("demo", SEARCH, {"query": "bug", "max_results": "5"}) == {
        "query": "bug",
        "max_results": 5,
    }


def test_validate_args_names_the_bad_field() -> None:
    with pytest.raises(ConnectorError, match="query"):
        validate_args("demo", SEARCH, {"max_results": 5})
    with pytest.raises(ConnectorError, match="state"):
        validate_args("demo", SEARCH, {"query": "x", "state": "merged"})


def test_catalogue_entry_describes_everything_the_studio_renders() -> None:
    entry = catalogue_entry(CONNECTOR)
    assert entry["id"] == "demo"
    assert entry["auth"]["kind"] == "token"
    assert entry["auth"]["base_url_default"] == "https://demo.test"
    assert entry["options"] == [
        {"key": "project", "label": "Default project", "help": "Used when an action names none"}
    ]
    action = entry["actions"][0]
    assert action["id"] == "search" and action["kind"] == "read"
    assert action["params"][0] == {
        "name": "query",
        "type": "string",
        "description": "What to look for",
        "required": True,
        "default": None,
        "enum": None,
    }
    assert action["params"][3]["enum"] == ["open", "closed"]


def test_unknown_action_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        CONNECTOR.action("nope")


def test_context_option_prefers_the_node_then_the_connection() -> None:
    secrets = ConnectionSecrets(base_url=None, username=None, token="t", options={"project": "A"})
    assert ConnectorContext(secrets, {"project": "B"}).option("project") == "B"
    assert ConnectorContext(secrets, {}).option("project") == "A"
    assert ConnectorContext(secrets, {"project": ""}).option("project", "C") == "A"
    empty = ConnectionSecrets(base_url=None, username=None, token="t")
    assert ConnectorContext(empty, {}).option("project", "C") == "C"

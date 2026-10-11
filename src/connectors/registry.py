"""The connectors this installation offers, in the order the Studio shows them."""

from __future__ import annotations

import importlib
from functools import cache

from src.connectors.base import Connector

_BUILTIN = ("jira", "gitlab", "gmail")


@cache
def _load() -> dict[str, Connector]:
    loaded: dict[str, Connector] = {}
    for module_name in _BUILTIN:
        connector: Connector = importlib.import_module(f"src.connectors.{module_name}").CONNECTOR
        loaded[connector.id] = connector
    return loaded


def all_connectors() -> list[Connector]:
    return list(_load().values())


def connector_ids() -> list[str]:
    return list(_load())


def get_connector(connector_id: str) -> Connector | None:
    return _load().get(connector_id)

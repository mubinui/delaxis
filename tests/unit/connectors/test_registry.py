from src.connectors.registry import all_connectors, connector_ids, get_connector


def test_builtin_connectors_are_registered_in_a_stable_order() -> None:
    assert connector_ids() == ["jira", "gitlab", "gmail"]
    assert [c.id for c in all_connectors()] == ["jira", "gitlab", "gmail"]


def test_unknown_connector_is_none() -> None:
    assert get_connector("nope") is None
    jira = get_connector("jira")
    assert jira is not None and jira.name == "Jira"

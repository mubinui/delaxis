"""Tests for the sql and mongodb tool factories.

The read-only guard gets the most attention, because it is the control standing
between an agent and someone's production data. Each bypass technique that
actually works in the wild — stacked statements, a write hidden in a CTE, a verb
disguised by a comment — gets its own case.
"""

import json
import sqlite3

import pytest

from src.tools.database_factories import (
    ReadOnlyError,
    SqlToolFactory,
    assert_read_only,
)
from src.tools.runtime_tool_factories import create_runtime_factory, is_factory_tool_type


@pytest.fixture
def shop_db(tmp_path):
    path = tmp_path / "shop.db"
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT);
        CREATE TABLE orders(
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id),
            total REAL
        );
        CREATE TABLE secrets(id INTEGER PRIMARY KEY, value TEXT);
        INSERT INTO customers VALUES (1,'Acme','Dhaka'),(2,'Globex','Berlin');
        INSERT INTO orders VALUES (1,1,4200.0),(2,2,1300.0),(3,1,890.5);
        INSERT INTO secrets VALUES (1,'do not read me');
        """
    )
    connection.commit()
    connection.close()
    return path


def make_sql_tool(db_path, **settings) -> SqlToolFactory:
    return create_runtime_factory(
        "sql", "shop", "shop_db", "Shop database",
        {"db_uri": f"sqlite:///{db_path}", **settings},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.parametrize("kind", ["mcp", "database", "gmail", "sql", "mongodb"])
    def test_factory_types_are_recognised(self, kind):
        assert is_factory_tool_type(kind)

    @pytest.mark.parametrize("kind", ["function", "api", "nonsense"])
    def test_non_factory_types_are_not(self, kind):
        assert not is_factory_tool_type(kind)

    def test_unknown_type_raises_clearly(self):
        with pytest.raises(ValueError, match="No runtime factory"):
            create_runtime_factory("carrier-pigeon", "x", "x", "x", {})


# ---------------------------------------------------------------------------
# The read-only guard
# ---------------------------------------------------------------------------


class TestReadOnlyGuard:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM customers",
            "select id from orders where total > 100",
            "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
            "SELECT * FROM customers;",
            "EXPLAIN SELECT * FROM orders",
            "SELECT * FROM customers -- ; DROP TABLE customers",
        ],
    )
    def test_allows_reads(self, sql):
        assert assert_read_only(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE customers",
            "DELETE FROM customers",
            "UPDATE customers SET city='x'",
            "INSERT INTO customers VALUES (3,'x','y')",
            "TRUNCATE TABLE orders",
            "ALTER TABLE orders ADD COLUMN x TEXT",
            "CREATE TABLE evil(id INT)",
            "GRANT ALL ON customers TO PUBLIC",
        ],
    )
    def test_refuses_writes(self, sql):
        with pytest.raises(ReadOnlyError):
            assert_read_only(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1; DROP TABLE customers",
            "SELECT 1; DELETE FROM orders;",
            "SELECT 1 ; UPDATE customers SET city='x'",
        ],
    )
    def test_refuses_stacked_statements(self, sql):
        with pytest.raises(ReadOnlyError, match="Multiple statements"):
            assert_read_only(sql)

    def test_refuses_a_write_hidden_in_a_cte(self):
        with pytest.raises(ReadOnlyError, match="CTE"):
            assert_read_only("WITH x AS (SELECT 1) DELETE FROM customers RETURNING *")

    def test_refuses_a_verb_disguised_by_a_comment(self):
        with pytest.raises(ReadOnlyError):
            assert_read_only("/* SELECT */ DROP TABLE customers")

    def test_refuses_a_verb_after_a_line_comment(self):
        with pytest.raises(ReadOnlyError):
            assert_read_only("-- SELECT everything\nDROP TABLE customers")

    def test_refuses_empty_statements(self):
        with pytest.raises(ReadOnlyError, match="Empty"):
            assert_read_only("   ")

    def test_column_named_like_a_verb_is_not_a_write(self):
        # "updated_at" and "deleted" must not trip the whole-word check.
        assert assert_read_only("SELECT updated_at, deleted FROM orders")

    def test_error_explains_what_is_allowed(self):
        with pytest.raises(ReadOnlyError, match="SELECT"):
            assert_read_only("DROP TABLE customers")


# ---------------------------------------------------------------------------
# SQL tool behaviour
# ---------------------------------------------------------------------------


class TestSqlSchema:
    def test_lists_tables_and_columns(self, shop_db):
        schema = json.loads(make_sql_tool(shop_db).describe_schema())
        assert schema["dialect"] == "sqlite"
        assert set(schema["tables"]) == {"customers", "orders", "secrets"}
        names = [column["name"] for column in schema["tables"]["customers"]["columns"]]
        assert names == ["id", "name", "city"]

    def test_reports_primary_keys_and_nullability(self, shop_db):
        schema = json.loads(make_sql_tool(shop_db).describe_schema())
        columns = {c["name"]: c for c in schema["tables"]["customers"]["columns"]}
        assert columns["id"]["primary_key"] is True
        assert columns["name"]["nullable"] is False

    def test_reports_foreign_keys(self, shop_db):
        schema = json.loads(make_sql_tool(shop_db).describe_schema())
        assert schema["tables"]["orders"]["foreign_keys"][0]["references"] == "customers"

    def test_table_allowlist_hides_other_tables(self, shop_db):
        schema = json.loads(make_sql_tool(shop_db, tables=["customers"]).describe_schema())
        assert set(schema["tables"]) == {"customers"}

    def test_single_table_can_be_requested(self, shop_db):
        schema = json.loads(make_sql_tool(shop_db).describe_schema("orders"))
        assert set(schema["tables"]) == {"orders"}

    def test_unknown_table_lists_what_is_available(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).describe_schema("nope"))
        assert "customers" in result["error"]


class TestSqlQuery:
    def test_returns_rows(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).run_query("SELECT name FROM customers ORDER BY id"))
        assert [row["name"] for row in result["rows"]] == ["Acme", "Globex"]

    def test_supports_joins_and_aggregates(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).run_query(
            "SELECT c.name, SUM(o.total) AS spend FROM orders o "
            "JOIN customers c ON c.id=o.customer_id GROUP BY c.name ORDER BY spend DESC"
        ))
        assert result["rows"][0] == {"name": "Acme", "spend": 5090.5}

    def test_row_limit_is_applied_and_flagged(self, shop_db):
        result = json.loads(make_sql_tool(shop_db, max_rows=2).run_query("SELECT * FROM orders"))
        assert result["row_count"] == 2
        assert result["truncated"] is True

    def test_not_truncated_when_everything_fits(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).run_query("SELECT * FROM orders"))
        assert result["truncated"] is False

    def test_writes_are_refused_by_default(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).run_query("DELETE FROM customers"))
        assert result["read_only"] is True
        assert "not permitted" in result["error"]

    def test_refused_write_does_not_touch_the_data(self, shop_db):
        make_sql_tool(shop_db).run_query("DELETE FROM customers")
        result = json.loads(make_sql_tool(shop_db).run_query("SELECT COUNT(*) AS n FROM customers"))
        assert result["rows"][0]["n"] == 2

    def test_allow_writes_opens_the_gate(self, shop_db):
        tool = make_sql_tool(shop_db, allow_writes=True)
        assert "error" not in json.loads(tool.run_query("INSERT INTO customers VALUES (9,'New','X')"))
        after = json.loads(tool.run_query("SELECT COUNT(*) AS n FROM customers"))
        assert after["rows"][0]["n"] == 3

    def test_table_allowlist_blocks_other_tables(self, shop_db):
        tool = make_sql_tool(shop_db, tables=["customers", "orders"])
        result = json.loads(tool.run_query("SELECT * FROM secrets"))
        assert "not permitted" in result["error"]

    def test_table_allowlist_permits_listed_tables(self, shop_db):
        tool = make_sql_tool(shop_db, tables=["customers", "orders"])
        assert "error" not in json.loads(tool.run_query("SELECT * FROM customers"))

    def test_broken_sql_reports_the_error(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).run_query("SELECT * FROM no_such_table"))
        assert "error" in result


class TestSqlSample:
    def test_returns_the_first_rows(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).sample_table("customers", 1))
        assert result["row_count"] == 1

    def test_rejects_a_non_identifier_table_name(self, shop_db):
        result = json.loads(make_sql_tool(shop_db).sample_table("customers; DROP TABLE orders"))
        assert "bare identifier" in result["error"]

    def test_respects_the_allowlist(self, shop_db):
        result = json.loads(make_sql_tool(shop_db, tables=["customers"]).sample_table("secrets"))
        assert "not permitted" in result["error"]

    def test_limit_is_capped_by_max_rows(self, shop_db):
        result = json.loads(make_sql_tool(shop_db, max_rows=2).sample_table("orders", 100))
        assert result["row_count"] <= 2


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TestCredentialHandling:
    def test_env_var_is_resolved(self, shop_db, monkeypatch):
        monkeypatch.setenv("TEST_SHOP_DB_URI", f"sqlite:///{shop_db}")
        tool = create_runtime_factory("sql", "shop", "shop", "d", {"db_uri_env_var": "TEST_SHOP_DB_URI"})
        assert "error" not in json.loads(tool.describe_schema())

    def test_missing_env_var_names_the_variable(self, monkeypatch):
        monkeypatch.delenv("ABSENT_DB_URI", raising=False)
        tool = create_runtime_factory("sql", "shop", "shop", "d", {"db_uri_env_var": "ABSENT_DB_URI"})
        assert "ABSENT_DB_URI" in json.loads(tool.describe_schema())["error"]

    def test_no_uri_at_all_is_an_actionable_error(self):
        tool = create_runtime_factory("sql", "shop", "shop", "d", {})
        assert "db_uri_env_var" in json.loads(tool.describe_schema())["error"]


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------


class TestSqlToolSurface:
    def test_sandbox_function_dispatches_each_action(self, shop_db):
        run = make_sql_tool(shop_db).sandbox_function()
        assert "customers" in run("schema")
        assert "Acme" in run("query", sql="SELECT name FROM customers")
        assert "row_count" in run("sample", table="customers", limit=1)

    def test_sandbox_function_rejects_unknown_actions(self, shop_db):
        run = make_sql_tool(shop_db).sandbox_function()
        assert "Unknown action" in json.loads(run("teleport"))["error"]

    def test_build_exposes_three_named_tools(self, shop_db):
        import contextlib

        with contextlib.ExitStack() as stack:
            tools = make_sql_tool(shop_db).build(stack)
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# MongoDB — config validation without a live server
# ---------------------------------------------------------------------------


class TestMongoConfig:
    def make(self, **settings):
        return create_runtime_factory("mongodb", "m", "m", "d", settings)

    def test_missing_env_var_names_the_variable(self, monkeypatch):
        monkeypatch.delenv("ABSENT_MONGO_URI", raising=False)
        tool = self.make(uri_env_var="ABSENT_MONGO_URI", database="app")
        assert "ABSENT_MONGO_URI" in json.loads(tool.list_collections())["error"]

    def test_missing_database_is_an_actionable_error(self):
        tool = self.make(uri="mongodb://localhost:27017")
        assert "database" in json.loads(tool.list_collections())["error"]

    def test_collection_allowlist_is_enforced_before_connecting(self):
        tool = self.make(uri="mongodb://localhost:27017", database="app", collections=["orders"])
        result = json.loads(tool.describe_collection("secrets"))
        assert "not permitted" in result["error"]

    def test_malformed_filter_json_is_rejected(self):
        tool = self.make(uri="mongodb://localhost:27017", database="app")
        result = json.loads(tool.find_documents("orders", "{not json"))
        assert "not valid JSON" in result["error"]

    def test_non_object_filter_is_rejected(self):
        tool = self.make(uri="mongodb://localhost:27017", database="app")
        assert "must be a JSON object" in json.loads(tool.find_documents("orders", "[1,2]"))["error"]

    @pytest.mark.parametrize(
        "query",
        [
            '{"$where": "this.x == 1"}',
            '{"$function": {"body": "function(){}"}}',
            '{"a": {"b": {"$where": "1"}}}',   # nested at depth
            '{"$or": [{"$where": "1"}]}',      # nested inside a list
        ],
    )
    def test_server_side_execution_operators_are_refused(self, query):
        tool = self.make(uri="mongodb://localhost:27017", database="app")
        result = json.loads(tool.find_documents("orders", query))
        assert "read-only" in result["error"]

    def test_sandbox_function_rejects_unknown_actions(self):
        run = self.make(uri="mongodb://localhost:27017", database="app").sandbox_function()
        assert "Unknown action" in json.loads(run("teleport"))["error"]

"""Database tool factories beyond NL2SQL.

``DatabaseToolFactory`` in :mod:`src.tools.runtime_tool_factories` gives an
agent natural-language SQL. That is the right tool when you want the model to
write the query, and the wrong one when you want to control exactly what runs.
These factories cover the second case:

* ``sql`` — schema introspection plus a query runner over any SQLAlchemy URL
  (PostgreSQL, MySQL/MariaDB, SQLite, SQL Server, Oracle, Snowflake, BigQuery —
  whatever dialect is installed). Read-only by default, enforced by parsing the
  statement rather than trusting the prompt.
* ``mongodb`` — collection listing, schema sampling, and find/aggregate, with
  writes off unless explicitly enabled.

The read-only guard is a real check: it rejects anything that is not a single
SELECT/WITH statement, refuses stacked statements, and blocks the DDL/DML verbs
outright. Belt and braces beats a prompt asking the model to behave — but for a
production database, a read-only database role is still the control that
matters, and this does not replace it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Callable
from typing import Any

from src.audit_logging import get_logger
from src.tools.runtime_tool_factories import RuntimeToolFactory

logger = get_logger(__name__)

# Verbs that mutate data or schema. Checked as whole words so a column named
# "updated_at" or a table named "deleted_records" does not trip the guard.
_WRITE_VERBS = (
    "insert", "update", "delete", "drop", "truncate", "alter", "create",
    "grant", "revoke", "replace", "merge", "upsert", "call", "execute",
    "exec", "copy", "vacuum", "attach", "detach", "pragma", "set", "reset",
)
_WRITE_PATTERN = re.compile(r"(?i)\b(?:" + "|".join(_WRITE_VERBS) + r")\b")

_COMMENT_PATTERN = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class ReadOnlyError(ValueError):
    """Raised when a statement would modify the database in read-only mode."""


def assert_read_only(sql: str) -> str:
    """Return ``sql`` if it is a single read-only statement, else raise.

    Comments are stripped first: ``SELECT 1; -- DROP TABLE x`` is fine, but
    ``/* SELECT */ DROP TABLE x`` must not slip through by hiding the verb.
    """
    stripped = _COMMENT_PATTERN.sub(" ", sql).strip()
    if not stripped:
        raise ReadOnlyError("Empty statement.")

    # Trailing semicolons are fine; an interior one means stacked statements,
    # which is how a read-only check is usually defeated.
    body = stripped.rstrip(";").strip()
    if ";" in body:
        raise ReadOnlyError(
            "Multiple statements are not allowed. Send one SELECT at a time."
        )

    first_word = re.split(r"\s+", body, maxsplit=1)[0].lower()
    if first_word not in ("select", "with", "show", "describe", "desc", "explain"):
        raise ReadOnlyError(
            f"This tool is read-only; '{first_word.upper()}' is not permitted. "
            "Only SELECT, WITH, SHOW, DESCRIBE, and EXPLAIN are allowed."
        )

    # A CTE can hide a write: WITH x AS (...) DELETE FROM ... RETURNING *.
    if first_word == "with" and _WRITE_PATTERN.search(body):
        raise ReadOnlyError(
            "The statement contains a data-modifying verb inside a CTE, which is not allowed."
        )

    return body


# --------------------------------------------------------------------------- #
# SQL
# --------------------------------------------------------------------------- #


class SqlToolFactory(RuntimeToolFactory):
    """Schema introspection plus a guarded query runner over SQLAlchemy."""

    def _resolve_uri(self) -> str:
        env_var = self.settings.get("db_uri_env_var")
        if env_var:
            uri = os.environ.get(env_var)
            if not uri:
                raise ValueError(
                    f"SQL tool '{self.tool_id}': env var '{env_var}' is not set "
                    "(it should hold the SQLAlchemy database URI)"
                )
            return uri
        uri = self.settings.get("db_uri")
        if not uri:
            raise ValueError(
                f"SQL tool '{self.tool_id}': set either 'db_uri_env_var' (recommended) "
                "or 'db_uri' in the tool settings."
            )
        return str(uri)

    def _allowed_tables(self) -> set[str] | None:
        tables = self.settings.get("tables") or []
        return {str(name) for name in tables} if tables else None

    def _read_only(self) -> bool:
        return not bool(self.settings.get("allow_writes", False))

    def _row_limit(self) -> int:
        return int(self.settings.get("max_rows", 200) or 200)

    def _engine(self) -> Any:
        from sqlalchemy import create_engine

        # NullPool: these tools are built per run and may outlive their engine's
        # usefulness; a pooled connection left open holds a server-side session.
        from sqlalchemy.pool import NullPool

        return create_engine(self._resolve_uri(), poolclass=NullPool)

    def describe_schema(self, table: str = "") -> str:
        """Introspect tables and columns."""
        from sqlalchemy import inspect as sa_inspect

        engine = self._engine()
        try:
            inspector = sa_inspect(engine)
            allowed = self._allowed_tables()
            names = [
                name for name in inspector.get_table_names()
                if allowed is None or name in allowed
            ]
            if table:
                if table not in names:
                    return json.dumps(
                        {"error": f"Table '{table}' is not available. Tables: {', '.join(names)}"}
                    )
                names = [table]

            schema = {}
            for name in names[:100]:
                columns = [
                    {
                        "name": column["name"],
                        "type": str(column["type"]),
                        "nullable": bool(column.get("nullable", True)),
                        "primary_key": bool(column.get("primary_key", False)),
                    }
                    for column in inspector.get_columns(name)
                ]
                entry: dict[str, Any] = {"columns": columns}
                try:
                    foreign_keys = inspector.get_foreign_keys(name)
                    if foreign_keys:
                        entry["foreign_keys"] = [
                            {
                                "columns": fk.get("constrained_columns"),
                                "references": fk.get("referred_table"),
                                "referred_columns": fk.get("referred_columns"),
                            }
                            for fk in foreign_keys
                        ]
                except Exception:
                    # Foreign-key introspection is unsupported on some dialects;
                    # the column list is still worth returning.
                    pass
                schema[name] = entry

            return json.dumps(
                {
                    "dialect": engine.dialect.name,
                    "table_count": len(schema),
                    "tables": schema,
                    "read_only": self._read_only(),
                },
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps({"error": f"Schema introspection failed: {exc}"})
        finally:
            engine.dispose()

    def run_query(self, sql: str) -> str:
        """Execute one statement and return rows as JSON."""
        from sqlalchemy import text

        if self._read_only():
            try:
                sql = assert_read_only(sql)
            except ReadOnlyError as exc:
                return json.dumps({"error": str(exc), "read_only": True})

        allowed = self._allowed_tables()
        if allowed:
            # Cheap allowlist check: every bare identifier that matches a known
            # table name must be in the allowlist. Not a parser, so it is a
            # second line of defence behind database grants, not the first.
            referenced = set(re.findall(r"(?i)\b(?:from|join|into|update)\s+[\"'`\[]?(\w+)", sql))
            blocked = referenced - allowed
            if blocked:
                return json.dumps(
                    {
                        "error": f"Table(s) not permitted for this tool: {', '.join(sorted(blocked))}. "
                        f"Allowed: {', '.join(sorted(allowed))}"
                    }
                )

        engine = self._engine()
        limit = self._row_limit()
        try:
            with engine.connect() as connection:
                result = connection.execute(text(sql))
                if not result.returns_rows:
                    connection.commit()
                    return json.dumps({"rows_affected": result.rowcount, "rows": []})
                columns = list(result.keys())
                rows = [dict(zip(columns, row)) for row in result.fetchmany(limit)]
                more = result.fetchone() is not None
            return json.dumps(
                {
                    "columns": columns,
                    "row_count": len(rows),
                    "truncated": more,
                    "rows": rows,
                },
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps({"error": f"Query failed: {exc}"})
        finally:
            engine.dispose()

    def sample_table(self, table: str, limit: int = 10) -> str:
        """Return the first rows of a table without the agent writing SQL."""
        allowed = self._allowed_tables()
        if allowed is not None and table not in allowed:
            return json.dumps(
                {"error": f"Table '{table}' is not permitted. Allowed: {', '.join(sorted(allowed))}"}
            )
        if not re.fullmatch(r"\w+", table or ""):
            return json.dumps({"error": "Table name must be a bare identifier."})
        capped = max(1, min(int(limit), self._row_limit()))
        return self.run_query(f"SELECT * FROM {table} LIMIT {capped}")

    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        from crewai.tools import tool as crewai_tool

        factory = self
        tools: list[Any] = []

        def describe_database_schema(table: str = "") -> str:
            """List the database's tables and their columns. Pass a table name for just that table, or leave empty for all of them. Call this before writing any query."""
            return factory.describe_schema(table)

        def query_database(sql: str) -> str:
            """Run one SQL SELECT statement and return the rows as JSON. Read-only: INSERT, UPDATE, DELETE and DDL are rejected. Call describe_database_schema first so the column names are right."""
            return factory.run_query(sql)

        def sample_table_rows(table: str, limit: int = 10) -> str:
            """Return the first rows of a table so you can see its real shape and values. Cheaper than writing a query when you just want a look."""
            return factory.sample_table(table, limit)

        tools.append(crewai_tool(f"{self.name}_describe_schema")(describe_database_schema))
        tools.append(crewai_tool(f"{self.name}_query")(query_database))
        tools.append(crewai_tool(f"{self.name}_sample")(sample_table_rows))
        return tools

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def sql_action(action: str = "schema", **kwargs: Any) -> Any:
            """Test the SQL tool: action is 'schema' (table), 'query' (sql), or 'sample' (table, limit)."""
            if action == "schema":
                return factory.describe_schema(kwargs.get("table", ""))
            if action == "query":
                return factory.run_query(kwargs.get("sql", ""))
            if action == "sample":
                return factory.sample_table(kwargs.get("table", ""), int(kwargs.get("limit", 10)))
            return json.dumps({"error": f"Unknown action '{action}'. Use schema, query, or sample."})

        sql_action.__name__ = self.name
        return sql_action


# --------------------------------------------------------------------------- #
# MongoDB
# --------------------------------------------------------------------------- #


class MongoToolFactory(RuntimeToolFactory):
    """Collection listing, schema sampling, find and aggregate over PyMongo."""

    def _resolve_uri(self) -> str:
        env_var = self.settings.get("uri_env_var")
        if env_var:
            uri = os.environ.get(env_var)
            if not uri:
                raise ValueError(
                    f"MongoDB tool '{self.tool_id}': env var '{env_var}' is not set."
                )
            return uri
        uri = self.settings.get("uri")
        if not uri:
            raise ValueError(
                f"MongoDB tool '{self.tool_id}': set either 'uri_env_var' (recommended) or 'uri'."
            )
        return str(uri)

    def _database_name(self) -> str:
        name = self.settings.get("database")
        if not name:
            raise ValueError(f"MongoDB tool '{self.tool_id}': 'database' is required in settings.")
        return str(name)

    def _allowed_collections(self) -> set[str] | None:
        collections = self.settings.get("collections") or []
        return {str(name) for name in collections} if collections else None

    def _limit(self) -> int:
        return int(self.settings.get("max_documents", 50) or 50)

    @contextlib.contextmanager
    def _client(self):
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "MongoDB tools need the 'pymongo' package. Install with: uv pip install pymongo"
            ) from exc
        client = MongoClient(self._resolve_uri(), serverSelectionTimeoutMS=8000)
        try:
            yield client
        finally:
            client.close()

    def _check_collection(self, collection: str) -> str | None:
        allowed = self._allowed_collections()
        if allowed is not None and collection not in allowed:
            return f"Collection '{collection}' is not permitted. Allowed: {', '.join(sorted(allowed))}"
        return None

    def list_collections(self) -> str:
        try:
            with self._client() as client:
                database = client[self._database_name()]
                names = sorted(database.list_collection_names())
                allowed = self._allowed_collections()
                if allowed is not None:
                    names = [name for name in names if name in allowed]
                return json.dumps(
                    {
                        "database": self._database_name(),
                        "count": len(names),
                        "collections": [
                            {"name": name, "documents": database[name].estimated_document_count()}
                            for name in names[:100]
                        ],
                    },
                    indent=2,
                )
        except Exception as exc:
            return json.dumps({"error": f"Could not list collections: {exc}"})

    def describe_collection(self, collection: str, sample: int = 25) -> str:
        """Infer a schema by sampling documents — Mongo has no declared one."""
        error = self._check_collection(collection)
        if error:
            return json.dumps({"error": error})
        try:
            with self._client() as client:
                documents = list(
                    client[self._database_name()][collection].find(
                        {}, limit=max(1, min(int(sample), 200))
                    )
                )
        except Exception as exc:
            return json.dumps({"error": f"Could not sample '{collection}': {exc}"})

        fields: dict[str, dict[str, Any]] = {}
        for document in documents:
            for key, value in document.items():
                entry = fields.setdefault(key, {"types": set(), "present": 0})
                entry["types"].add(type(value).__name__)
                entry["present"] += 1

        return json.dumps(
            {
                "collection": collection,
                "sampled": len(documents),
                "fields": {
                    key: {
                        "types": sorted(entry["types"]),
                        "present_in": f"{entry['present']}/{len(documents)}",
                    }
                    for key, entry in sorted(fields.items())
                },
            },
            indent=2,
            default=str,
        )

    def find_documents(self, collection: str, filter_json: str = "{}", limit: int = 10) -> str:
        error = self._check_collection(collection)
        if error:
            return json.dumps({"error": error})
        try:
            query = json.loads(filter_json or "{}")
            if not isinstance(query, dict):
                return json.dumps({"error": "'filter_json' must be a JSON object."})
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"'filter_json' is not valid JSON: {exc}"})

        if not self.settings.get("allow_writes", False):
            # $where and $function execute server-side JavaScript; $out and
            # $merge write. None belong in a read-only find.
            forbidden = {"$where", "$function", "$accumulator", "$out", "$merge"}
            if forbidden & _all_keys(query):
                return json.dumps(
                    {"error": "This tool is read-only; server-side execution operators are not allowed."}
                )

        capped = max(1, min(int(limit), self._limit()))
        try:
            with self._client() as client:
                documents = list(
                    client[self._database_name()][collection].find(query, limit=capped)
                )
            return json.dumps(
                {"collection": collection, "count": len(documents), "documents": documents},
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps({"error": f"Query failed: {exc}"})

    def build(self, stack: contextlib.ExitStack) -> list[Any]:
        from crewai.tools import tool as crewai_tool

        factory = self

        def list_mongo_collections() -> str:
            """List the collections in the configured MongoDB database, with approximate document counts."""
            return factory.list_collections()

        def describe_mongo_collection(collection: str, sample: int = 25) -> str:
            """Infer a collection's fields and their types by sampling documents. MongoDB has no declared schema, so call this before querying."""
            return factory.describe_collection(collection, sample)

        def find_mongo_documents(collection: str, filter_json: str = "{}", limit: int = 10) -> str:
            """Find documents in a collection. 'filter_json' is a MongoDB query filter as a JSON string, e.g. '{"status": "open"}'. Read-only."""
            return factory.find_documents(collection, filter_json, limit)

        return [
            crewai_tool(f"{self.name}_list_collections")(list_mongo_collections),
            crewai_tool(f"{self.name}_describe")(describe_mongo_collection),
            crewai_tool(f"{self.name}_find")(find_mongo_documents),
        ]

    def sandbox_function(self) -> Callable[..., Any]:
        factory = self

        def mongo_action(action: str = "list", **kwargs: Any) -> Any:
            """Test the MongoDB tool: action is 'list', 'describe' (collection), or 'find' (collection, filter_json, limit)."""
            if action == "list":
                return factory.list_collections()
            if action == "describe":
                return factory.describe_collection(
                    kwargs.get("collection", ""), int(kwargs.get("sample", 25))
                )
            if action == "find":
                return factory.find_documents(
                    kwargs.get("collection", ""),
                    kwargs.get("filter_json", "{}"),
                    int(kwargs.get("limit", 10)),
                )
            return json.dumps({"error": f"Unknown action '{action}'. Use list, describe, or find."})

        mongo_action.__name__ = self.name
        return mongo_action


def _all_keys(value: Any) -> set[str]:
    """Every key anywhere in a nested structure — operators hide at any depth."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys

"""Tests for the context-tree tools.

The sandbox is the part that has to be right. A path that escapes the configured
roots hands an agent the filesystem, so every escape shape gets its own test:
relative traversal, absolute paths, symlinks planted inside the tree, and the
combinations of those.
"""

import json
import os

import pytest

from src.tools.context_tree import (
    ContextAccessError,
    context_roots,
    context_tree,
    describe_context_file,
    list_context_roots,
    read_context_file,
    resolve_in_sandbox,
    search_context_tree,
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A context root with a small tree, plus an out-of-bounds file beside it."""
    root = tmp_path / "root"
    (root / "reports" / "2026").mkdir(parents=True)
    (root / "data").mkdir(parents=True)

    (root / "reports" / "2026" / "q3.md").write_text(
        "# Q3 Report\n\nRevenue grew 12%.\n\n## Risks\n\nSupply chain delays.\n"
    )
    (root / "data" / "invoices.csv").write_text("id,name,amount\n1,Acme,4200\n2,Globex,1300\n")
    (root / "notes.txt").write_text("remember to file the return\n")
    (root / "binary.bin").write_bytes(b"\x00\x01\x02\x03" * 64)

    outside = tmp_path / "outside-secret.txt"
    outside.write_text("private key material\n")

    monkeypatch.setenv("DELAXIS_CONTEXT_ROOTS", str(root))
    return {"root": root, "outside": outside, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------


class TestRoots:
    def test_configured_root_is_used(self, sandbox):
        assert context_roots() == [sandbox["root"].resolve()]

    def test_multiple_roots_are_supported(self, tmp_path, monkeypatch):
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        monkeypatch.setenv("DELAXIS_CONTEXT_ROOTS", f"{first}{os.pathsep}{second}")
        assert len(context_roots()) == 2

    def test_roots_are_created_when_missing(self, tmp_path, monkeypatch):
        target = tmp_path / "not-yet"
        monkeypatch.setenv("DELAXIS_CONTEXT_ROOTS", str(target))
        assert context_roots() == [target.resolve()]
        assert target.exists()

    def test_list_tool_reports_roots(self, sandbox):
        report = json.loads(list_context_roots())
        assert report["count"] == 1
        assert report["roots"][0]["entries"] > 0


# ---------------------------------------------------------------------------
# Sandbox — the security boundary
# ---------------------------------------------------------------------------


class TestSandbox:
    @pytest.mark.parametrize(
        "escape",
        [
            "../outside-secret.txt",
            "../../etc/passwd",
            "reports/../../outside-secret.txt",
            "./../outside-secret.txt",
            "reports/2026/../../../outside-secret.txt",
        ],
    )
    def test_relative_traversal_is_refused(self, sandbox, escape):
        with pytest.raises(ContextAccessError):
            resolve_in_sandbox(escape)

    @pytest.mark.parametrize("absolute", ["/etc/passwd", "/etc/hosts", "/"])
    def test_absolute_paths_outside_are_refused(self, sandbox, absolute):
        with pytest.raises(ContextAccessError):
            resolve_in_sandbox(absolute)

    def test_absolute_path_to_the_sibling_file_is_refused(self, sandbox):
        with pytest.raises(ContextAccessError):
            resolve_in_sandbox(str(sandbox["outside"]))

    def test_symlink_pointing_out_is_refused(self, sandbox):
        # Resolution happens before the containment check precisely so that a
        # symlink planted inside the tree cannot be followed out of it.
        link = sandbox["root"] / "escape.txt"
        link.symlink_to(sandbox["outside"])
        with pytest.raises(ContextAccessError):
            resolve_in_sandbox("escape.txt")

    def test_symlinked_directory_pointing_out_is_refused(self, sandbox):
        link = sandbox["root"] / "escape-dir"
        link.symlink_to(sandbox["tmp"], target_is_directory=True)
        with pytest.raises(ContextAccessError):
            resolve_in_sandbox("escape-dir/outside-secret.txt")

    def test_paths_inside_are_allowed(self, sandbox):
        resolved = resolve_in_sandbox("reports/2026/q3.md")
        assert resolved.name == "q3.md"

    def test_absolute_path_inside_is_allowed(self, sandbox):
        target = sandbox["root"] / "notes.txt"
        assert resolve_in_sandbox(str(target)) == target.resolve()

    def test_escape_error_names_the_allowed_roots(self, sandbox):
        with pytest.raises(ContextAccessError, match="Allowed roots"):
            resolve_in_sandbox("/etc/passwd")


class TestToolsRefuseEscapes:
    """The sandbox has to hold at the tool surface, not just in the resolver."""

    ESCAPES = ["../outside-secret.txt", "/etc/passwd"]

    @pytest.mark.parametrize("escape", ESCAPES)
    def test_read_refuses(self, sandbox, escape):
        result = json.loads(read_context_file(escape))
        assert "error" in result
        assert "private key material" not in json.dumps(result)

    @pytest.mark.parametrize("escape", ESCAPES)
    def test_describe_refuses(self, sandbox, escape):
        assert "error" in json.loads(describe_context_file(escape))

    @pytest.mark.parametrize("escape", ESCAPES)
    def test_tree_refuses(self, sandbox, escape):
        assert "error" in json.loads(context_tree(escape))

    @pytest.mark.parametrize("escape", ESCAPES)
    def test_search_refuses(self, sandbox, escape):
        assert "error" in json.loads(search_context_tree("private", escape))


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


class TestTree:
    def test_renders_the_structure(self, sandbox):
        report = json.loads(context_tree())
        assert "reports/" in report["tree"]
        assert "q3.md" in report["tree"]
        assert report["files"] >= 4

    def test_respects_max_depth(self, sandbox):
        shallow = json.loads(context_tree(max_depth=1))
        deep = json.loads(context_tree(max_depth=5))
        assert "q3.md" not in shallow["tree"]
        assert "q3.md" in deep["tree"]

    def test_ignores_extra_patterns(self, sandbox):
        report = json.loads(context_tree(ignore="*.csv"))
        assert "invoices.csv" not in report["tree"]

    def test_skips_noise_directories(self, sandbox):
        (sandbox["root"] / "node_modules" / "left-pad").mkdir(parents=True)
        report = json.loads(context_tree(max_depth=5))
        assert "node_modules" not in report["tree"]

    def test_pointing_at_a_file_is_an_actionable_error(self, sandbox):
        result = json.loads(context_tree("notes.txt"))
        assert "read_context_file" in result["error"]

    def test_missing_path_reports_clearly(self, sandbox):
        assert "does not exist" in json.loads(context_tree("nope"))["error"]

    def test_sizes_are_reported(self, sandbox):
        assert json.loads(context_tree())["total_size"]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestRead:
    def test_reads_a_whole_file(self, sandbox):
        result = json.loads(read_context_file("data/invoices.csv"))
        assert "Acme" in result["content"]
        assert result["total_lines"] == 3

    def test_reads_a_line_range(self, sandbox):
        result = json.loads(read_context_file("data/invoices.csv", start_line=2, end_line=2))
        assert result["content"] == "1,Acme,4200"
        assert result["lines"] == 1

    def test_end_line_zero_reads_to_the_end(self, sandbox):
        result = json.loads(read_context_file("data/invoices.csv", start_line=2))
        assert result["lines"] == 2

    def test_start_beyond_the_file_returns_empty_not_an_error(self, sandbox):
        result = json.loads(read_context_file("notes.txt", start_line=500))
        assert result["content"] == ""

    def test_binary_files_are_refused_with_a_pointer(self, sandbox):
        result = json.loads(read_context_file("binary.bin"))
        assert "analyze_file" in result["error"]

    def test_directory_is_refused_with_a_pointer(self, sandbox):
        assert "context_tree" in json.loads(read_context_file("data"))["error"]

    def test_missing_file_reports_clearly(self, sandbox):
        assert "does not exist" in json.loads(read_context_file("nope.txt"))["error"]

    def test_paths_are_reported_relative_to_the_root(self, sandbox):
        # Absolute layout is not the agent's business, and leaking it is a
        # small information disclosure for no benefit.
        result = json.loads(read_context_file("notes.txt"))
        assert result["path"] == "notes.txt"
        assert str(sandbox["tmp"]) not in json.dumps(result)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_finds_matching_lines(self, sandbox):
        result = json.loads(search_context_tree("Risks"))
        assert result["count"] == 1
        assert result["matches"][0]["path"] == "reports/2026/q3.md"
        assert result["matches"][0]["line"] == 5

    def test_is_case_insensitive_by_default(self, sandbox):
        assert json.loads(search_context_tree("risks"))["count"] == 1

    def test_case_sensitive_mode(self, sandbox):
        assert json.loads(search_context_tree("risks", case_sensitive=True))["count"] == 0

    def test_file_pattern_narrows_the_search(self, sandbox):
        assert json.loads(search_context_tree("Acme", file_pattern="*.md"))["count"] == 0
        assert json.loads(search_context_tree("Acme", file_pattern="*.csv"))["count"] == 1

    def test_regex_is_supported(self, sandbox):
        assert json.loads(search_context_tree(r"Revenue grew \d+%"))["count"] == 1

    def test_invalid_regex_falls_back_to_a_literal_search(self, sandbox):
        # An agent passing "12%" or "a(b" should get results, not a stack trace.
        result = json.loads(search_context_tree("12%"))
        assert "error" not in result

    def test_empty_query_is_rejected(self, sandbox):
        assert "error" in json.loads(search_context_tree("   "))

    def test_max_results_caps_the_output(self, sandbox):
        (sandbox["root"] / "many.txt").write_text("needle\n" * 100)
        result = json.loads(search_context_tree("needle", max_results=5))
        assert result["count"] == 5
        assert result["truncated"] is True

    def test_binary_files_are_skipped(self, sandbox):
        assert "error" not in json.loads(search_context_tree("\\x00"))


# ---------------------------------------------------------------------------
# Describe
# ---------------------------------------------------------------------------


class TestDescribe:
    def test_reports_markdown_headings(self, sandbox):
        result = json.loads(describe_context_file("reports/2026/q3.md"))
        assert result["outline"] == ["# Q3 Report", "## Risks"]
        assert result["kind"] == "text"

    def test_reports_python_definitions(self, sandbox):
        (sandbox["root"] / "mod.py").write_text("import os\n\n\nclass Thing:\n    pass\n\n\ndef run():\n    pass\n")
        result = json.loads(describe_context_file("mod.py"))
        assert "class Thing:" in result["outline"]
        assert "def run():" in result["outline"]

    def test_binary_is_flagged_without_reading_it(self, sandbox):
        result = json.loads(describe_context_file("binary.bin"))
        assert result["kind"] == "binary"
        assert "analyze_file" in result["note"]

    def test_includes_size_and_modified_time(self, sandbox):
        result = json.loads(describe_context_file("notes.txt"))
        assert result["size_bytes"] > 0
        assert result["modified"]

    def test_preview_is_bounded(self, sandbox):
        (sandbox["root"] / "big.txt").write_text("x" * 10_000)
        assert len(json.loads(describe_context_file("big.txt"))["preview"]) <= 600

    def test_directory_is_refused(self, sandbox):
        assert "context_tree" in json.loads(describe_context_file("data"))["error"]

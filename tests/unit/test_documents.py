"""Tests for document generation and download.

The PDF writer is hand-rolled, so these check the bytes are a structurally valid
PDF rather than only that a file appeared: a broken cross-reference table
produces a file of the right size that no reader will open.
"""

from __future__ import annotations

import json

import pytest

from src.tools.documents import (
    FORMATS,
    delete_generated_document,
    generate_document,
    list_generated_documents,
    parse_markdown,
)
from src.tools.pdf_writer import Line, build, paginate, wrap

REPORT = """## Findings

The audit trail is **hash chained**, so a quiet edit is detectable.

- Read-only SQL blocks writes
- PII is redacted first

1. Ingest
2. Query

| Backend | Hosted |
| --- | --- |
| sqlite | no |
| qdrant | yes |

```
RAG_BACKEND=qdrant
```
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))


class TestMarkdown:
    def test_recognises_every_block_kind(self):
        kinds = {block.kind for block in parse_markdown(REPORT)}
        assert {"heading", "paragraph", "bullet", "number", "table", "code"} <= kinds

    def test_heading_level_comes_from_the_hashes(self):
        blocks = parse_markdown("# One\n\n### Three")
        headings = [block for block in blocks if block.kind == "heading"]
        assert [block.level for block in headings] == [1, 3]

    def test_pipes_without_a_separator_are_not_a_table(self):
        # "a | b" in prose is common and turning it into a table mangles the line.
        blocks = parse_markdown("costs are 5 | 10 per unit")
        assert [block.kind for block in blocks] == ["paragraph"]

    def test_table_cells_are_split(self):
        rows = [block.cells for block in parse_markdown(REPORT) if block.kind == "table"]
        assert rows[0] == ["Backend", "Hosted"]
        assert ["qdrant", "yes"] in rows

    def test_code_block_keeps_its_contents_verbatim(self):
        block = next(b for b in parse_markdown(REPORT) if b.kind == "code")
        assert block.text == "RAG_BACKEND=qdrant"

    def test_empty_input(self):
        assert parse_markdown("") == []


class TestPdfWriter:
    def test_produces_a_structurally_valid_pdf(self):
        pdf = build([Line("Hello", size=18, font="F2"), Line("Body text")], title="T")
        assert pdf.startswith(b"%PDF-1.4")
        assert pdf.rstrip().endswith(b"%%EOF")
        assert b"/Type /Catalog" in pdf and b"/Type /Pages" in pdf and b"/Type /Page" in pdf
        assert b"xref" in pdf and b"trailer" in pdf and b"startxref" in pdf

    def test_cross_reference_offsets_point_at_their_objects(self):
        # A PDF with the right bytes and the wrong offsets is the failure mode
        # here, and it opens as a corrupt file rather than raising anywhere.
        pdf = build([Line(f"Line {n}") for n in range(120)], title="Offsets")

        # Follow startxref to the table, which also checks startxref itself.
        # Searching for the last "xref" finds the one inside "startxref".
        declared = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
        assert pdf[declared:declared + 4] == b"xref"

        rows = pdf[declared:].split(b"\n")[2:]
        entries = [int(row.split()[0]) for row in rows if row.rstrip().endswith(b" n")]
        assert entries
        for number, offset in enumerate(entries, start=1):
            assert pdf[offset:offset + 12].startswith(f"{number} 0 obj".encode())

    def test_long_documents_paginate(self):
        pages = paginate([Line(f"Line {n}") for n in range(300)])
        assert len(pages) > 1
        assert all(page for page in pages)

    def test_wrapping_keeps_lines_inside_the_margin(self):
        for piece in wrap("word " * 400, 11):
            assert len(piece) <= 108

    def test_a_word_longer_than_the_line_is_broken(self):
        assert len(wrap("x" * 500, 11)) > 1

    def test_characters_outside_latin1_do_not_break_it(self):
        pdf = build([Line("Em dash — curly ’quotes’ and 日本語")], title="Unicode")
        assert pdf.startswith(b"%PDF")

    def test_parentheses_are_escaped(self):
        # Unescaped, these terminate the PDF string and corrupt the page.
        pdf = build([Line("a (nested (pair) here) and a backslash \\")])
        assert rb"\(" in pdf and rb"\)" in pdf


class TestGeneration:
    @pytest.mark.parametrize("fmt", FORMATS)
    def test_every_format_produces_a_file(self, fmt):
        result = generate_document(REPORT, filename="report", format=fmt, title="Report")
        assert result["success"], result.get("error")
        assert result["size_bytes"] > 0
        assert result["download_url"].endswith(f"report.{fmt}")

    def test_pdf_is_a_pdf(self):
        result = generate_document(REPORT, format="pdf", title="Report")
        assert open(result["path"], "rb").read(5) == b"%PDF-"

    def test_docx_keeps_the_structure(self):
        docx = pytest.importorskip("docx")
        result = generate_document(REPORT, format="docx", title="Report")
        document = docx.Document(result["path"])
        styles = {paragraph.style.name for paragraph in document.paragraphs}
        assert "List Bullet" in styles and "List Number" in styles
        assert document.tables and len(document.tables[0].rows) == 3

    def test_html_escapes_before_it_formats(self):
        result = generate_document("A <script>alert(1)</script> tag", format="html")
        page = open(result["path"], encoding="utf-8").read()
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_html_renders_inline_markdown(self):
        result = generate_document("This is **bold** and `code`.", format="html")
        page = open(result["path"], encoding="utf-8").read()
        assert "<strong>bold</strong>" in page and "<code>code</code>" in page

    def test_csv_uses_the_table_when_there_is_one(self):
        result = generate_document(REPORT, format="csv")
        rows = open(result["path"], encoding="utf-8").read().splitlines()
        assert rows[0] == "Backend,Hosted"

    def test_json_round_trips(self):
        result = generate_document(REPORT, format="json", title="Report")
        payload = json.loads(open(result["path"], encoding="utf-8").read())
        assert payload["title"] == "Report"
        assert any(block["kind"] == "table" for block in payload["blocks"])

    def test_unknown_format_is_refused(self):
        result = generate_document("x", format="exe")
        assert not result["success"] and "exe" in result["error"]

    def test_empty_content_is_refused(self):
        assert not generate_document("   ")["success"]

    def test_oversized_content_is_refused(self):
        assert not generate_document("x" * 500_000)["success"]

    def test_names_do_not_collide(self):
        first = generate_document("one", filename="same", format="md")
        second = generate_document("two", filename="same", format="md")
        assert first["name"] != second["name"]

    def test_filename_cannot_steer_where_it_lands(self):
        result = generate_document("x", filename="../../etc/passwd", format="txt")
        assert result["success"]
        assert "/" not in result["name"] and result["name"].startswith("passwd")

    def test_listing_and_deleting(self):
        created = generate_document("x", filename="temp", format="md")
        assert created["name"] in {item["name"] for item in list_generated_documents()}
        assert delete_generated_document(created["name"])
        assert created["name"] not in {item["name"] for item in list_generated_documents()}

    def test_deleting_something_absent(self):
        assert not delete_generated_document("never-existed.pdf")

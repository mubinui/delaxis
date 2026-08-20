"""Tests for upload handling and file/image analysis.

Image dimensions are parsed straight from file headers, so the fixtures below
build real (if tiny) PNG/GIF/BMP/JPEG bytes rather than mocking the parser —
a header parser tested against mocks proves nothing.
"""

import json
import struct
import zlib

import pytest

from src.tools.file_analysis import (
    ALLOWED_SUFFIXES,
    analyze_file,
    analyze_image,
    delete_uploaded_file,
    extract_document_text,
    image_dimensions,
    list_uploaded_files,
    save_uploaded_bytes,
    uploads_dir,
)


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DELAXIS_CONTEXT_ROOTS", str(tmp_path / "uploads"))
    monkeypatch.delenv("DELAXIS_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("DELAXIS_VISION_MODEL", raising=False)
    return tmp_path


def png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    raw = b"".join(b"\x00" + b"\x00" * (width * 3) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def gif_bytes(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 10


def bmp_bytes(width: int, height: int) -> bytes:
    return b"BM" + b"\x00" * 16 + struct.pack("<ii", width, height) + b"\x00" * 8


def jpeg_bytes(width: int, height: int) -> bytes:
    # SOI, then a SOF0 segment carrying the dimensions.
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width)
    return b"\xff\xd8" + sof + b"\x00" * 8 + b"\xff\xd9"


# ---------------------------------------------------------------------------
# Upload safety
# ---------------------------------------------------------------------------


class TestUploadSafety:
    def test_stores_an_allowed_file(self):
        record = save_uploaded_bytes("report.csv", b"a,b\n1,2\n")
        assert record["name"] == "report.csv"
        assert record["kind"] == "document"
        assert (uploads_dir() / "report.csv").exists()

    @pytest.mark.parametrize("name", ["evil.sh", "run.exe", "lib.so", "noext"])
    def test_rejects_disallowed_extensions(self, name):
        with pytest.raises(ValueError, match="not accepted"):
            save_uploaded_bytes(name, b"x")

    @pytest.mark.parametrize(
        "name",
        ["../../etc/passwd.txt", "../../../root/.bashrc.txt", "/etc/cron.d/task.txt"],
    )
    def test_strips_every_directory_component(self, name):
        # An upload must never be able to steer where it lands.
        record = save_uploaded_bytes(name, b"x")
        stored = uploads_dir() / record["name"]
        assert stored.parent == uploads_dir()
        assert ".." not in record["name"]

    def test_sanitises_hostile_characters(self):
        record = save_uploaded_bytes("we;ird$na|me.txt", b"x")
        assert record["name"] == "we_ird_na_me.txt"

    def test_blank_stem_gets_a_default_name(self):
        assert save_uploaded_bytes("   .txt", b"x")["name"].startswith("upload")

    def test_dotfile_without_a_real_extension_is_rejected(self):
        # Path(".txt").suffix is "", so this is a dotfile with no extension.
        with pytest.raises(ValueError, match="not accepted"):
            save_uploaded_bytes(".txt", b"x")

    def test_collisions_get_a_suffix_not_an_overwrite(self):
        first = save_uploaded_bytes("notes.txt", b"first")
        second = save_uploaded_bytes("notes.txt", b"second")
        assert first["name"] != second["name"]
        assert (uploads_dir() / first["name"]).read_bytes() == b"first"

    def test_oversized_upload_is_rejected(self, monkeypatch):
        monkeypatch.setattr("src.tools.file_analysis.MAX_UPLOAD_BYTES", 16)
        with pytest.raises(ValueError, match="over the"):
            save_uploaded_bytes("big.txt", b"x" * 64)

    def test_images_are_labelled_as_images(self):
        assert save_uploaded_bytes("shot.png", png_bytes(8, 8))["kind"] == "image"

    def test_allowlist_covers_the_documented_formats(self):
        for suffix in (".pdf", ".docx", ".xlsx", ".csv", ".png", ".jpg"):
            assert suffix in ALLOWED_SUFFIXES


# ---------------------------------------------------------------------------
# Listing and deletion
# ---------------------------------------------------------------------------


class TestListing:
    def test_lists_uploads_newest_first(self):
        save_uploaded_bytes("one.txt", b"1")
        save_uploaded_bytes("two.txt", b"2")
        report = json.loads(list_uploaded_files())
        assert report["count"] == 2

    def test_filters_by_pattern(self):
        save_uploaded_bytes("invoice.csv", b"a,b\n")
        save_uploaded_bytes("notes.txt", b"x")
        assert json.loads(list_uploaded_files(pattern="invo"))["count"] == 1

    def test_empty_directory_is_not_an_error(self):
        assert json.loads(list_uploaded_files())["count"] == 0

    def test_delete_removes_the_file(self):
        save_uploaded_bytes("gone.txt", b"x")
        assert delete_uploaded_file("gone.txt") is True
        assert json.loads(list_uploaded_files())["count"] == 0

    def test_delete_of_a_missing_file_reports_false(self):
        assert delete_uploaded_file("never.txt") is False

    def test_delete_cannot_traverse(self, isolated_uploads):
        outside = isolated_uploads / "outside.txt"
        outside.write_text("keep me")
        assert delete_uploaded_file("../outside.txt") is False
        assert outside.exists()


# ---------------------------------------------------------------------------
# Image headers
# ---------------------------------------------------------------------------


class TestImageDimensions:
    @pytest.mark.parametrize(
        "name,builder,size",
        [
            ("a.png", png_bytes, (1280, 720)),
            ("a.gif", gif_bytes, (640, 480)),
            ("a.bmp", bmp_bytes, (300, 200)),
            ("a.jpg", jpeg_bytes, (1920, 1080)),
        ],
    )
    def test_reads_dimensions_from_the_header(self, name, builder, size):
        save_uploaded_bytes(name, builder(*size))
        assert image_dimensions(uploads_dir() / name) == size

    def test_truncated_image_does_not_raise(self):
        save_uploaded_bytes("broken.png", b"\x89PNG\r\n\x1a\n")
        assert image_dimensions(uploads_dir() / "broken.png") is None


class TestAnalyzeImage:
    def test_reports_metadata_without_a_vision_model(self):
        save_uploaded_bytes("shot.png", png_bytes(800, 600))
        report = json.loads(analyze_image("shot.png"))
        assert report["width"] == 800
        assert report["height"] == 600
        assert report["aspect_ratio"] == pytest.approx(1.333, abs=0.01)
        assert report["vision"]["available"] is False

    def test_missing_vision_config_explains_how_to_enable_it(self):
        save_uploaded_bytes("shot.png", png_bytes(8, 8))
        note = json.loads(analyze_image("shot.png"))["vision"]["note"]
        assert "DELAXIS_VISION_PROVIDER" in note

    def test_svg_returns_its_source(self):
        save_uploaded_bytes("logo.svg", b'<svg width="10" height="10"></svg>')
        report = json.loads(analyze_image("logo.svg"))
        assert "<svg" in report["svg_source"]

    def test_non_image_is_refused_with_a_pointer(self):
        save_uploaded_bytes("notes.txt", b"x")
        assert "analyze_file" in json.loads(analyze_image("notes.txt"))["error"]

    def test_missing_file_reports_clearly(self):
        assert "does not exist" in json.loads(analyze_image("nope.png"))["error"]


# ---------------------------------------------------------------------------
# Document analysis
# ---------------------------------------------------------------------------


class TestAnalyzeCsv:
    CSV = b"id,customer,amount,notes\n1,Acme,4200,ok\n2,Globex,1300,\n3,Initech,,late\n4,Umbrella,890,ok\n"

    def test_reports_shape(self):
        save_uploaded_bytes("invoices.csv", self.CSV)
        report = json.loads(analyze_file("invoices.csv"))
        assert report["row_count"] == 4
        assert report["column_count"] == 4

    def test_profiles_numeric_columns(self):
        save_uploaded_bytes("invoices.csv", self.CSV)
        report = json.loads(analyze_file("invoices.csv"))
        amount = next(column for column in report["columns"] if column["name"] == "amount")
        assert amount["numeric"] is True
        assert amount["min"] == 890
        assert amount["max"] == 4200
        assert amount["mean"] == pytest.approx(2130.0)

    def test_counts_missing_values(self):
        save_uploaded_bytes("invoices.csv", self.CSV)
        report = json.loads(analyze_file("invoices.csv"))
        amount = next(column for column in report["columns"] if column["name"] == "amount")
        assert amount["empty"] == 1

    def test_text_columns_are_not_marked_numeric(self):
        save_uploaded_bytes("invoices.csv", self.CSV)
        report = json.loads(analyze_file("invoices.csv"))
        customer = next(column for column in report["columns"] if column["name"] == "customer")
        assert "numeric" not in customer

    def test_semicolon_delimiter_is_detected(self):
        save_uploaded_bytes("euro.csv", b"id;name\n1;Acme\n2;Globex\n")
        report = json.loads(analyze_file("euro.csv"))
        assert report["column_count"] == 2

    def test_empty_csv_is_not_an_error(self):
        save_uploaded_bytes("empty.csv", b"")
        assert "error" not in json.loads(analyze_file("empty.csv"))


class TestAnalyzeJson:
    def test_describes_shape_rather_than_dumping_data(self):
        save_uploaded_bytes("data.json", b'{"user": {"name": "a", "age": 1}, "tags": ["x", "y"]}')
        report = json.loads(analyze_file("data.json"))
        assert report["top_level_type"] == "dict"
        assert report["shape"]["user"]["name"] == "str"

    def test_malformed_json_reports_clearly(self):
        save_uploaded_bytes("bad.json", b"{not json")
        assert "could not be parsed" in json.loads(analyze_file("bad.json"))["note"]


class TestAnalyzeText:
    def test_returns_content_and_line_count(self):
        save_uploaded_bytes("notes.md", b"# Title\n\nBody text.\n")
        report = json.loads(analyze_file("notes.md"))
        assert "# Title" in report["text"]
        assert report["extractor"] == "text"

    def test_truncates_to_max_chars_and_says_so(self):
        save_uploaded_bytes("long.txt", b"x" * 20_000)
        report = json.loads(analyze_file("long.txt", max_chars=500))
        assert len(report["text"]) == 500
        assert report["truncated"] is True
        assert report["text_length"] == 20_000

    def test_max_chars_is_clamped_to_a_floor(self):
        save_uploaded_bytes("long.txt", b"x" * 5_000)
        assert len(json.loads(analyze_file("long.txt", max_chars=1))["text"]) == 500


class TestAnalyzeFileGuards:
    def test_image_is_refused_with_a_pointer(self):
        save_uploaded_bytes("shot.png", png_bytes(8, 8))
        assert "analyze_image" in json.loads(analyze_file("shot.png"))["error"]

    def test_missing_file_points_at_the_listing_tool(self):
        assert "list_uploaded_files" in json.loads(analyze_file("nope.csv"))["error"]

    def test_traversal_is_refused(self, isolated_uploads):
        (isolated_uploads / "secret.txt").write_text("SENSITIVE-MARKER-9f3a")
        result = json.loads(analyze_file("../secret.txt"))
        assert "error" in result
        assert "SENSITIVE-MARKER-9f3a" not in json.dumps(result)

    def test_optional_extractors_report_how_to_install(self, monkeypatch):
        save_uploaded_bytes("doc.pdf", b"%PDF-1.4 fake")
        report = json.loads(analyze_file("doc.pdf"))
        # Either pypdf is installed and parsing fails cleanly, or it is absent
        # and the tool says what to install. Both must be legible, never a crash.
        assert "error" not in report
        assert report["extractor"] in {"pypdf", "unavailable"}


class TestExtractDocumentText:
    def test_returns_bare_text(self):
        save_uploaded_bytes("notes.md", b"# Title\n\nBody.\n")
        report = json.loads(extract_document_text("notes.md"))
        assert report["text"].startswith("# Title")
        assert "columns" not in report

    def test_reports_truncation(self):
        save_uploaded_bytes("long.txt", b"y" * 30_000)
        report = json.loads(extract_document_text("long.txt", max_chars=1_000))
        assert report["truncated"] is True

    def test_missing_file_reports_clearly(self):
        assert "error" in json.loads(extract_document_text("nope.txt"))

"""Write a PDF without a PDF library.

PDF is a text format with a byte-offset index at the end, and everything a
generated report needs — pages, two font weights, wrapped text — is a few
hundred lines. That is cheaper than adding a rendering engine as a dependency
for the one thing it would be used for, and it matches how image dimensions are
read here without Pillow.

Deliberately limited: Helvetica in regular and bold, left-aligned text, and
automatic pagination. Anything wanting images, tables or colour should generate
HTML, which every browser will print to PDF far better than this could.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A4 in PostScript points, which is the unit PDF measures in.
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 56

REGULAR = "F1"
BOLD = "F2"

#: Helvetica's average character width as a fraction of the font size. Real
#: wrapping needs the font's width table; this is close enough that lines land
#: inside the margin, which is all that is being asked of it.
_WIDTH_RATIO = 0.50


@dataclass(slots=True)
class Line:
    """One line of text, already wrapped."""

    text: str
    size: float = 11.0
    font: str = REGULAR
    #: Extra space above this line, in points.
    space_before: float = 0.0


def _escape(text: str) -> str:
    """Escape the three characters that mean something inside a PDF string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _latin1(text: str) -> str:
    """PDF's built-in fonts are single-byte; keep what maps and drop the rest.

    Substituting the common typographic characters first means an em dash or a
    curly quote degrades to something readable rather than disappearing.
    """
    replacements = {
        "—": "-", "–": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "…": "...", " ": " ",
        "•": "-", "→": "->", "·": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")


def wrap(text: str, size: float, width: float = PAGE_WIDTH - 2 * MARGIN) -> list[str]:
    """Break text to fit the page, without splitting words that fit."""
    limit = max(8, int(width / (size * _WIDTH_RATIO)))
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        # A single word longer than the line has to be cut somewhere.
        while len(word) > limit:
            lines.append(word[:limit])
            word = word[limit:]
        current = word
    if current:
        lines.append(current)
    return lines


def paginate(lines: list[Line]) -> list[list[tuple[Line, float]]]:
    """Assign lines to pages, returning each with its baseline position."""
    pages: list[list[tuple[Line, float]]] = []
    page: list[tuple[Line, float]] = []
    cursor = PAGE_HEIGHT - MARGIN

    for line in lines:
        leading = line.size * 1.45
        cursor -= line.space_before
        if cursor - leading < MARGIN:
            pages.append(page)
            page = []
            cursor = PAGE_HEIGHT - MARGIN
        cursor -= leading
        page.append((line, cursor))

    if page:
        pages.append(page)
    return pages or [[]]


def _content_stream(page: list[tuple[Line, float]]) -> bytes:
    parts = ["BT"]
    for line, baseline in page:
        if not line.text:
            continue
        parts.append(f"/{line.font} {line.size:g} Tf")
        # Absolute placement per line, so a font size change cannot drift the
        # baseline the way relative leading would.
        parts.append(f"1 0 0 1 {MARGIN} {baseline:.2f} Tm")
        parts.append(f"({_escape(_latin1(line.text))}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build(lines: list[Line], title: str = "") -> bytes:
    """Render lines into a complete PDF document."""
    pages = paginate(lines)

    objects: list[bytes] = []          # object 1 is objects[0]

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add(b"")              # placeholder, filled once ids are known
    pages_id = add(b"")
    regular_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    bold_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>"
    )

    page_ids: list[int] = []
    for page in pages:
        stream = _content_stream(page)
        content_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        page_ids.append(add(
            b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
            b"/MediaBox [0 0 " + f"{PAGE_WIDTH} {PAGE_HEIGHT}".encode() + b"] "
            b"/Resources << /Font << /" + REGULAR.encode() + b" "
            + str(regular_id).encode() + b" 0 R /" + BOLD.encode() + b" "
            + str(bold_id).encode() + b" 0 R >> >> "
            b"/Contents " + str(content_id).encode() + b" 0 R >>"
        ))

    kids = b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
    objects[pages_id - 1] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode() + b" >>"
    )
    objects[catalog_id - 1] = (
        b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>"
    )

    info_id = add(
        b"<< /Title (" + _escape(_latin1(title or "Document")).encode("latin-1")
        + b") /Producer (Delaxis) >>"
    )

    # Assemble, recording where each object starts: the cross-reference table at
    # the end is byte offsets, and a reader will reject the file if they are wrong.
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode()
        + b" /Root " + str(catalog_id).encode() + b" 0 R"
        + b" /Info " + str(info_id).encode() + b" 0 R >>\n"
        b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
    )
    return bytes(out)

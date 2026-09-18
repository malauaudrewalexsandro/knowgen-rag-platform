"""
Extracts an ordered, structure-preserving list of "blocks" (heading /
paragraph / table / image) from a source document, for the "clone this PDF
as a template" flow (POST /generate/clone).

STRATEGY: walks Docling's own `DoclingDocument.export_to_markdown()`
output instead of hand-reconstructing order from HybridChunker's text
chunks. An earlier version built blocks from each text chunk's "nearest
heading" metadata, which silently DROPPED section headers that have no
body paragraph directly beneath them before the next sub-heading — common
in resumes/CVs: a big "PROFESSIONAL EXPERIENCE" header immediately
followed by a company name sub-heading, with no prose of its own under
the section header itself. Docling's markdown export is built specifically
to serialize the whole document in true reading order including every
detected heading, so parsing that directly is more reliable. Heading
level is taken from the markdown's '#' count.

NOTE (version drift, same caveat as chunking.py): `export_to_markdown()`
is a long-standing docling_core API but if it's renamed in whatever
version `pip install docling` resolves to, this is the one place to
update.

Images have no reliable position in the markdown text (Docling doesn't
embed image bytes there), so they're extracted separately
(chunking.extract_images) and appended at the end rather than spliced in
— a known limitation (position, not data, is lost).
"""
import re

from app.core import chunking

MAX_HEADING_LEVEL = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")


def extract_document_blocks(file_path: str) -> list[dict]:
    doc = chunking.convert_document(file_path)
    markdown = doc.export_to_markdown()
    blocks = _parse_markdown_blocks(markdown)

    for img in chunking.extract_images(doc):
        blocks.append({
            "type": "image", "image_bytes": img.image_bytes,
            "mime_type": img.mime_type, "page": img.page,
        })

    return blocks


def _parse_markdown_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    lines = markdown.splitlines()
    paragraph_buf: list[str] = []

    def flush_paragraph():
        if paragraph_buf:
            text = " ".join(paragraph_buf).strip()
            if text:
                blocks.append({"type": "paragraph", "text": text, "page": None})
            paragraph_buf.clear()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            flush_paragraph()
            level = min(len(heading_match.group(1)), MAX_HEADING_LEVEL)
            text = heading_match.group(2).strip()
            if text:
                blocks.append({"type": "heading", "text": text, "level": level, "page": None})
            i += 1
            continue

        # A markdown table: a '|' row followed immediately by a
        # '|---|---|' alignment-separator row.
        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1].strip()):
            flush_paragraph()
            table_lines = [lines[i], lines[i + 1]]
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                table_lines.append(lines[j])
                j += 1
            blocks.append({"type": "table", "markdown": "\n".join(table_lines), "page": None})
            i = j
            continue

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        paragraph_buf.append(stripped)
        i += 1

    flush_paragraph()
    return blocks


def detect_title(blocks: list[dict], fallback: str) -> tuple[str, list[dict]]:
    """
    Uses the first level-1 heading (if the document starts with one) as the
    document title instead of the raw uploaded filename — e.g. a resume's
    name line rather than "some_resume.pdf". Returns (title, remaining_blocks)
    with that heading block removed so it isn't rendered twice.
    """
    # Docling doesn't reliably mark a document's own title as H1 in its
    # markdown export (this resume's name line came out H2) — so any
    # heading in the very first block position is treated as the title,
    # regardless of the numeric level Docling assigned it.
    if blocks and blocks[0]["type"] == "heading":
        return blocks[0]["text"], blocks[1:]
    return fallback, blocks


def parse_markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    """
    A markdown table block's raw text -> (columns, rows). Skips the '---'
    alignment separator row that markdown tables always have.
    """
    lines = [ln.strip() for ln in markdown.strip().splitlines() if ln.strip()]
    if not lines:
        return [], []

    def split_row(line: str) -> list[str]:
        cells = line.strip().strip("|").split("|")
        return [c.strip() for c in cells]

    columns = split_row(lines[0])
    rows = []
    for line in lines[1:]:
        if _TABLE_SEPARATOR_RE.match(line):
            continue
        rows.append(split_row(line))
    return columns, rows

"""PDF clone generation (reportlab) from ordered document blocks — see
app/core/doc_generation/document_blocks.py."""
import io

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.doc_generation.document_blocks import parse_markdown_table

_HEADING_STYLES = ["Heading1", "Heading2", "Heading3", "Heading4"]


def _table_flowable(markdown: str):
    columns, rows = parse_markdown_table(markdown)
    if not columns:
        return None
    data = [columns] + rows
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4057")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    return t


def _image_flowable(image_bytes: bytes, max_width_cm: float = 14):
    try:
        pil_img = PILImage.open(io.BytesIO(image_bytes))
        w, h = pil_img.size
        max_w = max_width_cm * cm
        scale = max_w / w
        return Image(io.BytesIO(image_bytes), width=max_w, height=h * scale)
    except Exception:
        return None


def generate_pdf_clone(title: str, blocks: list[dict], output_path: str) -> str:
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 0.5 * cm)]

    for b in blocks:
        if b["type"] == "heading":
            level = b.get("level", 1)
            style_name = _HEADING_STYLES[min(level, len(_HEADING_STYLES)) - 1]
            story.append(Paragraph(b["text"], styles[style_name]))
        elif b["type"] == "paragraph":
            story.append(Paragraph(b["text"], styles["BodyText"]))
            story.append(Spacer(1, 0.2 * cm))
        elif b["type"] == "table":
            flowable = _table_flowable(b["markdown"])
            if flowable:
                story.append(flowable)
                story.append(Spacer(1, 0.3 * cm))
        elif b["type"] == "image":
            flowable = _image_flowable(b["image_bytes"])
            if flowable:
                story.append(flowable)
                story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    return output_path

"""
PDF report generation (reportlab). Each section becomes: heading,
narrative paragraph, an optional chart image, and an optional data table.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.core.doc_generation.chart_builder import build_chart


def _table_flowable(rows: list[dict]) -> Table:
    columns = list(rows[0].keys())
    data = [columns] + [[str(r.get(c, "")) for c in columns] for r in rows]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4057")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    return t


def generate_pdf(spec: dict, output_path: str) -> str:
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = [Paragraph(spec["title"], styles["Title"]), Spacer(1, 0.5 * cm)]

    for section in spec["sections"]:
        story.append(Paragraph(section["heading"], styles["Heading2"]))
        if section.get("narrative"):
            story.append(Paragraph(section["narrative"], styles["BodyText"]))
        story.append(Spacer(1, 0.3 * cm))

        if section.get("chart_data"):
            cd = section["chart_data"]
            chart_path = build_chart(cd["type"], cd["labels"], cd["values"], title=cd.get("title"))
            story.append(Image(chart_path, width=14 * cm, height=8 * cm))
            story.append(Spacer(1, 0.3 * cm))

        preview = section.get("table_preview") or {}
        if preview.get("rows"):
            story.append(_table_flowable(preview["rows"]))
        story.append(Spacer(1, 0.6 * cm))

    doc.build(story)
    return output_path

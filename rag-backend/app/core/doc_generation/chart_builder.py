"""
Chart image generation for the document generation pipeline.

Renders matplotlib charts to PNG files on disk. Charts are produced as
static images so they can be embedded uniformly across PDF/DOCX/PPTX (all
three need a raster/vector image, not a live chart object). XLSX is the
one exception — xlsx_generator.py builds a NATIVE Excel chart object there
instead of embedding this PNG, so it stays editable/interactive in Excel.
"""
import os
import uuid
from typing import Literal

import matplotlib
matplotlib.use("Agg")  # headless — no display backend needed on a server
import matplotlib.pyplot as plt

from app.config import settings

ChartType = Literal["bar", "line", "pie", "scatter"]

# Sibling of storage/metadata, storage/uploads, etc.
CHART_TMP_DIR = os.path.join(os.path.dirname(settings.metadata_db_path), "..", "generated_charts")


def build_chart(
    chart_type: ChartType,
    labels: list[str],
    values: list[float] | dict[str, list[float]],
    title: str | None = None,
    x_label: str | None = None,
    y_label: str | None = None,
) -> str:
    """
    Renders a chart to a PNG file and returns its path.

    `values` is either a plain list (single-series bar/line/pie/scatter) or
    a dict of {series_name: values} for multi-series bar/line charts.
    """
    os.makedirs(CHART_TMP_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)

    series = values if isinstance(values, dict) else {"": values}

    if chart_type == "bar":
        n_series = len(series)
        width = 0.8 / max(n_series, 1)
        x = range(len(labels))
        for i, (name, vals) in enumerate(series.items()):
            offsets = [xi + i * width for xi in x]
            ax.bar(offsets, vals, width=width, label=name or None)
        ax.set_xticks([xi + width * (n_series - 1) / 2 for xi in x])
        ax.set_xticklabels(labels, rotation=30, ha="right")
    elif chart_type == "line":
        for name, vals in series.items():
            ax.plot(labels, vals, marker="o", label=name or None)
        plt.xticks(rotation=30, ha="right")
    elif chart_type == "pie":
        vals = next(iter(series.values()))
        ax.pie(vals, labels=labels, autopct="%1.1f%%")
    elif chart_type == "scatter":
        vals = next(iter(series.values()))
        ax.scatter(labels, vals)
        plt.xticks(rotation=30, ha="right")
    else:
        raise ValueError(f"Unsupported chart_type: {chart_type}")

    if title:
        ax.set_title(title)
    if x_label and chart_type != "pie":
        ax.set_xlabel(x_label)
    if y_label and chart_type != "pie":
        ax.set_ylabel(y_label)
    if len(series) > 1 or (len(series) == 1 and next(iter(series.keys()))):
        ax.legend()

    fig.tight_layout()
    path = os.path.join(CHART_TMP_DIR, f"{uuid.uuid4()}.png")
    fig.savefig(path)
    plt.close(fig)
    return path

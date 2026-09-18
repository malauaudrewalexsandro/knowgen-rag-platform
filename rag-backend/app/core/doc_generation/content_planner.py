"""
Plans and writes the narrative content of a generated document, and (new)
plans a single chart on demand for the /chat tool-calling flow.

Given a document_id that has one or more ingested Excel/CSV tables
(app/core/excel_ingest.py + app/db/metadata_store.py), this either:
  - takes a user-supplied section spec as-is (routes_generate.py handles
    that branch), or
  - asks the LLM (reusing app/core/llm.py's chat(), same pattern
    app/core/rag_chain.py already uses) to look at each table's schema +
    sample rows and propose one section: a heading, a short narrative, and
    optionally a chart (which column to group by / aggregate).

plan_chart_for_table() is the single-table version of that same chart
planning, used when the user asks in plain chat to visualize one specific
table (rag_chain.py's `generate_chart` tool calls this).

Only schema + a few sample rows ever go to the LLM here — never full row
data — matching the "efficient retrieval" rule the rest of the codebase
already follows for spreadsheets (see excel_ingest.py's docstring).
"""
import json

from app.config import settings
from app.core import llm as llm_core
from app.core.sql_tool import run_readonly_query
from app.db import metadata_store

PLANNER_SYSTEM_PROMPT = """You are a business report writer. You are given \
metadata about one spreadsheet table (schema + a few sample rows) that has \
been ingested into a database. Propose ONE report section for it.

Respond with ONLY a JSON object, no other text, in this exact shape:
{
  "heading": "short section title",
  "narrative": "2-4 sentence written insight/summary a business reader would want",
  "chart": {
    "type": "bar" | "line" | "pie" | "scatter",
    "group_by_column": "column name to group by",
    "value_column": "numeric column to aggregate",
    "aggregate": "sum" | "avg" | "count"
  }
}
Only propose a chart if there is a sensible categorical column to group by \
and a numeric column to aggregate over it. If no chart makes sense, set \
"chart" to null.
"""

CHART_ONLY_SYSTEM_PROMPT = """You are given metadata about one spreadsheet \
table (schema + a few sample rows), plus what a user wants to visualize.

Respond with ONLY a JSON object, no other text, in this exact shape:
{
  "chart": {
    "type": "bar" | "line" | "pie" | "scatter",
    "group_by_column": "column name to group by",
    "value_column": "numeric column to aggregate",
    "aggregate": "sum" | "avg" | "count"
  }
}
Pick the group_by_column and value_column that best match what the user
asked to visualize. If nothing in the table can satisfy the request, set
"chart" to null.
"""


def _table_meta_to_prompt(table_row: dict) -> str:
    columns = json.loads(table_row["columns_json"])
    dtypes = json.loads(table_row["dtypes_json"])
    sample = run_readonly_query(f"SELECT * FROM {table_row['table_name']} LIMIT 3")
    cols_desc = ", ".join(f"{c} ({dtypes.get(c, '?')})" for c in columns)
    return (
        f"table_name: {table_row['table_name']}\n"
        f"sheet_name: {table_row['sheet_name']}\n"
        f"row_count: {table_row['row_count']}\n"
        f"columns: {cols_desc}\n"
        f"sample_rows: {sample.get('rows', [])}"
    )


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        if raw.endswith("```"):
            raw = raw[: -3]
    return raw.strip()


def plan_sections(document_id: str, llm_model: str | None = None) -> list[dict]:
    """Auto-plans one section per ingested Excel/CSV table for this document."""
    llm_model = llm_model or settings.default_llm_model
    tables = metadata_store.excel_tables_by_document(document_id)
    if not tables:
        raise ValueError(f"No ingested Excel tables found for document_id={document_id}")

    sections = []
    for table_row in tables:
        prompt = _table_meta_to_prompt(table_row)
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        resp = llm_core.chat(messages, model=llm_model, tools=None)
        raw = resp.choices[0].message.content or "{}"
        try:
            plan = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError:
            plan = {"heading": table_row["sheet_name"], "narrative": "", "chart": None}

        sections.append({
            "heading": plan.get("heading") or table_row["sheet_name"],
            "narrative": plan.get("narrative", ""),
            "table_name": table_row["table_name"],
            "chart_plan": plan.get("chart") or None,
        })
    return sections


def plan_chart_for_table(table_name: str, chart_intent: str, llm_model: str | None = None) -> dict | None:
    """
    Single-table chart planning, used by rag_chain.py's `generate_chart`
    tool when the user asks in plain chat to visualize a specific table
    (e.g. "buatin chart dari data_dummy_penjualan.xlsx").
    """
    llm_model = llm_model or settings.default_llm_model
    table_row = metadata_store.get_excel_table(table_name)
    if not table_row:
        return None

    prompt = _table_meta_to_prompt(table_row) + f"\n\nWhat the user wants to visualize: {chart_intent}"
    messages = [
        {"role": "system", "content": CHART_ONLY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    resp = llm_core.chat(messages, model=llm_model, tools=None)
    raw = resp.choices[0].message.content or "{}"
    try:
        plan = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None
    return plan.get("chart")


def resolve_chart_data(table_name: str | None, chart_plan: dict | None) -> dict | None:
    """
    Runs the actual GROUP BY aggregate SQL for a planned/requested chart and
    returns {"type", "title", "labels": [...], "values": [...]} ready for
    chart_builder.build_chart — or None if it isn't chartable / the query
    fails (a bad plan should degrade to "no chart", never break generation).
    """
    if not table_name or not chart_plan:
        return None
    group_col = chart_plan.get("group_by_column")
    value_col = chart_plan.get("value_column")
    if not group_col or not value_col:
        return None

    agg = {"sum": "SUM", "avg": "AVG", "count": "COUNT"}.get(chart_plan.get("aggregate", "sum"), "SUM")
    sql = (
        f"SELECT {group_col} AS label, {agg}({value_col}) AS value "
        f"FROM {table_name} GROUP BY {group_col} ORDER BY value DESC LIMIT 20"
    )
    result = run_readonly_query(sql)
    if result.get("error") or not result.get("rows"):
        return None

    rows = result["rows"]
    return {
        "type": chart_plan.get("type") or "bar",
        "title": f"{agg}({value_col}) by {group_col}",
        "labels": [str(r["label"]) for r in rows],
        "values": [float(r["value"]) if r["value"] is not None else 0.0 for r in rows],
    }


def get_table_preview(table_name: str, limit: int = 50) -> dict:
    """Small preview of raw rows for the report's data table (not embedded to the LLM)."""
    return run_readonly_query(f"SELECT * FROM {table_name} LIMIT {limit}")

"""
Excel/CSV ingestion.

Design choice (this is the "efficient retrieval" part Guido asked for):
each sheet becomes a real SQLite table, not a pile of embedded row-text.
Only a compact per-table SCHEMA SUMMARY gets embedded (sheet name, columns,
a couple of sample rows) — never the full row data. That keeps ingestion
cheap even for large spreadsheets, and lets the LLM find the *right table*
semantically, then query it *exactly* via SQL (app/core/sql_tool.py) instead
of guessing numbers from a handful of semantically-similar chunks.
"""
import os
import re

import pandas as pd

from app.config import settings

EXCEL_DB_PATH = os.path.join(os.path.dirname(settings.metadata_db_path), "excel_data.sqlite3")


def _sanitize_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(name).strip())
    if not name or name[0].isdigit():
        name = f"t_{name}"
    return name.lower()


def get_excel_conn():
    import sqlite3
    os.makedirs(os.path.dirname(EXCEL_DB_PATH), exist_ok=True)
    return sqlite3.connect(EXCEL_DB_PATH)


def ingest_excel(file_path: str, workbook_label: str) -> list[dict]:
    """
    Reads every sheet (or the single table, for CSV), writes each to its own
    SQLite table, and returns per-table metadata used both for the SQL tool
    (table_name/columns) and for building the embeddable schema summary.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        sheets = {"Sheet1": pd.read_csv(file_path)}
    else:
        sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")

    conn = get_excel_conn()
    results = []
    workbook_prefix = _sanitize_name(workbook_label)[:20]

    try:
        for sheet_name, df in sheets.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue

            df.columns = [_sanitize_name(c) for c in df.columns]
            # De-duplicate column names that collided after sanitizing. Checked
            # against the growing set of already-assigned names (not just an
            # occurrence counter) because pandas' own dupe-suffixing on the
            # Excel round-trip (e.g. "Total" / "Total.1") can otherwise collide
            # with a suffix we generate ourselves (both sanitizing to "total_1").
            used: set[str] = set()
            new_cols = []
            for c in df.columns:
                candidate = c
                n = 1
                while candidate in used:
                    candidate = f"{c}_{n}"
                    n += 1
                used.add(candidate)
                new_cols.append(candidate)
            df.columns = new_cols

            table_name = f"{workbook_prefix}_{_sanitize_name(sheet_name)}"[:60]
            df.to_sql(table_name, conn, if_exists="replace", index=False)

            sample_rows = df.head(3).astype(str).to_dict(orient="records")
            dtypes = {c: str(t) for c, t in df.dtypes.items()}

            results.append({
                "table_name": table_name,
                "sheet_name": sheet_name,
                "columns": list(df.columns),
                "dtypes": dtypes,
                "row_count": int(len(df)),
                "sample_rows": sample_rows,
            })
    finally:
        conn.commit()
        conn.close()

    return results


def build_schema_summary(table_meta: dict) -> str:
    """Compact natural-language description of a table, for embedding — this
    is what makes the table discoverable semantically without ever
    embedding its actual row data."""
    cols = ", ".join(f"{c} ({table_meta['dtypes'].get(c, '?')})" for c in table_meta["columns"])
    sample = "; ".join(str(r) for r in table_meta["sample_rows"][:2])
    return (
        f"Table '{table_meta['table_name']}' (from spreadsheet sheet "
        f"'{table_meta['sheet_name']}'), {table_meta['row_count']} rows. "
        f"Columns: {cols}. Example rows: {sample}"
    )

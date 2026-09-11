"""
Read-only SQL execution against the ingested Excel/CSV tables.

This is what makes retrieval "efficient" for tabular data (per the
requirement): instead of forcing every question through semantic chunk
similarity — which can only ever find text that *looks* similar, never
compute a real sum/average/count — the LLM writes an exact SQL query here
and gets a precise, computed answer back.

Safety, since this runs whatever SQL the LLM decides to write:
  - only SELECT (optionally prefixed with a WITH/CTE) is allowed
  - a fixed blocklist of write/schema/pragma keywords
  - only one statement per call (no `; DROP TABLE ...` smuggled in)
  - hard row cap on results
  - execution timeout via SQLite's progress handler
"""
import re
import sqlite3
import time

from app.core.excel_ingest import get_excel_conn

MAX_ROWS = 200
TIMEOUT_SECONDS = 5

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REPLACE\s+INTO)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    pass


def _validate(sql: str) -> str:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise UnsafeQueryError("Only a single statement is allowed (no ';' inside the query).")
    if not re.match(r"^\s*(WITH\b.*?\bSELECT\b|SELECT\b)", stripped, re.IGNORECASE | re.DOTALL):
        raise UnsafeQueryError("Only SELECT (optionally with a WITH/CTE prefix) is allowed.")
    if _FORBIDDEN.search(stripped):
        raise UnsafeQueryError("Query contains a disallowed keyword.")
    return stripped


def run_readonly_query(sql: str) -> dict:
    """Returns {columns, rows, truncated} on success, or {error} on failure."""
    try:
        clean_sql = _validate(sql)
    except UnsafeQueryError as e:
        return {"error": str(e)}

    conn = get_excel_conn()
    conn.execute("PRAGMA query_only = TRUE")  # belt-and-suspenders on top of _validate

    start = time.monotonic()

    def _abort_if_too_slow():
        return 1 if (time.monotonic() - start) > TIMEOUT_SECONDS else 0

    conn.set_progress_handler(_abort_if_too_slow, 1000)

    try:
        cur = conn.execute(clean_sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        return {
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows],
            "truncated": truncated,
        }
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            return {"error": f"Query timed out after {TIMEOUT_SECONDS}s — try a narrower query."}
        return {"error": f"SQL error: {e}"}
    except sqlite3.Error as e:
        return {"error": f"SQL error: {e}"}
    finally:
        conn.close()

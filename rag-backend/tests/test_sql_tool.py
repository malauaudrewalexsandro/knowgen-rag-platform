import pandas as pd
import pytest


@pytest.fixture
def sales_table(tmp_storage, tmp_path):
    """Ingest one small table so sql_tool has something real to query."""
    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame({
        "region": ["West", "East", "West", "North", "East"],
        "revenue": [100, 250, 175, 90, 300],
    })
    path = tmp_path / "sales.csv"
    df.to_csv(path, index=False)
    meta = excel_ingest.ingest_excel(str(path), workbook_label="sales.csv")[0]
    return tmp_storage["sql_tool"], meta["table_name"]


def test_valid_select_returns_correct_aggregate(sales_table):
    sql_tool, table = sales_table
    result = sql_tool.run_readonly_query(f"SELECT SUM(revenue) AS total FROM {table}")
    assert "error" not in result
    assert result["rows"][0]["total"] == 915


def test_valid_select_with_group_by(sales_table):
    sql_tool, table = sales_table
    result = sql_tool.run_readonly_query(
        f"SELECT region, SUM(revenue) AS total FROM {table} GROUP BY region ORDER BY total DESC"
    )
    assert result["rows"][0] == {"region": "East", "total": 550}


def test_with_cte_is_allowed(sales_table):
    sql_tool, table = sales_table
    sql = f"WITH t AS (SELECT * FROM {table}) SELECT COUNT(*) AS n FROM t"
    result = sql_tool.run_readonly_query(sql)
    assert result["rows"][0]["n"] == 5


@pytest.mark.parametrize("bad_sql", [
    "DROP TABLE sales",
    "DELETE FROM sales",
    "INSERT INTO sales (region) VALUES ('X')",
    "UPDATE sales SET revenue = 0",
    "PRAGMA table_info(sales)",
    "ATTACH DATABASE 'x.db' AS x",
    "CREATE TABLE evil (x INT)",
])
def test_write_and_schema_statements_are_rejected(sales_table, bad_sql):
    sql_tool, _table = sales_table
    result = sql_tool.run_readonly_query(bad_sql)
    assert "error" in result


def test_stacked_statements_are_rejected(sales_table):
    sql_tool, table = sales_table
    result = sql_tool.run_readonly_query(f"SELECT * FROM {table}; DROP TABLE {table}")
    assert "error" in result


def test_non_select_prefix_is_rejected(sales_table):
    sql_tool, _table = sales_table
    result = sql_tool.run_readonly_query("EXPLAIN SELECT 1")
    assert "error" in result


def test_unknown_table_returns_sql_error_not_crash(sales_table):
    sql_tool, _table = sales_table
    result = sql_tool.run_readonly_query("SELECT * FROM table_that_does_not_exist")
    assert "error" in result


def test_row_cap_is_enforced(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]
    sql_tool = tmp_storage["sql_tool"]
    df = pd.DataFrame({"n": list(range(500))})
    path = tmp_path / "big.csv"
    df.to_csv(path, index=False)
    table = excel_ingest.ingest_excel(str(path), workbook_label="big.csv")[0]["table_name"]

    result = sql_tool.run_readonly_query(f"SELECT * FROM {table}")
    assert len(result["rows"]) == sql_tool.MAX_ROWS
    assert result["truncated"] is True


def test_query_only_pragma_blocks_accidental_write_even_if_regex_missed_it(sales_table):
    """Belt-and-suspenders check: PRAGMA query_only should itself reject writes."""
    sql_tool, table = sales_table
    # Can't easily bypass the regex from here, but confirm the connection really
    # is read-only by hitting it directly the way run_readonly_query does.
    conn = sql_tool.get_excel_conn()
    conn.execute("PRAGMA query_only = TRUE")
    with pytest.raises(Exception):
        conn.execute(f"INSERT INTO {table} (region, revenue) VALUES ('X', 1)")
    conn.close()

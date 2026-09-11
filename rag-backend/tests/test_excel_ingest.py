import pandas as pd


def _write_xlsx(path, sheets: dict):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)


def test_ingest_xlsx_creates_one_table_per_sheet(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]

    sales = pd.DataFrame({
        "Region": ["West", "East", "West", "North"],
        "Revenue (IDR)": [1_000_000, 2_500_000, 1_750_000, 900_000],
        "Units Sold": [10, 25, 17, 9],
    })
    inventory = pd.DataFrame({
        "SKU": ["A1", "A2", "A3"],
        "Qty": [100, 0, 42],
    })
    path = tmp_path / "Q3 Report.xlsx"
    _write_xlsx(path, {"Sales": sales, "Inventory": inventory})

    results = excel_ingest.ingest_excel(str(path), workbook_label="Q3 Report.xlsx")

    assert len(results) == 2
    names = {r["sheet_name"] for r in results}
    assert names == {"Sales", "Inventory"}

    sales_meta = next(r for r in results if r["sheet_name"] == "Sales")
    assert sales_meta["row_count"] == 4
    # Column names must be sanitized to valid SQL identifiers.
    assert "revenue__idr_" in sales_meta["columns"] or all(
        c.replace("_", "").isalnum() for c in sales_meta["columns"]
    )
    assert len(sales_meta["sample_rows"]) == 3

    # Data actually landed in SQLite and is queryable.
    conn = excel_ingest.get_excel_conn()
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {sales_meta['table_name']}")
        assert cur.fetchone()[0] == 4
    finally:
        conn.close()


def test_ingest_csv_single_table(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame({"name": ["Budi", "Sari"], "score": [88, 92]})
    path = tmp_path / "scores.csv"
    df.to_csv(path, index=False)

    results = excel_ingest.ingest_excel(str(path), workbook_label="scores.csv")
    assert len(results) == 1
    assert results[0]["row_count"] == 2
    assert results[0]["sheet_name"] == "Sheet1"


def test_ingest_skips_fully_empty_sheets(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]
    empty = pd.DataFrame()
    real = pd.DataFrame({"x": [1, 2]})
    path = tmp_path / "mixed.xlsx"
    _write_xlsx(path, {"Empty": empty, "Real": real})

    results = excel_ingest.ingest_excel(str(path), workbook_label="mixed.xlsx")
    assert len(results) == 1
    assert results[0]["sheet_name"] == "Real"


def test_duplicate_column_names_are_deduplicated(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame([[1, 2, 3]], columns=["Total", "Total", "total"])
    path = tmp_path / "dupe_cols.xlsx"
    _write_xlsx(path, {"Sheet1": df})

    results = excel_ingest.ingest_excel(str(path), workbook_label="dupe_cols.xlsx")
    cols = results[0]["columns"]
    assert len(cols) == len(set(cols)), f"expected unique columns, got {cols}"


def test_table_names_are_namespaced_by_workbook(tmp_storage, tmp_path):
    """Two workbooks with a same-named sheet must not collide into one table."""
    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame({"a": [1]})
    p1 = tmp_path / "workbook_one.xlsx"
    p2 = tmp_path / "workbook_two.xlsx"
    _write_xlsx(p1, {"Data": df})
    _write_xlsx(p2, {"Data": df})

    r1 = excel_ingest.ingest_excel(str(p1), workbook_label="workbook_one.xlsx")
    r2 = excel_ingest.ingest_excel(str(p2), workbook_label="workbook_two.xlsx")
    assert r1[0]["table_name"] != r2[0]["table_name"]


def test_build_schema_summary_mentions_table_and_columns(tmp_storage, tmp_path):
    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame({"City": ["Jakarta", "Bandung"], "Population": [10000000, 2500000]})
    path = tmp_path / "cities.xlsx"
    _write_xlsx(path, {"Cities": df})

    meta = excel_ingest.ingest_excel(str(path), workbook_label="cities.xlsx")[0]
    summary = excel_ingest.build_schema_summary(meta)

    assert meta["table_name"] in summary
    assert "city" in summary.lower()
    assert "population" in summary.lower()
    # The summary must stay compact — never dump every row (efficiency requirement).
    assert len(summary) < 2000

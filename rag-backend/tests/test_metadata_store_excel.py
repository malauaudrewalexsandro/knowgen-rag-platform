def test_record_and_fetch_excel_table(tmp_storage):
    ms = tmp_storage["metadata_store"]
    ms.record_document(
        doc_id="doc1", filename="q3.xlsx", embedding_model="local/all-MiniLM-L6-v2",
        embedding_dims=384, collection_key="local_all-MiniLM-L6-v2__384d",
        vlm_enabled=False, vlm_model=None,
    )
    ms.record_excel_table(
        table_name="q3_sales", document_id="doc1", sheet_name="Sales",
        columns=["region", "revenue"], dtypes={"region": "object", "revenue": "int64"},
        row_count=4,
    )

    fetched = ms.get_excel_table("q3_sales")
    assert fetched is not None
    assert fetched["document_id"] == "doc1"
    assert fetched["sheet_name"] == "Sales"
    assert fetched["row_count"] == 4

    by_doc = ms.excel_tables_by_document("doc1")
    assert len(by_doc) == 1
    assert by_doc[0]["table_name"] == "q3_sales"


def test_count_excel_tables_by_document(tmp_storage):
    ms = tmp_storage["metadata_store"]
    ms.record_document(
        doc_id="doc1", filename="q3.xlsx", embedding_model="local/all-MiniLM-L6-v2",
        embedding_dims=384, collection_key="k", vlm_enabled=False, vlm_model=None,
    )
    for i, sheet in enumerate(["Sales", "Inventory"]):
        ms.record_excel_table(
            table_name=f"q3_{sheet.lower()}", document_id="doc1", sheet_name=sheet,
            columns=["a"], dtypes={"a": "int64"}, row_count=1,
        )

    counts = ms.count_excel_tables_by_document()
    assert counts["doc1"] == 2


def test_get_excel_table_missing_returns_none(tmp_storage):
    ms = tmp_storage["metadata_store"]
    assert ms.get_excel_table("does_not_exist") is None

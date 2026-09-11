import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """
    Point app.config.settings at a throwaway storage dir for this test, then
    reload the excel_ingest / sql_tool / metadata_store modules so their
    module-level path constants (computed at import time) pick it up.
    Prevents tests from reading/writing the real ./storage on disk.
    """
    metadata_db = tmp_path / "metadata" / "metadata.sqlite3"
    monkeypatch.setenv("METADATA_DB_PATH", str(metadata_db))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTOR_INDEX_DIR", str(tmp_path / "vector_indexes"))

    from app import config
    importlib.reload(config)

    from app.core import excel_ingest, sql_tool
    from app.db import metadata_store
    importlib.reload(excel_ingest)
    importlib.reload(sql_tool)
    importlib.reload(metadata_store)
    metadata_store.init_db()

    return {
        "config": config,
        "excel_ingest": excel_ingest,
        "sql_tool": sql_tool,
        "metadata_store": metadata_store,
    }

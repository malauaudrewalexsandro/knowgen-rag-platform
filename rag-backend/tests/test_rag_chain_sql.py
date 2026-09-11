import json
import types

import pandas as pd
import pytest


def _fake_response(content=None, tool_calls=None):
    """Mimic the shape litellm.completion()'s response has (resp.choices[0].message)."""
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _fake_tool_call(call_id, sql):
    function = types.SimpleNamespace(name="query_table", arguments=json.dumps({"sql": sql}))
    return types.SimpleNamespace(id=call_id, function=function)


@pytest.fixture
def rag_chain_with_table(tmp_storage, tmp_path, monkeypatch):
    """
    Reload rag_chain against the same isolated storage as tmp_storage, and
    ingest one real table so a genuine SQL query can run against it.
    """
    import importlib
    from app.core import rag_chain, vectorstore
    importlib.reload(vectorstore)
    importlib.reload(rag_chain)

    excel_ingest = tmp_storage["excel_ingest"]
    df = pd.DataFrame({"region": ["West", "East", "West"], "revenue": [100, 250, 175]})
    path = tmp_path / "sales.csv"
    df.to_csv(path, index=False)
    table_meta = excel_ingest.ingest_excel(str(path), workbook_label="sales.csv")[0]

    schema_hit = vectorstore.SearchHit(
        id="v1", score=0.9,
        payload={
            "chunk_type": "table_schema",
            "content": excel_ingest.build_schema_summary(table_meta),
            "table_name": table_meta["table_name"],
        },
    )
    return rag_chain, schema_hit, table_meta["table_name"]


def test_has_table_context_detection(rag_chain_with_table):
    rag_chain, schema_hit, _table = rag_chain_with_table
    assert rag_chain._has_table_context([schema_hit]) is True

    text_hit = schema_hit.__class__(id="v2", score=0.5, payload={"chunk_type": "text", "content": "hello"})
    assert rag_chain._has_table_context([text_hit]) is False


def test_sql_tool_loop_executes_query_and_returns_final_answer(rag_chain_with_table, monkeypatch):
    rag_chain, schema_hit, table = rag_chain_with_table
    sql = f"SELECT SUM(revenue) AS total FROM {table}"

    calls = {"n": 0}

    def fake_chat(messages, model=None, tools=None, tool_choice="auto", max_tokens=1024):
        calls["n"] += 1
        if calls["n"] == 1:
            # First turn: model asks to run SQL.
            assert tools is not None
            return _fake_response(tool_calls=[_fake_tool_call("call_1", sql)])
        # Second turn: model has the tool result and answers in plain text.
        assert any(m["role"] == "tool" for m in messages)
        return _fake_response(content="Total pendapatan adalah 525.")

    monkeypatch.setattr(rag_chain.llm_core, "chat", fake_chat)

    text, hits = rag_chain._answer_with_sql_tool("berapa total revenue?", [schema_hit], "openrouter/deepseek/deepseek-chat")

    assert text == "Total pendapatan adalah 525."
    assert calls["n"] == 2
    sql_hits = [h for h in hits if h.payload.get("chunk_type") == "sql_result"]
    assert len(sql_hits) == 1
    assert sql_hits[0].payload["sql"] == sql
    assert "525" in sql_hits[0].payload["content"]


def test_sql_tool_loop_survives_malicious_sql_attempt(rag_chain_with_table, monkeypatch):
    """If the model tries a write statement, sql_tool rejects it and the loop
    keeps going (feeding the error back) instead of crashing or executing it."""
    rag_chain, schema_hit, table = rag_chain_with_table
    calls = {"n": 0}

    def fake_chat(messages, model=None, tools=None, tool_choice="auto", max_tokens=1024):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_response(tool_calls=[_fake_tool_call("call_1", f"DROP TABLE {table}")])
        return _fake_response(content="Maaf, saya tidak bisa menjalankan operasi tulis.")

    monkeypatch.setattr(rag_chain.llm_core, "chat", fake_chat)

    text, hits = rag_chain._answer_with_sql_tool("hapus semua data", [schema_hit], "some/model")

    assert "tidak bisa" in text
    sql_hits = [h for h in hits if h.payload.get("chunk_type") == "sql_result"]
    assert "error" in sql_hits[0].payload["content"].lower() or sql_hits[0].payload["content"] != ""

    # And the table must still exist / be untouched.
    result = rag_chain.run_readonly_query(f"SELECT COUNT(*) AS n FROM {table}")
    assert "error" not in result
    assert result["rows"][0]["n"] == 3


def test_sql_tool_loop_stops_after_max_rounds(rag_chain_with_table, monkeypatch):
    """A model that keeps calling the tool forever must still get cut off."""
    rag_chain, schema_hit, table = rag_chain_with_table
    calls = {"n": 0}

    def fake_chat(messages, model=None, tools=None, tool_choice="auto", max_tokens=1024):
        calls["n"] += 1
        if tools is not None:
            return _fake_response(tool_calls=[_fake_tool_call(f"call_{calls['n']}", f"SELECT 1 FROM {table}")])
        return _fake_response(content="(forced final answer)")

    monkeypatch.setattr(rag_chain.llm_core, "chat", fake_chat)

    text, hits = rag_chain._answer_with_sql_tool("terus coba lagi", [schema_hit], "some/model")

    assert text == "(forced final answer)"
    # Must not loop unboundedly.
    assert calls["n"] <= rag_chain.MAX_TOOL_ROUNDS + 1

"""
Orchestration layer using LangChain (per requirement — LangGraph is a drop-in
alternative if the flow grows branches; see the commented note at the bottom
for how that swap would look).

Kept deliberately explicit rather than hiding everything behind a prebuilt
LangChain chain class, so retrieval, prompt assembly, and generation are each
inspectable and swappable independently.

Excel/CSV retrieval path: when retrieval surfaces one or more spreadsheet
"table_schema" chunks (see app/core/excel_ingest.py), plain semantic
similarity is not enough to actually answer a question like "total X per Y"
— that requires computing over real rows. So instead of stuffing raw rows
into the prompt, the LLM is handed a single `query_table` tool (LiteLLM's
OpenAI-style function calling — see app/core/llm.py) backed by
app/core/sql_tool.py's sandboxed read-only executor. The model decides
whether/what SQL to run, we execute it, feed the result back, and let it
write the final answer. This keeps the "efficient" property: no row data
is ever embedded, and no row data touches the prompt unless the model
explicitly asked a targeted SQL question for it.
"""
import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from app.core import embeddings, llm as llm_core, vectorstore
from app.core.sql_tool import run_readonly_query
from app.core.vectorstore import SearchHit
from app.config import settings

SYSTEM_PROMPT = """You are a document Q&A assistant. Answer using only the
provided context. If the context doesn't contain the answer, say so plainly
instead of guessing. When you use a table or image-derived chunk, mention
that the information came from a table/figure.

Context:
{context}
"""

SQL_SYSTEM_PROMPT = """You are a document Q&A assistant. Some of the context
below are SCHEMA SUMMARIES of spreadsheet tables that have been ingested
into a SQLite database (table name, columns with types, and a couple of
sample rows) — NOT the full data. You do not have the real row data yet.

If the question needs a computed or exact answer from one of these tables
(a total, an average, a count, a filter, a lookup, a top-N, ...), call the
`query_table` tool with a single SQLite SELECT statement written against the
exact table_name and column names shown in the schema summary. You may call
it more than once (e.g. to fix a mistake or ask a follow-up query) but keep
it to what's necessary. Only use tables that are actually shown in the
context — never invent a table or column name.

If the question is answerable from plain text/table/image context instead,
or no context is relevant, just answer directly without calling the tool.

Context:
{context}
"""

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{question}"),
])

_QUERY_TABLE_TOOL = {
    "type": "function",
    "function": {
        "name": "query_table",
        "description": (
            "Run one read-only SQLite SELECT statement against an ingested "
            "spreadsheet table to get an exact, computed answer (sum, count, "
            "average, filter, sort, top-N, join across ingested tables, ...) "
            "instead of guessing from the schema summary alone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single SELECT (optionally WITH ... SELECT) statement.",
                }
            },
            "required": ["sql"],
        },
    },
}

MAX_TOOL_ROUNDS = 3


def _format_context(hits) -> str:
    if not hits:
        return "(no relevant context found)"
    lines = []
    for i, hit in enumerate(hits, start=1):
        payload = hit.payload
        kind = payload.get("chunk_type", "text")
        label = {
            "table_schema": "spreadsheet table schema",
            "sql_result": "SQL query result",
        }.get(kind, kind)
        lines.append(f"[{i}] ({label}) {payload.get('content', '')}")
    return "\n\n".join(lines)


def _has_table_context(hits) -> bool:
    return any(h.payload.get("chunk_type") == "table_schema" for h in hits)


def _answer_with_sql_tool(question: str, hits: list, llm_model: str) -> tuple[str, list]:
    """
    Bounded tool-calling loop: let the model write SQL against the schemas
    it was shown, execute it read-only, and hand the result back — up to
    MAX_TOOL_ROUNDS round trips, then force a final answer either way so a
    confused model can't loop forever.
    """
    context = _format_context(hits)
    messages = [
        {"role": "system", "content": SQL_SYSTEM_PROMPT.format(context=context)},
        {"role": "user", "content": question},
    ]

    executed: list[SearchHit] = []
    tools = [_QUERY_TABLE_TOOL]

    for round_num in range(MAX_TOOL_ROUNDS):
        resp = llm_core.chat(messages, model=llm_model, tools=tools, tool_choice="auto")
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            return msg.content or "", hits + executed

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            try:
                sql = json.loads(tc.function.arguments or "{}").get("sql", "")
            except (json.JSONDecodeError, AttributeError):
                sql = ""
            result = run_readonly_query(sql) if sql else {"error": "No SQL provided."}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result)[:4000],
            })
            preview = result.get("error") or json.dumps(result.get("rows", []))[:400]
            executed.append(SearchHit(
                id=f"sql-{len(executed) + 1}",
                score=1.0,
                payload={"chunk_type": "sql_result", "content": preview, "sql": sql, "page": None},
            ))

        # Only allow the tool for the first couple of rounds; force a plain
        # answer on the last round even if it wants to call again.
        if round_num == MAX_TOOL_ROUNDS - 2:
            tools = None

    # Ran out of rounds without a final text answer — one last untooled call.
    resp = llm_core.chat(messages, model=llm_model, tools=None)
    return resp.choices[0].message.content or "", hits + executed


def retrieve(question: str, embedding_model: str | None = None,
             dims: int | None = None, top_k: int = 5):
    embedding_model = embedding_model or settings.default_embedding_model
    dims = dims or settings.default_embedding_dims

    query_embedding = embeddings.embed_text(question, model=embedding_model)
    collection = vectorstore.get_collection(embedding_model, dims)
    return collection.search(query_embedding.vector, k=top_k)


def build_rag_chain(llm_model: str | None = None):
    """
    Returns a LangChain runnable: {question, embedding_model, dims, top_k} -> str.
    Retrieval happens as a RunnableLambda so it's a normal pipeline step,
    not bolted on outside LangChain's abstractions.
    """
    from langchain_community.chat_models import ChatLiteLLM

    llm = ChatLiteLLM(model=llm_model or settings.default_llm_model, max_tokens=1024)

    def _retrieve_step(inputs: dict) -> dict:
        hits = retrieve(
            inputs["question"],
            embedding_model=inputs.get("embedding_model"),
            dims=inputs.get("dims"),
            top_k=inputs.get("top_k", 5),
        )
        inputs["_hits"] = hits
        inputs["context"] = _format_context(hits)
        return inputs

    chain = (
        RunnableLambda(_retrieve_step)
        | _prompt
        | llm
    )
    return chain


def answer(question: str, llm_model: str | None = None, embedding_model: str | None = None,
           dims: int | None = None, top_k: int = 5) -> tuple[str, list]:
    """Convenience entrypoint used by the /chat route."""
    llm_model = llm_model or settings.default_llm_model
    hits = retrieve(question, embedding_model, dims, top_k)

    if _has_table_context(hits):
        return _answer_with_sql_tool(question, hits, llm_model)

    chain = build_rag_chain(llm_model)
    result = chain.invoke({
        "question": question,
        "embedding_model": embedding_model,
        "dims": dims,
        "top_k": top_k,
    })
    return result.content, hits


# ── LangGraph alternative (kept commented — swap in if the flow needs
#    branching, e.g. "decide whether retrieval is needed at all" or
#    "retry retrieval with a rewritten query if the first pass scores low") ──
#
# from langgraph.graph import StateGraph, END
#
# class RAGState(TypedDict):
#     question: str
#     hits: list
#     answer: str
#
# graph = StateGraph(RAGState)
# graph.add_node("retrieve", retrieve_node)
# graph.add_node("generate", generate_node)
# graph.set_entry_point("retrieve")
# graph.add_edge("retrieve", "generate")
# graph.add_edge("generate", END)
# app_graph = graph.compile()

"""
Orchestration layer using LangChain (per requirement — LangGraph is a drop-in
alternative if the flow grows branches; see the commented note at the bottom
for how that swap would look).

Kept deliberately explicit rather than hiding everything behind a prebuilt
LangChain chain class, so retrieval, prompt assembly, and generation are each
inspectable and swappable independently.

Tool-calling runs on every turn (not just when retrieval surfaces
spreadsheet context) because `clone_document` needs to be reachable from
plain chat even for documents with no ingested Excel tables (e.g. "buatin
dokumen based on resume.pdf"). Three tools, all LiteLLM OpenAI-style
function calling (see app/core/llm.py):
  - `query_table`   — backed by app/core/sql_tool.py's sandboxed read-only
                       executor, for exact computed text answers. Only
                       offered when retrieval surfaces spreadsheet schema
                       context (there'd be nothing to query otherwise).
  - `generate_chart` — backed by app/core/doc_generation/ (content_planner
                       + chart_builder). Same table-context gate as above.
  - `clone_document` — backed by app/core/doc_generation/clone_runner.py.
                       Always offered: re-parses an uploaded file (matched
                       by filename, fuzzy) into structured blocks and
                       rebuilds it in a chosen format.
The model decides whether/what to call, we execute it, feed the result
back, and let it write the final answer. This keeps the "efficient"
property: no row data is ever embedded, and no row data touches the prompt
unless the model explicitly asked a targeted question for it.
"""
import json
import os
from urllib.parse import quote

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from app.core import embeddings, llm as llm_core, vectorstore
from app.core.sql_tool import run_readonly_query
from app.core.vectorstore import SearchHit
from app.config import settings

BASE_SYSTEM_PROMPT = """You are a document Q&A assistant. Answer using only
the provided context when the question is about document content. If the
context doesn't contain the answer, say so plainly instead of guessing.
When you use a table or image-derived chunk, mention that the information
came from a table/figure.

CRITICAL: Never print a tool's JSON definition, schema, or a fake "here's
what I would call" JSON block as part of your answer text. If you need a
tool, invoke it through the actual function-calling mechanism — never as
text in your response.

Context:
{context}
"""

TABLE_TOOLS_ADDENDUM = """
Some of the context above are SCHEMA SUMMARIES of spreadsheet tables that
have been ingested into a SQLite database (table name, columns with types,
and a couple of sample rows) — NOT the full data. You do not have the real
row data yet.

If the question needs a computed or exact TEXT answer from one of these
tables (a total, an average, a count, a filter, a lookup, a top-N, ...),
call the `query_table` tool with a single SQLite SELECT statement written
against the exact table_name and column names shown in the schema summary.

If the user asks to visualize, chart, plot, or graph data from one of
these tables, call the `generate_chart` tool instead — do NOT try to
describe a chart in text and do NOT call query_table for this.

Only use tables that are actually shown in the context — never invent a
table or column name.
"""

CLONE_TOOL_ADDENDUM = """
If the user asks to build/generate/create a document "based on", "like",
"following the template of", or "using as a template" a specific uploaded
file (pdf, docx, pptx, or image — not necessarily one with tables), call
the `clone_document` tool with that file's name (or the part of the name
the user mentioned) and the desired output format (default to "pdf" if
they don't say). This actually creates a new downloadable file by
re-parsing and rebuilding the original — it doesn't just describe one, and
it is NOT the same as query_table/generate_chart.
"""

_prompt = ChatPromptTemplate.from_messages([
    ("system", BASE_SYSTEM_PROMPT),
    ("human", "{question}"),
])

_QUERY_TABLE_TOOL = {
    "type": "function",
    "function": {
        "name": "query_table",
        "description": (
            "Run one read-only SQLite SELECT statement against an ingested "
            "spreadsheet table to get an exact, computed TEXT answer (sum, "
            "count, average, filter, sort, top-N, join across ingested "
            "tables, ...) instead of guessing from the schema summary alone."
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

_GENERATE_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_chart",
        "description": (
            "Generate a chart image (PNG) visualizing data from an ingested "
            "spreadsheet table. Use this whenever the user explicitly asks "
            "to visualize, chart, plot, or graph data — never for plain "
            "text questions, and never in combination with query_table for "
            "the same request."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Exact table_name from a schema summary shown in the context.",
                },
                "chart_intent": {
                    "type": "string",
                    "description": (
                        "Natural language description of what to visualize, "
                        "e.g. 'total revenue by region' or 'average salary "
                        "per department'."
                    ),
                },
            },
            "required": ["table_name", "chart_intent"],
        },
    },
}

_CLONE_DOCUMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "clone_document",
        "description": (
            "Recreate an uploaded document (pdf/docx/pptx/image) as a new "
            "downloadable file, rebuilding its headings/paragraphs/tables/"
            "images from scratch in a chosen format. Use this when the "
            "user asks to build a document 'based on', 'like', or 'using "
            "as a template' an uploaded file — not for plain Q&A about the "
            "file's content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The uploaded file's name, or the part of it the user mentioned.",
                },
                "format": {
                    "type": "string",
                    "enum": ["pdf", "docx", "pptx", "xlsx"],
                    "description": "Desired output format. Default to 'pdf' if the user didn't specify.",
                },
            },
            "required": ["filename", "format"],
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
            "chart_result": "generated chart",
            "clone_result": "generated document",
        }.get(kind, kind)
        lines.append(f"[{i}] ({label}) {payload.get('content', '')}")
    return "\n\n".join(lines)


def _has_table_context(hits) -> bool:
    return any(h.payload.get("chunk_type") == "table_schema" for h in hits)


def _looks_like_leaked_tool_json(content: str) -> bool:
    """
    Some models occasionally narrate a tool's JSON schema/definition as
    plain text instead of actually invoking it through tool_calls. Detect
    that so we can force a real call instead of showing raw JSON to the
    user.
    """
    if not content:
        return False
    if content.strip().startswith(("{", "```json", "json {")):
        return True
    return '"function"' in content and (
        "query_table" in content or "generate_chart" in content or "clone_document" in content
    )


def _run_generate_chart(table_name: str, chart_intent: str, llm_model: str) -> tuple[dict, str | None]:
    from app.core.doc_generation import chart_builder, content_planner

    chart_plan = content_planner.plan_chart_for_table(table_name, chart_intent, llm_model)
    chart_data = content_planner.resolve_chart_data(table_name, chart_plan)
    if not chart_data:
        return {"error": "Could not determine a chartable column pair for this table."}, None

    path = chart_builder.build_chart(
        chart_data["type"], chart_data["labels"], chart_data["values"], title=chart_data.get("title"),
    )
    filename = os.path.basename(path)
    return (
        {"status": "generated", "chart_title": chart_data.get("title"), "chart_type": chart_data["type"]},
        f"/generate/chart/{filename}",
    )


def _run_clone_document(filename_query: str, fmt: str) -> tuple[dict, dict | None]:
    """
    Returns (tool_result_dict, file_info) where file_info is
    {"url": ..., "name": ...} on success, or None on failure.
    """
    from app.core.doc_generation.clone_runner import CloneError, find_document_by_filename, run_clone

    doc = find_document_by_filename(filename_query)
    if not doc:
        return {"error": f"No uploaded document matching '{filename_query}' was found."}, None

    try:
        out_path, download_filename = run_clone(doc["id"], fmt)
    except CloneError as e:
        return {"error": str(e)}, None

    server_filename = os.path.basename(out_path)
    url = f"/generate/download/{server_filename}?download_name={quote(download_filename)}"
    return (
        {"status": "generated", "source_filename": doc["filename"], "format": fmt},
        {"url": url, "name": download_filename},
    )


def _answer_with_tools(question: str, hits: list, llm_model: str) -> tuple[str, list, str | None, dict | None]:
    """
    Bounded tool-calling loop: query_table/generate_chart (only offered
    when spreadsheet context is present) plus clone_document (always
    offered). Up to MAX_TOOL_ROUNDS round trips, then forces a final
    answer either way so a confused model can't loop forever.

    Returns (answer_text, hits_including_tool_results, chart_url, file_info).
    file_info is {"url": ..., "name": ...} for a clone_document result, or
    None.
    """
    has_tables = _has_table_context(hits)
    system_prompt = BASE_SYSTEM_PROMPT.format(context=_format_context(hits))
    if has_tables:
        system_prompt += TABLE_TOOLS_ADDENDUM
    system_prompt += CLONE_TOOL_ADDENDUM

    tools = [_CLONE_DOCUMENT_TOOL]
    if has_tables:
        tools = [_QUERY_TABLE_TOOL, _GENERATE_CHART_TOOL] + tools

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    executed: list[SearchHit] = []
    chart_url: str | None = None
    file_info: dict | None = None
    forced_retry_used = False
    active_tools = tools

    for round_num in range(MAX_TOOL_ROUNDS):
        resp = llm_core.chat(messages, model=llm_model, tools=active_tools, tool_choice="auto")
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            content = msg.content or ""
            if _looks_like_leaked_tool_json(content) and not forced_retry_used and active_tools:
                # The model narrated a tool schema as text instead of
                # actually calling it — nudge it once, forcing a real call.
                forced_retry_used = True
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Do not print tool definitions or JSON in your answer. "
                        "If you need data, a chart, or a cloned document, call "
                        "the tool directly now."
                    ),
                })
                continue
            return content, hits + executed, chart_url, file_info

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
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, AttributeError):
                args = {}

            if tc.function.name == "generate_chart":
                table_name = args.get("table_name", "")
                chart_intent = args.get("chart_intent", "")
                result, url = (
                    _run_generate_chart(table_name, chart_intent, llm_model)
                    if table_name and chart_intent
                    else ({"error": "Missing table_name or chart_intent."}, None)
                )
                if url:
                    chart_url = url
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)[:2000]})
                executed.append(SearchHit(
                    id=f"chart-{len(executed) + 1}", score=1.0,
                    payload={"chunk_type": "chart_result", "content": json.dumps(result)[:400], "page": None},
                ))

            elif tc.function.name == "clone_document":
                filename_query = args.get("filename", "")
                fmt = args.get("format", "pdf")
                result, info = (
                    _run_clone_document(filename_query, fmt)
                    if filename_query
                    else ({"error": "Missing filename."}, None)
                )
                if info:
                    file_info = info
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)[:2000]})
                executed.append(SearchHit(
                    id=f"clone-{len(executed) + 1}", score=1.0,
                    payload={"chunk_type": "clone_result", "content": json.dumps(result)[:400], "page": None},
                ))

            else:  # query_table
                sql = args.get("sql", "")
                result = run_readonly_query(sql) if sql else {"error": "No SQL provided."}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)[:4000]})
                preview = result.get("error") or json.dumps(result.get("rows", []))[:400]
                executed.append(SearchHit(
                    id=f"sql-{len(executed) + 1}", score=1.0,
                    payload={"chunk_type": "sql_result", "content": preview, "sql": sql, "page": None},
                ))

        # Only allow tools for the first couple of rounds; force a plain
        # answer on the last round even if it wants to call again.
        if round_num == MAX_TOOL_ROUNDS - 2:
            active_tools = None

    # Ran out of rounds without a final text answer — one last untooled call.
    resp = llm_core.chat(messages, model=llm_model, tools=None)
    return resp.choices[0].message.content or "", hits + executed, chart_url, file_info


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
    Kept available as a simpler no-tools path (e.g. for programmatic use
    elsewhere); the /chat route itself now always goes through
    _answer_with_tools so `clone_document` stays reachable from any turn.
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
           dims: int | None = None, top_k: int = 5) -> tuple[str, list, str | None, dict | None]:
    """
    Convenience entrypoint used by the /chat route.
    Returns (reply, hits, chart_url, file_info).
    """
    llm_model = llm_model or settings.default_llm_model
    hits = retrieve(question, embedding_model, dims, top_k)
    return _answer_with_tools(question, hits, llm_model)


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

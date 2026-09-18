from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    llm_model: str | None = None            # override default LLM, e.g. "openai/gpt-4o-mini"
    embedding_model: str | None = None       # which collection to retrieve from
    embedding_dims: int | None = None
    top_k: int = 5


class ChatResponse(BaseModel):
    reply: str
    retrieved_chunks: list[dict] = Field(default_factory=list)
    model_used: str
    # Relative path (e.g. "/generate/chart/xyz.png") when the assistant
    # called the generate_chart tool for this turn — see app/core/rag_chain.py.
    chart_url: str | None = None
    file_url: str | None = None
    file_name: str | None = None


class IngestRequest(BaseModel):
    embedding_model: str | None = None
    vlm_enabled: bool = False
    vlm_model: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    filename: str
    collection_key: str
    text_chunks: int
    table_chunks: int
    image_chunks: int
    excel_tables: int = 0   # sheets ingested as queryable SQL tables (xlsx/xls/csv)


class DocumentSummary(BaseModel):
    id: str
    filename: str
    embedding_model: str
    embedding_dims: int
    collection_key: str
    vlm_enabled: bool
    created_at: str
    excel_tables: int = 0
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.core.rag_chain import answer
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_turns = [m for m in req.messages if m.role == "user"]
    if not user_turns:
        raise HTTPException(status_code=400, detail="At least one user message is required")

    question = user_turns[-1].content
    llm_model = req.llm_model or settings.default_llm_model

    try:
        reply_text, hits = answer(
            question=question,
            llm_model=req.llm_model,
            embedding_model=req.embedding_model,
            dims=req.embedding_dims,
            top_k=req.top_k,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline failed: {e}")

    return ChatResponse(
        reply=reply_text,
        retrieved_chunks=[{"id": h.id, "score": h.score, **h.payload} for h in hits],
        model_used=llm_model,
    )

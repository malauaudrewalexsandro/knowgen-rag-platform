"""
Chat + vision calls, both routed through LiteLLM. Same reasoning as
embeddings.py: model choice is a string, never a provider-specific SDK call
sprinkled through the codebase.
"""
import base64

import litellm

from app.config import settings


def chat(messages: list[dict], model: str | None = None, tools: list[dict] | None = None,
         tool_choice: str = "auto", max_tokens: int = 1024):
    """
    Thin wrapper over litellm.completion. `messages` and `tools` follow the
    OpenAI-style schema — LiteLLM translates that shape to whatever the
    underlying provider expects.
    """
    model = model or settings.default_llm_model
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    return litellm.completion(**kwargs)


def analyze_image(image_bytes: bytes, prompt: str, model: str | None = None,
                   mime_type: str = "image/png") -> str:
    """
    VLM call for describing an image or a table crop extracted from a
    document. Used by core/vlm.py when VLM analysis is toggled on for a
    given document during ingestion.
    """
    model = model or settings.default_vlm_model
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = litellm.completion(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=512,
    )
    return resp.choices[0].message.content or ""

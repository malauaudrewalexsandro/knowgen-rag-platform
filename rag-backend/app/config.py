"""
Central config. Everything that changes between environments (keys, model
names, storage paths) lives here — nothing hardcoded in business logic.
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider keys — LiteLLM reads these via env vars at call time too,
    # we just surface them here so config is inspectable in one place.
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""

    # Default models. Any endpoint can override these per-request.
    default_llm_model: str = "openrouter/deepseek/deepseek-chat"
    default_embedding_model: str = "local/all-MiniLM-L6-v2"
    default_embedding_dims: int = 384
    default_vlm_model: str = "gemini/gemini-2.0-flash"

    # Storage
    vector_index_dir: str = "./storage/vector_indexes"
    metadata_db_path: str = "./storage/metadata/metadata.sqlite3"
    upload_dir: str = "./storage/uploads"

    app_env: str = "development"
    log_level: str = "INFO"


settings = Settings()

# LiteLLM (and the provider SDKs it wraps) read credentials directly from
# process environment variables — NOT from this Settings object. Reading
# .env into `settings` above does not, by itself, make these visible to
# LiteLLM. Export them explicitly so a filled-in .env actually takes effect.
_provider_env_vars = {
    "OPENAI_API_KEY": settings.openai_api_key,
    "GEMINI_API_KEY": settings.gemini_api_key,
    "DEEPSEEK_API_KEY": settings.deepseek_api_key,
    "ANTHROPIC_API_KEY": settings.anthropic_api_key,
    "OPENROUTER_API_KEY": settings.openrouter_api_key,
}
for _env_name, _value in _provider_env_vars.items():
    if _value and not os.environ.get(_env_name):
        os.environ[_env_name] = _value

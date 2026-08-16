"""Application settings, read from the environment (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Hugging Face -------------------------------------------------
    hf_token: str | None = None
    # Meta-Llama-3-8B-Instruct was retired from the HF Inference Providers
    # catalogue; 3.1-8B-Instruct is the supported successor.
    model_id: str = "meta-llama/Llama-3.1-8B-Instruct"
    # Tried in order when the primary model is retired, gated, or overloaded.
    # A single hardcoded model is exactly how v1 died: the id stopped being
    # served and every request 400'd with `model_not_supported`.
    fallback_models: list[str] = [
        "Qwen/Qwen2.5-7B-Instruct",
        "meta-llama/Llama-3.3-70B-Instruct",
    ]
    request_timeout: float = 60.0
    max_retries: int = 2
    retry_backoff: float = 0.5

    # --- Generation ---------------------------------------------------
    max_tokens: int = 512
    temperature: float = 0.7

    # --- Retrieval ----------------------------------------------------
    # Datasets are pulled at startup. Set to False for offline/CI runs:
    # the app still serves, it just answers without retrieved examples.
    enable_retrieval: bool = True
    medical_dataset: str = "avaliev/chat_doctor"
    mental_health_dataset: str = "Amod/mental_health_counseling_conversations"
    # The medical corpus is ~95k rows; indexing all of it costs startup time
    # for little quality gain. Cap it, and raise if you want more coverage.
    max_index_rows: int = 20_000
    top_k: int = 2
    # Below this cosine similarity a retrieved example is judged irrelevant
    # and dropped rather than injected as a misleading exemplar.
    min_similarity: float = 0.12

    # --- Conversation memory -----------------------------------------
    max_history_turns: int = 8
    session_ttl_seconds: int = 3600
    max_sessions: int = 1000

    # --- Server -------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 7860
    cors_origins: list[str] = []

    # --- Operations ---------------------------------------------------
    log_level: str = "INFO"
    # JSON logs are for log platforms; humans get the text formatter locally.
    json_logs: bool = False
    rate_limit_requests: int = 20
    rate_limit_window_seconds: float = 60.0
    security_headers: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

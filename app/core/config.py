"""Runtime settings and connection helpers for the backend service."""

from functools import lru_cache
import os

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _local_env_file() -> str:
    """Return the local-only dotenv path for backend development."""
    return os.getenv("LOCAL_ENV_FILE", "local/.env.backend")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Backend API", alias="APP_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    db_dsn: str | None = Field(default=None, alias="DB_DSN")
    db_user: str | None = Field(default=None, alias="DB_USER")
    db_password: str | None = Field(default=None, alias="DB_PASSWORD")
    run_migrations_on_startup: bool = Field(
        default=False, alias="RUN_MIGRATIONS_ON_STARTUP"
    )
    access_token_signing_key: str = Field(
        default="demo-phase1-change-me", alias="ACCESS_TOKEN_SIGNING_KEY"
    )
    access_token_ttl_seconds: int = Field(
        default=604800, alias="ACCESS_TOKEN_TTL_SECONDS"
    )
    admin_api_secret: str = Field(
        default="demo-admin-change-me", alias="ADMIN_API_SECRET"
    )
    default_workflow_key: str = Field(
        default="messy-notes-v1", alias="DEFAULT_WORKFLOW_KEY"
    )
    workflow_config_dir: str = Field(
        default="app/resources/workflows", alias="WORKFLOW_CONFIG_DIR"
    )
    post_processor_config_path: str = Field(
        default="app/resources/post_processors/post-processors.yaml",
        alias="POST_PROCESSOR_CONFIG_PATH",
    )
    context_engine_model_config_path: str = Field(
        default="app/resources/context_engine/model-flows.yaml",
        alias="CONTEXT_ENGINE_MODEL_CONFIG_PATH",
    )
    context_engine_execution_mode: str = Field(
        default="hybrid", alias="CONTEXT_ENGINE_EXECUTION_MODE"
    )
    max_files_per_run: int = Field(default=3, alias="MAX_FILES_PER_RUN")
    max_file_size_bytes: int = Field(default=5_242_880, alias="MAX_FILE_SIZE_BYTES")
    max_extracted_text_bytes: int = Field(
        default=250_000, alias="MAX_EXTRACTED_TEXT_BYTES"
    )
    max_total_workflow_text_bytes: int = Field(
        default=400_000, alias="MAX_TOTAL_WORKFLOW_TEXT_BYTES"
    )
    max_pasted_text_bytes: int = Field(default=200_000, alias="MAX_PASTED_TEXT_BYTES")
    rag_embedding_provider: str = Field(
        default="ollama", alias="RAG_EMBEDDING_PROVIDER"
    )
    rag_ollama_base_url: str = Field(
        default="http://127.0.0.1:11434", alias="RAG_OLLAMA_BASE_URL"
    )
    rag_embedding_model: str = Field(
        default="all-minilm:l12-v2", alias="RAG_EMBEDDING_MODEL"
    )
    rag_oracle_embedding_model: str = Field(
        default="MINILM_L12_V2", alias="RAG_ORACLE_EMBEDDING_MODEL"
    )
    rag_oracle_chunking_provider: str = Field(
        default="oracle", alias="RAG_ORACLE_CHUNKING_PROVIDER"
    )
    rag_chunk_size: int = Field(default=600, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=60, alias="RAG_CHUNK_OVERLAP")
    rag_chat_provider: str = Field(default="anthropic", alias="RAG_CHAT_PROVIDER")
    rag_chat_model: str = Field(
        default="claude-haiku-4-5-20251001", alias="RAG_CHAT_MODEL"
    )
    rag_chat_temperature: float = Field(default=0.2, alias="RAG_CHAT_TEMPERATURE")
    rag_chat_max_tokens: int = Field(default=4096, alias="RAG_CHAT_MAX_TOKENS")
    text_tools_enabled: bool = Field(default=False, alias="TEXT_TOOLS_ENABLED")
    text_tools_base_url: str = Field(
        default="http://127.0.0.1:8081", alias="TEXT_TOOLS_BASE_URL"
    )
    text_tools_timeout_seconds: float = Field(
        default=2.0, alias="TEXT_TOOLS_TIMEOUT_SECONDS"
    )

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str | None = Field(default=None, alias="TWILIO_FROM_NUMBER")
    sms_notification_enabled: bool = Field(
        default=False, alias="SMS_NOTIFICATION_ENABLED"
    )
    sms_reply_provider: str = Field(default="openai", alias="SMS_REPLY_PROVIDER")
    sms_reply_model: str = Field(default="gpt-5-mini", alias="SMS_REPLY_MODEL")
    plivo_auth_id: str | None = Field(default=None, alias="PLIVO_AUTH_ID")
    plivo_auth_token: str | None = Field(default=None, alias="PLIVO_AUTH_TOKEN")
    email_provider: str = Field(default="stub", alias="EMAIL_PROVIDER")
    invite_email_from: str | None = Field(default=None, alias="INVITE_EMAIL_FROM")
    invite_email_reply_to: str | None = Field(
        default=None, alias="INVITE_EMAIL_REPLY_TO"
    )
    invite_email_base_url: str = Field(
        default="https://demo.lebedev.ai", alias="INVITE_EMAIL_BASE_URL"
    )
    invite_email_draft_provider: str = Field(
        default="openai", alias="INVITE_EMAIL_DRAFT_PROVIDER"
    )
    invite_email_draft_model: str = Field(
        default="gpt-5-mini", alias="INVITE_EMAIL_DRAFT_MODEL"
    )
    invite_email_bcc_address: str | None = Field(
        default=None, alias="INVITE_EMAIL_BCC_ADDRESS"
    )
    oci_email_smtp_host: str | None = Field(default=None, alias="OCI_EMAIL_SMTP_HOST")
    oci_email_smtp_port: int = Field(default=587, alias="OCI_EMAIL_SMTP_PORT")
    oci_email_smtp_username: str | None = Field(
        default=None, alias="OCI_EMAIL_SMTP_USERNAME"
    )
    oci_email_smtp_password: str | None = Field(
        default=None, alias="OCI_EMAIL_SMTP_PASSWORD"
    )
    oci_email_from_address: str | None = Field(
        default=None, alias="OCI_EMAIL_FROM_ADDRESS"
    )
    oci_email_from_name: str | None = Field(default=None, alias="OCI_EMAIL_FROM_NAME")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")
    fireworks_api_key: str | None = Field(default=None, alias="FIREWORKS_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    xai_api_key: str | None = Field(default=None, alias="XAI_API_KEY")
    voice_xai_model: str = Field(
        default="grok-voice-think-fast-1.0", alias="VOICE_XAI_MODEL"
    )
    voice_provider: str = Field(default="xai", alias="VOICE_PROVIDER")
    voice_greeting_provider: str = Field(
        default="openai", alias="VOICE_GREETING_PROVIDER"
    )
    voice_greeting_model: str = Field(
        default="gpt-4o-mini", alias="VOICE_GREETING_MODEL"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load local dotenv values only for local development."""
        if os.getenv("ENVIRONMENT", "local") == "local":
            return (
                init_settings,
                env_settings,
                DotEnvSettingsSource(
                    settings_cls,
                    env_file=_local_env_file(),
                    env_file_encoding="utf-8",
                ),
                file_secret_settings,
            )
        return init_settings, env_settings, file_secret_settings

    @model_validator(mode="after")
    def validate_database_settings(self) -> "Settings":
        """Ensure either a full database URL or Oracle connection triplet is set."""
        if self.database_url:
            return self

        missing = [
            key
            for key, value in (
                ("DB_DSN", self.db_dsn),
                ("DB_USER", self.db_user),
                ("DB_PASSWORD", self.db_password),
            )
            if not value
        ]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                f"Configure DATABASE_URL or the Oracle connection variables: missing {missing_text}."
            )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """Return the SQLAlchemy driver URL for the active database backend."""
        if self.database_url:
            return self.database_url
        return "oracle+oracledb://"

    @property
    def sqlalchemy_connect_args(self) -> dict[str, str]:
        """Return SQLAlchemy connect args for Oracle split environment settings."""
        if self.database_url:
            return {}
        return {
            "dsn": self.db_dsn or "",
            "user": self.db_user or "",
            "password": self.db_password or "",
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings for the current process."""
    return Settings()

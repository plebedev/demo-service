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
    max_files_per_run: int = Field(default=3, alias="MAX_FILES_PER_RUN")
    max_file_size_bytes: int = Field(default=5_242_880, alias="MAX_FILE_SIZE_BYTES")
    max_extracted_text_bytes: int = Field(
        default=250_000, alias="MAX_EXTRACTED_TEXT_BYTES"
    )
    max_total_workflow_text_bytes: int = Field(
        default=400_000, alias="MAX_TOTAL_WORKFLOW_TEXT_BYTES"
    )
    max_pasted_text_bytes: int = Field(default=200_000, alias="MAX_PASTED_TEXT_BYTES")

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    plivo_auth_id: str | None = Field(default=None, alias="PLIVO_AUTH_ID")
    plivo_auth_token: str | None = Field(default=None, alias="PLIVO_AUTH_TOKEN")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")

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

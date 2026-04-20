from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_name: str = Field(default="Backend API", alias="APP_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    db_dsn: str | None = Field(default=None, alias="DB_DSN")
    db_user: str | None = Field(default=None, alias="DB_USER")
    db_password: str | None = Field(default=None, alias="DB_PASSWORD")
    run_migrations_on_startup: bool = Field(default=False, alias="RUN_MIGRATIONS_ON_STARTUP")

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    plivo_auth_id: str | None = Field(default=None, alias="PLIVO_AUTH_ID")
    plivo_auth_token: str | None = Field(default=None, alias="PLIVO_AUTH_TOKEN")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")

    @model_validator(mode="after")
    def validate_database_settings(self) -> "Settings":
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
        if self.database_url:
            return self.database_url
        return "oracle+oracledb://"

    @property
    def sqlalchemy_connect_args(self) -> dict[str, str]:
        if self.database_url:
            return {}
        return {
            "dsn": self.db_dsn or "",
            "user": self.db_user or "",
            "password": self.db_password or "",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

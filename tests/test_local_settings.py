"""Tests for local-only dotenv loading behavior."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings


def test_local_environment_loads_local_env_file(
    monkeypatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text(
        "\n".join(
            [
                'APP_NAME="Loaded from dotenv"',
                "ENVIRONMENT=local",
                "DATABASE_URL=postgresql+psycopg://demo_service:demo_service@127.0.0.1:5432/demo_service",
                "ADMIN_API_SECRET=dotenv-secret",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOCAL_ENV_FILE", str(env_file))
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ADMIN_API_SECRET", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "local")

    settings = Settings()

    assert settings.app_name == "Loaded from dotenv"
    assert settings.database_url is not None
    assert settings.admin_api_secret == "dotenv-secret"


def test_non_local_environment_ignores_local_env_file(
    monkeypatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text(
        "\n".join(
            [
                'APP_NAME="Loaded from dotenv"',
                "ENVIRONMENT=local",
                "DATABASE_URL=postgresql+psycopg://ignored:ignored@127.0.0.1:5432/ignored",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOCAL_ENV_FILE", str(env_file))
    monkeypatch.setenv("ENVIRONMENT", "demo")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://demo_service:demo_service@127.0.0.1:5432/demo_service",
    )
    monkeypatch.setenv("APP_NAME", "From environment")

    settings = Settings()

    assert settings.environment == "demo"
    assert settings.app_name == "From environment"

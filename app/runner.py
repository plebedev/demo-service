"""Service entrypoint used by the container runtime."""

import subprocess

import uvicorn

from app.core.config import get_settings


def run_migrations() -> None:
    """Apply the latest Alembic migrations before startup."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)


def main() -> None:
    """Run the API service with the configured runtime settings."""
    settings = get_settings()

    if settings.run_migrations_on_startup:
        run_migrations()

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

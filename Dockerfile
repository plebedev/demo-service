FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.5

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip \
  && pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock* README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN poetry config virtualenvs.create false \
  && poetry install --only main --no-interaction --no-ansi

EXPOSE 8000

CMD ["python", "-m", "app.runner"]

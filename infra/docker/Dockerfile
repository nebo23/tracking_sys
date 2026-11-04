FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --require-hashes -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/local-data/mail \
    && chown -R appuser:appuser /app/local-data

COPY --chown=appuser:appuser backend/app ./app
COPY --chown=appuser:appuser backend/migrations ./migrations
COPY --chown=appuser:appuser backend/alembic.ini ./alembic.ini

USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

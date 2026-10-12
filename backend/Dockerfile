FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/models UPLOAD_DIR=/data/uploads REPORT_DIR=/data/reports
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download the free local embedding model so the first upload is fast (falls back to download at first use).
ARG PRELOAD_EMBEDDINGS=1
RUN mkdir -p /models /data/uploads /data/reports && \
    if [ "$PRELOAD_EMBEDDINGS" = "1" ]; then (python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))" \
     || echo "Embedding model will be downloaded on first use"); fi

COPY . .
RUN useradd -m appuser && chown -R appuser /app /data /models
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

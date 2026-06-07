# Phoenix Agent — multi-stage Dockerfile
# Copyright (c) 2026 Kaushikkumaran

FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target /app/deps

FROM python:3.11-slim AS runtime
WORKDIR /app

RUN groupadd -r phoenix && useradd -r -g phoenix -s /bin/false phoenix

COPY --from=builder /app/deps /app/deps
COPY src/ /app/src/

# Data volume for SQLite memory store
RUN mkdir -p /data && chown phoenix:phoenix /data
VOLUME ["/data"]

ENV PYTHONPATH="/app/deps:/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER phoenix

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

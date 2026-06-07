FROM python:3.11-slim

# Copyright (c) 2026 Kaushikkumaran
# Apache License 2.0 — see root LICENSE

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Compile Hubble proto stubs at build time.
# grpcio-tools bundles the google/protobuf/*.proto files; the three Cilium
# protos below are everything else the observer service needs.
COPY deps/protos /build/protos
RUN mkdir -p /app/src && python -m grpc_tools.protoc \
    -I /build/protos \
    --python_out=/app/src \
    --grpc_python_out=/app/src \
    /build/protos/flow/flow.proto \
    /build/protos/relay/relay.proto \
    /build/protos/observer/observer.proto

COPY deps /app/deps
COPY src /app/src

# src/ is not a package — flat absolute imports via PYTHONPATH
ENV PYTHONPATH=/app/deps:/app/src

EXPOSE 8003

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser /app
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]

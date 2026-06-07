"""
Blast-Radius Graph Builder — FastAPI application entry point.
Copyright (c) 2026 Kaushikkumaran
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from routers.graph import router as graph_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("phoenix_graph_started", service=config.SERVICE_NAME)
    yield
    log.info("phoenix_graph_stopped", service=config.SERVICE_NAME)


app = FastAPI(
    title="phoenix-graph",
    description=(
        "Blast-Radius Graph Builder — derives the service dependency graph "
        "from live k8s topology (services, pods, env-var references) and "
        "Hubble-observed network flows, then computes which downstream "
        "components are in the blast radius of a planned chaos scenario."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(graph_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": config.SERVICE_NAME}

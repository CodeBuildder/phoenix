"""
Chaos Injection Engine — FastAPI entrypoint
Copyright (c) 2026 Kaushikkumaran

Wraps Chaos Mesh (pod kill, network latency, packet loss, IO delay) and the
Provisioning Simulator's fault hooks (issue #1) behind one control surface —
a unified `Scenario` model and a single start/stop/status API — so M2's agent
and M3's dashboard can launch, monitor, and stop chaos scenarios uniformly,
regardless of which backend actually runs the fault.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from engine import engine
from routers import scenarios

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("phoenix_chaos_starting", version="0.1.0")
    engine.start_sweeper()
    yield
    await engine.stop_sweeper()
    log.info("phoenix_chaos_stopping")


app = FastAPI(
    title="Phoenix Chaos Injection Engine",
    description="Unified control surface over Chaos Mesh experiments and Provisioning Simulator faults",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scenarios.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": config.SERVICE_NAME,
        "version": "0.1.0",
    }

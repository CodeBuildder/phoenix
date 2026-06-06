"""
Provisioning Simulator — FastAPI entrypoint
Copyright (c) 2026 Kaushikkumaran

A deliberately faultable service that mimics generic enterprise infrastructure
operations — volume create/attach/detach, VLAN/subnet create, instance
provision/deprovision — each with a realistic async lifecycle and per-operation
fault-injection hooks (latency, transient error, partial failure, quota limit).
Phoenix's chaos engine (M1 issue #2) drives those hooks; M2's agent reasons
about the failures they produce; M3's dashboard renders "what exists right now".
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from routers import faults, instances, subnets, volumes
from store import store

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("phoenix_sim_starting", version="0.1.0")
    yield
    log.info("phoenix_sim_stopping")


app = FastAPI(
    title="Phoenix Provisioning Simulator",
    description="Synthetic enterprise infrastructure ops — intentionally faultable",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(volumes.router)
app.include_router(subnets.router)
app.include_router(instances.router)
app.include_router(faults.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": config.SERVICE_NAME,
        "version": "0.1.0",
    }


@app.get("/state")
async def get_state():
    """"What exists right now" — every simulated resource, grouped by type.
    Backs the dashboard's live-state view (M3) and gives the chaos engine
    (M1 issue #2) a way to pick concrete targets for a scenario."""
    snapshot = await store.snapshot()
    return {
        "resources": snapshot,
        "totals": {resource_type: len(resources) for resource_type, resources in snapshot.items()},
    }

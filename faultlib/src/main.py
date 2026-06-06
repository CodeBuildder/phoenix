"""
Fault Library & Taxonomy Classifier — FastAPI entrypoint
Copyright (c) 2026 Kaushikkumaran

The M1 issue #3 surface: a structured catalog of every fault `/chaos` can
launch, a deterministic classifier that labels a failure's taxonomy category
from its structural signature, and a live ranking of which components have
actually experienced which failure modes — all derived, on every request,
from the fault library's own static reference data and `/chaos`'s real
scenario history. Nothing here owns state of its own to drift out of sync.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from routers import library

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("phoenix_faultlib_starting", version="0.1.0")
    yield
    log.info("phoenix_faultlib_stopping")


app = FastAPI(
    title="Phoenix Fault Library & Taxonomy Classifier",
    description="Fault catalog, failure-mode classifier, and live failure-mode-frequency rankings",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": config.SERVICE_NAME,
        "version": "0.1.0",
    }

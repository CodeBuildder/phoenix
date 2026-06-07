"""
Phoenix Agent — FastAPI application
Copyright (c) 2026 Kaushikkumaran

Exposes:
  GET  /health
  GET  /runs                        — all healing pipeline runs
  GET  /runs/{scenario_id}          — one run's full state
  POST /runs/{scenario_id}/approve  — human approves a pending action
  POST /runs/{scenario_id}/reject   — human rejects a pending action
  GET  /memory                      — healing memory records

Background poller: every POLL_INTERVAL_SECONDS it checks /scenarios?status=running
on the chaos service and starts a new pipeline run for any scenario not already
being processed.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import config
from memory import MemoryStore
from models import AgentNode, AgentRun, ApprovalStatus
from runner import run_pipeline
from store import RunStore
from tools import get_running_scenarios

log = structlog.get_logger()

run_store    = RunStore()
memory_store = MemoryStore(config.DB_PATH)

# Active pipeline tasks keyed by scenario_id
_tasks: dict[str, asyncio.Task] = {}


async def _poller() -> None:
    """Poll chaos service for running scenarios and start agent runs for new ones."""
    await asyncio.sleep(5)  # brief startup grace period
    while True:
        try:
            scenarios = await get_running_scenarios()
            for scenario in scenarios:
                sid = scenario.get("id")
                if not sid:
                    continue
                if await run_store.has(sid):
                    continue  # already being processed
                if sid in _tasks and not _tasks[sid].done():
                    continue

                run = AgentRun(scenario_id=sid, scenario=scenario)
                await run_store.put(run)
                log.info("poller.new_scenario", scenario_id=sid,
                         fault_type=scenario.get("fault_type"))

                task = asyncio.create_task(
                    run_pipeline(run, run_store, memory_store),
                    name=f"pipeline-{sid}",
                )
                _tasks[sid] = task

        except Exception as exc:
            log.warning("poller.error", error=str(exc))

        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    poller_task = asyncio.create_task(_poller(), name="scenario-poller")
    yield
    poller_task.cancel()
    for t in _tasks.values():
        t.cancel()


app = FastAPI(
    title="phoenix-agent",
    description="Phoenix self-healing agent — detect, diagnose, heal, verify",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "phoenix-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_runs": sum(1 for t in _tasks.values() if not t.done()),
    }


# ── runs ──────────────────────────────────────────────────────────────────────

@app.get("/runs")
async def list_runs():
    runs = await run_store.list()
    return [r.model_dump() for r in runs]


@app.get("/runs/{scenario_id}")
async def get_run(scenario_id: str):
    run = await run_store.get(scenario_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run for scenario {scenario_id}")
    return run.model_dump()


@app.post("/runs/{scenario_id}/approve")
async def approve_action(scenario_id: str):
    run = await run_store.get(scenario_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run for scenario {scenario_id}")
    if run.approval_status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=409, detail="No pending approval for this run")
    await run_store.update(scenario_id, approval_status=ApprovalStatus.APPROVED)
    log.info("api.approved", scenario_id=scenario_id)
    return {"status": "approved", "scenario_id": scenario_id}


@app.post("/runs/{scenario_id}/reject")
async def reject_action(scenario_id: str):
    run = await run_store.get(scenario_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run for scenario {scenario_id}")
    if run.approval_status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=409, detail="No pending approval for this run")
    await run_store.update(scenario_id, approval_status=ApprovalStatus.REJECTED)
    log.info("api.rejected", scenario_id=scenario_id)
    return {"status": "rejected", "scenario_id": scenario_id}


@app.post("/runs/{scenario_id}/trigger")
async def trigger_run(scenario_id: str, scenario: dict):
    """
    Manually trigger a pipeline run for a scenario that the poller may have missed.
    Used by the dashboard's inject flow to immediately start processing.
    """
    if await run_store.has(scenario_id):
        existing = await run_store.get(scenario_id)
        return existing.model_dump()

    run = AgentRun(scenario_id=scenario_id, scenario=scenario)
    await run_store.put(run)
    task = asyncio.create_task(
        run_pipeline(run, run_store, memory_store),
        name=f"pipeline-{scenario_id}",
    )
    _tasks[scenario_id] = task
    log.info("api.trigger", scenario_id=scenario_id)
    return run.model_dump()


# ── memory ────────────────────────────────────────────────────────────────────

@app.get("/memory")
async def list_memory():
    return memory_store.list_all()


@app.get("/memory/{fault_type}")
async def recall_memory(fault_type: str):
    return {"fault_type": fault_type, "context": memory_store.recall(fault_type)}


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, workers=1)

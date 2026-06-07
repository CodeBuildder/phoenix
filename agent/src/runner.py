"""
Phoenix Agent — state machine runner
Copyright (c) 2026 Kaushikkumaran

Drives one AgentRun through the detect→diagnose→heal_plan→
[approve→]execute→verify→report pipeline.  Each node transition is
persisted to the RunStore so the API always reflects the live state.

Structured as a plain coroutine (not a compiled LangGraph graph) because
the approve node needs to poll async state changes — LangGraph's interrupt
mechanism would require a checkpointer and more infrastructure.  The node
functions themselves are identical in shape to LangGraph nodes (pure
state-in / state-out) so migration is mechanical if needed later.
"""

from __future__ import annotations

import asyncio

import structlog

from models import AgentNode, AgentRun, ApprovalStatus
from nodes import detect, diagnose, heal_plan, approve, execute, verify, report
from store import RunStore
from memory import MemoryStore
from events import Severity, publish_event

log = structlog.get_logger()


async def run_pipeline(
    run: AgentRun,
    run_store: RunStore,
    memory_store: MemoryStore,
) -> None:
    """
    Run the full healing pipeline for one scenario, updating RunStore after
    each node so the REST API always reflects the current state.
    """
    async def _save(r: AgentRun, node: AgentNode) -> AgentRun:
        r.node = node
        await run_store.put(r)
        return r

    publish_event(
        "phoenix.agent.run.started",
        severity=Severity.INFO,
        component=f"chaos.scenario.{run.scenario_id}",
        payload={"scenario_id": run.scenario_id},
    )

    try:
        # ── DETECT ──────────────────────────────────────────────────────────
        await _save(run, AgentNode.DETECT)
        run = await detect(run)

        # ── DIAGNOSE ────────────────────────────────────────────────────────
        await _save(run, AgentNode.DIAGNOSE)
        memory_ctx = memory_store.recall(run.scenario.get("fault_type", "unknown"))
        run = await diagnose(run, memory_ctx)

        # ── HEAL_PLAN ───────────────────────────────────────────────────────
        await _save(run, AgentNode.HEAL_PLAN)
        run = await heal_plan(run)

        # ── APPROVE (only for high-risk) ────────────────────────────────────
        if run.approval_status == ApprovalStatus.PENDING:
            await _save(run, AgentNode.APPROVE)
            run = await approve(run, run_store)

            if run.node == AgentNode.ABORTED:
                await _save(run, AgentNode.ABORTED)
                log.info("runner.aborted", scenario_id=run.scenario_id)
                return

        # ── EXECUTE ─────────────────────────────────────────────────────────
        await _save(run, AgentNode.EXECUTE)
        run = await execute(run)

        # ── VERIFY ──────────────────────────────────────────────────────────
        await _save(run, AgentNode.VERIFY)
        run = await verify(run)

        # ── REPORT ──────────────────────────────────────────────────────────
        await _save(run, AgentNode.REPORT)
        run = await report(run, memory_store)

        await _save(run, AgentNode.DONE)
        log.info("runner.done", scenario_id=run.scenario_id, mttr=run.mttr_seconds)

    except asyncio.CancelledError:
        run.node  = AgentNode.ERROR
        run.error = "Pipeline cancelled"
        await run_store.put(run)
        raise

    except Exception as exc:
        run.node  = AgentNode.ERROR
        run.error = str(exc)
        await run_store.put(run)
        publish_event(
            "phoenix.agent.run.error",
            severity=Severity.HIGH,
            component=f"chaos.scenario.{run.scenario_id}",
            payload={"scenario_id": run.scenario_id, "error": str(exc)},
        )
        log.error("runner.error", scenario_id=run.scenario_id, error=str(exc))

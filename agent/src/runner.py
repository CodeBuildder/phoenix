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
import world_model as wm

log = structlog.get_logger()


async def _update_world_model(run: AgentRun) -> None:
    """Post-pipeline: update trust ledger, calibration, and SLO budget."""
    if run.diagnosis is None:
        return

    action_type = run.diagnosis.recommended_action
    scenario    = run.scenario
    fault_type  = scenario.get("fault_type", "unknown")
    namespace   = scenario.get("namespace", "phoenix-system")
    service     = scenario.get("target_deployment") or scenario.get("target")

    # Was the healing prediction correct?
    verify_ok   = (run.verify_result or "").lower().startswith("success")
    outcome     = "success" if verify_ok else "surprise"
    brier       = 0.0 if verify_ok else 1.0

    await asyncio.gather(
        wm.update_trust(action_type, outcome, brier_score=brier),
        wm.record_calibration(
            action_id=run.scenario_id,
            action_type=action_type,
            predicted_outcome="resolved",
            actual_outcome="resolved" if verify_ok else "unresolved",
        ),
        *(
            [wm.burn_slo_budget(
                service_id=f"service/{namespace}/{service}",
                duration_minutes=(run.mttr_seconds or 0) / 60,
                scenario_id=run.scenario_id,
            )]
            if service and run.mttr_seconds
            else []
        ),
        return_exceptions=True,
    )


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

        # ── WORLD MODEL: trust ledger + SLO budget ───────────────────────────
        await _update_world_model(run)

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
            payload={
                "scenario_id": run.scenario_id,
                "correlation_id": run.scenario.get("correlation_id") or run.scenario_id,
                "domain": run.scenario.get("domain", "chaos_mesh"),
                "error": str(exc),
            },
        )
        log.error("runner.error", scenario_id=run.scenario_id, error=str(exc))

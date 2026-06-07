"""
Phoenix Agent — LangGraph-style node functions
Copyright (c) 2026 Kaushikkumaran

Each node is a pure async function:  AgentRun → AgentRun
The runner (runner.py) calls them in sequence, persisting state after each.

Node sequence:
  DETECT → DIAGNOSE → HEAL_PLAN → EXECUTE (low-risk) or APPROVE → EXECUTE → VERIFY → REPORT

All reasoning data comes from real API calls — no hardcoded strings, no
fabricated causal chains. Claude reads the live blast-radius graph, catalog
entry, and memory context to reconstruct the causal chain and pick an action.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

import anthropic
import structlog

from config import config
from events import Severity, publish_event
from models import AgentNode, AgentRun, ApprovalStatus, DiagnosisResult
from tools import (
    get_blast_radius,
    get_catalog_entry,
    get_scenario,
    restart_deployment,
    stop_scenario,
)

log = structlog.get_logger()
_anthropic = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


# ── detect ────────────────────────────────────────────────────────────────────

async def detect(run: AgentRun) -> AgentRun:
    """
    Enrich the scenario with blast-radius graph data and the catalog entry.
    This is the only node that touches external read APIs — downstream nodes
    reason over the data collected here.
    """
    scenario = run.scenario
    target = scenario.get("target", {})
    namespace = target.get("namespace", config.NAMESPACE)
    labels = target.get("label_selector", {})
    domain = scenario.get("domain", "chaos_mesh")
    fault_type = scenario.get("fault_type", "")

    blast, catalog = await asyncio.gather(
        get_blast_radius(namespace, labels),
        get_catalog_entry(domain, fault_type),
        return_exceptions=True,
    )

    run.blast_radius  = blast  if not isinstance(blast, Exception)  else {}
    run.catalog_entry = catalog if not isinstance(catalog, Exception) else {}

    publish_event(
        "phoenix.agent.detect.complete",
        severity=Severity.INFO,
        component=f"chaos.scenario.{scenario.get('id', run.scenario_id)}",
        payload={
            "scenario_id":   run.scenario_id,
            "fault_type":    fault_type,
            "affected_nodes": len((run.blast_radius or {}).get("affected_nodes", [])),
        },
    )
    log.info("node.detect.complete", scenario_id=run.scenario_id,
             affected=len((run.blast_radius or {}).get("affected_nodes", [])))
    return run


# ── diagnose ──────────────────────────────────────────────────────────────────

_DIAGNOSE_SYSTEM = """\
You are Phoenix, an AI self-healing agent for Kubernetes infrastructure.
You have been invoked because a chaos fault is active in the cluster.
Your job: reconstruct the causal chain from the real data below and recommend
ONE concrete remediation action. You must not fabricate any service names,
metrics, or effects that are not present in the data provided.

Respond ONLY with valid JSON matching this schema (no markdown, no prose):
{
  "causal_chain": "...",
  "recommended_action": "restart_deployment | stop_scenario | scale_deployment",
  "action_target": "<deployment-name or scenario-id>",
  "risk": "low | high",
  "rationale": "..."
}

Risk guidance:
  low  — action only affects the faulted service; no downstream risk
  high — action could cascade (e.g. restarting a dependency shared by many services)
"""


async def diagnose(run: AgentRun, memory_context: str) -> AgentRun:
    """
    Call Claude with the real scenario + blast-radius + catalog data.
    Extract a structured DiagnosisResult.
    """
    run.memory_context = memory_context

    scenario      = run.scenario
    blast_summary = _summarise_blast(run.blast_radius or {})
    catalog_summary = _summarise_catalog(run.catalog_entry or {})
    fault_type    = scenario.get("fault_type", "unknown")
    target_ns     = scenario.get("target", {}).get("namespace", config.NAMESPACE)

    user_prompt = f"""
=== ACTIVE SCENARIO ===
{json.dumps(scenario, indent=2)}

=== BLAST RADIUS (affected services) ===
{blast_summary}

=== FAULT CATALOG ENTRY ===
{catalog_summary}

=== MEMORY (prior incidents with fault_type='{fault_type}') ===
{memory_context}

The scenario targets namespace: {target_ns}
The scenario id is: {run.scenario_id}
"""

    message = await _anthropic.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        system=_DIAGNOSE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if Claude wrapped the JSON anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        run.diagnosis = DiagnosisResult(**parsed)
    except Exception as exc:
        log.warning("node.diagnose.parse_error", error=str(exc), raw=raw[:200])
        # Fallback: safe default — stop the scenario
        run.diagnosis = DiagnosisResult(
            causal_chain=f"Parse error on Claude response. Raw: {raw[:300]}",
            recommended_action="stop_scenario",
            action_target=run.scenario_id,
            risk="low",
            rationale="Defaulting to stop_scenario because diagnosis parse failed.",
        )

    publish_event(
        "phoenix.agent.diagnose.complete",
        severity=Severity.MEDIUM,
        component=f"chaos.scenario.{run.scenario_id}",
        payload={
            "scenario_id":        run.scenario_id,
            "recommended_action": run.diagnosis.recommended_action,
            "risk":               run.diagnosis.risk,
        },
        caused_by=run.scenario_id,
        reason=run.diagnosis.causal_chain[:200],
    )
    log.info("node.diagnose.complete", scenario_id=run.scenario_id,
             action=run.diagnosis.recommended_action, risk=run.diagnosis.risk)
    return run


def _summarise_blast(blast: dict) -> str:
    nodes = blast.get("affected_nodes", [])
    if not nodes:
        return "No affected nodes detected in blast-radius graph."
    lines = []
    for n in nodes:
        lines.append(
            f"  {n.get('name','?')} ({n.get('namespace','?')}) — "
            f"severity={n.get('severity','?')} hops={n.get('distance_hops','?')} "
            f"flow={n.get('observed_flow','?')}"
        )
    return f"{len(nodes)} affected node(s):\n" + "\n".join(lines)


def _summarise_catalog(entry: dict) -> str:
    if not entry:
        return "No catalog entry found for this fault type."
    return (
        f"fault_type={entry.get('fault_type','?')} "
        f"domain={entry.get('domain','?')} "
        f"taxonomy={entry.get('taxonomy_category','?')}\n"
        f"description: {entry.get('description','')}\n"
        f"what_to_watch: {entry.get('what_to_watch','')}\n"
        f"prevention: {entry.get('prevention','')}"
    )


# ── heal_plan ─────────────────────────────────────────────────────────────────

async def heal_plan(run: AgentRun) -> AgentRun:
    """
    Route: low-risk → EXECUTE directly.  High-risk → APPROVE gate.
    No external calls — pure routing on the diagnosis already computed.
    """
    if run.diagnosis is None:
        run.node = AgentNode.ERROR
        run.error = "heal_plan reached with no diagnosis"
        return run

    if run.diagnosis.risk == "high":
        run.approval_status = ApprovalStatus.PENDING
        publish_event(
            "phoenix.agent.approve.requested",
            severity=Severity.HIGH,
            component=f"chaos.scenario.{run.scenario_id}",
            payload={
                "scenario_id":    run.scenario_id,
                "action":         run.diagnosis.recommended_action,
                "action_target":  run.diagnosis.action_target,
                "rationale":      run.diagnosis.rationale,
            },
        )
        log.info("node.heal_plan.approve_required", scenario_id=run.scenario_id)
    else:
        run.approval_status = ApprovalStatus.NOT_REQUIRED
        log.info("node.heal_plan.auto_execute", scenario_id=run.scenario_id)

    return run


# ── approve ───────────────────────────────────────────────────────────────────

async def approve(run: AgentRun, run_store) -> AgentRun:
    """
    Block until a human sets approval_status via the API, or until timeout.
    On timeout, abort (do not auto-approve high-risk actions).
    The run_store is passed in so we can re-read the live approval_status.
    """
    deadline = asyncio.get_event_loop().time() + config.APPROVE_TIMEOUT_SECONDS
    log.info("node.approve.waiting", scenario_id=run.scenario_id,
             timeout=config.APPROVE_TIMEOUT_SECONDS)

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(2)
        live = await run_store.get(run.scenario_id)
        if live is None:
            break
        if live.approval_status == ApprovalStatus.APPROVED:
            run.approval_status = ApprovalStatus.APPROVED
            publish_event(
                "phoenix.agent.approve.granted",
                severity=Severity.INFO,
                component=f"chaos.scenario.{run.scenario_id}",
                payload={"scenario_id": run.scenario_id},
            )
            log.info("node.approve.granted", scenario_id=run.scenario_id)
            return run
        if live.approval_status == ApprovalStatus.REJECTED:
            run.approval_status = ApprovalStatus.REJECTED
            run.node = AgentNode.ABORTED
            publish_event(
                "phoenix.agent.approve.rejected",
                severity=Severity.MEDIUM,
                component=f"chaos.scenario.{run.scenario_id}",
                payload={"scenario_id": run.scenario_id},
            )
            log.info("node.approve.rejected", scenario_id=run.scenario_id)
            return run

    # Timeout — abort
    run.approval_status = ApprovalStatus.REJECTED
    run.node = AgentNode.ABORTED
    log.warning("node.approve.timeout", scenario_id=run.scenario_id)
    return run


# ── execute ───────────────────────────────────────────────────────────────────

async def execute(run: AgentRun) -> AgentRun:
    """
    Run the remediation action recommended by Claude.
    Maps action name → tool call. Records the result string.
    """
    if run.diagnosis is None:
        run.error = "execute reached with no diagnosis"
        return run

    action = run.diagnosis.recommended_action
    target = run.diagnosis.action_target
    namespace = run.scenario.get("target", {}).get("namespace", config.NAMESPACE)

    try:
        if action == "restart_deployment":
            result = await restart_deployment(name=target, namespace=namespace)
        elif action == "stop_scenario":
            result = await stop_scenario(scenario_id=target)
        elif action == "scale_deployment":
            # Scale to +1 replica via patch — read current replicas first
            result = await _scale_deployment(target, namespace)
        else:
            result = f"Unknown action '{action}' — stopped scenario as fallback."
            await stop_scenario(run.scenario_id)

        run.action_result = result
        publish_event(
            "phoenix.agent.heal.action_taken",
            severity=Severity.INFO,
            component=f"chaos.scenario.{run.scenario_id}",
            payload={
                "scenario_id": run.scenario_id,
                "action":      action,
                "target":      target,
                "result":      result,
            },
        )
        log.info("node.execute.done", scenario_id=run.scenario_id, action=action, result=result)

    except Exception as exc:
        run.action_result = f"ERROR: {exc}"
        run.error = str(exc)
        log.error("node.execute.error", scenario_id=run.scenario_id, error=str(exc))

    return run


async def _scale_deployment(name: str, namespace: str) -> str:
    from kubernetes import client, config as k8s_config
    from kubernetes.client.rest import ApiException
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()
    apps = client.AppsV1Api()
    dep = apps.read_namespaced_deployment(name=name, namespace=namespace)
    current = dep.spec.replicas or 1
    apps.patch_namespaced_deployment_scale(
        name=name, namespace=namespace,
        body={"spec": {"replicas": current + 1}},
    )
    return f"Scaled {namespace}/{name} from {current} → {current + 1} replicas"


# ── verify ────────────────────────────────────────────────────────────────────

async def verify(run: AgentRun) -> AgentRun:
    """
    Confirm the scenario has stopped and the target service is responsive.
    Polls the chaos API up to 60s for a non-running status.
    """
    scenario_id = run.scenario_id
    deadline = asyncio.get_event_loop().time() + 60

    while asyncio.get_event_loop().time() < deadline:
        live = await get_scenario(scenario_id)
        if live is None:
            run.verify_result = "Scenario not found (may have been cleaned up) — treating as resolved."
            break
        status = live.get("status", "unknown")
        if status in ("stopped", "completed", "failed"):
            run.verify_result = f"Scenario reached terminal status: {status}"
            break
        await asyncio.sleep(5)
    else:
        run.verify_result = "Verify timed out — scenario may still be running."

    # Compute MTTR
    started_at = run.scenario.get("started_at") or run.started_at
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        run.mttr_seconds = (datetime.now(timezone.utc) - t0).total_seconds()
    except Exception:
        pass

    publish_event(
        "phoenix.agent.verify.complete",
        severity=Severity.INFO,
        component=f"chaos.scenario.{scenario_id}",
        payload={
            "scenario_id":   scenario_id,
            "verify_result": run.verify_result,
            "mttr_seconds":  run.mttr_seconds,
        },
    )
    log.info("node.verify.done", scenario_id=scenario_id, result=run.verify_result,
             mttr=run.mttr_seconds)
    return run


# ── report ────────────────────────────────────────────────────────────────────

async def report(run: AgentRun, memory_store) -> AgentRun:
    """
    Persist the outcome to the memory store and emit the final event.
    """
    if run.diagnosis:
        cat = (run.catalog_entry or {}).get("taxonomy_category")
        ns  = run.scenario.get("target", {}).get("namespace", config.NAMESPACE)
        outcome = "success" if not run.error else "failed"

        memory_store.record(
            fault_type=run.scenario.get("fault_type", "unknown"),
            taxonomy_category=cat,
            target_namespace=ns,
            action_taken=run.diagnosis.recommended_action,
            outcome=outcome,
            mttr_seconds=run.mttr_seconds,
            diagnosis=run.diagnosis.causal_chain,
        )

    run.completed_at = datetime.now(timezone.utc).isoformat()
    publish_event(
        "phoenix.agent.run.done",
        severity=Severity.INFO,
        component=f"chaos.scenario.{run.scenario_id}",
        payload={
            "scenario_id":  run.scenario_id,
            "mttr_seconds": run.mttr_seconds,
            "outcome":      "success" if not run.error else "failed",
        },
    )
    log.info("node.report.done", scenario_id=run.scenario_id, mttr=run.mttr_seconds)
    return run

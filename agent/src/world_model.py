"""
Phoenix → World Model client.

Posts healing findings, updates the trust ledger, and burns SLO budget
in the shared World Model. All calls are best-effort; Phoenix's own
pipeline is not gated on World Model availability.
"""

import hashlib
import os
from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger()

_WM_URL = os.getenv("WORLD_MODEL_URL", "").rstrip("/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(scenario_id: str, node: str) -> str:
    raw = f"phoenix|{scenario_id}|{node}"
    return "phoenix-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


async def post_finding(
    *,
    scenario_id: str,
    node: str,
    fault_type: str,
    namespace: str,
    service: str | None,
    severity: str,
    outcome: str,
    payload: dict,
) -> None:
    if not _WM_URL:
        return

    entity_id = f"service/{namespace}/{service}" if service else None

    body: dict = {
        "event_id":  _event_id(scenario_id, node),
        "type":      "finding",
        "source":    "phoenix",
        "timestamp": _now(),
        "severity":  severity,
        "payload": {
            "finding_type":  "healing_action",
            "scenario_id":   scenario_id,
            "pipeline_node": node,
            "fault_type":    fault_type,
            "outcome":       outcome,
            **payload,
        },
    }
    if entity_id:
        body["entity_id"] = entity_id

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(f"{_WM_URL}/findings", json=body)
        log.debug("wm.finding_posted", scenario_id=scenario_id, node=node,
                  status=resp.status_code)
    except Exception as exc:  # noqa: BLE001
        log.debug("wm.finding_error", scenario_id=scenario_id, error=str(exc))


async def update_trust(action_type: str, outcome: str, brier_score: float | None = None) -> None:
    """Record action outcome in the trust ledger (success|surprise)."""
    if not _WM_URL:
        return
    body: dict = {"action_type": action_type, "outcome": outcome}
    if brier_score is not None:
        body["brier_score"] = brier_score
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{_WM_URL}/trust/update", json=body)
    except Exception as exc:  # noqa: BLE001
        log.debug("wm.trust_error", action_type=action_type, error=str(exc))


async def record_calibration(
    *,
    action_id: str,
    action_type: str,
    predicted_outcome: str,
    actual_outcome: str,
) -> None:
    """Push a Brier-score calibration record (predicted vs actual)."""
    if not _WM_URL:
        return
    body = {
        "action_id":        action_id,
        "action_type":      action_type,
        "predicted_outcome": predicted_outcome,
        "actual_outcome":    actual_outcome,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{_WM_URL}/calibration", json=body)
    except Exception as exc:  # noqa: BLE001
        log.debug("wm.calibration_error", action_id=action_id, error=str(exc))


async def burn_slo_budget(
    service_id: str,
    duration_minutes: float,
    scenario_id: str,
    impact_factor: float = 1.0,
) -> None:
    """Deduct error budget consumed by this chaos / healing event."""
    if not _WM_URL:
        return
    body = {
        "source":           "chaos",
        "event_id":         f"chaos-{scenario_id}",
        "duration_minutes": duration_minutes,
        "impact_factor":    impact_factor,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{_WM_URL}/slo/{service_id}/burn", json=body)
    except Exception as exc:  # noqa: BLE001
        log.debug("wm.slo_burn_error", service_id=service_id, error=str(exc))

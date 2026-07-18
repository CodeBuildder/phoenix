"""
Phoenix Agent — event publisher  (#11)
Copyright (c) 2026 Kaushikkumaran

M0 stub: structured-log + World Model write.
M1 (this file): publishes to both structlog (backward compat) AND
posts key events to the World Model findings API as source="phoenix".

Call sites unchanged — same signature, same Event return type.
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from config import config

log = structlog.get_logger()


class Severity(str, Enum):
    INFO     = "info"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class Causality(BaseModel):
    caused_by: str | None = None
    reason:    str | None = None


class Event(BaseModel):
    event_type:   str
    source_agent: str = config.SOURCE_AGENT
    severity:     Severity
    component:    str
    causality:    Causality | None = None
    timestamp:    str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload:      dict[str, Any] = Field(default_factory=dict)


# Event types that represent actionable findings worth posting to World Model
_WM_EVENTS = {
    "phoenix.agent.detect.complete",
    "phoenix.agent.heal.action_taken",
    "phoenix.agent.verify.complete",
    "phoenix.agent.run.done",
    "phoenix.agent.run.error",
}


def publish_event(
    event_type: str,
    *,
    severity: Severity,
    component: str,
    payload: dict[str, Any] | None = None,
    caused_by: str | None = None,
    reason: str | None = None,
) -> Event:
    causality = Causality(caused_by=caused_by, reason=reason) if (caused_by or reason) else None
    event = Event(
        event_type=event_type,
        severity=severity,
        component=component,
        causality=causality,
        payload=payload or {},
    )
    log.info(
        event.event_type,
        event_type=event.event_type,
        source_agent=event.source_agent,
        severity=event.severity.value,
        component=event.component,
        causality=event.causality.model_dump() if event.causality else None,
        timestamp=event.timestamp,
        payload=event.payload,
    )

    if event_type in _WM_EVENTS:
        _fire_wm(event)

    return event


def _fire_wm(event: Event) -> None:
    """Schedule a best-effort World Model POST without blocking the caller."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_post_to_wm(event))
    except RuntimeError:
        pass  # no event loop — skip (test / sync context)


async def _post_to_wm(event: Event) -> None:
    import hashlib, os
    from world_model import post_finding

    # Extract scenario metadata from payload for entity_id resolution
    p       = event.payload
    sid     = p.get("scenario_id", "unknown")
    ns      = p.get("namespace") or config.NAMESPACE
    service = p.get("service") or p.get("action_target")
    scenario = p.get("scenario") if isinstance(p.get("scenario"), dict) else {}
    domain = p.get("domain") or scenario.get("domain") or "observed"
    provenance = "live_chaos" if domain == "chaos_mesh" else "simulator" if domain == "simulator" else "observed"

    await post_finding(
        scenario_id=sid,
        node=event.event_type.split(".")[-1],
        fault_type=p.get("fault_type", "unknown"),
        namespace=ns,
        service=service,
        severity=event.severity.value,
        outcome=p.get("outcome", "unknown"),
        payload=p,
        correlation_id=p.get("correlation_id") or scenario.get("correlation_id") or sid,
        provenance=provenance,
    )

"""
Phoenix Agent — event publisher  (#11)
Copyright (c) 2026 Kaushikkumaran

Mirrors chaos/src/events.py exactly: structured-log stub, same field names
as sentinel-platform's M0 schema, same Loki-queryable output pattern.

Swap for Redis-streams transport once sentinel-platform M0 lands:
  1. Delete phoenix/schemas/event.schema.json (use the real one)
  2. Replace the structlog emit below with the Redis publisher
  3. Call sites do not need to change (same Event shape, same publish_event signature)

Event types emitted by the agent:
  phoenix.agent.run.started
  phoenix.agent.detect.complete
  phoenix.agent.diagnose.complete
  phoenix.agent.heal.action_taken
  phoenix.agent.approve.requested
  phoenix.agent.approve.granted
  phoenix.agent.approve.rejected
  phoenix.agent.verify.complete
  phoenix.agent.run.done
  phoenix.agent.run.aborted
  phoenix.agent.run.error
"""

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
    return event

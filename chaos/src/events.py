"""
Chaos Injection Engine — event bus publisher
Copyright (c) 2026 Kaushikkumaran

STUB NOTICE
-----------
sentinel-platform's M0 milestone owns the shared event schema
(`/schemas/event.schema.json`) and the Redis-streams event bus that every
Sentinel agent publishes onto. Neither exists yet as of this writing, so this
module defines a local stub of the schema (mirrored at
`phoenix/schemas/event.schema.json`, the same stub `phoenix-sim` uses) and
publishes events as structured logs instead — the same "queryable in Loki"
pattern argus's audit logger and phoenix-sim use:
`{app="phoenix-chaos"} | json | event_type != ""`.

`Event` and `publish_event` are the only things callers should depend on. Once
sentinel-platform's M0 lands:
  1. delete `phoenix/schemas/event.schema.json` and depend on the real one
  2. swap this module's transport for the Redis-streams client
  3. `Event`'s field names are chosen to match the schema fields named in the
     M1 issue (event_type, source_agent, severity, component, causality,
     timestamp, payload) so that swap should not require touching call sites
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from config import config

log = structlog.get_logger()


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Causality(BaseModel):
    """Optional causal link back to whatever triggered this event."""
    caused_by: str | None = None
    reason: str | None = None


class Event(BaseModel):
    """
    Mirrors the field set sentinel-platform's M0 schema is expected to define:
    event_type, source_agent, severity, component, causality, timestamp, payload.
    """
    event_type: str
    source_agent: str = config.SOURCE_AGENT
    severity: Severity
    component: str
    causality: Causality | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)


def publish_event(
    event_type: str,
    *,
    severity: Severity,
    component: str,
    payload: dict[str, Any] | None = None,
    caused_by: str | None = None,
    reason: str | None = None,
) -> Event:
    """
    Build an Event in the shared shape and emit it.

    Emission is a structured log line at the top level (not nested under a
    message field) so Loki/Promtail picks up every field for filtering —
    matching how argus's audit entries and phoenix-sim's events are queried
    in Grafana.
    """
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

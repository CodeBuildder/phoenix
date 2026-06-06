"""
Tests for the event-bus stub publisher.
Copyright (c) 2026 Kaushikkumaran

Verifies every emitted event carries the field set the M1 issue specifies
(event_type, source_agent, severity, component, causality, timestamp,
payload) — the contract M2/M3 build against, and the shape that needs to
converge with sentinel-platform's M0 schema once it lands.
"""

from events import Causality, Event, Severity, publish_event


def test_event_carries_required_fields():
    event = publish_event(
        "sim.lifecycle.transition",
        severity=Severity.INFO,
        component="sim.volume",
        payload={"resource_id": "vol-abc123", "state": "available"},
    )

    assert isinstance(event, Event)
    assert event.event_type == "sim.lifecycle.transition"
    assert event.source_agent == "phoenix"
    assert event.severity == Severity.INFO
    assert event.component == "sim.volume"
    assert event.payload == {"resource_id": "vol-abc123", "state": "available"}
    assert event.causality is None
    # ISO 8601 / RFC 3339 — the schema's documented timestamp format
    assert "T" in event.timestamp


def test_event_records_causality_when_given():
    event = publish_event(
        "sim.lifecycle.error",
        severity=Severity.MEDIUM,
        component="sim.instance",
        payload={"resource_id": "inst-xyz"},
        caused_by="fault-789",
        reason="transient_error fault during provision",
    )

    assert event.causality == Causality(caused_by="fault-789", reason="transient_error fault during provision")


def test_event_defaults_payload_to_empty_dict():
    event = publish_event("sim.fault.triggered", severity=Severity.LOW, component="sim.subnet")
    assert event.payload == {}

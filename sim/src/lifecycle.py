"""
Provisioning Simulator — async lifecycle engine
Copyright (c) 2026 Kaushikkumaran

Drives every resource through a "realistic async lifecycle": an operation
returns immediately with the resource in a transitional state, a background
task carries it to its terminal state after a simulated delay, and every
state change is published as an event. A pre-resolved fault rule (see
faults.py) can stretch, derail, or stall that transition.

(resource_type, operation) -> (transitional_state, terminal_state, delay_range_seconds)
"""

import asyncio
import random
from typing import Final

from config import config
from events import Severity, publish_event
from faults import FaultRule, FaultType
from models import Resource, ResourceType
from store import ResourceStore, store

TRANSITIONS: Final[dict[tuple[ResourceType, str], tuple[str, str, tuple[float, float]]]] = {
    (ResourceType.VOLUME, "create"): ("creating", "available", (0.4, 1.5)),
    (ResourceType.VOLUME, "attach"): ("attaching", "in_use", (0.2, 0.8)),
    (ResourceType.VOLUME, "detach"): ("detaching", "available", (0.2, 0.8)),
    (ResourceType.VOLUME, "delete"): ("deleting", "deleted", (0.2, 0.6)),
    (ResourceType.SUBNET, "create"): ("creating", "active", (0.4, 1.2)),
    (ResourceType.SUBNET, "delete"): ("deleting", "deleted", (0.2, 0.6)),
    (ResourceType.INSTANCE, "provision"): ("provisioning", "running", (0.8, 2.5)),
    (ResourceType.INSTANCE, "deprovision"): ("deprovisioning", "terminated", (0.4, 1.5)),
}


class LifecycleEngine:
    def __init__(self, store: ResourceStore) -> None:
        self._store = store

    async def run(self, resource: Resource, operation: str, fault: FaultRule | None) -> None:
        """Carry `resource` through its (operation) transition. Awaited as a
        background task — callers get the transitional state back immediately."""
        transitional, terminal, delay_range = TRANSITIONS[(resource.type, operation)]

        resource.touch(state=transitional)
        await self._store.put(resource)
        self._emit_transition(resource, operation, transitional)

        base_delay = random.uniform(*delay_range) * config.LIFECYCLE_SPEED

        if fault is None:
            await asyncio.sleep(base_delay)
            resource.touch(state=terminal)
            await self._store.put(resource)
            self._emit_transition(resource, operation, terminal)
            return

        await self._apply_fault(resource, operation, fault, transitional, terminal, base_delay)

    def _emit_transition(self, resource: Resource, operation: str, state: str) -> None:
        publish_event(
            "sim.lifecycle.transition",
            severity=Severity.INFO,
            component=f"sim.{resource.type.value}",
            payload={
                "resource_id": resource.id,
                "resource_type": resource.type.value,
                "operation": operation,
                "state": state,
            },
        )

    async def _apply_fault(
        self,
        resource: Resource,
        operation: str,
        fault: FaultRule,
        transitional: str,
        terminal: str,
        base_delay: float,
    ) -> None:
        component = f"sim.{resource.type.value}"
        base_payload = {
            "resource_id": resource.id,
            "resource_type": resource.type.value,
            "operation": operation,
            "fault_rule_id": fault.id,
            "fault_type": fault.fault_type.value,
        }

        if fault.fault_type == FaultType.LATENCY:
            extra = float(fault.params.get("extra_seconds", 5.0))
            total_delay = base_delay + extra
            publish_event(
                "sim.fault.triggered",
                severity=Severity.LOW,
                component=component,
                payload={**base_payload, "delay_seconds": round(total_delay, 2)},
            )
            await asyncio.sleep(total_delay)
            resource.touch(state=terminal)
            await self._store.put(resource)
            self._emit_transition(resource, operation, terminal)
            return

        if fault.fault_type == FaultType.TRANSIENT_ERROR:
            await asyncio.sleep(base_delay * 0.5)
            resource.touch(state="error")
            await self._store.put(resource)
            publish_event(
                "sim.fault.triggered",
                severity=Severity.MEDIUM,
                component=component,
                payload={**base_payload, "resulting_state": "error"},
                caused_by=fault.id,
                reason=f"{fault.fault_type.value} fault during {operation}",
            )
            self._emit_transition(resource, operation, "error")
            return

        if fault.fault_type == FaultType.PARTIAL_FAILURE:
            await asyncio.sleep(base_delay)
            resource.touch(state="degraded")
            await self._store.put(resource)
            publish_event(
                "sim.fault.triggered",
                severity=Severity.HIGH,
                component=component,
                payload={**base_payload, "stuck_in": transitional, "resulting_state": "degraded"},
                caused_by=fault.id,
                reason=f"{fault.fault_type.value} fault stalled {operation} mid-transition ({transitional})",
            )
            self._emit_transition(resource, operation, "degraded")
            return


engine = LifecycleEngine(store=store)

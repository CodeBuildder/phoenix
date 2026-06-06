"""
Provisioning Simulator — fault injection
Copyright (c) 2026 Kaushikkumaran

Fault rules are registered via the `/faults` API (by a human, the dashboard,
or — in M1 issue #2 — the chaos engine) and matched against every lifecycle
operation the simulator runs. This is the hook issue #2 wraps to trigger
"simulator faults" alongside Chaos Mesh experiments through one control surface.

Four fault types, matching the issue #1 scope checklist exactly:
  latency          — stretches the operation's simulated delay
  transient_error  — the operation fails after starting (resource -> "error")
  partial_failure  — the operation stalls mid-transition (resource -> "degraded")
  quota_limit      — the operation is rejected up front, before anything is created
"""

import random
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from models import ResourceType


class FaultType(str, Enum):
    LATENCY = "latency"
    TRANSIENT_ERROR = "transient_error"
    PARTIAL_FAILURE = "partial_failure"
    QUOTA_LIMIT = "quota_limit"


class FaultRuleCreateRequest(BaseModel):
    fault_type: FaultType
    resource_type: ResourceType | None = None
    operation: str | None = None
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = Field(default=None, gt=0)


class FaultRule(BaseModel):
    id: str
    fault_type: FaultType
    resource_type: ResourceType | None = None
    operation: str | None = None
    probability: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    expires_at: str | None = None
    hits: int = 0

    def matches(self, resource_type: ResourceType, operation: str) -> bool:
        if self.resource_type is not None and self.resource_type != resource_type:
            return False
        if self.operation is not None and self.operation != operation:
            return False
        if self.expires_at is not None:
            if datetime.now(timezone.utc) > datetime.fromisoformat(self.expires_at):
                return False
        return True


class FaultInjector:
    """In-memory registry of active fault rules and the resolver the
    lifecycle engine consults before (and during) every operation."""

    def __init__(self) -> None:
        self._rules: dict[str, FaultRule] = {}

    def register(self, req: FaultRuleCreateRequest) -> FaultRule:
        now = datetime.now(timezone.utc)
        expires_at = (
            (now + timedelta(seconds=req.duration_seconds)).isoformat()
            if req.duration_seconds
            else None
        )
        rule = FaultRule(
            id=f"fault-{uuid4().hex[:10]}",
            fault_type=req.fault_type,
            resource_type=req.resource_type,
            operation=req.operation,
            probability=req.probability,
            params=req.params,
            created_at=now.isoformat(),
            expires_at=expires_at,
        )
        self._rules[rule.id] = rule
        return rule

    def list(self) -> list[FaultRule]:
        return sorted(self._rules.values(), key=lambda r: r.created_at)

    def get(self, rule_id: str) -> FaultRule | None:
        return self._rules.get(rule_id)

    def clear(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def clear_all(self) -> int:
        count = len(self._rules)
        self._rules.clear()
        return count

    def resolve(
        self,
        resource_type: ResourceType,
        operation: str,
        fault_types: set[FaultType] | None = None,
    ) -> FaultRule | None:
        """Return the first active rule that matches, is in `fault_types`
        (when given), and rolls true on its probability — `None` means the
        operation runs cleanly. `fault_types` lets callers separate "checked
        up front" faults (quota_limit) from "in-flight" ones (latency,
        transient_error, partial_failure)."""
        candidates = [
            r for r in self._rules.values()
            if r.matches(resource_type, operation) and (fault_types is None or r.fault_type in fault_types)
        ]
        for rule in candidates:
            if random.random() <= rule.probability:
                rule.hits += 1
                return rule
        return None


injector = FaultInjector()

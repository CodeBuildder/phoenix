"""
Chaos Injection Engine — scenario models
Copyright (c) 2026 Kaushikkumaran

The "unified scenario model" the M1 issue calls for: one shape — `Scenario` —
that the agent (M2) and dashboard (M3) can launch/stop/monitor uniformly,
whether the underlying fault runs through Chaos Mesh (real cluster-level chaos:
pod kill, network latency, packet loss, IO delay) or through the Provisioning
Simulator's fault hooks (issue #1's `latency` / `transient_error` /
`partial_failure` / `quota_limit`).

A scenario's `target` and `params` shapes are necessarily domain-specific (a
network-latency experiment needs a k8s label selector and a jitter value; a
simulator quota-limit fault needs a resource type and an operation) — that
domain knowledge lives in `chaos_mesh.py` / `simulator_client.py`, which
validate and translate the request's `target`/`params` dicts. What's unified
is the *control surface*: one `POST /scenarios` to launch either kind, and one
`Scenario` shape coming back from every list/get/stop call.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def _new_id() -> str:
    return f"scn-{uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScenarioDomain(str, Enum):
    """Which backend actually runs the fault."""
    CHAOS_MESH = "chaos_mesh"
    SIMULATOR = "simulator"


class ScenarioStatus(str, Enum):
    PENDING = "pending"      # accepted, not yet applied to its backend
    RUNNING = "running"      # applied — the fault is live
    STOPPING = "stopping"    # stop requested, cleanup in flight
    STOPPED = "stopped"      # explicitly stopped before its natural end
    COMPLETED = "completed"  # backend reported the fault's natural end (duration elapsed)
    FAILED = "failed"        # could not be applied, or its backend reported an error


class ChaosMeshFaultType(str, Enum):
    """The four Chaos Mesh fault types named in the M1 issue scope, each
    backed by a real chaos-mesh.org/v1alpha1 CRD kind (see chaos_mesh.py)."""
    POD_KILL = "pod_kill"
    NETWORK_LATENCY = "network_latency"
    PACKET_LOSS = "packet_loss"
    IO_DELAY = "io_delay"


class SimulatorFaultType(str, Enum):
    """Mirrors phoenix-sim's `FaultType` values exactly (sim/src/faults.py) —
    duplicated rather than imported because the two are independently
    deployed services with no shared package."""
    LATENCY = "latency"
    TRANSIENT_ERROR = "transient_error"
    PARTIAL_FAILURE = "partial_failure"
    QUOTA_LIMIT = "quota_limit"


# ---------------------------------------------------------------------------
# Targets — what the fault is aimed at. Shape depends on the domain.
# ---------------------------------------------------------------------------

class K8sTarget(BaseModel):
    """Selects pods for a Chaos Mesh experiment — mirrors chaos-mesh.org's
    PodSelectorSpec (namespaces + labelSelectors + mode/value), the subset
    every one of our four fault types needs."""
    namespace: str
    label_selector: dict[str, str] = Field(default_factory=dict)
    mode: str = Field(default="one", pattern="^(one|all|fixed|fixed-percent|random-max-percent)$")
    value: str | None = None  # required by chaos-mesh when mode is fixed / fixed-percent / random-max-percent

    @model_validator(mode="after")
    def _value_required_for_fixed_modes(self) -> "K8sTarget":
        """chaos-mesh.org rejects fixed/fixed-percent/random-max-percent
        selectors with no `value` — catching that here, as part of request
        translation, means it surfaces as a 422 with nothing recorded,
        instead of slipping through to manifest-build time and coming back
        as a misleading 502 'backend error' on a scenario we already created."""
        needs_value = self.mode in ("fixed", "fixed-percent", "random-max-percent")
        if needs_value and not self.value:
            raise ValueError(f"target.value is required when mode is '{self.mode}'")
        return self


class SimulatorTarget(BaseModel):
    """Selects which simulator operations a fault rule matches — mirrors
    phoenix-sim's FaultRule matching fields (resource_type + operation),
    both optional so a scenario can target broadly."""
    resource_type: str | None = None  # "volume" | "subnet" | "instance"
    operation: str | None = None      # e.g. "create", "attach", "provision"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ScenarioCreateRequest(BaseModel):
    """One shape for launching either kind of scenario. `target` and `params`
    are validated and translated against the chosen `domain` + `fault_type`
    by the engine — see ScenarioEngine._build_chaos_mesh_spec /
    _build_simulator_fault, which reject anything that doesn't resolve to a
    real, well-formed backend request."""
    name: str
    domain: ScenarioDomain
    fault_type: str
    target: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = Field(default=None, gt=0)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)  # simulator domain only
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# The unified scenario record
# ---------------------------------------------------------------------------

class Scenario(BaseModel):
    """What every list/get/stop call returns, regardless of domain — the
    "launch/stop/monitor uniformly" shape the issue calls for."""
    id: str = Field(default_factory=_new_id)
    name: str
    domain: ScenarioDomain
    fault_type: str
    target: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    # Populated by issue #4's blast-radius graph builder once it lands —
    # deliberately `None` until then. We do not predict or estimate this
    # ourselves; a fabricated number here would be exactly the kind of
    # invented statistic the project must never produce.
    blast_radius: dict[str, Any] | None = None

    status: ScenarioStatus = ScenarioStatus.PENDING
    backend_ref: str | None = None        # Chaos Mesh CR name, or simulator fault-rule id
    live_status: dict[str, Any] | None = None  # last-observed status straight from the backend
    error: str | None = None

    created_at: str = Field(default_factory=_now)
    started_at: str | None = None
    ended_at: str | None = None

    def touch_status(self, status: ScenarioStatus, *, error: str | None = None) -> None:
        self.status = status
        if error is not None:
            self.error = error
        now = _now()
        if status == ScenarioStatus.RUNNING and self.started_at is None:
            self.started_at = now
        if status in (ScenarioStatus.STOPPED, ScenarioStatus.COMPLETED, ScenarioStatus.FAILED):
            self.ended_at = now

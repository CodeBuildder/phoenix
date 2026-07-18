"""
Chaos Injection Engine — scenario orchestration
Copyright (c) 2026 Kaushikkumaran

`ScenarioEngine` is the one control surface the M1 issue calls for: it takes
a `ScenarioCreateRequest`, validates and translates its domain-specific
`target`/`params` against either Chaos Mesh's real CRD shapes or the
simulator's real `/faults` shape, applies it to that backend, and tracks the
resulting `Scenario` through a lifecycle whose every transition is a genuine
event — never a guess about what's happening, always a direct readout from
the backend that's actually running the fault.

A background sweeper periodically asks each running scenario's backend "are
you still going?" — that's how `chaos.scenario.completed` gets published the
moment a Chaos Mesh experiment or simulator fault rule runs its course,
rather than on a timer that might drift from reality.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

import chaos_mesh as chaos_mesh_module
from chaos_mesh import ChaosMeshClient, chaos_mesh as default_chaos_mesh
from config import config
from events import Severity, publish_event
from models import (
    ChaosMeshFaultType,
    K8sTarget,
    Scenario,
    ScenarioCreateRequest,
    ScenarioDomain,
    ScenarioStatus,
    SimulatorFaultType,
    SimulatorTarget,
)
from simulator_client import SimulatorClient, simulator as default_simulator
from store import ScenarioStore, store as default_store

log = structlog.get_logger()

COMPONENT = "chaos.scenario"


class ScenarioNotFoundError(Exception):
    pass


class InvalidScenarioStateError(Exception):
    pass


class BackendError(Exception):
    """The scenario's request was well-formed, but applying/stopping/querying
    it against its real backend (Chaos Mesh or the simulator) failed."""


def _parse_enum(enum_cls: Any, value: str, label: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError:
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(f"unknown {label} fault_type '{value}' — expected one of: {valid}") from None


class ScenarioEngine:
    def __init__(self, *, store: ScenarioStore, chaos_mesh: ChaosMeshClient, simulator: SimulatorClient,
                 sweep_interval_seconds: float | None = None) -> None:
        self._store = store
        self._chaos_mesh = chaos_mesh
        self._simulator = simulator
        self._sweep_interval = sweep_interval_seconds if sweep_interval_seconds is not None else config.SWEEP_INTERVAL_SECONDS
        self._sweeper_task: asyncio.Task | None = None

    # -- lifecycle of the engine itself (not scenarios) --------------------

    def start_sweeper(self) -> None:
        if self._sweeper_task is None:
            self._sweeper_task = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self) -> None:
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
            self._sweeper_task = None

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_interval)
            for scenario in await self._store.list(status=ScenarioStatus.RUNNING):
                try:
                    await self._sync(scenario)
                except Exception as exc:
                    log.warning("chaos_sweep_sync_failed", scenario_id=scenario.id, error=str(exc))

    # -- request validation / translation -----------------------------------

    def _translate_chaos_mesh(self, req: ScenarioCreateRequest) -> tuple[ChaosMeshFaultType, K8sTarget, Any]:
        fault_type = _parse_enum(ChaosMeshFaultType, req.fault_type, "chaos_mesh")
        target = K8sTarget.model_validate(req.target)
        params = chaos_mesh_module.parse_params(fault_type, req.params)
        return fault_type, target, params

    def _translate_simulator(self, req: ScenarioCreateRequest) -> tuple[SimulatorFaultType, SimulatorTarget]:
        fault_type = _parse_enum(SimulatorFaultType, req.fault_type, "simulator")
        target = SimulatorTarget.model_validate(req.target)
        return fault_type, target

    # -- public API ----------------------------------------------------------

    async def start(self, req: ScenarioCreateRequest) -> Scenario:
        """Validate, record, and apply a scenario to its real backend.
        Raises `ValueError`/`pydantic.ValidationError` for malformed
        requests (-> 422, nothing recorded) and `BackendError` if the
        backend rejects an otherwise well-formed request (-> 502, the
        scenario is recorded as `failed` so the failure is itself visible)."""
        if req.domain == ScenarioDomain.CHAOS_MESH:
            fault_type, target, params = self._translate_chaos_mesh(req)
        else:
            fault_type, target = self._translate_simulator(req)
            params = req.params

        scenario = Scenario(
            name=req.name,
            correlation_id=req.correlation_id,
            domain=req.domain,
            fault_type=fault_type.value,
            target=target.model_dump(),
            duration_seconds=req.duration_seconds,
            params=req.params,
        )
        await self._store.put(scenario)
        publish_event(
            "chaos.scenario.created",
            severity=Severity.INFO,
            component=COMPONENT,
            payload={
                "scenario_id": scenario.id,
                "name": scenario.name,
                "domain": scenario.domain.value,
                "fault_type": scenario.fault_type,
                "target": scenario.target,
                "duration_seconds": scenario.duration_seconds,
            },
            caused_by=scenario.id,
            reason="scenario requested",
        )

        try:
            if req.domain == ScenarioDomain.CHAOS_MESH:
                backend_ref, _manifest = await self._chaos_mesh.apply(
                    scenario.id, fault_type, target, req.duration_seconds, params,
                )
            else:
                rule = await self._simulator.register_fault(
                    fault_type, target, req.probability, req.duration_seconds, req.params,
                )
                backend_ref = rule["id"]
        except Exception as exc:
            scenario.touch_status(ScenarioStatus.FAILED, error=str(exc))
            await self._store.put(scenario)
            publish_event(
                "chaos.scenario.failed",
                severity=Severity.HIGH,
                component=COMPONENT,
                payload={"scenario_id": scenario.id, "stage": "apply", "error": str(exc)},
                caused_by=scenario.id,
                reason=str(exc),
            )
            raise BackendError(str(exc)) from exc

        scenario.backend_ref = backend_ref
        scenario.touch_status(ScenarioStatus.RUNNING)
        await self._store.put(scenario)
        publish_event(
            "chaos.scenario.started",
            severity=Severity.MEDIUM,
            component=COMPONENT,
            payload={"scenario_id": scenario.id, "domain": scenario.domain.value, "backend_ref": backend_ref},
            caused_by=scenario.id,
            reason="applied to backend",
        )
        return scenario

    async def stop(self, scenario_id: str) -> Scenario:
        """Explicitly tear a running scenario down before its natural end —
        deletes the Chaos Mesh CR, or clears the simulator fault rule."""
        scenario = await self._require(scenario_id)
        if scenario.status != ScenarioStatus.RUNNING:
            raise InvalidScenarioStateError(f"scenario '{scenario_id}' is {scenario.status.value}, not running")

        scenario.touch_status(ScenarioStatus.STOPPING)
        await self._store.put(scenario)

        try:
            if scenario.domain == ScenarioDomain.CHAOS_MESH:
                fault_type = ChaosMeshFaultType(scenario.fault_type)
                target = K8sTarget.model_validate(scenario.target)
                await self._chaos_mesh.delete(fault_type, scenario.backend_ref, target.namespace)
            else:
                await self._simulator.clear_fault(scenario.backend_ref)
        except Exception as exc:
            scenario.touch_status(ScenarioStatus.FAILED, error=str(exc))
            await self._store.put(scenario)
            publish_event(
                "chaos.scenario.failed",
                severity=Severity.HIGH,
                component=COMPONENT,
                payload={"scenario_id": scenario.id, "stage": "stop", "error": str(exc)},
                caused_by=scenario.id,
                reason=str(exc),
            )
            raise BackendError(str(exc)) from exc

        scenario.touch_status(ScenarioStatus.STOPPED)
        await self._store.put(scenario)
        publish_event(
            "chaos.scenario.stopped",
            severity=Severity.INFO,
            component=COMPONENT,
            payload={"scenario_id": scenario.id},
            caused_by=scenario.id,
            reason="stopped on request",
        )
        return scenario

    async def get(self, scenario_id: str, *, refresh: bool = True) -> Scenario:
        scenario = await self._require(scenario_id)
        if refresh and scenario.status == ScenarioStatus.RUNNING:
            scenario = await self._sync(scenario)
        return scenario

    async def list(self, *, status: ScenarioStatus | None = None) -> list[Scenario]:
        return await self._store.list(status=status)

    async def remove(self, scenario_id: str) -> None:
        scenario = await self._require(scenario_id)
        if scenario.status == ScenarioStatus.RUNNING:
            raise InvalidScenarioStateError(f"scenario '{scenario_id}' is still running — stop it first")
        await self._store.remove(scenario_id)

    # -- internals ------------------------------------------------------------

    async def _require(self, scenario_id: str) -> Scenario:
        scenario = await self._store.get(scenario_id)
        if scenario is None:
            raise ScenarioNotFoundError(f"scenario '{scenario_id}' not found")
        return scenario

    async def _sync(self, scenario: Scenario) -> Scenario:
        """Ask the scenario's real backend whether it's still active. This —
        not a timer — is what marks a scenario `completed` and emits the
        event for it; the engine never infers completion from `duration`
        elapsing, since the backend is the only authority on whether the
        fault actually ran that long (Chaos Mesh experiments and simulator
        fault rules can both be cleared out from under us by other actors)."""
        if scenario.status != ScenarioStatus.RUNNING:
            return scenario

        if scenario.domain == ScenarioDomain.CHAOS_MESH:
            fault_type = ChaosMeshFaultType(scenario.fault_type)
            target = K8sTarget.model_validate(scenario.target)
            cr = await self._chaos_mesh.get(fault_type, scenario.backend_ref, target.namespace)
            if cr is None:
                await self._mark_completed(scenario, reason="Chaos Mesh experiment no longer exists — it ran its course")
                return scenario
            scenario.live_status = chaos_mesh_module.summarize_status(cr.get("status"))
        else:
            rule = await self._simulator.get_fault(scenario.backend_ref)
            if rule is None:
                await self._mark_completed(scenario, reason="simulator fault rule expired or was cleared")
                return scenario
            scenario.live_status = {"hits": rule.get("hits"), "expires_at": rule.get("expires_at")}

        await self._store.put(scenario)
        return scenario

    async def _mark_completed(self, scenario: Scenario, *, reason: str) -> None:
        scenario.touch_status(ScenarioStatus.COMPLETED)
        await self._store.put(scenario)
        publish_event(
            "chaos.scenario.completed",
            severity=Severity.INFO,
            component=COMPONENT,
            payload={"scenario_id": scenario.id},
            caused_by=scenario.id,
            reason=reason,
        )


engine = ScenarioEngine(store=default_store, chaos_mesh=default_chaos_mesh, simulator=default_simulator)

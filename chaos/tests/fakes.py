"""
Test doubles for the Chaos Injection Engine's two backends.
Copyright (c) 2026 Kaushikkumaran

`ScenarioEngine` is built to take its `chaos_mesh`/`simulator` clients as
constructor arguments precisely so tests can swap in faithful in-memory
stand-ins instead of a live cluster or a live simulator deployment — these
implement the same create/get/delete (and register/get/clear) semantics the
real backends do, so the engine's *orchestration logic* (state transitions,
event ordering, error handling) gets genuinely exercised. They're a stand-in
for the backend, never a stand-in for what the engine itself reports — the
engine's output is exactly what these fakes' real, traceable state produces.
"""

from __future__ import annotations

from typing import Any

import chaos_mesh as chaos_mesh_module
from models import ChaosMeshFaultType, K8sTarget, SimulatorFaultType, SimulatorTarget


class FakeChaosMeshClient:
    """In-memory stand-in for the chaos-mesh.org CustomObjectsApi: apply
    builds the same manifest the real client would and stores it; get/delete
    read and mutate that same store, so a test can inspect exactly what the
    engine asked for and how it reacted to what came back."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.apply_calls: list[tuple[Any, ...]] = []
        self.delete_calls: list[tuple[Any, ...]] = []

    async def apply(self, scenario_id: str, fault_type: ChaosMeshFaultType, target: K8sTarget,
                    duration_seconds: float | None, params: Any) -> tuple[str, dict[str, Any]]:
        manifest = chaos_mesh_module.build_manifest(scenario_id, fault_type, target, duration_seconds, params)
        name = manifest["metadata"]["name"]
        self.objects[(target.namespace, name)] = {
            **manifest,
            "status": {"experiment": {"phase": "Running"}},
        }
        self.apply_calls.append((scenario_id, fault_type, target, duration_seconds, params))
        return name, manifest

    async def get(self, fault_type: ChaosMeshFaultType, name: str, namespace: str) -> dict[str, Any] | None:
        return self.objects.get((namespace, name))

    async def delete(self, fault_type: ChaosMeshFaultType, name: str, namespace: str) -> None:
        self.delete_calls.append((fault_type, name, namespace))
        self.objects.pop((namespace, name), None)


class ExplodingChaosMeshClient(FakeChaosMeshClient):
    """Always fails to apply — exercises the engine's failure path (scenario
    -> failed, `chaos.scenario.failed` published, BackendError raised)."""

    async def apply(self, *args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("admission webhook denied the request")


class FakeSimulatorClient:
    """In-memory stand-in for phoenix-sim's /faults API — register/get/clear
    operate on a real dict of rules, mirroring the simulator's own shape
    (id, fault_type, hits, expires_at, ...) closely enough that the engine's
    `_sync` / `live_status` logic is genuinely exercised."""

    def __init__(self) -> None:
        self.rules: dict[str, dict[str, Any]] = {}
        self._next = 1
        self.register_calls: list[tuple[Any, ...]] = []
        self.clear_calls: list[str] = []

    async def register_fault(self, fault_type: SimulatorFaultType, target: SimulatorTarget,
                             probability: float, duration_seconds: float | None, params: dict[str, Any]) -> dict[str, Any]:
        rule_id = f"fault-fake{self._next:04d}"
        self._next += 1
        rule = {
            "id": rule_id,
            "fault_type": fault_type.value,
            "resource_type": target.resource_type,
            "operation": target.operation,
            "probability": probability,
            "params": params,
            "created_at": "2026-01-01T00:00:00+00:00",
            "expires_at": None,
            "hits": 0,
        }
        self.rules[rule_id] = rule
        self.register_calls.append((fault_type, target, probability, duration_seconds, params))
        return rule

    async def get_fault(self, fault_id: str) -> dict[str, Any] | None:
        return self.rules.get(fault_id)

    async def clear_fault(self, fault_id: str) -> None:
        self.clear_calls.append(fault_id)
        self.rules.pop(fault_id, None)


class ExplodingSimulatorClient(FakeSimulatorClient):
    async def register_fault(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulator unreachable")

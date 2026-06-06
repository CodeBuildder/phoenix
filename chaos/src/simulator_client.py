"""
Chaos Injection Engine — Provisioning Simulator client
Copyright (c) 2026 Kaushikkumaran

A small httpx wrapper around phoenix-sim's `/faults` API (issue #1) — the
"simulator faults triggered via the Provisioning Simulator's fault-injection
endpoints" half of the M1 issue #2 control surface. It registers, queries,
and clears *real* fault rules on the live simulator over HTTP; nothing about
a simulator-domain scenario is computed or mirrored locally — the simulator
remains the single source of truth for its own fault state (`hits`,
`expires_at`, …), exactly as a wrapper should behave.
"""

from __future__ import annotations

from typing import Any

import httpx

from config import config
from models import SimulatorFaultType, SimulatorTarget


class SimulatorClientError(Exception):
    """The simulator's /faults API returned something the engine can't use —
    surfaced to callers as a backend error (502), same as a Chaos Mesh
    apply/delete failure."""


class SimulatorClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or config.SIMULATOR_URL).rstrip("/")

    async def register_fault(
        self,
        fault_type: SimulatorFaultType,
        target: SimulatorTarget,
        probability: float,
        duration_seconds: float | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /faults — returns the registered FaultRule. Its `id` becomes
        the scenario's `backend_ref`."""
        body: dict[str, Any] = {"fault_type": fault_type.value, "probability": probability, "params": params}
        if target.resource_type is not None:
            body["resource_type"] = target.resource_type
        if target.operation is not None:
            body["operation"] = target.operation
        if duration_seconds is not None:
            body["duration_seconds"] = duration_seconds

        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as http:
            response = await http.post("/faults", json=body)
        if response.status_code != 201:
            raise SimulatorClientError(f"simulator rejected fault registration ({response.status_code}): {response.text}")
        return response.json()

    async def get_fault(self, fault_id: str) -> dict[str, Any] | None:
        """The simulator has no get-by-id route, so list (cheap — in-memory,
        small N) and find the match. Returns the genuine rule the simulator
        is tracking — including its real `hits`/`expires_at` — or `None` if
        it has expired or been cleared."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as http:
            response = await http.get("/faults")
        if response.status_code != 200:
            raise SimulatorClientError(f"simulator rejected fault listing ({response.status_code}): {response.text}")
        for rule in response.json().get("rules", []):
            if rule.get("id") == fault_id:
                return rule
        return None

    async def clear_fault(self, fault_id: str) -> None:
        """DELETE /faults/{id} — idempotent: a rule that's already gone
        (expired naturally between our last sync and this call) isn't an error."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as http:
            response = await http.delete(f"/faults/{fault_id}")
        if response.status_code not in (204, 404):
            raise SimulatorClientError(f"simulator rejected fault clear ({response.status_code}): {response.text}")


simulator = SimulatorClient()

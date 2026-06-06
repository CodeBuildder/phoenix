"""
Test doubles for the Fault Library & Taxonomy Classifier's one dependency.
Copyright (c) 2026 Kaushikkumaran

`routers.library` reaches `/chaos` through the module-level `chaos_client.chaos`
singleton precisely so a test can swap it for something that hands back
exactly the scenario records a test wants to exercise — without a live
cluster or a live `/chaos` deployment. `FakeChaosClient.list_scenarios`
returns *exactly* what it's seeded with: nothing here adds, infers, or
reshapes a single field beyond what `ChaosClient.list_scenarios` itself
would hand back from a real `/chaos` response body.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class FakeChaosClient:
    """In-memory stand-in for `chaos_client.ChaosClient` — seed it with
    scenario-shaped dicts (see `scenario()` below) and it reports back
    precisely those, the same "real records, fake transport" posture
    chaos/tests/fakes.py takes toward Chaos Mesh and the simulator."""

    def __init__(self, scenarios: list[dict[str, Any]] | None = None) -> None:
        self.scenarios: list[dict[str, Any]] = list(scenarios) if scenarios else []
        self.list_calls = 0

    async def list_scenarios(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return list(self.scenarios)


def scenario(
    *,
    domain: str = "chaos_mesh",
    fault_type: str = "pod_kill",
    target: dict[str, Any] | None = None,
    status: str = "completed",
    started: bool = True,
) -> dict[str, Any]:
    """
    Builds one scenario record in exactly the shape `GET /scenarios` on
    `/chaos` returns (see chaos/src/models.py's `Scenario`) — the minimum
    set of fields `aggregator.build_rankings` actually reads
    (`domain`, `fault_type`, `target`, `started_at`). Defaults describe a
    scenario that genuinely ran and finished; `started=False` produces the
    "recorded but never launched" shape `_actually_ran` is built to exclude.
    """
    if target is None:
        target = (
            {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}}
            if domain == "chaos_mesh"
            else {"resource_type": "volume", "operation": "create"}
        )
    return {
        "id": f"scn-{uuid4().hex[:10]}",
        "name": f"test-{fault_type}",
        "domain": domain,
        "fault_type": fault_type,
        "target": target,
        "status": status,
        "started_at": "2026-06-01T00:00:00+00:00" if started else None,
    }

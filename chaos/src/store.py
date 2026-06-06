"""
Chaos Injection Engine — in-memory scenario store
Copyright (c) 2026 Kaushikkumaran

Mirrors phoenix-sim's ResourceStore: in-memory state behind a small
repository (issue #1 explicitly allowed this, and issue #2 inherits the same
"in-memory or lightweight persisted" latitude), so swapping in persistence
later only touches this one module.
"""

from __future__ import annotations

import asyncio

from models import Scenario, ScenarioStatus


class ScenarioStore:
    def __init__(self) -> None:
        self._scenarios: dict[str, Scenario] = {}
        self._lock = asyncio.Lock()

    async def put(self, scenario: Scenario) -> Scenario:
        async with self._lock:
            self._scenarios[scenario.id] = scenario
        return scenario

    async def get(self, scenario_id: str) -> Scenario | None:
        return self._scenarios.get(scenario_id)

    async def list(self, status: ScenarioStatus | None = None) -> list[Scenario]:
        values = list(self._scenarios.values())
        if status is not None:
            values = [s for s in values if s.status == status]
        return sorted(values, key=lambda s: s.created_at)

    async def remove(self, scenario_id: str) -> None:
        async with self._lock:
            self._scenarios.pop(scenario_id, None)

    async def clear(self) -> None:
        """Reset to empty — used between test cases."""
        async with self._lock:
            self._scenarios.clear()


store = ScenarioStore()

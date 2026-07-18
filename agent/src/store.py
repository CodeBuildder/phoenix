"""
Phoenix Agent — in-memory run store
Copyright (c) 2026 Kaushikkumaran

One AgentRun per scenario. Thread-safe via asyncio.Lock.
"""

from __future__ import annotations

import asyncio
from typing import Any

from models import AgentNode, AgentRun


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._lock = asyncio.Lock()

    async def put(self, run: AgentRun) -> AgentRun:
        run.updated_at = _now()
        async with self._lock:
            self._runs[run.scenario_id] = run
        return run

    async def get(self, scenario_id: str) -> AgentRun | None:
        return self._runs.get(scenario_id)

    async def list(self) -> list[AgentRun]:
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)

    async def update(self, scenario_id: str, **kwargs: Any) -> AgentRun | None:
        async with self._lock:
            run = self._runs.get(scenario_id)
            if run is None:
                return None
            for k, v in kwargs.items():
                setattr(run, k, v)
            run.updated_at = _now()
        return run

    async def transition(self, scenario_id: str, node: AgentNode) -> AgentRun | None:
        return await self.update(scenario_id, node=node)

    async def has(self, scenario_id: str) -> bool:
        return scenario_id in self._runs


store = RunStore()

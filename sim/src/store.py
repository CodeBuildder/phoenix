"""
Provisioning Simulator — in-memory resource store
Copyright (c) 2026 Kaushikkumaran

Issue #1 explicitly allows "in-memory or lightweight persisted state" — this
is in-memory, kept behind a small repository so swapping in persistence later
(e.g. SQLite, for state to survive restarts across long-running scenarios)
only touches this one module.
"""

from __future__ import annotations

import asyncio

from models import Resource, ResourceType


class ResourceStore:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._lock = asyncio.Lock()

    async def put(self, resource: Resource) -> Resource:
        async with self._lock:
            self._resources[resource.id] = resource
        return resource

    async def get(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    async def list(self, resource_type: ResourceType | None = None) -> list[Resource]:
        values = list(self._resources.values())
        if resource_type is not None:
            values = [r for r in values if r.type == resource_type]
        return sorted(values, key=lambda r: r.created_at)

    async def count(self, resource_type: ResourceType) -> int:
        return sum(1 for r in self._resources.values() if r.type == resource_type)

    async def remove(self, resource_id: str) -> None:
        async with self._lock:
            self._resources.pop(resource_id, None)

    async def clear(self) -> None:
        """Reset to empty — used between test cases and (later) between
        chaos-engine scenario runs that want a clean slate."""
        async with self._lock:
            self._resources.clear()

    async def snapshot(self) -> dict[str, list[Resource]]:
        """"What exists right now", grouped by resource type — backs the
        dashboard's live-state view."""
        grouped: dict[str, list[Resource]] = {rt.value: [] for rt in ResourceType}
        for resource in await self.list():
            grouped[resource.type.value].append(resource)
        return grouped


store = ResourceStore()

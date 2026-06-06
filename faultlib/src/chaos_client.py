"""
Fault Library & Taxonomy Classifier — Chaos Injection Engine client
Copyright (c) 2026 Kaushikkumaran

A small httpx wrapper around `/chaos`'s `GET /scenarios` (issue #2) — the
*only* source of failure history this service ever consults. Every scenario
record it returns is whatever `/chaos` is currently storing about a real
launch against a real backend (Chaos Mesh or the simulator); this client
neither caches it past the request nor reshapes it beyond what
`aggregator.py` needs to tally — same "wrapper, not a mirror" posture
chaos/src/simulator_client.py takes toward phoenix-sim.
"""

from __future__ import annotations

from typing import Any

import httpx

from config import config


class ChaosClientError(Exception):
    """`/chaos` returned something this service can't use — surfaced to
    callers as a backend error (502), the same shape `/chaos` itself uses
    when *its* backends misbehave."""


class ChaosClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or config.CHAOS_URL).rstrip("/")

    async def list_scenarios(self) -> list[dict[str, Any]]:
        """GET /scenarios — every scenario `/chaos` has ever recorded,
        exactly as it reports them (id, domain, fault_type, target, status,
        started_at, …). No filtering happens here; `aggregator.py` decides
        which of these real records actually represent induced failures."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as http:
            response = await http.get("/scenarios")
        if response.status_code != 200:
            raise ChaosClientError(f"chaos engine rejected scenario listing ({response.status_code}): {response.text}")
        return response.json().get("scenarios", [])


chaos = ChaosClient()

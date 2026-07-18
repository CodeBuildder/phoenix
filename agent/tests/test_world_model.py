import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import world_model


class FakeClient:
    requests = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, json):
        self.requests.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))


@pytest.mark.asyncio
async def test_finding_preserves_correlation_and_provenance(monkeypatch):
    FakeClient.requests = []
    monkeypatch.setattr(world_model, "_WM_URL", "http://world-model.test")
    monkeypatch.setattr(world_model.httpx, "AsyncClient", FakeClient)

    await world_model.post_finding(
        scenario_id="scn-1", node="verify", fault_type="pod_kill",
        namespace="phoenix-system", service="phoenix-sim", severity="high",
        outcome="verified", payload={"mttr_seconds": 12},
        correlation_id="case-argus-phoenix-1", provenance="live_chaos",
    )

    _, body = FakeClient.requests[0]
    assert body["correlation_id"] == "case-argus-phoenix-1"
    assert body["payload"]["provenance"] == "live_chaos"
    assert body["payload"]["scenario_id"] == "scn-1"

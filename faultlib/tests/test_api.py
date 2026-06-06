"""
HTTP contract tests for the Fault Library & Taxonomy Classifier API.
Copyright (c) 2026 Kaushikkumaran

Exercises the three endpoints end to end through `TestClient` — `/catalog`
and `/classify` need nothing beyond the static library (no fakes required);
`/rankings` swaps in `FakeChaosClient` so the test controls exactly which
"real" `/chaos` history the aggregation runs over, the same
swap-the-backend-at-the-router pattern chaos/tests/test_api.py uses.
"""

import pytest
from fastapi.testclient import TestClient

import routers.library as library_router
from chaos_client import ChaosClientError
from .fakes import FakeChaosClient, scenario
from main import app

client = TestClient(app)


def _swap_chaos_client(monkeypatch, fake: FakeChaosClient | None = None) -> FakeChaosClient:
    fake = fake if fake is not None else FakeChaosClient()
    monkeypatch.setattr(library_router, "chaos", fake)
    return fake


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "phoenix-faultlib"


class TestCatalogEndpoint:
    def test_lists_every_entry_by_default(self):
        response = client.get("/catalog")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == len(body["entries"]) == 8  # 4 chaos_mesh + 4 simulator

    def test_filters_by_domain(self):
        response = client.get("/catalog", params={"domain": "simulator"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert all(e["domain"] == "simulator" for e in body["entries"])

    def test_get_single_entry(self):
        response = client.get("/catalog/chaos_mesh/pod_kill")
        assert response.status_code == 200
        body = response.json()
        assert body["fault_type"] == "pod_kill"
        assert body["taxonomy_category"] == "cascading"
        assert body["typical_symptoms"]

    def test_unknown_entry_is_404_not_a_fabricated_stand_in(self):
        response = client.get("/catalog/chaos_mesh/does-not-exist")
        assert response.status_code == 404


class TestClassifyEndpoint:
    def test_classifies_a_known_fault_type(self):
        response = client.post("/classify", params={"domain": "simulator", "fault_type": "quota_limit"})
        assert response.status_code == 200
        body = response.json()
        assert body["taxonomy_category"] == "quota-limit"
        assert body["rationale"]

    def test_unknown_fault_type_is_404_not_a_guess(self):
        response = client.post("/classify", params={"domain": "chaos_mesh", "fault_type": "made-up"})
        assert response.status_code == 404
        assert "no fault library entry" in response.json()["detail"]


class TestRankingsEndpoint:
    def test_empty_chaos_history_yields_empty_rankings(self, monkeypatch):
        fake = _swap_chaos_client(monkeypatch, FakeChaosClient(scenarios=[]))
        response = client.get("/rankings")
        assert response.status_code == 200
        body = response.json()
        assert body["rankings"] == []
        assert body["scenarios_considered"] == 0
        assert fake.list_calls == 1

    def test_rankings_reflect_real_chaos_history(self, monkeypatch):
        records = [
            scenario(domain="chaos_mesh", fault_type="pod_kill"),
            scenario(domain="chaos_mesh", fault_type="pod_kill"),
            scenario(domain="simulator", fault_type="quota_limit"),
        ]
        _swap_chaos_client(monkeypatch, FakeChaosClient(scenarios=records))

        response = client.get("/rankings")
        assert response.status_code == 200
        body = response.json()
        assert body["scenarios_considered"] == 3

        by_component = {r["component"]: r for r in body["rankings"]}
        assert by_component["phoenix-system/app=phoenix-sim"]["total"] == 2
        assert by_component["phoenix-system/app=phoenix-sim"]["tally"]["cascading"] == 2
        assert by_component["volume/create"]["tally"]["quota_limit"] == 1

    def test_rankings_are_recomputed_live_on_every_call(self, monkeypatch):
        """Calling /rankings twice with different backend state in between
        must yield different results — proof there's no caching anywhere
        between the live `/chaos` history and what this endpoint reports."""
        fake = _swap_chaos_client(monkeypatch, FakeChaosClient(scenarios=[]))

        first = client.get("/rankings").json()
        assert first["scenarios_considered"] == 0

        fake.scenarios.append(scenario(domain="chaos_mesh", fault_type="pod_kill"))
        second = client.get("/rankings").json()
        assert second["scenarios_considered"] == 1
        assert second["generated_at"] != first["generated_at"] or second != first

    def test_backend_error_surfaces_as_502(self, monkeypatch):
        class ExplodingChaosClient(FakeChaosClient):
            async def list_scenarios(self):
                raise ChaosClientError("chaos engine unreachable")

        _swap_chaos_client(monkeypatch, ExplodingChaosClient())
        response = client.get("/rankings")
        assert response.status_code == 502
        assert "chaos engine unreachable" in response.json()["detail"]

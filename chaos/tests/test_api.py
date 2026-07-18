"""
Tests for the Chaos Injection Engine's HTTP contract.
Copyright (c) 2026 Kaushikkumaran

Checks status codes, validation, and response shapes — the surface M2's agent
and M3's dashboard integrate against. The global `engine` singleton backs
`app` directly (as it does in production); each test swaps its store and
backend clients for fresh fakes via monkeypatch, so requests genuinely flow
client -> FastAPI -> engine -> (fake) backend and back, with no live cluster
or simulator required, and no canned responses anywhere in the chain.
"""

from fastapi.testclient import TestClient

from engine import engine
from main import app
from store import ScenarioStore

from .fakes import ExplodingChaosMeshClient, FakeChaosMeshClient, FakeSimulatorClient

client = TestClient(app)


def _swap_backends(monkeypatch, *, chaos_mesh=None, simulator=None):
    monkeypatch.setattr(engine, "_store", ScenarioStore())
    monkeypatch.setattr(engine, "_chaos_mesh", chaos_mesh if chaos_mesh is not None else FakeChaosMeshClient())
    monkeypatch.setattr(engine, "_simulator", simulator if simulator is not None else FakeSimulatorClient())


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "phoenix-chaos"


CHAOS_MESH_PAYLOAD = {
    "name": "kill-sim-pod",
    "domain": "chaos_mesh",
    "fault_type": "pod_kill",
    "target": {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}},
    "duration_seconds": 30,
}

SIMULATOR_PAYLOAD = {
    "name": "inject-volume-latency",
    "domain": "simulator",
    "fault_type": "latency",
    "target": {"resource_type": "volume", "operation": "create"},
    "duration_seconds": 60,
    "probability": 0.5,
    "params": {"min_ms": 200, "max_ms": 500},
}


class TestCreateScenario:
    def test_chaos_mesh_scenario_returns_201_and_running(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        response = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "running"
        assert body["domain"] == "chaos_mesh"
        assert body["backend_ref"] == "phoenix-chaos-" + body["id"]
        assert body["blast_radius"] is None
        # the fake genuinely built and stored a PodChaos manifest for this scenario
        assert len(fake.apply_calls) == 1
        assert fake.objects[("phoenix-system", body["backend_ref"])]["spec"]["action"] == "pod-kill"

    def test_simulator_scenario_returns_201_and_running(self, monkeypatch):
        fake = FakeSimulatorClient()
        _swap_backends(monkeypatch, simulator=fake)

        response = client.post("/scenarios", json=SIMULATOR_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "running"
        assert body["domain"] == "simulator"
        assert body["backend_ref"] in fake.rules
        assert fake.rules[body["backend_ref"]]["resource_type"] == "volume"

    def test_scenario_preserves_explicit_correlation_id(self, monkeypatch):
        _swap_backends(monkeypatch, simulator=FakeSimulatorClient())
        response = client.post("/scenarios", json={**SIMULATOR_PAYLOAD, "correlation_id": "case-argus-phoenix-1"})
        assert response.status_code == 201
        assert response.json()["correlation_id"] == "case-argus-phoenix-1"

    def test_unknown_fault_type_returns_422_and_records_nothing(self, monkeypatch):
        _swap_backends(monkeypatch)
        response = client.post("/scenarios", json={**CHAOS_MESH_PAYLOAD, "fault_type": "black_hole"})
        assert response.status_code == 422
        assert "unknown chaos_mesh fault_type" in response.json()["detail"]
        assert client.get("/scenarios").json()["total"] == 0

    def test_malformed_target_returns_422_and_records_nothing(self, monkeypatch):
        _swap_backends(monkeypatch)
        bad_target = {**CHAOS_MESH_PAYLOAD, "target": {"namespace": "phoenix-system", "mode": "fixed"}}
        response = client.post("/scenarios", json=bad_target)
        assert response.status_code == 422
        assert "target.value is required" in response.json()["detail"]
        assert client.get("/scenarios").json()["total"] == 0

    def test_missing_required_field_returns_422_from_pydantic(self, monkeypatch):
        _swap_backends(monkeypatch)
        response = client.post("/scenarios", json={"domain": "chaos_mesh", "fault_type": "pod_kill"})
        assert response.status_code == 422  # FastAPI's own request-body validation — `name` is required

    def test_backend_failure_returns_502_and_records_failed_scenario(self, monkeypatch):
        _swap_backends(monkeypatch, chaos_mesh=ExplodingChaosMeshClient())
        response = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD)
        assert response.status_code == 502
        assert "admission webhook denied" in response.json()["detail"]

        listed = client.get("/scenarios").json()["scenarios"]
        assert len(listed) == 1
        assert listed[0]["status"] == "failed"
        assert "admission webhook denied" in listed[0]["error"]


class TestReadScenarios:
    def test_get_unknown_scenario_404(self, monkeypatch):
        _swap_backends(monkeypatch)
        response = client.get("/scenarios/scn-doesnotexist")
        assert response.status_code == 404

    def test_list_reflects_what_was_created(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        names = {client.post("/scenarios", json={**CHAOS_MESH_PAYLOAD, "name": n}).json()["name"] for n in ("a", "b")}
        response = client.get("/scenarios")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {s["name"] for s in body["scenarios"]} == names

    def test_list_filters_by_status_query_param(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()
        client.post(f"/scenarios/{created['id']}/stop")

        running = client.get("/scenarios", params={"status": "running"}).json()
        stopped = client.get("/scenarios", params={"status": "stopped"}).json()
        assert running["total"] == 0
        assert stopped["total"] == 1
        assert stopped["scenarios"][0]["id"] == created["id"]

    def test_get_returns_refreshed_live_status_for_running_scenario(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()
        fake.objects[("phoenix-system", created["backend_ref"])]["status"] = {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "AllInjected", "status": "True"}],
        }

        refreshed = client.get(f"/scenarios/{created['id']}").json()
        assert refreshed["live_status"] == {
            "experiment": {"phase": "Running"},
            "conditions": [{"type": "AllInjected", "status": "True"}],
        }


class TestStopAndRemove:
    def test_stop_then_remove_full_lifecycle(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()

        stopped = client.post(f"/scenarios/{created['id']}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert ("phoenix-system", created["backend_ref"]) not in fake.objects

        removed = client.delete(f"/scenarios/{created['id']}")
        assert removed.status_code == 204
        assert client.get(f"/scenarios/{created['id']}").status_code == 404

    def test_stop_unknown_scenario_404(self, monkeypatch):
        _swap_backends(monkeypatch)
        assert client.post("/scenarios/scn-ghost/stop").status_code == 404

    def test_stop_already_stopped_scenario_409(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()
        client.post(f"/scenarios/{created['id']}/stop")

        again = client.post(f"/scenarios/{created['id']}/stop")
        assert again.status_code == 409
        assert "not running" in again.json()["detail"]

    def test_remove_while_running_409(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)

        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()
        response = client.delete(f"/scenarios/{created['id']}")
        assert response.status_code == 409
        assert "still running" in response.json()["detail"]

    def test_remove_unknown_scenario_404(self, monkeypatch):
        _swap_backends(monkeypatch)
        assert client.delete("/scenarios/scn-ghost").status_code == 404

    def test_stop_backend_failure_returns_502(self, monkeypatch):
        fake = FakeChaosMeshClient()
        _swap_backends(monkeypatch, chaos_mesh=fake)
        created = client.post("/scenarios", json=CHAOS_MESH_PAYLOAD).json()

        async def _exploding_delete(*args, **kwargs):
            raise RuntimeError("finalizer stuck")
        fake.delete = _exploding_delete

        response = client.post(f"/scenarios/{created['id']}/stop")
        assert response.status_code == 502
        assert "finalizer stuck" in response.json()["detail"]

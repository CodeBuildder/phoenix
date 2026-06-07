"""
Tests for the FastAPI HTTP endpoints.
Copyright (c) 2026 Kaushikkumaran

Each test monkeypatches the router's k8s and hubble singletons so no live
cluster or Hubble relay is needed.
"""

import pytest
from anyio import from_thread
from fastapi.testclient import TestClient

from .fakes import FakeHubbleClient, FakeK8sClient, flow, pod, service
from main import app
import routers.graph as graph_router


@pytest.fixture
def client():
    return TestClient(app)


def _swap_clients(k8s, hubble):
    """Replace the router-level singletons and return a restorer."""
    original_k8s = graph_router.k8s
    original_hubble = graph_router.hubble
    graph_router.k8s = k8s
    graph_router.hubble = hubble

    def restore():
        graph_router.k8s = original_k8s
        graph_router.hubble = original_hubble

    return restore


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestTopologyEndpoint:
    def test_empty_cluster_returns_empty_graph(self, client):
        restore = _swap_clients(FakeK8sClient(), FakeHubbleClient())
        try:
            resp = client.get("/topology")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nodes"] == []
            assert data["edges"] == []
            assert data["node_count"] == 0
            assert data["edge_count"] == 0
        finally:
            restore()

    def test_topology_nodes_match_k8s_services(self, client):
        k8s = FakeK8sClient(
            services=[
                service(name="phoenix-sim", namespace="phoenix-system"),
                service(name="phoenix-chaos", namespace="phoenix-system"),
            ]
        )
        restore = _swap_clients(k8s, FakeHubbleClient())
        try:
            resp = client.get("/topology")
            assert resp.status_code == 200
            data = resp.json()
            names = {n["name"] for n in data["nodes"]}
            assert names == {"phoenix-sim", "phoenix-chaos"}
        finally:
            restore()

    def test_env_ref_edge_present_in_topology(self, client):
        k8s = FakeK8sClient(
            services=[
                service(name="phoenix-chaos", namespace="phoenix-system"),
                service(name="phoenix-faultlib", namespace="phoenix-system"),
            ],
            pods=[
                pod(
                    name="faultlib-pod",
                    namespace="phoenix-system",
                    labels={"app": "phoenix-faultlib"},
                    owner_name="phoenix-faultlib",
                    env={"CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local"},
                )
            ],
        )
        restore = _swap_clients(k8s, FakeHubbleClient())
        try:
            resp = client.get("/topology")
            assert resp.status_code == 200
            edges = resp.json()["edges"]
            assert any(
                e["source"] == "phoenix-system/phoenix-faultlib"
                and e["target"] == "phoenix-system/phoenix-chaos"
                and e["edge_type"] == "env_ref"
                for e in edges
            )
        finally:
            restore()

    def test_topology_is_recomputed_on_every_call(self, client):
        k8s = FakeK8sClient()
        hubble = FakeHubbleClient()
        restore = _swap_clients(k8s, hubble)
        try:
            client.get("/topology")
            client.get("/topology")
            assert k8s.list_services_calls == 2
        finally:
            restore()


class TestBlastRadiusEndpoint:
    def test_missing_required_params_returns_422(self, client):
        resp = client.get("/blast-radius")
        assert resp.status_code == 422

    def test_invalid_selector_format_returns_422(self, client):
        resp = client.get(
            "/blast-radius?target_namespace=ns&fault_type=pod_kill&selector=badformat"
        )
        assert resp.status_code == 422

    def test_empty_cluster_blast_radius_returns_no_affected(self, client):
        restore = _swap_clients(FakeK8sClient(), FakeHubbleClient())
        try:
            resp = client.get(
                "/blast-radius?target_namespace=phoenix-system&fault_type=pod_kill&selector=app=phoenix-chaos"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["matched_nodes"] == []
            assert data["affected_nodes"] == []
        finally:
            restore()

    def test_blast_radius_identifies_direct_dependent(self, client):
        k8s = FakeK8sClient(
            services=[
                service(name="phoenix-chaos", namespace="phoenix-system"),
                service(name="phoenix-faultlib", namespace="phoenix-system"),
            ],
            pods=[
                pod(
                    name="faultlib-pod",
                    namespace="phoenix-system",
                    labels={"app": "phoenix-faultlib"},
                    owner_name="phoenix-faultlib",
                    env={"CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local"},
                )
            ],
        )
        restore = _swap_clients(k8s, FakeHubbleClient())
        try:
            resp = client.get(
                "/blast-radius"
                "?target_namespace=phoenix-system"
                "&fault_type=network_latency"
                "&selector=app=phoenix-chaos"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "phoenix-system/phoenix-chaos" in data["matched_nodes"]
            affected_ids = [a["node_id"] for a in data["affected_nodes"]]
            assert "phoenix-system/phoenix-faultlib" in affected_ids
            faultlib = next(a for a in data["affected_nodes"] if a["node_id"] == "phoenix-system/phoenix-faultlib")
            assert faultlib["distance_hops"] == 1
            assert faultlib["severity"] == "high"
        finally:
            restore()

"""
Tests for the topology builder.
Copyright (c) 2026 Kaushikkumaran

These verify the assembly logic — that empty inputs yield empty outputs, that
env-ref edges are only emitted when both the source service and the destination
service exist in the k8s data, and that Hubble flow edges are correctly
mapped through the workload-to-service index.
"""

import pytest
from .fakes import FakeHubbleClient, FakeK8sClient, flow, pod, service
from topology_builder import build_topology


@pytest.mark.asyncio
class TestBuildTopologyEmptyState:
    async def test_no_services_yields_no_nodes(self):
        result = await build_topology(FakeK8sClient(), FakeHubbleClient())
        assert result.nodes == []
        assert result.edges == []

    async def test_no_pods_means_no_edges_even_with_services(self):
        k8s = FakeK8sClient(services=[service(name="svc-a", namespace="ns")])
        result = await build_topology(k8s, FakeHubbleClient())
        assert len(result.nodes) == 1
        assert result.edges == []

    async def test_empty_hubble_yields_kubernetes_only_source(self):
        result = await build_topology(FakeK8sClient(), FakeHubbleClient())
        assert result.topology_sources == ["kubernetes"]

    async def test_hubble_with_flows_adds_hubble_source(self):
        k8s = FakeK8sClient(
            services=[
                service(name="a", namespace="ns"),
                service(name="b", namespace="ns"),
            ],
            pods=[
                pod(name="a-pod", namespace="ns", labels={"app": "a"}, owner_name="a"),
                pod(name="b-pod", namespace="ns", labels={"app": "b"}, owner_name="b"),
            ],
        )
        hubble = FakeHubbleClient(
            flows=[flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="b")]
        )
        result = await build_topology(k8s, hubble)
        assert "hubble" in result.topology_sources

    async def test_empty_hubble_topology_sources_excludes_hubble(self):
        k8s = FakeK8sClient(services=[service(name="x", namespace="n")])
        result = await build_topology(k8s, FakeHubbleClient())
        assert "hubble" not in result.topology_sources


@pytest.mark.asyncio
class TestEnvRefEdges:
    async def test_env_ref_creates_directed_edge(self):
        """faultlib pod references chaos service via CHAOS_URL → faultlib → chaos edge."""
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
                    env={
                        "CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local"
                    },
                )
            ],
        )
        result = await build_topology(k8s, FakeHubbleClient())
        edge_pairs = {(e.source, e.target, e.edge_type) for e in result.edges}
        assert (
            "phoenix-system/phoenix-faultlib",
            "phoenix-system/phoenix-chaos",
            "env_ref",
        ) in edge_pairs

    async def test_env_ref_to_unknown_service_is_ignored(self):
        """A pod ENV pointing to a service not in k8s data produces no edge."""
        k8s = FakeK8sClient(
            services=[service(name="phoenix-faultlib", namespace="phoenix-system")],
            pods=[
                pod(
                    name="faultlib-pod",
                    namespace="phoenix-system",
                    labels={"app": "phoenix-faultlib"},
                    owner_name="phoenix-faultlib",
                    env={
                        "CHAOS_URL": "http://phoenix-chaos.phoenix-system.svc.cluster.local"
                    },
                )
            ],
        )
        result = await build_topology(k8s, FakeHubbleClient())
        assert result.edges == []

    async def test_env_ref_carries_env_var_name(self):
        k8s = FakeK8sClient(
            services=[
                service(name="svc-a", namespace="n"),
                service(name="svc-b", namespace="n"),
            ],
            pods=[
                pod(
                    name="a-pod",
                    namespace="n",
                    labels={"app": "svc-a"},
                    owner_name="svc-a",
                    env={"MY_URL": "http://svc-b.n.svc.cluster.local"},
                )
            ],
        )
        result = await build_topology(k8s, FakeHubbleClient())
        assert len(result.edges) == 1
        assert result.edges[0].env_var == "MY_URL"

    async def test_duplicate_env_ref_same_var_not_doubled(self):
        """Two pods in the same Deployment both referencing the same service
        should produce only one env_ref edge."""
        k8s = FakeK8sClient(
            services=[
                service(name="a", namespace="n"),
                service(name="b", namespace="n"),
            ],
            pods=[
                pod(
                    name="a-pod-1",
                    namespace="n",
                    labels={"app": "a"},
                    owner_name="a",
                    env={"URL": "http://b.n.svc.cluster.local"},
                ),
                pod(
                    name="a-pod-2",
                    namespace="n",
                    labels={"app": "a"},
                    owner_name="a",
                    env={"URL": "http://b.n.svc.cluster.local"},
                ),
            ],
        )
        result = await build_topology(k8s, FakeHubbleClient())
        env_edges = [e for e in result.edges if e.edge_type == "env_ref"]
        assert len(env_edges) == 1


@pytest.mark.asyncio
class TestFlowObservedEdges:
    async def test_hubble_flow_creates_flow_observed_edge(self):
        k8s = FakeK8sClient(
            services=[
                service(name="a", namespace="ns"),
                service(name="b", namespace="ns"),
            ],
            pods=[
                pod(name="a-p", namespace="ns", labels={"app": "a"}, owner_name="a"),
                pod(name="b-p", namespace="ns", labels={"app": "b"}, owner_name="b"),
            ],
        )
        hubble = FakeHubbleClient(
            flows=[flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="b")]
        )
        result = await build_topology(k8s, hubble)
        flow_edges = [e for e in result.edges if e.edge_type == "flow_observed"]
        assert len(flow_edges) == 1
        assert flow_edges[0].source == "ns/a"
        assert flow_edges[0].target == "ns/b"

    async def test_flow_count_reflects_observed_flows(self):
        k8s = FakeK8sClient(
            services=[
                service(name="a", namespace="ns"),
                service(name="b", namespace="ns"),
            ],
            pods=[
                pod(name="a-p", namespace="ns", labels={"app": "a"}, owner_name="a"),
                pod(name="b-p", namespace="ns", labels={"app": "b"}, owner_name="b"),
            ],
        )
        hubble = FakeHubbleClient(
            flows=[
                flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="b"),
                flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="b"),
                flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="b"),
            ]
        )
        result = await build_topology(k8s, hubble)
        flow_edges = [e for e in result.edges if e.edge_type == "flow_observed"]
        assert len(flow_edges) == 1
        assert flow_edges[0].flow_count == 3

    async def test_flow_with_unknown_workload_is_ignored(self):
        k8s = FakeK8sClient(
            services=[service(name="a", namespace="ns")],
            pods=[pod(name="a-p", namespace="ns", labels={"app": "a"}, owner_name="a")],
        )
        hubble = FakeHubbleClient(
            flows=[flow(source_ns="ns", source_workload="a", dest_ns="ns", dest_workload="unknown")]
        )
        result = await build_topology(k8s, hubble)
        assert [e for e in result.edges if e.edge_type == "flow_observed"] == []

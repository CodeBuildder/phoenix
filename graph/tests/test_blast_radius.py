"""
Tests for the blast-radius BFS algorithm.
Copyright (c) 2026 Kaushikkumaran

These verify the core graph algorithm in isolation — no k8s or Hubble calls.
The TopologyResponse inputs are constructed directly from Node/Edge instances.
"""

import pytest
from models import AffectedNode, BlastRadiusResponse, Edge, Node, TopologyResponse
from blast_radius import compute_blast_radius


def _topology(
    nodes: list[Node],
    edges: list[Edge],
    sources: list[str] | None = None,
) -> TopologyResponse:
    s = sources or ["kubernetes"]
    return TopologyResponse(
        nodes=nodes,
        edges=edges,
        topology_sources=s,
        node_count=len(nodes),
        edge_count=len(edges),
    )


def _node(id_: str, labels: dict | None = None) -> Node:
    ns, name = id_.split("/", 1)
    return Node(
        id=id_,
        name=name,
        namespace=ns,
        labels=labels or {"app": name},
    )


def _edge(src: str, tgt: str, etype: str = "env_ref") -> Edge:
    return Edge(source=src, target=tgt, edge_type=etype, flow_count=0)


class TestNoMatchedNodes:
    def test_empty_graph_yields_no_results(self):
        result = compute_blast_radius(
            _topology([], []),
            target_namespace="ns",
            target_selector={"app": "x"},
            fault_type="pod_kill",
        )
        assert result.matched_nodes == []
        assert result.affected_nodes == []

    def test_selector_matches_nothing_yields_empty(self):
        topo = _topology([_node("ns/a")], [])
        result = compute_blast_radius(
            topo,
            target_namespace="ns",
            target_selector={"app": "nobody"},
            fault_type="pod_kill",
        )
        assert result.matched_nodes == []
        assert result.affected_nodes == []

    def test_no_dependents_on_target_yields_no_affected(self):
        # a and b exist; a has a ref to b; target is a (no one depends on a)
        topo = _topology(
            [_node("ns/a"), _node("ns/b")],
            [_edge("ns/a", "ns/b")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="ns",
            target_selector={"app": "a"},
            fault_type="pod_kill",
        )
        assert result.matched_nodes == ["ns/a"]
        assert result.affected_nodes == []


class TestDirectDependents:
    def test_direct_dependent_is_at_distance_one_with_high_severity(self):
        # faultlib → chaos; target = chaos → faultlib is affected at distance 1
        topo = _topology(
            [_node("ps/chaos"), _node("ps/faultlib")],
            [_edge("ps/faultlib", "ps/chaos")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="ps",
            target_selector={"app": "chaos"},
            fault_type="network_latency",
        )
        assert result.matched_nodes == ["ps/chaos"]
        assert len(result.affected_nodes) == 1
        affected = result.affected_nodes[0]
        assert affected.node_id == "ps/faultlib"
        assert affected.distance_hops == 1
        assert affected.severity == "high"

    def test_multiple_direct_dependents(self):
        # both faultlib and dashboard depend on chaos
        topo = _topology(
            [_node("ps/chaos"), _node("ps/faultlib"), _node("ps/dashboard")],
            [_edge("ps/faultlib", "ps/chaos"), _edge("ps/dashboard", "ps/chaos")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="ps",
            target_selector={"app": "chaos"},
            fault_type="pod_kill",
        )
        affected_ids = {a.node_id for a in result.affected_nodes}
        assert affected_ids == {"ps/faultlib", "ps/dashboard"}
        assert all(a.distance_hops == 1 for a in result.affected_nodes)


class TestIndirectDependents:
    def test_transitive_dependency_is_distance_two_with_medium_severity(self):
        # c → b → a; target = a → b at dist 1 (high), c at dist 2 (medium)
        topo = _topology(
            [_node("n/a"), _node("n/b"), _node("n/c")],
            [_edge("n/b", "n/a"), _edge("n/c", "n/b")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="n",
            target_selector={"app": "a"},
            fault_type="io_delay",
        )
        by_id = {a.node_id: a for a in result.affected_nodes}
        assert by_id["n/b"].distance_hops == 1
        assert by_id["n/b"].severity == "high"
        assert by_id["n/c"].distance_hops == 2
        assert by_id["n/c"].severity == "medium"

    def test_distance_three_yields_low_severity(self):
        topo = _topology(
            [_node("n/a"), _node("n/b"), _node("n/c"), _node("n/d")],
            [_edge("n/b", "n/a"), _edge("n/c", "n/b"), _edge("n/d", "n/c")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="n",
            target_selector={"app": "a"},
            fault_type="pod_kill",
        )
        by_id = {a.node_id: a for a in result.affected_nodes}
        assert by_id["n/d"].distance_hops == 3
        assert by_id["n/d"].severity == "low"


class TestSelectorMatching:
    def test_empty_selector_matches_all_in_namespace(self):
        topo = _topology(
            [_node("ns/a"), _node("ns/b"), _node("other/c")],
            [_edge("ns/b", "ns/a")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="ns",
            target_selector={},
            fault_type="pod_kill",
        )
        # both ns/a and ns/b are matched; b depends on a (but b is also targeted)
        assert "ns/a" in result.matched_nodes
        assert "ns/b" in result.matched_nodes
        # b is matched (targeted), not affected
        affected_ids = {a.node_id for a in result.affected_nodes}
        assert "ns/b" not in affected_ids

    def test_selector_filters_by_label(self):
        topo = _topology(
            [
                _node("ns/api", labels={"app": "api", "tier": "backend"}),
                _node("ns/db", labels={"app": "db", "tier": "backend"}),
                _node("ns/fe", labels={"app": "fe", "tier": "frontend"}),
            ],
            [_edge("ns/api", "ns/db"), _edge("ns/fe", "ns/api")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="ns",
            target_selector={"app": "db"},
            fault_type="io_delay",
        )
        assert result.matched_nodes == ["ns/db"]
        affected_ids = {a.node_id for a in result.affected_nodes}
        assert "ns/api" in affected_ids
        assert "ns/fe" in affected_ids


class TestCycleHandling:
    def test_cyclic_graph_does_not_loop_infinitely(self):
        # a → b, b → a (cycle); target = a
        topo = _topology(
            [_node("n/a"), _node("n/b")],
            [_edge("n/a", "n/b"), _edge("n/b", "n/a")],
        )
        result = compute_blast_radius(
            topo,
            target_namespace="n",
            target_selector={"app": "a"},
            fault_type="pod_kill",
        )
        # b depends on a → affected at distance 1; a is the target so not in affected
        affected_ids = {x.node_id for x in result.affected_nodes}
        assert "n/a" not in affected_ids
        assert "n/b" in affected_ids


class TestResponseShape:
    def test_response_carries_fault_type_and_selector(self):
        result = compute_blast_radius(
            _topology([], []),
            target_namespace="ns",
            target_selector={"app": "svc"},
            fault_type="packet_loss",
        )
        assert result.fault_type == "packet_loss"
        assert result.target_selector == {"app": "svc"}
        assert result.target_namespace == "ns"

    def test_topology_sources_passed_through(self):
        topo = _topology([], [], sources=["kubernetes", "hubble"])
        result = compute_blast_radius(topo, "ns", {}, "pod_kill")
        assert result.topology_sources == ["kubernetes", "hubble"]

"""
Blast-Radius Graph Builder — blast-radius BFS algorithm.
Copyright (c) 2026 Kaushikkumaran

Given a set of targeted node IDs and the topology graph, computes which
downstream (depending) components are at risk.

Algorithm: reverse BFS from the chaos target nodes.
  - Edges are directed: source → target means "source depends on target"
  - A chaos fault on target impacts source (source calls target; if target
    degrades, source's calls to it degrade too)
  - So: follow edges *backwards* from the targeted nodes (find all sources
    whose target edge points to a targeted node) and continue outward

Severity is derived from graph distance alone:
  distance 1 → "high"   (direct dependency, immediately in the failure path)
  distance 2 → "medium" (indirect, one hop removed)
  distance 3+ → "low"   (further removed, impact depends on error propagation)

Nothing here is statistical.  The only inputs are the graph topology (itself
derived from real cluster data) and the target node set.
"""

from __future__ import annotations

from collections import deque

from models import AffectedNode, BlastRadiusResponse, TopologyResponse


def _severity(distance: int) -> str:
    if distance == 1:
        return "high"
    if distance == 2:
        return "medium"
    return "low"


def compute_blast_radius(
    topology: TopologyResponse,
    target_namespace: str,
    target_selector: dict[str, str],
    fault_type: str,
) -> BlastRadiusResponse:
    """
    Compute which nodes are in the blast radius for a chaos scenario that
    targets services in target_namespace whose labels match target_selector.

    Returns a BlastRadiusResponse with:
      - matched_nodes: the targeted service(s) found in the graph
      - affected_nodes: all nodes that depend (directly or transitively) on
          the targeted services, with distance and severity
    """
    # Identify targeted nodes
    matched_ids: set[str] = set()
    for node in topology.nodes:
        if node.namespace != target_namespace:
            continue
        if target_selector and not all(
            node.labels.get(k) == v for k, v in target_selector.items()
        ):
            continue
        matched_ids.add(node.id)

    if not matched_ids:
        return BlastRadiusResponse(
            target_namespace=target_namespace,
            target_selector=target_selector,
            fault_type=fault_type,
            matched_nodes=[],
            affected_nodes=[],
            topology_sources=topology.topology_sources,
        )

    # Build: target_node_id → list of (source_node_id, edge_type)
    # "who has an edge pointing TO this node"
    dependents: dict[str, list[tuple[str, str]]] = {}
    for edge in topology.edges:
        if edge.target not in dependents:
            dependents[edge.target] = []
        dependents[edge.target].append((edge.source, edge.edge_type))

    # BFS from matched_ids, following dependents (reverse edges)
    node_by_id = {n.id: n for n in topology.nodes}
    visited: dict[str, int] = {}  # node_id → distance
    via_edges: dict[str, list[str]] = {}  # node_id → edge_types on the path

    queue: deque[tuple[str, int, str]] = deque()
    for tid in matched_ids:
        for src_id, etype in dependents.get(tid, []):
            if src_id in matched_ids:
                continue
            if src_id not in visited:
                visited[src_id] = 1
                via_edges[src_id] = [etype]
                queue.append((src_id, 1, etype))
            elif etype not in via_edges[src_id]:
                via_edges[src_id].append(etype)

    while queue:
        current_id, dist, _ = queue.popleft()
        for src_id, etype in dependents.get(current_id, []):
            if src_id in matched_ids:
                continue
            new_dist = dist + 1
            if src_id not in visited:
                visited[src_id] = new_dist
                via_edges[src_id] = [etype]
                queue.append((src_id, new_dist, etype))
            elif etype not in via_edges[src_id]:
                via_edges[src_id].append(etype)

    affected: list[AffectedNode] = []
    for node_id, dist in sorted(visited.items(), key=lambda x: (x[1], x[0])):
        node = node_by_id.get(node_id)
        if node is None:
            continue
        affected.append(
            AffectedNode(
                node_id=node_id,
                name=node.name,
                namespace=node.namespace,
                distance_hops=dist,
                severity=_severity(dist),
                via_edge_types=via_edges.get(node_id, []),
            )
        )

    return BlastRadiusResponse(
        target_namespace=target_namespace,
        target_selector=target_selector,
        fault_type=fault_type,
        matched_nodes=sorted(matched_ids),
        affected_nodes=affected,
        topology_sources=topology.topology_sources,
    )

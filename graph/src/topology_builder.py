"""
Blast-Radius Graph Builder — topology assembly.
Copyright (c) 2026 Kaushikkumaran

Combines k8s API data and Hubble flow data into the dependency graph.
Every node is a real k8s Service; every edge is traceable to either a
concrete env-var reference or an observed Hubble flow.

Design invariants:
  - Empty k8s data → empty graph (no phantom nodes)
  - Hubble unavailability → graph is built from k8s data alone
  - Duplicate edges between the same (source, target) pair are collapsed:
      env_ref + flow_observed → two distinct edges (they convey different info)
      multiple flows for the same (source, target) workload pair → one edge
      with flow_count = total observed flows
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import structlog

from env_parser import parse_service_refs
from models import Edge, Node, TopologyResponse

log = structlog.get_logger()


async def build_topology(k8s, hubble) -> TopologyResponse:
    """
    Build the full dependency graph from live cluster data.

    k8s  — anything with async list_services() → list[dict]
                                  list_pods()    → list[dict]
    hubble — anything with async get_flows(max_flows) → list[dict]
    """
    services_data, pods_data, replicasets_data, flows_data = await asyncio.gather(
        k8s.list_services(),
        k8s.list_pods(),
        k8s.list_replicasets(),
        hubble.get_flows(max_flows=2000),
    )

    # ReplicaSet name → Deployment name.  Pods owned by a ReplicaSet report the
    # RS name as their owner, but Hubble reports the Deployment name as the
    # workload identity.  This mapping bridges the gap.
    rs_to_deployment: dict[str, str] = {}
    for rs in replicasets_data:
        if rs.get("deployment_name"):
            rs_to_deployment[rs["name"]] = rs["deployment_name"]

    topology_sources = ["kubernetes"]
    if flows_data:
        topology_sources.append("hubble")

    # -----------------------------------------------------------------
    # Build the node index: (namespace, name) → Node
    # One node per k8s Service.
    # -----------------------------------------------------------------
    service_index: dict[tuple[str, str], Node] = {}
    for svc in services_data:
        key = (svc["namespace"], svc["name"])
        service_index[key] = Node(
            id=f"{svc['namespace']}/{svc['name']}",
            name=svc["name"],
            namespace=svc["namespace"],
            kind="Service",
            labels=svc.get("labels", {}),
            cluster_ip=svc.get("cluster_ip"),
        )

    # -----------------------------------------------------------------
    # Build env-ref edges.
    #
    # For each pod, check its env vars for k8s DNS service references.
    # Map the pod to its owner workload (Deployment/StatefulSet/…) using
    # the pod's owner_name.  If the destination service is in the service
    # index, emit an env_ref edge from the owner's service to the target.
    # -----------------------------------------------------------------

    # Build: owner_workload_name → service keys that have that workload as a pod selector match.
    # Simpler approach: look for the service whose selector labels are a subset of the pod's labels.
    def pod_to_service_key(pod: dict) -> tuple[str, str] | None:
        """Return the (namespace, service_name) key for the service that selects this pod."""
        ns = pod["namespace"]
        pod_labels = pod.get("labels", {})
        for (svc_ns, svc_name), node in service_index.items():
            if svc_ns != ns:
                continue
            selector = next(
                (s["selector"] for s in services_data if s["namespace"] == svc_ns and s["name"] == svc_name),
                {},
            )
            if selector and all(pod_labels.get(k) == v for k, v in selector.items()):
                return (svc_ns, svc_name)
        return None

    # (source_key, target_key, env_var) → already emitted
    env_edges_seen: set[tuple[tuple[str, str], tuple[str, str], str]] = set()
    env_edges: list[Edge] = []

    for pod in pods_data:
        src_key = pod_to_service_key(pod)
        if src_key is None:
            continue

        refs = parse_service_refs(pod.get("env", {}))
        for ref in refs:
            dst_key = (ref["namespace"], ref["name"])
            if dst_key not in service_index:
                continue
            if src_key == dst_key:
                continue
            dedup = (src_key, dst_key, ref["env_var"])
            if dedup in env_edges_seen:
                continue
            env_edges_seen.add(dedup)
            env_edges.append(
                Edge(
                    source=f"{src_key[0]}/{src_key[1]}",
                    target=f"{dst_key[0]}/{dst_key[1]}",
                    edge_type="env_ref",
                    flow_count=0,
                    env_var=ref["env_var"],
                )
            )

    # -----------------------------------------------------------------
    # Build flow-observed edges.
    #
    # Each Hubble flow dict has:
    #   source_ns, source_workload → the Deployment/workload name on the source side
    #   dest_ns,   dest_workload   → the Deployment/workload name on the dest side
    #
    # Map (workload, ns) → the Service that owns that workload, using the
    # pod_to_service_key lookup (which checks selector match).  Build a
    # mapping from workload owner_name to service key first to avoid
    # O(flows × pods) scanning.
    # -----------------------------------------------------------------

    # workload_name@ns → service key
    # Hubble reports the Deployment name as the workload identity for
    # Deployment-managed pods, even though the pod's direct owner is a
    # ReplicaSet.  Resolve through rs_to_deployment to get the name Hubble uses.
    workload_to_svc: dict[str, tuple[str, str]] = {}
    for pod in pods_data:
        owner = pod.get("owner_name")
        if not owner:
            continue
        # Resolve ReplicaSet → Deployment if applicable
        workload_name = rs_to_deployment.get(owner, owner)
        svc_key = pod_to_service_key(pod)
        if svc_key:
            # Index by the Deployment/workload name (what Hubble reports)
            workload_to_svc[f"{workload_name}@{pod['namespace']}"] = svc_key

    # (source_key, target_key) → flow count
    flow_tally: dict[tuple[tuple[str, str], tuple[str, str]], int] = defaultdict(int)

    for flow in flows_data:
        src_wkey = f"{flow['source_workload']}@{flow['source_ns']}"
        dst_wkey = f"{flow['dest_workload']}@{flow['dest_ns']}"
        src_key = workload_to_svc.get(src_wkey)
        dst_key = workload_to_svc.get(dst_wkey)
        if src_key is None or dst_key is None:
            continue
        if src_key == dst_key:
            continue
        if src_key not in service_index or dst_key not in service_index:
            continue
        flow_tally[(src_key, dst_key)] += 1

    flow_edges: list[Edge] = [
        Edge(
            source=f"{src[0]}/{src[1]}",
            target=f"{dst[0]}/{dst[1]}",
            edge_type="flow_observed",
            flow_count=count,
        )
        for (src, dst), count in flow_tally.items()
    ]

    all_edges = env_edges + flow_edges
    nodes = list(service_index.values())

    log.info(
        "topology_built",
        nodes=len(nodes),
        env_edges=len(env_edges),
        flow_edges=len(flow_edges),
        sources=topology_sources,
    )

    return TopologyResponse(
        nodes=nodes,
        edges=all_edges,
        topology_sources=topology_sources,
        node_count=len(nodes),
        edge_count=len(all_edges),
    )

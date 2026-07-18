"""
Blast-Radius Graph Builder — HTTP router.
Copyright (c) 2026 Kaushikkumaran
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from blast_radius import compute_blast_radius
from config import config
from demo_topology import build_demo_topology
from hubble_client import HubbleClient
from k8s_client import K8sTopologyClient
from models import BlastRadiusResponse, TopologyResponse
from topology_builder import build_topology

router = APIRouter(tags=["graph"])

# Module-level singletons — swappable in tests via monkeypatching.
k8s = K8sTopologyClient()
hubble = HubbleClient(
    address=config.HUBBLE_ADDRESS,
    timeout_seconds=config.HUBBLE_TIMEOUT_SECONDS,
)


@router.get("/topology", response_model=TopologyResponse)
async def get_topology() -> TopologyResponse:
    """
    Return the full service dependency graph derived from the live cluster.

    Nodes are k8s Services.  Edges are directed source → target meaning
    "source depends on target" — inferred from pod environment variables
    (env_ref edges) and Hubble-observed TCP flows (flow_observed edges).

    Every call recomputes from live data — there is no cache.
    """
    if config.LOCAL_DEMO:
        return build_demo_topology()
    return await build_topology(k8s, hubble)


@router.get("/blast-radius", response_model=BlastRadiusResponse)
async def get_blast_radius(
    target_namespace: str = Query(description="Namespace of the chaos target."),
    fault_type: str = Query(description="Chaos fault type (e.g. network_latency, pod_kill)."),
    selector: list[str] = Query(
        default=[],
        description=(
            "Label selector key=value pairs that identify the target service(s). "
            "Pass multiple times for multiple labels, e.g. "
            "?selector=app=phoenix-chaos&selector=tier=backend."
        ),
    ),
) -> BlastRadiusResponse:
    """
    Compute which services are in the blast radius for a planned chaos scenario.

    1. Builds the live topology (same as GET /topology).
    2. Matches services in target_namespace whose labels match all selector pairs.
    3. Runs reverse BFS from matched nodes to find all dependents.
    4. Returns affected nodes with distance and severity.

    An empty selector matches ALL services in target_namespace.
    """
    parsed_selector: dict[str, str] = {}
    for pair in selector:
        if "=" not in pair:
            raise HTTPException(
                status_code=422,
                detail=f"selector '{pair}' must be in key=value format",
            )
        k, _, v = pair.partition("=")
        parsed_selector[k] = v

    topology = build_demo_topology() if config.LOCAL_DEMO else await build_topology(k8s, hubble)
    return compute_blast_radius(
        topology=topology,
        target_namespace=target_namespace,
        target_selector=parsed_selector,
        fault_type=fault_type,
    )

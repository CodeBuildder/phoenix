"""
Blast-Radius Graph Builder — API data shapes.
Copyright (c) 2026 Kaushikkumaran

All fields carry real observed or declared data only.  No field here has a
default that would produce a plausible-looking number in the absence of real
cluster data — empty inputs produce empty outputs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Topology graph shapes
# ---------------------------------------------------------------------------


class Node(BaseModel):
    """One vertex in the dependency graph — a real k8s Service or Deployment."""

    id: str = Field(
        description="Stable identifier: '<namespace>/<name>'. Used as edge source/target."
    )
    name: str
    namespace: str
    kind: Literal["Service", "Deployment", "ExternalService"] = "Service"
    labels: dict[str, str] = Field(default_factory=dict)
    cluster_ip: str | None = None


class Edge(BaseModel):
    """
    One directed dependency edge: source *depends on* target.

    That means: source calls target, reads from target, or otherwise requires
    target to be healthy.  When chaos hits target, source is in the blast
    radius.
    """

    source: str = Field(description="Node id of the dependent service.")
    target: str = Field(description="Node id of the service being depended on.")
    edge_type: Literal["env_ref", "flow_observed"] = Field(
        description=(
            "env_ref — inferred from a pod environment variable whose value is"
            " a k8s DNS name pointing at the target service.  "
            "flow_observed — a FORWARDED TCP/UDP flow seen by Hubble in the"
            " last N minutes whose source workload maps to source and whose"
            " destination workload maps to target."
        )
    )
    flow_count: int = Field(
        default=0,
        description=(
            "Number of FORWARDED flows Hubble saw between these two workloads"
            " in the observation window.  Zero for env_ref edges (no flow"
            " data was the basis for that edge)."
        ),
    )
    env_var: str | None = Field(
        default=None,
        description="Name of the env var that established this edge (env_ref only).",
    )


class TopologyResponse(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    topology_sources: list[str] = Field(
        description="Which data sources contributed ('kubernetes', 'hubble')."
    )
    node_count: int
    edge_count: int
    observed_at: str = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Blast-radius prediction shapes
# ---------------------------------------------------------------------------


class AffectedNode(BaseModel):
    """One downstream component identified as being in the blast radius."""

    node_id: str
    name: str
    namespace: str
    distance_hops: int = Field(
        description=(
            "Graph distance from the chaos target — 1 means directly depends"
            " on the target, 2 means depends on a node at distance 1, etc."
        )
    )
    severity: Literal["high", "medium", "low"] = Field(
        description=(
            "high at distance 1, medium at 2, low at 3+.  Derived purely"
            " from graph distance — not a statistical estimate."
        )
    )
    via_edge_types: list[str] = Field(
        description="Edge type(s) on the path that brought this node into scope."
    )


class BlastRadiusResponse(BaseModel):
    target_namespace: str
    target_selector: dict[str, str]
    fault_type: str
    matched_nodes: list[str] = Field(
        description="Node ids of the services/deployments the selector matched."
    )
    affected_nodes: list[AffectedNode]
    topology_sources: list[str]
    computed_at: str = Field(default_factory=_now)

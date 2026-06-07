"""
Test doubles for the graph service's two cluster data dependencies.
Copyright (c) 2026 Kaushikkumaran

FakeK8sClient and FakeHubbleClient return exactly the data they are seeded
with — no inference, no defaults beyond what the helper builders below
produce for their documented fields.
"""

from __future__ import annotations

from typing import Any


class FakeK8sClient:
    def __init__(
        self,
        services: list[dict] | None = None,
        pods: list[dict] | None = None,
        replicasets: list[dict] | None = None,
    ) -> None:
        self.services = list(services) if services else []
        self.pods = list(pods) if pods else []
        self.replicasets = list(replicasets) if replicasets else []
        self.list_services_calls = 0
        self.list_pods_calls = 0

    async def list_services(self) -> list[dict]:
        self.list_services_calls += 1
        return list(self.services)

    async def list_pods(self) -> list[dict]:
        self.list_pods_calls += 1
        return list(self.pods)

    async def list_replicasets(self) -> list[dict]:
        return list(self.replicasets)


class FakeHubbleClient:
    def __init__(self, flows: list[dict] | None = None) -> None:
        self.flows = list(flows) if flows else []
        self.get_flows_calls = 0

    async def get_flows(self, max_flows: int = 2000) -> list[dict]:
        self.get_flows_calls += 1
        return list(self.flows)


# ---------------------------------------------------------------------------
# Builder helpers — produce realistic but minimal dict shapes
# ---------------------------------------------------------------------------


def service(
    *,
    name: str,
    namespace: str = "default",
    labels: dict[str, str] | None = None,
    selector: dict[str, str] | None = None,
    cluster_ip: str = "10.0.0.1",
) -> dict[str, Any]:
    """Build one service dict in the shape K8sTopologyClient returns."""
    return {
        "name": name,
        "namespace": namespace,
        "labels": labels if labels is not None else {"app": name},
        "selector": selector if selector is not None else {"app": name},
        "cluster_ip": cluster_ip,
    }


def pod(
    *,
    name: str,
    namespace: str = "default",
    labels: dict[str, str] | None = None,
    owner_name: str | None = None,
    owner_kind: str = "Deployment",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one pod dict in the shape K8sTopologyClient returns."""
    return {
        "name": name,
        "namespace": namespace,
        "labels": labels if labels is not None else ({"app": owner_name} if owner_name else {}),
        "owner_name": owner_name,
        "owner_kind": owner_kind,
        "node_name": "k3s-master",
        "env": env if env is not None else {},
    }


def flow(
    *,
    source_ns: str,
    source_workload: str,
    dest_ns: str,
    dest_workload: str,
    source_workload_kind: str = "Deployment",
    dest_workload_kind: str = "Deployment",
) -> dict[str, Any]:
    """Build one flow dict in the shape HubbleClient.get_flows() returns."""
    return {
        "source_ns": source_ns,
        "source_workload": source_workload,
        "source_workload_kind": source_workload_kind,
        "dest_ns": dest_ns,
        "dest_workload": dest_workload,
        "dest_workload_kind": dest_workload_kind,
    }

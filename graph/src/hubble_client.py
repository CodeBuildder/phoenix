"""
Blast-Radius Graph Builder — Hubble gRPC client.
Copyright (c) 2026 Kaushikkumaran

Connects to hubble-relay's Observer gRPC service and retrieves the most
recent N FORWARDED flows.  Each flow is returned as a plain dict with
source/destination workload identity — the same "real records, no
fabrication" posture the rest of the service takes.

The proto stubs (observer_pb2, flow_pb2, etc.) are compiled from the
vendored Cilium v1.15.0 .proto files at Docker image build time.  In a
local development environment without the stubs compiled, the ImportError
is caught and get_flows() returns [] — the topology builder degrades to
k8s-only data rather than crashing.
"""

from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger()


class HubbleClient:
    def __init__(self, address: str, timeout_seconds: float = 8.0) -> None:
        self._address = address
        self._timeout = timeout_seconds

    def _collect_flows_sync(self, max_flows: int) -> list[dict]:
        """
        Synchronous gRPC streaming call — runs in a thread-pool executor so
        it doesn't block the async event loop.

        Returns one dict per FORWARDED flow where both source and destination
        have workload identity (pod-to-pod traffic between named k8s
        workloads).  Flows to/from reserved Cilium identities (world, host,
        health, init) are excluded because they don't correspond to k8s
        Service nodes in the graph.
        """
        try:
            import grpc
            from flow.flow_pb2 import Verdict as FlowVerdict  # type: ignore[import]
            from observer.observer_pb2 import GetFlowsRequest  # type: ignore[import]
            from observer.observer_pb2_grpc import ObserverStub  # type: ignore[import]
        except ImportError:
            log.debug("hubble_stubs_not_compiled", hint="proto stubs are generated at Docker build time")
            return []

        channel = grpc.insecure_channel(self._address)
        stub = ObserverStub(channel)
        request = GetFlowsRequest(number=max_flows, follow=False)
        flows: list[dict] = []

        try:
            for response in stub.GetFlows(request, timeout=self._timeout):
                if not response.HasField("flow"):
                    continue
                flow = response.flow
                if flow.verdict != FlowVerdict.FORWARDED:
                    continue

                src = flow.source
                dst = flow.destination

                # Skip flows involving reserved identities (world, host, health, init).
                # These don't correspond to named k8s workloads.
                if not src.namespace or not dst.namespace:
                    continue
                if not src.workloads or not dst.workloads:
                    continue

                src_workload = src.workloads[0]
                dst_workload = dst.workloads[0]

                flows.append(
                    {
                        "source_ns": src.namespace,
                        "source_workload": src_workload.name,
                        "source_workload_kind": src_workload.kind,
                        "dest_ns": dst.namespace,
                        "dest_workload": dst_workload.name,
                        "dest_workload_kind": dst_workload.kind,
                    }
                )
        except Exception as e:
            log.warning("hubble_grpc_error", address=self._address, error=str(e))
        finally:
            channel.close()

        return flows

    async def get_flows(self, max_flows: int) -> list[dict]:
        """Async wrapper — delegates to the sync gRPC call in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._collect_flows_sync, max_flows)

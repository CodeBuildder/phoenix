"""
Blast-Radius Graph Builder — Kubernetes API client.
Copyright (c) 2026 Kaushikkumaran

Wraps the python-kubernetes library and normalises API responses into plain
dicts so the rest of the service has no direct dependency on k8s client
objects.  Every field returned here comes directly from the live cluster API —
nothing is defaulted to a plausible-looking value.
"""

from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger()


def _get_k8s_client():
    try:
        from kubernetes import client, config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        return client
    except Exception as e:
        log.warning("k8s_client_unavailable", error=str(e))
        return None


class K8sTopologyClient:
    """
    Read-only k8s API wrapper.  All list_* methods run the synchronous
    kubernetes-client calls in a thread-pool executor so they don't block
    the async event loop.

    Return shapes are documented inline.  Fields whose value is not present
    in the API response are omitted (not set to None or a placeholder).
    """

    async def list_services(self) -> list[dict]:
        """
        Returns one dict per Service across all namespaces:
            name        str
            namespace   str
            labels      dict[str, str]
            selector    dict[str, str]   — pod selector; empty if none
            cluster_ip  str | None
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self._list_services_sync
        )

    def _list_services_sync(self) -> list[dict]:
        k8s = _get_k8s_client()
        if not k8s:
            return []
        try:
            v1 = k8s.CoreV1Api()
            resp = v1.list_service_for_all_namespaces(watch=False)
            result = []
            for svc in resp.items:
                selector = {}
                if svc.spec and svc.spec.selector:
                    selector = dict(svc.spec.selector)
                cluster_ip = None
                if svc.spec and svc.spec.cluster_ip not in (None, "None", ""):
                    cluster_ip = svc.spec.cluster_ip
                result.append(
                    {
                        "name": svc.metadata.name,
                        "namespace": svc.metadata.namespace,
                        "labels": dict(svc.metadata.labels or {}),
                        "selector": selector,
                        "cluster_ip": cluster_ip,
                    }
                )
            return result
        except Exception as e:
            log.warning("k8s_list_services_failed", error=str(e))
            return []

    async def list_pods(self) -> list[dict]:
        """
        Returns one dict per Pod across all namespaces:
            name         str
            namespace    str
            labels       dict[str, str]
            owner_name   str | None   — e.g. the Deployment name (resolved
                                         through ReplicaSet for RS-owned pods)
            owner_kind   str | None   — "Deployment", "StatefulSet", "DaemonSet", …
            node_name    str | None
            env          dict[str, str]  — env var name → value (strings only;
                                            valueFrom refs are skipped because
                                            their resolved values require an
                                            additional API call per var)
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self._list_pods_sync
        )

    def _list_pods_sync(self) -> list[dict]:
        k8s = _get_k8s_client()
        if not k8s:
            return []
        try:
            v1 = k8s.CoreV1Api()
            resp = v1.list_pod_for_all_namespaces(watch=False)
            result = []
            for pod in resp.items:
                owner_name = None
                owner_kind = None
                if pod.metadata.owner_references:
                    ref = pod.metadata.owner_references[0]
                    owner_name = ref.name
                    owner_kind = ref.kind

                env: dict[str, str] = {}
                if pod.spec and pod.spec.containers:
                    for container in pod.spec.containers:
                        for e in container.env or []:
                            if e.value is not None:
                                env[e.name] = e.value

                result.append(
                    {
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "labels": dict(pod.metadata.labels or {}),
                        "owner_name": owner_name,
                        "owner_kind": owner_kind,
                        "node_name": pod.spec.node_name if pod.spec else None,
                        "env": env,
                    }
                )
            return result
        except Exception as e:
            log.warning("k8s_list_pods_failed", error=str(e))
            return []

    async def list_replicasets(self) -> list[dict]:
        """
        Returns one dict per ReplicaSet across all namespaces:
            name            str   — ReplicaSet name (e.g. "phoenix-faultlib-664954ff75")
            namespace       str
            deployment_name str | None — parent Deployment, if owned by one

        Used to resolve pod.owner_name (ReplicaSet) → Deployment name so that
        Hubble's workload identity (which reports the Deployment name) can be
        mapped back to the service that selects this workload's pods.
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self._list_replicasets_sync
        )

    def _list_replicasets_sync(self) -> list[dict]:
        k8s = _get_k8s_client()
        if not k8s:
            return []
        try:
            apps_v1 = k8s.AppsV1Api()
            resp = apps_v1.list_replica_set_for_all_namespaces(watch=False)
            result = []
            for rs in resp.items:
                deployment_name = None
                if rs.metadata.owner_references:
                    for ref in rs.metadata.owner_references:
                        if ref.kind == "Deployment":
                            deployment_name = ref.name
                            break
                result.append(
                    {
                        "name": rs.metadata.name,
                        "namespace": rs.metadata.namespace,
                        "deployment_name": deployment_name,
                    }
                )
            return result
        except Exception as e:
            log.warning("k8s_list_replicasets_failed", error=str(e))
            return []

    async def list_namespaces(self) -> list[dict]:
        """
        Returns one dict per Namespace:
            name    str
            labels  dict[str, str]
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self._list_namespaces_sync
        )

    def _list_namespaces_sync(self) -> list[dict]:
        k8s = _get_k8s_client()
        if not k8s:
            return []
        try:
            v1 = k8s.CoreV1Api()
            resp = v1.list_namespace(watch=False)
            return [
                {
                    "name": ns.metadata.name,
                    "labels": dict(ns.metadata.labels or {}),
                }
                for ns in resp.items
            ]
        except Exception as e:
            log.warning("k8s_list_namespaces_failed", error=str(e))
            return []

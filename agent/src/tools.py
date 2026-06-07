"""
Phoenix Agent — remediation tools
Copyright (c) 2026 Kaushikkumaran

MCP-style async tools the heal/execute node calls to actually fix things.
Each tool returns a plain string result logged as the action_result.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

from config import config

log = structlog.get_logger()

# Kubernetes client — loaded lazily so unit tests can stub it
_apps_v1: client.AppsV1Api | None = None


def _get_apps_v1() -> client.AppsV1Api:
    global _apps_v1
    if _apps_v1 is None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        _apps_v1 = client.AppsV1Api()
    return _apps_v1


async def restart_deployment(name: str, namespace: str) -> str:
    """
    Patch the deployment's pod template annotations to trigger a rollout
    restart — equivalent to `kubectl rollout restart deployment/{name}`.
    Only touches the restart annotation; no other pod spec is changed.
    """
    ts = datetime.now(timezone.utc).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": ts,
                        "phoenix-agent/restarted-by": "phoenix-agent",
                    }
                }
            }
        }
    }
    try:
        api = _get_apps_v1()
        api.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
        msg = f"Deployment {namespace}/{name} restart patched at {ts}"
        log.info("tool.restart_deployment", name=name, namespace=namespace)
        return msg
    except ApiException as exc:
        raise RuntimeError(f"kubectl restart failed for {namespace}/{name}: {exc.reason}") from exc


async def stop_scenario(scenario_id: str) -> str:
    """POST /scenarios/{id}/stop on the chaos service."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{config.CHAOS_URL}/scenarios/{scenario_id}/stop")
        if r.status_code not in (200, 202, 204):
            raise RuntimeError(f"stop_scenario failed: {r.status_code} {r.text}")
        log.info("tool.stop_scenario", scenario_id=scenario_id)
        return f"Scenario {scenario_id} stop requested (HTTP {r.status_code})"


async def get_blast_radius(namespace: str, labels: dict[str, str]) -> dict:
    label_str = ",".join(f"{k}={v}" for k, v in labels.items())
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{config.GRAPH_URL}/blast-radius",
            params={"namespace": namespace, "label_selector": label_str},
        )
        if r.status_code == 200:
            return r.json()
        return {}


async def get_catalog_entry(domain: str, fault_type: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{config.FAULTLIB_URL}/catalog/{domain}/{fault_type}")
        if r.status_code == 200:
            return r.json()
        return {}


async def get_running_scenarios() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{config.CHAOS_URL}/scenarios", params={"status": "running"})
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("scenarios", [])
        return []


async def get_scenario(scenario_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{config.CHAOS_URL}/scenarios/{scenario_id}")
        if r.status_code == 200:
            return r.json()
        return None

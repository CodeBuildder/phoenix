"""
Chaos Injection Engine — Chaos Mesh wrapper
Copyright (c) 2026 Kaushikkumaran

Translates our four Chaos Mesh fault types into genuine
`chaos-mesh.org/v1alpha1` custom resources (PodChaos / NetworkChaos / IOChaos)
and applies/queries/cleans them up via the k8s CustomObjectsApi — "Chaos Mesh
experiments applied/cleaned up via the k8s API", per the M1 issue scope.

Every field name and enum value below was checked directly against the CRD
schemas installed in the live cluster
(`kubectl get crd <kind>.chaos-mesh.org -o jsonpath=...properties.spec...`),
not guessed from memory — see the mapping table in chaos/README.md. Lazily
imports `kubernetes` and tries in-cluster config before local kubeconfig,
mirroring argus-agent's actions.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from models import ChaosMeshFaultType, K8sTarget

GROUP = "chaos-mesh.org"
VERSION = "v1alpha1"

_PLURAL = {
    ChaosMeshFaultType.POD_KILL: "podchaos",
    ChaosMeshFaultType.NETWORK_LATENCY: "networkchaos",
    ChaosMeshFaultType.PACKET_LOSS: "networkchaos",
    ChaosMeshFaultType.IO_DELAY: "iochaos",
}

_KIND = {
    ChaosMeshFaultType.POD_KILL: "PodChaos",
    ChaosMeshFaultType.NETWORK_LATENCY: "NetworkChaos",
    ChaosMeshFaultType.PACKET_LOSS: "NetworkChaos",
    ChaosMeshFaultType.IO_DELAY: "IOChaos",
}


# ---------------------------------------------------------------------------
# Per-fault-type params — the genuine, type-checked knobs each CRD exposes.
# Defaults are deliberately mild (short delays, low percentages) so a
# scenario launched without `params` perturbs rather than annihilates.
# ---------------------------------------------------------------------------

class PodKillParams(BaseModel):
    """-> PodChaos{action: pod-kill}. `gracePeriod` is a genuine spec field
    (seconds the kubelet waits before force-removing the pod)."""
    grace_period_seconds: int = Field(default=0, ge=0, le=600)


class NetworkLatencyParams(BaseModel):
    """-> NetworkChaos{action: delay, delay: {latency, jitter, correlation}}.
    Values are Chaos Mesh's own string formats: latency/jitter are Go
    durations ("100ms"), correlation is a percentage string ("0"-"100")."""
    latency: str = "100ms"
    jitter: str = "0ms"
    correlation: str = "0"


class PacketLossParams(BaseModel):
    """-> NetworkChaos{action: loss, loss: {loss, correlation}}. Both are
    percentage strings, exactly as Chaos Mesh's CRD schema defines them."""
    loss_percent: str = Field(default="25", alias="loss")
    correlation: str = "0"

    model_config = {"populate_by_name": True}


class IODelayParams(BaseModel):
    """-> IOChaos{action: latency, delay, percent, path, volumePath}.
    `delay` is a Go duration string; `percent` is what fraction of matching
    file operations are slowed."""
    delay: str = "100ms"
    percent: int = Field(default=100, ge=0, le=100)
    path: str = "/*"
    volume_path: str = "/"


_PARAMS_MODEL: dict[ChaosMeshFaultType, type[BaseModel]] = {
    ChaosMeshFaultType.POD_KILL: PodKillParams,
    ChaosMeshFaultType.NETWORK_LATENCY: NetworkLatencyParams,
    ChaosMeshFaultType.PACKET_LOSS: PacketLossParams,
    ChaosMeshFaultType.IO_DELAY: IODelayParams,
}


def parse_params(fault_type: ChaosMeshFaultType, raw: dict[str, Any]) -> BaseModel:
    """Validate a scenario request's free-form `params` dict against the real
    shape its fault type's CRD expects. Raises pydantic.ValidationError on
    anything malformed — the engine surfaces that as 422, before any scenario
    record or cluster object is created."""
    return _PARAMS_MODEL[fault_type].model_validate(raw)


# ---------------------------------------------------------------------------
# Manifest construction — pure functions, independently testable without a
# cluster. Every key here is a real field on the corresponding CRD's spec.
# ---------------------------------------------------------------------------

def _selector(target: K8sTarget) -> dict[str, Any]:
    selector: dict[str, Any] = {"namespaces": [target.namespace]}
    if target.label_selector:
        selector["labelSelectors"] = target.label_selector
    return selector


def _mode_fields(target: K8sTarget) -> dict[str, Any]:
    """`target` is a `K8sTarget`, whose own validator already guarantees
    `value` is present whenever `mode` requires one — nothing left to check
    here but how to shape the spec fields."""
    fields: dict[str, Any] = {"mode": target.mode}
    if target.value:
        fields["value"] = target.value
    return fields


def _duration(duration_seconds: float | None) -> str | None:
    """Chaos Mesh durations are Go duration strings ("30s"); we only ever
    deal in whole seconds here."""
    if duration_seconds is None:
        return None
    return f"{int(duration_seconds)}s"


def _spec_pod_kill(target: K8sTarget, duration_seconds: float | None, params: PodKillParams) -> dict[str, Any]:
    spec: dict[str, Any] = {"action": "pod-kill", "selector": _selector(target), **_mode_fields(target)}
    if params.grace_period_seconds:
        spec["gracePeriod"] = params.grace_period_seconds
    duration = _duration(duration_seconds)
    if duration:
        spec["duration"] = duration
    return spec


def _spec_network_latency(target: K8sTarget, duration_seconds: float | None, params: NetworkLatencyParams) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "action": "delay",
        "selector": _selector(target),
        **_mode_fields(target),
        "delay": {"latency": params.latency, "jitter": params.jitter, "correlation": params.correlation},
    }
    duration = _duration(duration_seconds)
    if duration:
        spec["duration"] = duration
    return spec


def _spec_packet_loss(target: K8sTarget, duration_seconds: float | None, params: PacketLossParams) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "action": "loss",
        "selector": _selector(target),
        **_mode_fields(target),
        "loss": {"loss": params.loss_percent, "correlation": params.correlation},
    }
    duration = _duration(duration_seconds)
    if duration:
        spec["duration"] = duration
    return spec


def _spec_io_delay(target: K8sTarget, duration_seconds: float | None, params: IODelayParams) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "action": "latency",
        "selector": _selector(target),
        **_mode_fields(target),
        "volumePath": params.volume_path,
        "path": params.path,
        "delay": params.delay,
        "percent": params.percent,
    }
    duration = _duration(duration_seconds)
    if duration:
        spec["duration"] = duration
    return spec


_BUILDERS = {
    ChaosMeshFaultType.POD_KILL: _spec_pod_kill,
    ChaosMeshFaultType.NETWORK_LATENCY: _spec_network_latency,
    ChaosMeshFaultType.PACKET_LOSS: _spec_packet_loss,
    ChaosMeshFaultType.IO_DELAY: _spec_io_delay,
}


def cr_name(scenario_id: str) -> str:
    """Scenario ids (`scn-<10 hex>`) are already valid DNS-1123 subdomains;
    prefixing keeps every Chaos Mesh object phoenix-chaos owns easy to spot
    and grep for (`kubectl get podchaos -A | grep phoenix-chaos`)."""
    return f"phoenix-chaos-{scenario_id}"


def build_manifest(scenario_id: str, fault_type: ChaosMeshFaultType, target: K8sTarget,
                   duration_seconds: float | None, params: BaseModel) -> dict[str, Any]:
    spec = _BUILDERS[fault_type](target, duration_seconds, params)
    return {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": _KIND[fault_type],
        "metadata": {
            "name": cr_name(scenario_id),
            "namespace": target.namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "phoenix-chaos",
                "phoenix.io/scenario-id": scenario_id,
            },
        },
        "spec": spec,
    }


def summarize_status(raw_status: dict[str, Any] | None) -> dict[str, Any] | None:
    """Chaos Mesh's `.status` carries a lot of internal bookkeeping
    (finalizers, instances, records...) — surface just the parts that say
    something genuinely useful about how the experiment is going."""
    if not raw_status:
        return None
    summary: dict[str, Any] = {}
    if "experiment" in raw_status:
        summary["experiment"] = raw_status["experiment"]
    conditions = raw_status.get("conditions")
    if conditions:
        summary["conditions"] = conditions
    return summary or None


# ---------------------------------------------------------------------------
# k8s API access — every call is a genuine create/get/delete against the
# cluster's CustomObjectsApi, run off the event loop like argus-agent does.
# ---------------------------------------------------------------------------

def _custom_objects_api():
    from kubernetes import client, config as k8s_config
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()
    return client.CustomObjectsApi()


def _is_not_found(exc: Exception) -> bool:
    status = getattr(exc, "status", None)
    return status == 404 or "not found" in str(exc).lower()


class ChaosMeshClient:
    """Applies/queries/deletes the real chaos-mesh.org CRDs that back our
    four Chaos Mesh fault types."""

    async def apply(self, scenario_id: str, fault_type: ChaosMeshFaultType, target: K8sTarget,
                    duration_seconds: float | None, params: BaseModel) -> tuple[str, dict[str, Any]]:
        manifest = build_manifest(scenario_id, fault_type, target, duration_seconds, params)
        plural = _PLURAL[fault_type]
        name = manifest["metadata"]["name"]

        def _create() -> None:
            api = _custom_objects_api()
            api.create_namespaced_custom_object(
                group=GROUP, version=VERSION, namespace=target.namespace, plural=plural, body=manifest,
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _create)
        return name, manifest

    async def get(self, fault_type: ChaosMeshFaultType, name: str, namespace: str) -> dict[str, Any] | None:
        plural = _PLURAL[fault_type]

        def _get() -> dict[str, Any] | None:
            api = _custom_objects_api()
            try:
                return api.get_namespaced_custom_object(
                    group=GROUP, version=VERSION, namespace=namespace, plural=plural, name=name,
                )
            except Exception as exc:
                if _is_not_found(exc):
                    return None
                raise

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get)

    async def delete(self, fault_type: ChaosMeshFaultType, name: str, namespace: str) -> None:
        plural = _PLURAL[fault_type]

        def _delete() -> None:
            api = _custom_objects_api()
            try:
                api.delete_namespaced_custom_object(
                    group=GROUP, version=VERSION, namespace=namespace, plural=plural, name=name,
                )
            except Exception as exc:
                if not _is_not_found(exc):
                    raise

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _delete)


chaos_mesh = ChaosMeshClient()

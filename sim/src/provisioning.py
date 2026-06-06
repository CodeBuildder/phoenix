"""
Provisioning Simulator — orchestration service
Copyright (c) 2026 Kaushikkumaran

Ties the resource store, lifecycle engine, and fault injector together behind
one set of operations. Routers are thin HTTP adapters over this module so the
provisioning rules stay testable independent of FastAPI.
"""

import asyncio

from config import config
from events import Severity, publish_event
from faults import FaultInjector, FaultType, injector
from lifecycle import LifecycleEngine, engine
from models import (
    InstanceProvisionRequest,
    Resource,
    ResourceType,
    SubnetCreateRequest,
    VolumeAttachRequest,
    VolumeCreateRequest,
    new_instance,
    new_subnet,
    new_volume,
)
from store import ResourceStore, store


class ResourceNotFoundError(Exception):
    pass


class InvalidStateError(Exception):
    pass


class QuotaExceededError(Exception):
    pass


def _quota_for(resource_type: ResourceType) -> int:
    return {
        ResourceType.VOLUME: config.VOLUME_QUOTA,
        ResourceType.SUBNET: config.SUBNET_QUOTA,
        ResourceType.INSTANCE: config.INSTANCE_QUOTA,
    }[resource_type]


class ProvisioningService:
    def __init__(self, store: ResourceStore, injector: FaultInjector, engine: LifecycleEngine) -> None:
        self._store = store
        self._injector = injector
        self._engine = engine

    # -- volumes ------------------------------------------------------------

    async def create_volume(self, req: VolumeCreateRequest) -> Resource:
        await self._check_create_quota(ResourceType.VOLUME, "create")
        resource = new_volume(req)
        await self._store.put(resource)
        self._launch(resource, "create")
        return resource

    async def attach_volume(self, volume_id: str, req: VolumeAttachRequest) -> Resource:
        volume = await self._require(volume_id, ResourceType.VOLUME)
        if volume.state != "available":
            raise InvalidStateError(f"volume {volume_id} is '{volume.state}', must be 'available' to attach")
        await self._require(req.instance_id, ResourceType.INSTANCE)
        volume.attributes["attached_to"] = req.instance_id
        volume.attributes["device"] = req.device
        self._launch(volume, "attach")
        return volume

    async def detach_volume(self, volume_id: str) -> Resource:
        volume = await self._require(volume_id, ResourceType.VOLUME)
        if volume.state != "in_use":
            raise InvalidStateError(f"volume {volume_id} is '{volume.state}', must be 'in_use' to detach")
        volume.attributes["attached_to"] = None
        volume.attributes["device"] = None
        self._launch(volume, "detach")
        return volume

    async def delete_volume(self, volume_id: str) -> Resource:
        volume = await self._require(volume_id, ResourceType.VOLUME)
        if volume.state not in ("available", "error", "degraded"):
            raise InvalidStateError(f"volume {volume_id} is '{volume.state}', detach it before deleting")
        self._launch(volume, "delete")
        return volume

    # -- subnets -------------------------------------------------------------

    async def create_subnet(self, req: SubnetCreateRequest) -> Resource:
        await self._check_create_quota(ResourceType.SUBNET, "create")
        resource = new_subnet(req)
        await self._store.put(resource)
        self._launch(resource, "create")
        return resource

    async def delete_subnet(self, subnet_id: str) -> Resource:
        subnet = await self._require(subnet_id, ResourceType.SUBNET)
        if subnet.state not in ("active", "error", "degraded"):
            raise InvalidStateError(f"subnet {subnet_id} is '{subnet.state}', cannot delete")
        self._launch(subnet, "delete")
        return subnet

    # -- instances ------------------------------------------------------------

    async def provision_instance(self, req: InstanceProvisionRequest) -> Resource:
        await self._check_create_quota(ResourceType.INSTANCE, "provision")
        if req.subnet_id is not None:
            await self._require(req.subnet_id, ResourceType.SUBNET)
        resource = new_instance(req)
        await self._store.put(resource)
        self._launch(resource, "provision")
        return resource

    async def deprovision_instance(self, instance_id: str) -> Resource:
        instance = await self._require(instance_id, ResourceType.INSTANCE)
        if instance.state not in ("running", "error", "degraded"):
            raise InvalidStateError(f"instance {instance_id} is '{instance.state}', cannot deprovision")
        self._launch(instance, "deprovision")
        return instance

    # -- shared ----------------------------------------------------------------

    async def _require(self, resource_id: str, expected_type: ResourceType) -> Resource:
        resource = await self._store.get(resource_id)
        if resource is None or resource.type != expected_type:
            raise ResourceNotFoundError(f"{expected_type.value} '{resource_id}' not found")
        return resource

    async def _check_create_quota(self, resource_type: ResourceType, operation: str) -> None:
        """Two ways to hit a quota wall: an explicitly registered `quota_limit`
        fault rule (the chaos engine's hook), or the simulator's own baseline
        per-type quota (so quota failures are part of the simulator's realism,
        not only something a fault rule can produce)."""
        component = f"sim.{resource_type.value}"

        rule = self._injector.resolve(resource_type, operation, fault_types={FaultType.QUOTA_LIMIT})
        if rule is not None:
            publish_event(
                "sim.fault.triggered",
                severity=Severity.MEDIUM,
                component=component,
                payload={
                    "operation": operation,
                    "fault_rule_id": rule.id,
                    "fault_type": FaultType.QUOTA_LIMIT.value,
                    "source": "fault_rule",
                },
                caused_by=rule.id,
                reason="quota_limit fault rule rejected the operation",
            )
            raise QuotaExceededError(f"{resource_type.value} quota exceeded (fault rule {rule.id})")

        limit = _quota_for(resource_type)
        current = await self._store.count(resource_type)
        if current >= limit:
            publish_event(
                "sim.lifecycle.rejected",
                severity=Severity.MEDIUM,
                component=component,
                payload={"operation": operation, "reason": "quota_limit", "limit": limit, "current": current},
            )
            raise QuotaExceededError(f"{resource_type.value} quota of {limit} reached ({current}/{limit})")

    def _launch(self, resource: Resource, operation: str) -> None:
        """Resolve any in-flight fault up front so the whole transition — not
        just its starting state — reflects it, then run it in the background."""
        fault = self._injector.resolve(
            resource.type,
            operation,
            fault_types={FaultType.LATENCY, FaultType.TRANSIENT_ERROR, FaultType.PARTIAL_FAILURE},
        )
        asyncio.create_task(self._engine.run(resource, operation, fault))


service = ProvisioningService(store=store, injector=injector, engine=engine)

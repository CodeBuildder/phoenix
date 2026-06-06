"""
Tests for the Provisioning Simulator's lifecycle engine and fault hooks.
Copyright (c) 2026 Kaushikkumaran

These exercise the scope checklist directly — realistic async lifecycle
transitions, and each of the four fault types (latency, transient_error,
partial_failure, quota_limit) doing what it says — through the service layer,
where transitions can be awaited deterministically instead of raced through
HTTP. test_api.py covers the HTTP contract on top of this.
"""

import asyncio

import pytest

from config import config
from faults import FaultRuleCreateRequest, injector
from models import (
    InstanceProvisionRequest,
    ResourceType,
    SubnetCreateRequest,
    VolumeAttachRequest,
    VolumeCreateRequest,
)
from provisioning import InvalidStateError, QuotaExceededError, ResourceNotFoundError, service
from store import store


async def _wait_for_state(resource_id: str, *states: str, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        resource = await store.get(resource_id)
        if resource is not None and resource.state in states:
            return
        if loop.time() > deadline:
            raise AssertionError(
                f"{resource_id} did not reach {states} within {timeout}s "
                f"(last seen: {resource.state if resource else 'missing'})"
            )
        await asyncio.sleep(0.01)


class TestVolumeLifecycle:
    async def test_create_attach_detach_delete(self):
        instance = await service.provision_instance(InstanceProvisionRequest(name="host"))
        await _wait_for_state(instance.id, "running")

        volume = await service.create_volume(VolumeCreateRequest(name="vol", size_gb=50))
        assert volume.state == "creating"
        await _wait_for_state(volume.id, "available")

        await service.attach_volume(volume.id, VolumeAttachRequest(instance_id=instance.id))
        await _wait_for_state(volume.id, "in_use")
        attached = await store.get(volume.id)
        assert attached.attributes["attached_to"] == instance.id

        await service.detach_volume(volume.id)
        await _wait_for_state(volume.id, "available")
        detached = await store.get(volume.id)
        assert detached.attributes["attached_to"] is None

        await service.delete_volume(volume.id)
        await _wait_for_state(volume.id, "deleted")

    async def test_attach_requires_existing_instance(self):
        volume = await service.create_volume(VolumeCreateRequest(name="vol", size_gb=10))
        await _wait_for_state(volume.id, "available")
        with pytest.raises(ResourceNotFoundError):
            await service.attach_volume(volume.id, VolumeAttachRequest(instance_id="inst-ghost"))

    async def test_cannot_delete_twice(self):
        volume = await service.create_volume(VolumeCreateRequest(name="vol", size_gb=10))
        await _wait_for_state(volume.id, "available")
        await service.delete_volume(volume.id)
        await _wait_for_state(volume.id, "deleted")
        with pytest.raises(InvalidStateError):
            await service.delete_volume(volume.id)


class TestSubnetLifecycle:
    async def test_create_then_delete(self):
        subnet = await service.create_subnet(
            SubnetCreateRequest(name="app", cidr="10.0.2.0/24", vlan_id=200)
        )
        assert subnet.state == "creating"
        await _wait_for_state(subnet.id, "active")

        await service.delete_subnet(subnet.id)
        await _wait_for_state(subnet.id, "deleted")


class TestInstanceLifecycle:
    async def test_provision_then_deprovision(self):
        instance = await service.provision_instance(InstanceProvisionRequest(name="host"))
        assert instance.state == "provisioning"
        await _wait_for_state(instance.id, "running")

        await service.deprovision_instance(instance.id)
        await _wait_for_state(instance.id, "terminated")

    async def test_provision_into_subnet_records_link(self):
        subnet = await service.create_subnet(
            SubnetCreateRequest(name="app", cidr="10.0.3.0/24", vlan_id=300)
        )
        await _wait_for_state(subnet.id, "active")

        instance = await service.provision_instance(
            InstanceProvisionRequest(name="host", subnet_id=subnet.id)
        )
        assert instance.attributes["subnet_id"] == subnet.id


class TestFaultInjection:
    async def test_transient_error_drives_resource_to_error(self):
        injector.register(FaultRuleCreateRequest(
            fault_type="transient_error", resource_type="volume", operation="create",
        ))
        volume = await service.create_volume(VolumeCreateRequest(name="vol", size_gb=10))
        await _wait_for_state(volume.id, "error")

    async def test_partial_failure_stalls_mid_transition(self):
        injector.register(FaultRuleCreateRequest(
            fault_type="partial_failure", resource_type="instance", operation="provision",
        ))
        instance = await service.provision_instance(InstanceProvisionRequest(name="host"))
        await _wait_for_state(instance.id, "degraded")
        # it should stay degraded — partial failure means it never reaches "running"
        await asyncio.sleep(0.05)
        stalled = await store.get(instance.id)
        assert stalled.state == "degraded"

    async def test_latency_extends_delay_but_still_completes(self):
        injector.register(FaultRuleCreateRequest(
            fault_type="latency", resource_type="subnet", operation="create",
            params={"extra_seconds": 0.05},
        ))
        subnet = await service.create_subnet(
            SubnetCreateRequest(name="slow", cidr="10.0.4.0/24", vlan_id=400)
        )
        await _wait_for_state(subnet.id, "active", timeout=3.0)

    async def test_quota_limit_fault_rejects_before_resource_exists(self):
        injector.register(FaultRuleCreateRequest(fault_type="quota_limit", resource_type="volume"))
        with pytest.raises(QuotaExceededError):
            await service.create_volume(VolumeCreateRequest(name="vol", size_gb=10))
        assert await store.count(ResourceType.VOLUME) == 0

    async def test_baseline_quota_rejects_once_limit_reached(self, monkeypatch):
        monkeypatch.setattr(config, "VOLUME_QUOTA", 1)
        first = await service.create_volume(VolumeCreateRequest(name="v1", size_gb=10))
        await _wait_for_state(first.id, "available")
        with pytest.raises(QuotaExceededError):
            await service.create_volume(VolumeCreateRequest(name="v2", size_gb=10))
        assert await store.count(ResourceType.VOLUME) == 1

    async def test_fault_rules_only_match_their_target(self):
        injector.register(FaultRuleCreateRequest(
            fault_type="transient_error", resource_type="instance", operation="provision",
        ))
        # a volume create should be unaffected by an instance-scoped rule
        volume = await service.create_volume(VolumeCreateRequest(name="vol", size_gb=10))
        await _wait_for_state(volume.id, "available")

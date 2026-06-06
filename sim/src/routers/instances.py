"""
Provisioning Simulator — instance API
Copyright (c) 2026 Kaushikkumaran
"""

from fastapi import APIRouter, HTTPException

from models import InstanceProvisionRequest, Resource, ResourceType
from provisioning import InvalidStateError, QuotaExceededError, ResourceNotFoundError, service
from store import store

router = APIRouter(prefix="/instances", tags=["instances"])


@router.get("")
async def list_instances() -> dict:
    instances = await store.list(ResourceType.INSTANCE)
    return {"instances": instances, "total": len(instances)}


@router.get("/{instance_id}")
async def get_instance(instance_id: str) -> Resource:
    instance = await store.get(instance_id)
    if instance is None or instance.type != ResourceType.INSTANCE:
        raise HTTPException(status_code=404, detail=f"instance '{instance_id}' not found")
    return instance


@router.post("", status_code=202)
async def provision_instance(req: InstanceProvisionRequest) -> Resource:
    try:
        return await service.provision_instance(req)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@router.delete("/{instance_id}", status_code=202)
async def deprovision_instance(instance_id: str) -> Resource:
    try:
        return await service.deprovision_instance(instance_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

"""
Provisioning Simulator — VLAN/subnet API
Copyright (c) 2026 Kaushikkumaran
"""

from fastapi import APIRouter, HTTPException

from models import Resource, ResourceType, SubnetCreateRequest
from provisioning import InvalidStateError, QuotaExceededError, ResourceNotFoundError, service
from store import store

router = APIRouter(prefix="/subnets", tags=["subnets"])


@router.get("")
async def list_subnets() -> dict:
    subnets = await store.list(ResourceType.SUBNET)
    return {"subnets": subnets, "total": len(subnets)}


@router.get("/{subnet_id}")
async def get_subnet(subnet_id: str) -> Resource:
    subnet = await store.get(subnet_id)
    if subnet is None or subnet.type != ResourceType.SUBNET:
        raise HTTPException(status_code=404, detail=f"subnet '{subnet_id}' not found")
    return subnet


@router.post("", status_code=202)
async def create_subnet(req: SubnetCreateRequest) -> Resource:
    try:
        return await service.create_subnet(req)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@router.delete("/{subnet_id}", status_code=202)
async def delete_subnet(subnet_id: str) -> Resource:
    try:
        return await service.delete_subnet(subnet_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

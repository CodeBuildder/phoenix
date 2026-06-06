"""
Provisioning Simulator — volume API
Copyright (c) 2026 Kaushikkumaran
"""

from fastapi import APIRouter, HTTPException

from models import Resource, ResourceType, VolumeAttachRequest, VolumeCreateRequest
from provisioning import InvalidStateError, QuotaExceededError, ResourceNotFoundError, service
from store import store

router = APIRouter(prefix="/volumes", tags=["volumes"])


@router.get("")
async def list_volumes() -> dict:
    volumes = await store.list(ResourceType.VOLUME)
    return {"volumes": volumes, "total": len(volumes)}


@router.get("/{volume_id}")
async def get_volume(volume_id: str) -> Resource:
    volume = await store.get(volume_id)
    if volume is None or volume.type != ResourceType.VOLUME:
        raise HTTPException(status_code=404, detail=f"volume '{volume_id}' not found")
    return volume


@router.post("", status_code=202)
async def create_volume(req: VolumeCreateRequest) -> Resource:
    try:
        return await service.create_volume(req)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@router.post("/{volume_id}/attach", status_code=202)
async def attach_volume(volume_id: str, req: VolumeAttachRequest) -> Resource:
    try:
        return await service.attach_volume(volume_id, req)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{volume_id}/detach", status_code=202)
async def detach_volume(volume_id: str) -> Resource:
    try:
        return await service.detach_volume(volume_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/{volume_id}", status_code=202)
async def delete_volume(volume_id: str) -> Resource:
    try:
        return await service.delete_volume(volume_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

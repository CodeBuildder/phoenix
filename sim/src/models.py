"""
Provisioning Simulator — resource models
Copyright (c) 2026 Kaushikkumaran

Pydantic models for the three resource families the simulator provisions:
volumes, subnets (VLAN/subnet), and instances. Each carries a `state` field
that the lifecycle engine (lifecycle.py) drives asynchronously through a
realistic sequence of transitional -> terminal states.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ResourceType(str, Enum):
    VOLUME = "volume"
    SUBNET = "subnet"
    INSTANCE = "instance"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Resource(BaseModel):
    """Common shape every simulated resource shares — what the `/state`
    snapshot endpoint and the dashboard's "what exists right now" view read."""
    id: str
    type: ResourceType
    name: str
    state: str
    zone: str
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    attributes: dict[str, Any] = Field(default_factory=dict)

    def touch(self, *, state: str | None = None, **attrs: Any) -> None:
        if state is not None:
            self.state = state
        if attrs:
            self.attributes.update(attrs)
        self.updated_at = _now()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class VolumeCreateRequest(BaseModel):
    name: str
    size_gb: int = Field(gt=0, le=16384)
    volume_type: str = "standard"
    zone: str = "zone-a"


class VolumeAttachRequest(BaseModel):
    instance_id: str
    device: str = "/dev/sdb"


class SubnetCreateRequest(BaseModel):
    name: str
    cidr: str
    vlan_id: int = Field(ge=1, le=4094)
    zone: str = "zone-a"


class InstanceProvisionRequest(BaseModel):
    name: str
    instance_type: str = "standard.small"
    subnet_id: str | None = None
    zone: str = "zone-a"


# ---------------------------------------------------------------------------
# Constructors — each starts a resource in its first transitional state;
# the lifecycle engine takes it from there.
# ---------------------------------------------------------------------------

def new_volume(req: VolumeCreateRequest) -> Resource:
    return Resource(
        id=_new_id("vol"),
        type=ResourceType.VOLUME,
        name=req.name,
        state="creating",
        zone=req.zone,
        attributes={
            "size_gb": req.size_gb,
            "volume_type": req.volume_type,
            "attached_to": None,
            "device": None,
        },
    )


def new_subnet(req: SubnetCreateRequest) -> Resource:
    return Resource(
        id=_new_id("snet"),
        type=ResourceType.SUBNET,
        name=req.name,
        state="creating",
        zone=req.zone,
        attributes={
            "cidr": req.cidr,
            "vlan_id": req.vlan_id,
        },
    )


def new_instance(req: InstanceProvisionRequest) -> Resource:
    return Resource(
        id=_new_id("inst"),
        type=ResourceType.INSTANCE,
        name=req.name,
        state="provisioning",
        zone=req.zone,
        attributes={
            "instance_type": req.instance_type,
            "subnet_id": req.subnet_id,
        },
    )

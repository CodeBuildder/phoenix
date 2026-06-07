"""
Phoenix Agent — data models
Copyright (c) 2026 Kaushikkumaran
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentNode(str, Enum):
    DETECT    = "detect"
    DIAGNOSE  = "diagnose"
    HEAL_PLAN = "heal_plan"
    APPROVE   = "approve"
    EXECUTE   = "execute"
    VERIFY    = "verify"
    REPORT    = "report"
    DONE      = "done"
    ABORTED   = "aborted"
    ERROR     = "error"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING      = "pending"
    APPROVED     = "approved"
    REJECTED     = "rejected"


class DiagnosisResult(BaseModel):
    causal_chain:       str
    recommended_action: str   # "restart_deployment" | "stop_scenario" | "scale_deployment"
    action_target:      str   # deployment name or scenario id
    risk:               str   # "low" | "high"
    rationale:          str


class AgentRun(BaseModel):
    scenario_id:     str
    scenario:        dict[str, Any] = Field(default_factory=dict)
    blast_radius:    dict[str, Any] | None = None
    catalog_entry:   dict[str, Any] | None = None
    memory_context:  str | None = None
    diagnosis:       DiagnosisResult | None = None
    action_result:   str | None = None
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    verify_result:   str | None = None
    node:            AgentNode = AgentNode.DETECT
    error:           str | None = None
    started_at:      str = Field(default_factory=_now)
    updated_at:      str = Field(default_factory=_now)
    completed_at:    str | None = None
    mttr_seconds:    float | None = None

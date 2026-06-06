"""
Provisioning Simulator — fault-injection control API
Copyright (c) 2026 Kaushikkumaran

This is the surface issue #2's chaos engine drives to trigger "simulator
faults" alongside Chaos Mesh experiments through one control surface: register
a rule, list active rules, clear one or all of them.
"""

from fastapi import APIRouter, HTTPException

from faults import FaultRule, FaultRuleCreateRequest, injector

router = APIRouter(prefix="/faults", tags=["faults"])


@router.get("")
async def list_fault_rules() -> dict:
    rules = injector.list()
    return {"rules": rules, "total": len(rules)}


@router.post("", status_code=201)
async def register_fault_rule(req: FaultRuleCreateRequest) -> FaultRule:
    return injector.register(req)


@router.delete("/{rule_id}", status_code=204)
async def clear_fault_rule(rule_id: str) -> None:
    if not injector.clear(rule_id):
        raise HTTPException(status_code=404, detail=f"fault rule '{rule_id}' not found")


@router.delete("", status_code=200)
async def clear_all_fault_rules() -> dict:
    return {"cleared": injector.clear_all()}

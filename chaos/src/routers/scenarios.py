"""
Chaos Injection Engine — scenario control API
Copyright (c) 2026 Kaushikkumaran

The "start/stop/status API used by both the agent (M2) and dashboard (M3)"
the M1 issue calls for: one surface to launch, list, inspect, stop, and
remove a scenario regardless of whether it runs through Chaos Mesh or the
Provisioning Simulator.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from engine import BackendError, InvalidScenarioStateError, ScenarioNotFoundError, engine
from models import Scenario, ScenarioCreateRequest, ScenarioStatus

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
async def list_scenarios(status: Annotated[ScenarioStatus | None, Query()] = None) -> dict:
    scenarios = await engine.list(status=status)
    return {"scenarios": scenarios, "total": len(scenarios)}


@router.get("/{scenario_id}")
async def get_scenario(scenario_id: str) -> Scenario:
    try:
        return await engine.get(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("", status_code=201)
async def start_scenario(req: ScenarioCreateRequest) -> Scenario:
    try:
        return await engine.start(req)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{scenario_id}/stop")
async def stop_scenario(scenario_id: str) -> Scenario:
    try:
        return await engine.stop(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidScenarioStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.delete("/{scenario_id}", status_code=204)
async def remove_scenario(scenario_id: str) -> None:
    try:
        await engine.remove(scenario_id)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidScenarioStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

"""
Fault Library & Taxonomy Classifier — API
Copyright (c) 2026 Kaushikkumaran

Three endpoints, one per piece of the M1 issue:
  GET  /catalog              — the static fault library
  POST /classify             — the taxonomy classifier, by structural signature
  GET  /rankings             — live failure-mode-frequency ranking, over real
                               /chaos scenario history
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

import aggregator
import catalog
import classifier
from chaos_client import ChaosClientError, chaos
from models import Classification, FaultCatalogEntry, RankingsResponse, ScenarioDomain

router = APIRouter(tags=["fault-library"])


@router.get("/catalog")
async def get_catalog(domain: Annotated[ScenarioDomain | None, Query()] = None) -> dict:
    entries = catalog.for_domain(domain) if domain is not None else catalog.all_entries()
    return {"entries": entries, "total": len(entries)}


@router.get("/catalog/{domain}/{fault_type}")
async def get_catalog_entry(domain: ScenarioDomain, fault_type: str) -> FaultCatalogEntry:
    entry = catalog.lookup(domain, fault_type)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no catalog entry for {domain.value}/{fault_type}")
    return entry


@router.post("/classify")
async def classify_failure(domain: ScenarioDomain, fault_type: str) -> Classification:
    result = classifier.classify(domain, fault_type)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"no fault library entry for {domain.value}/{fault_type} — nothing to classify it against",
        )
    return result


@router.get("/rankings")
async def get_rankings() -> RankingsResponse:
    try:
        scenarios = await chaos.list_scenarios()
    except ChaosClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return aggregator.build_rankings(scenarios)

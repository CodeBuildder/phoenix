"""
Fault Library & Taxonomy Classifier — rankings aggregator
Copyright (c) 2026 Kaushikkumaran

"Aggregation that ranks components/datacenters by failure-mode frequency" —
the M1 issue's words, minus "datacenters": this cluster has no real notion of
one (it's three k3s nodes; phoenix-sim's "zones" aren't carried on a chaos
scenario's target — see SimulatorTarget in chaos/src/models.py), and
inventing a grouping axis the data can't actually support would be exactly
the kind of fabrication the project must never produce. "Component" is the
one grouping axis every scenario's `target` genuinely carries — see
`derive_component` below for precisely how it's read off the real record.

Every number this module produces is `len(...)` or `+= 1` over scenario
records fetched live from `/chaos` moments earlier. There is no store, no
cache, no scheduled recomputation: call `/rankings` twice in a row and you
get two independent live tallies, which will differ the instant a new
scenario starts, ends, or gets removed in between.
"""

from __future__ import annotations

from typing import Any

import classifier
from models import CategoryTally, ComponentRanking, RankingsResponse, ScenarioDomain


def derive_component(domain: ScenarioDomain, target: dict[str, Any]) -> str:
    """
    Read a human-meaningful "what did this fault actually point at" label
    straight off the scenario's real `target` — never invented, never
    resolved against some other system's notion of identity.

    chaos_mesh targets are K8sTarget-shaped ({namespace, label_selector, …});
    the most specific real identity available is "namespace + the labels that
    picked the pod(s)". simulator targets are SimulatorTarget-shaped
    ({resource_type, operation}); the most specific real identity available
    is "which kind of resource, doing which operation". Either way, what you
    get back is assembled only from fields that were actually present on the
    real request — nothing here is guessed when a field is missing.
    """
    if domain == ScenarioDomain.CHAOS_MESH:
        namespace = target.get("namespace") or "(no namespace)"
        selector = target.get("label_selector") or {}
        if selector:
            labels = ",".join(f"{k}={v}" for k, v in sorted(selector.items()))
            return f"{namespace}/{labels}"
        return namespace

    resource_type = target.get("resource_type")
    operation = target.get("operation")
    if resource_type and operation:
        return f"{resource_type}/{operation}"
    if resource_type:
        return f"{resource_type}/*"
    if operation:
        return f"*/{operation}"
    return "(unscoped simulator rule)"


def _actually_ran(scenario: dict[str, Any]) -> bool:
    """Only a scenario that reached `running` at some point represents a
    fault that genuinely executed against its backend — `started_at` is the
    field `Scenario.touch_status` sets exactly then (chaos/src/models.py).
    A `pending`/`failed-before-launch` record describes an *attempt*, not an
    observed failure mode of the targeted component, so it's excluded from
    the tally rather than counted as one."""
    return scenario.get("started_at") is not None


def build_rankings(scenarios: list[dict[str, Any]]) -> RankingsResponse:
    by_key: dict[tuple[str, str], ComponentRanking] = {}
    considered = 0
    excluded = 0

    for scenario in scenarios:
        if not _actually_ran(scenario):
            excluded += 1
            continue

        domain_raw = scenario.get("domain")
        try:
            domain = ScenarioDomain(domain_raw)
        except ValueError:
            excluded += 1
            continue

        result = classifier.classify(domain, scenario.get("fault_type", ""))
        if result is None:
            excluded += 1
            continue

        considered += 1
        component = derive_component(domain, scenario.get("target") or {})
        key = (component, domain.value)
        ranking = by_key.get(key)
        if ranking is None:
            ranking = ComponentRanking(component=component, domain=domain, tally=CategoryTally(), total=0)
            by_key[key] = ranking
        ranking.tally.bump(result.taxonomy_category)
        ranking.total += 1

    rankings = sorted(by_key.values(), key=lambda r: (-r.total, r.component))
    return RankingsResponse(rankings=rankings, scenarios_considered=considered, scenarios_excluded=excluded)

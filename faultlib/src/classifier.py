"""
Fault Library & Taxonomy Classifier — the classifier
Copyright (c) 2026 Kaushikkumaran

"An auto-classifier that labels every induced or real failure" — the M1
issue's words. The thing being classified can be:
  * an induced scenario `/chaos` actually ran (the only kind that exists
    today), or
  * a real failure some future detector reports (M2's agent, argus, …) —
    which won't have a `Scenario` record at all, but unavoidably *will* have
    a domain and a fault-type-shaped signature, because that's the minimum
    description of "what kind of bad thing happened" in this system

So the classifier is deliberately decoupled from `Scenario` — it takes only
the two facts true of *any* failure description in this system and returns a
deterministic label for it. There is nothing probabilistic, learned, or
inferred about it: `classify` returning `None` for an uncatalogued fault type
is the load-bearing guarantee — a fault type this library has never been told
about gets no label at all, not a best-effort one invented on the spot.
"""

from __future__ import annotations

import catalog
from models import Classification, ScenarioDomain


def classify(domain: ScenarioDomain, fault_type: str) -> Classification | None:
    """Look up `(domain, fault_type)` in the fault library and return its
    catalogued classification — or `None` if this is a fault type the
    library has never been told about. Returning `None` here (rather than
    falling back to some default category) is the whole point: a label this
    service can't justify by pointing at a catalog entry is not a label this
    service will produce."""
    entry = catalog.lookup(domain, fault_type)
    if entry is None:
        return None
    return Classification(
        domain=entry.domain,
        fault_type=entry.fault_type,
        taxonomy_category=entry.taxonomy_category,
        rationale=entry.category_rationale,
    )

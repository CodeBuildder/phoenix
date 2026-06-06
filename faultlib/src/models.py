"""
Fault Library & Taxonomy Classifier — models
Copyright (c) 2026 Kaushikkumaran

Three shapes, one for each piece the M1 issue asks for:
  * `FaultCatalogEntry` — one row of the static fault library (issue #3's
    "structured catalog of every fault Chaos Mesh + the provisioning
    simulator can produce, with metadata")
  * `Classification` — the taxonomy label issue #3's classifier assigns to
    a failure, identified purely by its *structural signature*
    (`domain` + `fault_type` — the only two facts true of every failure
    `/chaos` can launch, and the only two this module ever needs)
  * `ComponentRanking` / `RankingsResponse` — the "rank components by
    failure-mode frequency" aggregation, always computed live over real
    `/chaos` scenario history (see `aggregator.py`)

Mirrors `phoenix-chaos`'s `ScenarioDomain` enum exactly (duplicated rather
than imported — independently deployed services, no shared package, same
reasoning chaos/src/models.py gives for duplicating phoenix-sim's FaultType).
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScenarioDomain(str, Enum):
    CHAOS_MESH = "chaos_mesh"
    SIMULATOR = "simulator"


class TaxonomyCategory(str, Enum):
    """The five failure-mode labels named in the M1 issue scope, verbatim."""
    TRANSIENT = "transient"
    CASCADING = "cascading"
    RESOURCE_EXHAUSTION = "resource-exhaustion"
    NETWORK_PARTITION = "network-partition"
    QUOTA_LIMIT = "quota-limit"


class FaultCatalogEntry(BaseModel):
    """
    One entry in the fault library — everything we *know* about a fault type
    before a single instance of it has ever run. This is mechanical domain
    knowledge (what the fault does, and what that produces structurally), the
    same kind of verified-against-reality reference material as chaos/README's
    CRD field-mapping table — not a measurement, not a statistic, and
    deliberately free of any number that would imply one (no frequencies, no
    durations, no percentages: those can only ever come from real observed
    scenarios, via `/rankings`).
    """
    domain: ScenarioDomain
    fault_type: str
    mechanism: str               # what actually executes the fault (CRD+action, or simulator fault hook)
    description: str             # what the fault mechanically does
    blast_radius_shape: str      # structurally, what kind of thing it can reach
    typical_symptoms: list[str]  # observable signs grounded in that mechanism — not measured rates
    taxonomy_category: TaxonomyCategory
    category_rationale: str      # *why* this fault type maps to that category — kept next to the
                                 # mapping so the classifier's lookup table is auditable, not opaque


class Classification(BaseModel):
    """
    The classifier's output for one failure, identified by its structural
    signature alone. Deterministic and reproducible: the same
    (domain, fault_type) always yields the same category, because the
    mapping is a fixed property of *how the fault works* — not a statistical
    inference drawn from (and liable to be skewed by) however much or little
    history happens to exist for it yet.
    """
    domain: ScenarioDomain
    fault_type: str
    taxonomy_category: TaxonomyCategory
    rationale: str


class CategoryTally(BaseModel):
    """How many real, terminal-or-running scenarios against one component
    landed in each taxonomy category. Every count here is `len(...)` over
    actual `/chaos` scenario records — never estimated, never backfilled."""
    transient: int = 0
    cascading: int = 0
    resource_exhaustion: int = 0
    network_partition: int = 0
    quota_limit: int = 0

    def bump(self, category: TaxonomyCategory) -> None:
        field = category.value.replace("-", "_")
        setattr(self, field, getattr(self, field) + 1)

    @property
    def total(self) -> int:
        return self.transient + self.cascading + self.resource_exhaustion + self.network_partition + self.quota_limit


class ComponentRanking(BaseModel):
    """One component's real failure-mode tally — `component` is derived
    purely from the real `target` of each scenario that named it (see
    `aggregator.derive_component`); nothing here is grouped by a dimension
    (e.g. "datacenter") that the underlying scenario data doesn't actually
    carry. See faultlib/README.md for why "datacenter" isn't a ranking axis."""
    component: str
    domain: ScenarioDomain
    tally: CategoryTally
    total: int


class RankingsResponse(BaseModel):
    """
    The M3 "failure-mode catalog panel" feed and the M2 "rank the fleet's
    weakest areas" signal — a live snapshot, not a stored report. Re-running
    this immediately after `/chaos` launches a new scenario reflects it;
    re-running it against an empty `/chaos` (nothing ever launched) returns
    an empty `rankings` list and `scenarios_considered: 0` — the genuinely
    correct answer for "what has this fleet experienced so far", and not
    something this service will ever paper over with seeded examples.
    """
    rankings: list[ComponentRanking]
    scenarios_considered: int
    scenarios_excluded: int   # recorded but never actually started — see aggregator.py
    generated_at: str = Field(default_factory=_now)

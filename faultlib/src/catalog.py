"""
Fault Library & Taxonomy Classifier — the fault catalog
Copyright (c) 2026 Kaushikkumaran

The "structured catalog of every fault Chaos Mesh + the provisioning
simulator can produce, with metadata (blast-radius shape, typical symptoms)"
the M1 issue calls for.

Every entry below describes *mechanism*, not *measurement* — what the fault
actually does and what kind of thing that can structurally reach, grounded in
the same verified mechanics chaos/README documents (its CRD field-mapping
table was checked directly against the live cluster's installed CRD schemas;
the simulator entries are grounded in sim/src/faults.py's documented fault
hooks). Deliberately absent: any number that would imply a measurement —
no frequencies, no percentages, no durations, no "affects N services on
average". Those would be exactly the kind of fabricated statistic this
project must never produce; the only place real numbers about faults appear
is `/rankings`, and there every one of them is a live tally over scenarios
that actually ran (see aggregator.py).

`taxonomy_category` is the classifier's entire lookup table (classifier.py
just indexes into CATALOG by (domain, fault_type) and returns it) — so the
mapping rationale lives right here, next to the fact it explains, where it's
auditable rather than buried in branchy classification logic.
"""

from models import FaultCatalogEntry, ScenarioDomain, TaxonomyCategory

CATALOG: list[FaultCatalogEntry] = [
    # ---------------------------------------------------------------
    # chaos_mesh domain — real chaos-mesh.org/v1alpha1 CRDs (see
    # chaos/README.md's CRD field-mapping table for how each is built)
    # ---------------------------------------------------------------
    FaultCatalogEntry(
        domain=ScenarioDomain.CHAOS_MESH,
        fault_type="pod_kill",
        mechanism="PodChaos (action: pod-kill) — Chaos Mesh's controller deletes the "
                  "selected pod(s) outright; the kubelet/scheduler then do whatever they "
                  "would for any other pod loss.",
        description="Removes one or more running pods from the cluster without warning, "
                    "the same way an OOM kill, node failure, or `kubectl delete pod` would.",
        blast_radius_shape="The targeted pod(s), every in-flight connection/request they "
                           "were holding, and — transitively — every client and downstream "
                           "dependency whose calls were resting on those connections.",
        typical_symptoms=[
            "in-flight requests reset mid-response",
            "upstream callers see connection refused/reset until a replacement pod is ready",
            "load-balancer / service endpoints churn as the pod is deregistered and replaced",
            "readiness-probe failures and a visible rescheduling event in pod history",
        ],
        taxonomy_category=TaxonomyCategory.CASCADING,
        category_rationale="Killing a pod doesn't fail in place — its in-flight work and "
                           "open connections propagate the failure outward to whoever was "
                           "depending on it, which is the defining shape of a cascading fault.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.CHAOS_MESH,
        fault_type="network_latency",
        mechanism="NetworkChaos (action: delay) — Chaos Mesh installs `tc`/netem queuing "
                  "rules on the selected pod's network namespace that hold packets for "
                  "`delay.latency` (± `delay.jitter`, with `delay.correlation`) before "
                  "they're sent.",
        description="Adds artificial delay to every packet leaving (or, depending on "
                    "direction, arriving at) the targeted pod's network interface.",
        blast_radius_shape="Every network path between the targeted pod(s) and whichever "
                           "peers the experiment's direction covers — not the pod itself, "
                           "but the *links* it sits on.",
        typical_symptoms=[
            "elevated p95/p99 latency on calls that cross the affected link",
            "client-side timeouts and retry storms once delay exceeds configured timeouts",
            "queueing/backpressure building up on both sides of the slowed link",
        ],
        taxonomy_category=TaxonomyCategory.NETWORK_PARTITION,
        category_rationale="Both NetworkChaos fault types in this catalog (`network_latency`, "
                           "`packet_loss`) degrade the *network path* rather than the "
                           "endpoints on either side of it — the only category here that "
                           "names the network itself as the fault's locus is network-partition, "
                           "so degraded-but-not-fully-severed paths are grouped there too.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.CHAOS_MESH,
        fault_type="packet_loss",
        mechanism="NetworkChaos (action: loss) — Chaos Mesh installs netem rules that "
                  "drop a configured fraction (`loss.loss`, with `loss.correlation`) of "
                  "packets on the selected pod's network namespace.",
        description="Silently drops a portion of the packets crossing the targeted pod's "
                    "network interface — the sender gets no immediate signal that anything "
                    "was lost.",
        blast_radius_shape="Every network path between the targeted pod(s) and whichever "
                           "peers the experiment's direction covers — like network_latency, "
                           "this is a property of the link, not either endpoint.",
        typical_symptoms=[
            "TCP retransmits and reduced effective throughput on the affected link",
            "intermittent, hard-to-reproduce connection failures ('it works when I try it now')",
            "protocols without their own retry logic seeing outright data loss",
        ],
        taxonomy_category=TaxonomyCategory.NETWORK_PARTITION,
        category_rationale="Same reasoning as network_latency: the fault's locus is the "
                           "network path itself, and network-partition is the only category "
                           "naming that — a packet-loss link is a partial partition.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.CHAOS_MESH,
        fault_type="io_delay",
        mechanism="IOChaos (action: latency) — Chaos Mesh's sidecar intercepts filesystem "
                  "calls under `volumePath`/`path` on the selected pod and holds a "
                  "configured `percent` of them for `delay` before letting them through.",
        description="Adds artificial latency to a portion of the targeted pod's filesystem "
                    "operations against the selected volume path.",
        blast_radius_shape="The targeted pod's mounted volume, and every process inside that "
                           "pod whose request-handling path touches disk on it (reads, "
                           "writes, log flushes, anything that `fsync`s before responding).",
        typical_symptoms=[
            "elevated request latency specifically on code paths that touch disk "
            "(writes, log flushes, cache spills) while CPU/network look normal",
            "slow startup / readiness if the workload reads config or state from disk on boot",
            "growing write-buffer / queue depth as disk operations back up",
        ],
        taxonomy_category=TaxonomyCategory.RESOURCE_EXHAUSTION,
        category_rationale="From the application's vantage point, slow disk *is* a "
                           "saturated resource — the symptoms (queueing, backpressure, "
                           "growing latency under load) are indistinguishable from the "
                           "disk genuinely running out of throughput, which is what "
                           "resource-exhaustion names.",
    ),

    # ---------------------------------------------------------------
    # simulator domain — phoenix-sim's /faults hooks (see
    # sim/src/faults.py for exactly how each is applied)
    # ---------------------------------------------------------------
    FaultCatalogEntry(
        domain=ScenarioDomain.SIMULATOR,
        fault_type="latency",
        mechanism="A registered FaultRule matching {resource_type, operation} stretches "
                  "that operation's simulated processing delay before it resolves.",
        description="Makes a matched provisioning operation (e.g. volume create, instance "
                    "provision) take noticeably longer to reach its next lifecycle state "
                    "than it normally would.",
        blast_radius_shape="Every simulated operation matching the rule's "
                           "{resource_type, operation} filter, and whatever in the agent "
                           "or dashboard is waiting on that operation's completion.",
        typical_symptoms=[
            "the matched operation's lifecycle visibly stalls in its 'in transition' state "
            "longer than its peers",
            "callers polling for completion see repeated not-done-yet responses",
            "knock-on timeouts in anything that assumed the operation would finish promptly",
        ],
        taxonomy_category=TaxonomyCategory.TRANSIENT,
        category_rationale="The operation still completes — it's just slow. A fault that "
                           "resolves on its own without leaving lasting damage is the "
                           "textbook definition of transient.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.SIMULATOR,
        fault_type="transient_error",
        mechanism="A registered FaultRule causes the matched operation to fail *after* "
                  "starting — its resource lands in the 'error' lifecycle state rather "
                  "than completing normally.",
        description="A matched provisioning operation begins, then fails partway through, "
                    "leaving its resource in an explicit error state rather than the "
                    "state it was trying to reach.",
        blast_radius_shape="The specific resource the failed operation was acting on, and "
                           "anything that had already started depending on that resource "
                           "existing (e.g. an instance waiting on a volume attach).",
        typical_symptoms=[
            "an operation that was progressing normally suddenly reports 'error' instead "
            "of its expected terminal state",
            "the resource is left in a state that needs an explicit retry or cleanup — "
            "it doesn't recover on its own",
            "downstream operations that assumed success start failing their own preconditions",
        ],
        taxonomy_category=TaxonomyCategory.TRANSIENT,
        category_rationale="Despite the lasting 'error' state on the one resource it hit, "
                           "the *fault condition itself* is a one-shot event with no "
                           "self-reinforcing or spreading mechanism — re-running the same "
                           "operation a moment later is expected to simply succeed, which "
                           "is what distinguishes a transient failure from a cascading one.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.SIMULATOR,
        fault_type="partial_failure",
        mechanism="A registered FaultRule causes the matched operation to stall mid-"
                  "transition — its resource lands in the 'degraded' lifecycle state, "
                  "neither fully provisioned nor cleanly failed.",
        description="A matched provisioning operation gets partway to its goal and then "
                    "stops — the resource exists, but in a half-finished, degraded form "
                    "that nothing downstream can rely on.",
        blast_radius_shape="The half-finished resource itself, plus everything that "
                           "queries 'does X exist and is it ready' and now has to decide "
                           "whether a degraded answer counts as yes — which is exactly the "
                           "kind of ambiguity that propagates into more failures.",
        typical_symptoms=[
            "a resource visibly stuck in 'degraded' rather than reaching 'available'/'ready'",
            "some operations against it succeed while others fail, with no obvious pattern",
            "dependents that check 'does it exist' proceed, then fail later on 'is it usable'",
        ],
        taxonomy_category=TaxonomyCategory.CASCADING,
        category_rationale="Unlike transient_error's clean one-shot failure, a degraded "
                           "resource keeps participating in the system in a half-working "
                           "state — every consumer that touches it has to make its own "
                           "(possibly wrong) call about whether it's usable, which is how "
                           "one partial failure becomes several.",
    ),
    FaultCatalogEntry(
        domain=ScenarioDomain.SIMULATOR,
        fault_type="quota_limit",
        mechanism="A registered FaultRule rejects the matched operation immediately, "
                  "before the simulator creates anything — the same shape as a real cloud "
                  "provider returning a quota-exceeded error at admission time.",
        description="A matched provisioning operation is refused outright, up front, with "
                    "no resource ever coming into existence — exactly what an enterprise "
                    "infra backend does when an account/zone/project limit is hit.",
        blast_radius_shape="Whatever was about to be provisioned (it never comes to exist "
                           "at all), and any workflow whose plan assumed the request would "
                           "succeed.",
        typical_symptoms=[
            "provisioning calls fail immediately at admission, before any lifecycle state "
            "is even created — no 'creating', straight to rejected",
            "the rejection's payload names a concrete limit (the same shape a real cloud "
            "quota-exceeded error takes)",
            "retrying the identical request keeps failing the same way until the limit "
            "context changes — it isn't a one-shot blip",
        ],
        taxonomy_category=TaxonomyCategory.QUOTA_LIMIT,
        category_rationale="This is the one fault type that *names* its own taxonomy "
                           "category — the mechanism is, verbatim, a quota limit being hit.",
    ),
]


def all_entries() -> list[FaultCatalogEntry]:
    return list(CATALOG)


def for_domain(domain: ScenarioDomain) -> list[FaultCatalogEntry]:
    return [entry for entry in CATALOG if entry.domain == domain]


def lookup(domain: ScenarioDomain, fault_type: str) -> FaultCatalogEntry | None:
    for entry in CATALOG:
        if entry.domain == domain and entry.fault_type == fault_type:
            return entry
    return None

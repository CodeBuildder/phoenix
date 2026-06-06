<!--
Phoenix — Fault Library & Taxonomy Classifier
Copyright (c) 2026 Kaushikkumaran
-->

# Fault Library & Taxonomy Classifier

A FastAPI service that catalogs every fault `/chaos` (issue #2) can launch,
deterministically labels each one's failure mode (`transient`, `cascading`,
`resource-exhaustion`, `network-partition`, `quota-limit`), and ranks
components by how often each failure mode has actually shown up against
them — so M2's agent can "rank the fleet's weakest areas" and M3's dashboard
can render the failure-mode catalog panel, both off the same live numbers.

Issue: [#3 — Fault library + failure-mode taxonomy classifier](https://github.com/CodeBuildder/phoenix/issues/3)

## What's real here, what's reference data, and why nothing here can drift into fabrication

This service produces three different *kinds* of output, and they earn their
trustworthiness in three different ways. Spelling that out — the same
"what's real, what isn't, and why" rigor [chaos/README.md](../chaos/README.md#real-vs-simulated--what-this-service-actually-touches)
applies to its two backends — matters just as much here, maybe more, because
this is the one M1 service whose entire job is to *characterize* failures
rather than run them:

| Output | What it is | Why it can't become fabricated data |
|---|---|---|
| **The fault catalog** (`GET /catalog`) | Static reference material — mechanism, blast-radius shape, typical symptoms — for all 8 fault types `/chaos` exposes | This is *domain knowledge about mechanism*, not a measurement: every entry is grounded in the same verified-against-the-live-cluster facts [chaos/README.md's CRD field-mapping table](../chaos/README.md#chaos-mesh-crd-field-mapping) documents (what `PodChaos`'s `pod-kill` action does, what `NetworkChaos`'s `delay`/`loss` actions do, …) and in [`sim/src/faults.py`](../sim/src/faults.py)'s documented fault hooks for the simulator domain. [`catalog.py`](src/catalog.py) is deliberately, structurally incapable of carrying a number that would imply a measured rate, duration, or percentage — see its `TestNoFabricatedMeasurements` guard in [`test_catalog.py`](tests/test_catalog.py), which fails the build if any entry's prose starts to look like one. |
| **Classifications** (`POST /classify`) | A deterministic `(domain, fault_type) → taxonomy_category` lookup, with the *why* attached | [`classifier.py`](src/classifier.py) is not a trained model and draws no inference from history — it indexes one fixed table (the catalog's own `taxonomy_category`/`category_rationale` fields) and returns exactly what's there, or `None` if the fault type isn't catalogued. The same input always produces the same output; an uncatalogued fault type gets *no label*, never a best-effort guess (see `TestUnknownFaultTypes` in [`test_classifier.py`](tests/test_classifier.py)). |
| **Rankings** (`GET /rankings`) | A live tally of how many *real, actually-launched* `/chaos` scenarios against each component fell into each category | Computed fresh, on every single request, by fetching `/chaos`'s current `GET /scenarios` over HTTP, classifying each real record, and counting — see [`aggregator.py`](src/aggregator.py). There is no store, no cache, no precomputed snapshot anywhere in this service. **Zero scenarios ever launched produces an empty ranking list and `scenarios_considered: 0`** — not seeded examples, not a "here's what it'll look like" placeholder. `TestBuildRankingsEmptyState` in [`test_aggregator.py`](tests/test_aggregator.py) pins exactly that down, because an empty fleet history producing a non-empty ranking would be the single most direct way this service could end up showing something it never actually saw. |

So: the catalog is the kind of static, verifiable reference material a wiki
page about these fault types would contain (and could be checked the same
way); the classifier is a transparent, auditable lookup table you could
print out and check by hand; and the rankings are nothing but `len(...)` and
`+= 1` over scenario records this service asked `/chaos` for moments earlier.
None of the three has a code path that could output a number nobody actually
observed.

## How it works

```
        ┌──────────────────────┐        ┌───────────────────────────┐
        │   catalog.py (static) │──────▶│  classifier.py (lookup)    │
        └──────────────────────┘        └─────────────┬─────────────┘
                                                       │ classify each real record
        ┌──────────────────────┐   live HTTP   ┌──────▼─────────────┐
        │  GET /chaos/scenarios │◀─────────────│  chaos_client.py    │
        │   (the only history   │              └──────┬─────────────┘
        │   this service has)   │                     │ derive_component() + tally
        └──────────────────────┘              ┌───────▼─────────────┐
                                               │  aggregator.py       │──▶ /rankings
                                               └──────────────────────┘
```

`/catalog` and `/classify` answer purely out of the static library — no
network calls, no cluster access, nothing that could be unavailable.
`/rankings` is the one endpoint with a real dependency: it calls `/chaos`'s
`GET /scenarios` live, on every request, and reports a `502` (the same shape
`/chaos` itself uses for backend failures) if that call fails — it would
rather say "I can't tell you right now" than answer from something stale.

## The fault library

All 8 fault types `/chaos` can launch, each with its mechanism, structural
blast-radius shape, and observable symptoms — see [`catalog.py`](src/catalog.py)
for the full prose (it's long by design: this *is* the catalog the issue
asks for, not a summary of one elsewhere):

| Domain | Fault type | Mechanism | → Taxonomy category |
|---|---|---|---|
| `chaos_mesh` | `pod_kill` | `PodChaos` / `pod-kill` | `cascading` |
| `chaos_mesh` | `network_latency` | `NetworkChaos` / `delay` | `network-partition` |
| `chaos_mesh` | `packet_loss` | `NetworkChaos` / `loss` | `network-partition` |
| `chaos_mesh` | `io_delay` | `IOChaos` / `latency` | `resource-exhaustion` |
| `simulator` | `latency` | simulator fault hook (stretches op delay) | `transient` |
| `simulator` | `transient_error` | simulator fault hook (op → `error` state) | `transient` |
| `simulator` | `partial_failure` | simulator fault hook (op → `degraded` state) | `cascading` |
| `simulator` | `quota_limit` | simulator fault hook (op rejected pre-creation) | `quota-limit` |

Each mapping's *rationale* — why, mechanically, this fault type belongs in
that category and not another — is carried right alongside it in the catalog
entry's `category_rationale` (and surfaced verbatim through `/classify` and
`/catalog/{domain}/{fault_type}`), so the taxonomy is never an opaque label.

## Rankings: by component — deliberately not by "datacenter"

The M1 issue describes ranking "components/datacenters". This service ranks
by **component** only, and that's a deliberate choice forced by what the data
actually contains: this cluster has no real notion of a datacenter (it's
three k3s nodes on one local network), and a `/chaos` scenario's `target`
doesn't carry phoenix-sim's "zone" concept either — `SimulatorTarget` is just
`{resource_type, operation}` (see `chaos/src/models.py`). Inventing a
"datacenter" dimension to rank by would mean either fabricating one outright
or silently aliasing it onto something it doesn't actually mean — both are
exactly the kind of manufactured structure this project must never produce.
"Component" is the one grouping axis every scenario's real `target` genuinely
carries:

- **`chaos_mesh` scenarios** → `{namespace}/{sorted label_selector pairs}`,
  e.g. `phoenix-system/app=phoenix-sim` — the real k8s identity that picked
  the pod(s)
- **`simulator` scenarios** → `{resource_type}/{operation}`, e.g.
  `volume/create` — the real fault-rule match filter

See `derive_component` in [`aggregator.py`](src/aggregator.py) for the exact,
field-by-field derivation — every part of the label traces back to something
present on the real scenario record, and a missing field produces an
explicit placeholder (`(no namespace)`, `volume/*`, …) rather than a guess.

Only scenarios that actually reached `running` (i.e. `started_at` is set —
the field `Scenario.touch_status` populates exactly then) count toward a
component's tally; a scenario that was merely *recorded* but never launched
describes an attempt, not an observed failure mode of the thing it targeted.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/catalog` | GET | The full fault library (optional `?domain=chaos_mesh\|simulator`) |
| `/catalog/{domain}/{fault_type}` | GET | One catalog entry — `404` if uncatalogued |
| `/classify` | POST | Classify a failure by structural signature — `?domain=&fault_type=` → `Classification`, `404` if uncatalogued (never a guess) |
| `/rankings` | GET | Live failure-mode-frequency ranking by component, computed fresh from `/chaos`'s current scenario history — `502` if `/chaos` is unreachable |

## Running locally

```bash
cd faultlib
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8002
```

Useful env vars (see [`config.py`](src/config.py)): `CHAOS_URL` — where
`/rankings` fetches real scenario history (defaults to the in-cluster
`phoenix-chaos` service address). `/catalog` and `/classify` need nothing
beyond the static library, so they work even if `/chaos` is unreachable;
only `/rankings` depends on it.

## Deploying to the cluster

```bash
./deploy.sh
```

Builds the image, imports it into all three k3s nodes, and applies the
manifests in [`k8s/`](k8s/). No RBAC is needed — unlike `/chaos`, this
service never talks to the Kubernetes API; its one dependency is plain HTTP
to `/chaos`.

```bash
kubectl port-forward -n phoenix-system svc/phoenix-faultlib 8080:80
kubectl logs -n phoenix-system -l app=phoenix-faultlib -f
```

## Tests

```bash
pytest
```

`test_catalog.py` checks the catalog's completeness against `/chaos`'s own
fault-type enums and — the check that matters most — that nothing in it
*reads* like a fabricated measurement; `test_classifier.py` checks that
classification is a faithful, deterministic mirror of the catalog's mapping
and that uncatalogued fault types yield no label; `test_aggregator.py` and
`test_api.py` exercise component derivation and ranking aggregation against
realistically-shaped (but entirely fake-transport) `/chaos` scenario records,
with particular attention to the empty-history case — the surest possible
guard against this service ever quietly inventing something to show.

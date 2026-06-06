<!--
Phoenix — Chaos Injection Engine
Copyright (c) 2026 Kaushikkumaran
-->

# Chaos Injection Engine

A FastAPI service that wraps **Chaos Mesh** (real cluster-level chaos: pod
kills, network latency, packet loss, IO delay) and the **Provisioning
Simulator's** fault hooks (issue #1) behind one control surface — a single
`Scenario` model and a single start/stop/status API — so M2's agent and M3's
dashboard can launch, monitor, and stop chaos uniformly, regardless of which
backend actually runs the fault.

Issue: [#2 — Chaos injection engine](https://github.com/CodeBuildder/phoenix/issues/2)

## Real vs. simulated — what this service actually touches

This matters enough to be explicit about, since the two domains behind the
unified `Scenario` API are *very* different in kind:

| | Real or simulated? | What that means in practice |
|---|---|---|
| **Chaos Mesh** (`chaos_mesh` domain — `pod_kill`, `network_latency`, `packet_loss`, `io_delay`) | **Fully real.** Not simulated, not mocked, not a stand-in. | Chaos Mesh is a real, separately-installed system running in this cluster (Helm-installed into `kube-system`, the same way anyone runs it in production — just on a local k3s cluster of 3 nodes instead of a cloud-hosted one). When this engine launches a scenario, it applies a genuine `chaos-mesh.org/v1alpha1` custom resource via the k8s API; Chaos Mesh's own controllers pick it up and *actually do the thing* — kill a real pod, install real `tc`/netem rules on a real node's network namespace, slow down real file I/O on a real volume. `live_status` is read straight back from the object Chaos Mesh itself is updating in the cluster — this engine never computes, mirrors, or guesses at it. |
| **Provisioning Simulator** (`simulator` domain — `latency`, `transient_error`, `partial_failure`, `quota_limit`) | **The infrastructure being faulted is simulated; the fault-rule plumbing is real.** | [`phoenix-sim`](../sim/) is a deliberate in-memory simulator of an infra control plane (see its README for why) — its "volumes"/"subnets"/"instances" are Python objects on a timer, not real disks or real network segments. *But* this engine's half of the integration is genuinely real: it registers/queries/clears fault rules against the live simulator over real HTTP, and every `id`/`hits`/`expires_at` it reports comes back from the simulator's own state — nothing is mirrored or pre-computed locally. |
| **`blast_radius`** | **Always `null` — deliberately, for now.** | Reserved for issue #4's blast-radius graph builder, which will derive it from real cluster topology. A guessed number here would be exactly the kind of fabricated statistic this project must never produce. |

So: **the chaos half of this service is indistinguishable from chaos run
against a production cluster** — same CRDs, same controllers, same real
effects on real pods/nodes. The simulator half is a deliberate exception,
made *because* fault-injection requires a knob (deterministic, repeatable
failure rates on demand) that no real provisioning backend — cloud or
local — exposes; see [`sim/README.md`](../sim/README.md) for the full
reasoning. Every status this engine reports, in either domain, is read back
live from whichever backend is actually doing the work — never canned,
never estimated, never fabricated.

## How it works

```
POST /scenarios {domain, fault_type, target, params, ...}
        │
        ▼
  validate + translate  ──▶  record Scenario (pending)  ──▶  apply to backend
        │                                                          │
        │                                              ┌───────────┴───────────┐
        │                                              ▼                       ▼
        │                                        Chaos Mesh CR          simulator /faults
        │                                     (PodChaos/NetworkChaos/IOChaos)  rule
        ▼
  running ──▶ (stop requested) ──▶ stopping ──▶ stopped
     │
     └──▶ (backend reports it's gone) ──▶ completed     [via the sweeper, below]
     └──▶ (apply/stop call fails)       ──▶ failed
```

A background **sweeper** periodically asks each running scenario's real
backend "are you still going?" — that's how `chaos.scenario.completed` gets
published the moment a Chaos Mesh experiment or simulator fault rule actually
runs its course. Completion is never inferred from `duration_seconds` elapsing
on a timer; the backend is the only authority on whether the fault really ran
that long (either kind of object can also be cleared out from under us by
something else — `kubectl delete`, an expiring rule, …), so `_sync` always
asks before declaring anything finished.

## Domains and fault types

| Domain | Fault types | Backed by |
|---|---|---|
| `chaos_mesh` | `pod_kill`, `network_latency`, `packet_loss`, `io_delay` | real `chaos-mesh.org/v1alpha1` CRDs applied via the k8s `CustomObjectsApi` |
| `simulator` | `latency`, `transient_error`, `partial_failure`, `quota_limit` | the [Provisioning Simulator's](../sim/) `/faults` API (issue #1) |

### Chaos Mesh CRD field mapping

Every field name and enum value below was checked directly against the CRD
schemas installed in the live cluster (`kubectl get crd <kind>.chaos-mesh.org
-o jsonpath='{.spec.versions[0].schema.openAPIV3Schema.properties.spec...}'`),
not guessed from memory or documentation that may be out of date for the
installed version (Chaos Mesh 2.8.2):

| Fault type | CRD kind | `action` | Spec shape we build |
|---|---|---|---|
| `pod_kill` | `PodChaos` | `pod-kill` | `selector`, `mode`(`/value`), `gracePeriod`?, `duration`? |
| `network_latency` | `NetworkChaos` | `delay` | `...`, `delay: {latency, jitter, correlation}` |
| `packet_loss` | `NetworkChaos` | `loss` | `...`, `loss: {loss, correlation}` |
| `io_delay` | `IOChaos` | `latency` | `...`, `delay`, `percent`, `path`, `volumePath` |

`selector` is `{namespaces: [...], labelSelectors: {...}}`; `mode` is one of
`one | all | fixed | fixed-percent | random-max-percent` (the last three
require a `value`); `duration` is a Go duration string (`"30s"`). See
[`chaos_mesh.py`](src/chaos_mesh.py) for the exact builders — they're pure,
cluster-independent functions, unit-tested in
[`test_chaos_mesh.py`](tests/test_chaos_mesh.py) against these shapes.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/scenarios` | GET | List scenarios (optional `?status=`) |
| `/scenarios` | POST | Launch a scenario — `201` + the running `Scenario`, `422` if malformed, `502` if the backend rejects it |
| `/scenarios/{id}` | GET | Get a scenario (refreshes `live_status` from its backend if running) |
| `/scenarios/{id}/stop` | POST | Stop a running scenario early — deletes the Chaos Mesh CR / clears the simulator rule |
| `/scenarios/{id}` | DELETE | Remove a terminal scenario's record (`409` if still running) |

A `POST /scenarios` body:

```json
{
  "name": "kill-sim-pod",
  "domain": "chaos_mesh",
  "fault_type": "pod_kill",
  "target": {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}},
  "duration_seconds": 30,
  "params": {}
}
```

`target`/`params` shapes are domain- and fault-type-specific — see
[`models.py`](src/models.py) (`K8sTarget`/`SimulatorTarget`) and
[`chaos_mesh.py`](src/chaos_mesh.py) (`PodKillParams`/`NetworkLatencyParams`/
`PacketLossParams`/`IODelayParams`) for exactly what each accepts, and what
defaults apply when you omit `params` (deliberately mild — short delays, low
percentages — so an under-specified scenario perturbs rather than annihilates).

### `blast_radius`

Every `Scenario` carries a `blast_radius` field that is **always `null` right
now**. It's reserved for issue #4's blast-radius graph builder — once that
lands, it'll report which real, observed dependents a scenario's target
actually has. We do not predict, estimate, or otherwise fabricate that number
ourselves; a guessed value here would be exactly the kind of invented
statistic this project must never produce.

## Events — and the M0 schema stub

Every scenario transition (`created`, `started`, `stopped`, `completed`,
`failed`) publishes an event with the field set named in the M1 issue
(`event_type`, `source_agent`, `severity`, `component`, `causality`,
`timestamp`, `payload`) — see [`events.py`](src/events.py). This is the same
stub transport `phoenix-sim` uses (sentinel-platform's M0 owns the real shared
schema and Redis-streams bus; neither exists yet), emitted as structured logs:

```
{app="phoenix-chaos"} | json | event_type != ""
```

## Running locally

```bash
cd chaos
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8001
```

Useful env vars (see [`config.py`](src/config.py)): `SIMULATOR_URL` (where
`simulator`-domain scenarios register/clear fault rules — defaults to the
in-cluster `phoenix-sim` service address), `SWEEP_INTERVAL_SECONDS` (how often
the background sweeper re-checks running scenarios, default `5.0`).

Talking to Chaos Mesh requires a working kubeconfig (in-cluster service
account when deployed, local kubeconfig when run locally against the cluster);
talking to the simulator just requires `SIMULATOR_URL` to be reachable.

## Deploying to the cluster

```bash
./deploy.sh
```

Builds the image, imports it into all three k3s nodes, and applies the
manifests in [`k8s/`](k8s/) — including [`rbac.yaml`](k8s/rbac.yaml), which
grants the `phoenix-chaos` service account `get/list/watch/create/update/
patch/delete` on `podchaos`/`networkchaos`/`iochaos` in the `chaos-mesh.org`
API group (and nothing else — least privilege for exactly the CRDs this
service manages).

```bash
kubectl port-forward -n phoenix-system svc/phoenix-chaos 8080:80
kubectl logs -n phoenix-system -l app=phoenix-chaos -f
```

## Tests

```bash
pytest
```

`test_chaos_mesh.py` checks manifest construction and param validation against
the real CRD shapes (pure functions, no cluster needed); `test_engine.py`
exercises the orchestration core — state transitions, event ordering, error
paths, natural-completion detection — against faithful in-memory stand-ins for
both backends ([`fakes.py`](tests/fakes.py)); `test_api.py` checks the HTTP
contract end to end through the same fakes via `TestClient`.

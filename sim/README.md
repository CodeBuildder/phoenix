<!--
Phoenix — Provisioning Simulator
Copyright (c) 2026 Kaushikkumaran
-->

# Provisioning Simulator

A FastAPI service that mimics generic enterprise infrastructure operations —
volume create/attach/detach, VLAN/subnet create, instance provision/deprovision
— and is **deliberately faultable**, so Phoenix can induce *infrastructure-
operation* failures (a quota wall, a stuck attach, a transient provisioning
error), not just pod failures. It does not model or reference any real cloud
vendor or product; "enterprise infrastructure ops" here is generic on purpose.

Issue: [#1 — Provisioning Simulator service](https://github.com/CodeBuildder/phoenix/issues/1)

## How it works

Every operation returns immediately with the resource in a **transitional**
state (`creating`, `attaching`, `provisioning`, …) and a background task
carries it to its **terminal** state after a simulated delay — a "realistic
async lifecycle", as the issue calls for. Every transition publishes an event.

```
create_volume()  ──▶ creating ──▶ available ──▶ (attach) ──▶ in_use ──▶ …
provision_instance() ──▶ provisioning ──▶ running ──▶ (deprovision) ──▶ terminated
create_subnet()  ──▶ creating ──▶ active ──▶ (delete) ──▶ deleting ──▶ deleted
```

A registered **fault rule** (see below) can intercept any of these mid-flight:

| Fault type | Effect |
|---|---|
| `latency` | stretches the transition's delay by `params.extra_seconds` |
| `transient_error` | the operation fails partway through — resource lands in `error` |
| `partial_failure` | the transition stalls — resource lands in `degraded` and never reaches its terminal state |
| `quota_limit` | the operation is rejected up front — nothing is created |

`quota_limit` can also fire without any rule registered: each resource type has
a baseline quota (`VOLUME_QUOTA`/`SUBNET_QUOTA`/`INSTANCE_QUOTA`, default
50/20/30) so quota failures are part of the simulator's baseline realism, not
only something a fault rule can produce.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/state` | GET | "What exists right now" — every resource, grouped by type |
| `/volumes` | GET, POST | List / create volumes |
| `/volumes/{id}` | GET | Get a volume |
| `/volumes/{id}/attach` | POST | Attach to an instance |
| `/volumes/{id}/detach` | POST | Detach |
| `/volumes/{id}` | DELETE | Delete |
| `/subnets` | GET, POST | List / create VLAN/subnets |
| `/subnets/{id}` | GET, DELETE | Get / delete a subnet |
| `/instances` | GET, POST | List / provision instances |
| `/instances/{id}` | GET, DELETE | Get / deprovision an instance |
| `/faults` | GET, POST, DELETE | List / register / clear fault rules |
| `/faults/{id}` | DELETE | Clear one fault rule |

A fault rule (`POST /faults`) targets a `resource_type` + `operation` (both
optional — omit either to match more broadly), with a `probability` (0-1, what
fraction of matching operations it affects), an optional `duration_seconds`
(after which it expires), and type-specific `params` (e.g.
`{"extra_seconds": 5}` for `latency`). **This is the exact surface issue #2's
chaos engine drives** to trigger simulator faults alongside Chaos Mesh
experiments through one control surface.

## Events — and the M0 schema stub

Every lifecycle transition and fault publishes an event with the field set
named in the M1 issue: `event_type`, `source_agent`, `severity`, `component`,
`causality`, `timestamp`, `payload` (see [`events.py`](src/events.py) and the
mirrored [`schemas/event.schema.json`](../schemas/event.schema.json)).

**This is a stub.** sentinel-platform's M0 milestone owns the real shared
event schema and the Redis-streams bus every Sentinel agent publishes onto —
neither exists yet. Until it lands, events are emitted as structured logs
(the same "queryable in Loki" pattern argus's audit logger uses):

```
{app="phoenix-sim"} | json | event_type != ""
```

Once sentinel-platform's `/schemas/event.schema.json` lands: delete
`phoenix/schemas/event.schema.json`, depend on the real one, and swap this
module's transport for the Redis-streams client. `Event`'s field names were
chosen to match the issue's schema description so that swap shouldn't require
touching call sites.

## Running locally

```bash
cd sim
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8000
```

Useful env vars (see [`config.py`](src/config.py)): `LIFECYCLE_SPEED` (default
`1.0` — multiplies every simulated transition delay; set low for fast local
iteration), `VOLUME_QUOTA` / `SUBNET_QUOTA` / `INSTANCE_QUOTA`.

## Deploying to the cluster

```bash
./deploy.sh
```

Builds the image, imports it into all three k3s nodes, and applies the
manifests in [`k8s/`](k8s/) into the `phoenix-system` namespace (created if
missing). No secrets or special network egress are required — the simulator
is fully self-contained and emits events to stdout for Promtail to ship to
Loki, the same way every other workload in the cluster does.

```bash
kubectl port-forward -n phoenix-system svc/phoenix-sim 8080:80
kubectl logs -n phoenix-system -l app=phoenix-sim -f
```

## Tests

```bash
pytest
```

`test_api.py` covers the HTTP contract; `test_provisioning.py` exercises the
lifecycle engine and all four fault types end to end (awaiting transitions
directly rather than racing them through the test client); `test_events.py`
checks the emitted event shape.

<!--
Phoenix — Chaos Engineering & Self-Healing Agent
Copyright (c) 2026 Kaushikkumaran
Original work — see NOTICE for details
Commit history: https://github.com/CodeBuildder/phoenix/commits/main
-->

<h1 align="center">Phoenix</h1>

<p align="center">
  A chaos-engineering and self-healing agent for Kubernetes — induces real and synthetic
  infrastructure failures, then detects, diagnoses, and remediates them with OpenAI and
  a human-in-the-loop approval gate.
</p>

<p align="center">
  <a href="https://github.com/CodeBuildder/sentinel-platform/blob/main/docs/ARCHITECTURE.md"><strong>Architecture</strong></a>
  ·
  <a href="https://github.com/CodeBuildder/phoenix/milestones"><strong>Roadmap</strong></a>
  ·
  <a href="https://github.com/CodeBuildder/sentinel-platform"><strong>Sentinel Platform</strong></a>
</p>

## What Phoenix does

Phoenix is the resilience tier of the [Sentinel platform](https://github.com/CodeBuildder/sentinel-platform) —
the counterpart to [Argus](https://github.com/CodeBuildder/argus-k8s) (security). Where
Argus watches for attackers, Phoenix manufactures failure on purpose and proves the
cluster (and the agent) can recover from it.

- **Provisioning Simulator** — a FastAPI service that mimics enterprise cloud
  infrastructure operations (volume create/attach, VLAN/subnet create, instance
  provision) and is intentionally faultable, so Phoenix can induce
  *infrastructure-operation* failures, not just pod failures
- **Chaos injection engine** — wraps Chaos Mesh (pod kill, network latency, packet loss,
  IO delay) and the simulator's fault hooks behind one control surface
- **LangGraph agent** — detect (Prometheus/Loki anomaly watch) → diagnose (OpenAI reads
  logs/metrics and reconstructs the causal chain — "X failed *because* Y") → heal
  (executes remediation via MCP tools) → human-approval gate (risky actions pause for
  sign-off with full rationale + predicted outcome) → verify (confirm recovery, log MTTR)
- **Dashboard** — live chaos-scenario grid, blast-radius graph, healing pipeline swim
  lanes, action ledger, and failure-mode catalog, in the platform's dark command-center
  style

## Researcher-grade features on the roadmap

- **Causal incident chains** reconstructed from the dependency graph + event timeline
- **Blast-radius prediction** before a chaos scenario runs
- **Resilience score** per datacenter/component from MTTR, recovery rate, cascade-prevention rate
- **Failure-mode taxonomy** auto-classifying every failure (transient, cascading,
  resource-exhaustion, network-partition, quota-limit)
- **Predictive healing with confidence** — "seen this 7×, scaling replicas fixed 6,
  failover needed 1. Confidence 85%. Suggested action: …"
- **Synthetic user-journey simulation** measuring failure propagation end to end

## Build Week: prove the customer survives

The [`journeys/`](journeys/) service provides a cluster-free, seeded resilience
proof loop. It generates realistic customer operations, load profiles, and
faults; enforces safety budgets and human approval for high-risk experiments;
then reports availability, recovery, MTTR, error-budget consumption, and whether
the original journey passed after healing. The same seed replays the same test.

## Status

| Module | Description | Status |
|---|---|---|
| M1.1 — Provisioning Simulator | Faultable volume/subnet/instance lifecycle APIs ([`/sim`](sim/)) | Complete |
| M1.2 — Chaos Injection Engine | Chaos Mesh wrapper + simulator fault control surface ([`/chaos`](chaos/)) | Complete |
| M1.3 — Fault Library & Taxonomy Classifier | Failure-mode classification from observed events ([`/faultlib`](faultlib/)) | Complete |
| M1.4 — Blast-Radius Graph Builder | Dependency graph from live k8s + Hubble topology ([`/graph`](graph/)) | Complete |
| Build Week Phase 4 — Customer Journey Resilience Lab | Seeded load/fault generation, safety gates, recovery evidence ([`/journeys`](journeys/)) | Complete (cluster-free adapter) |
| M2 — Phoenix Agent | LangGraph detect → diagnose → heal → approve → verify state machine, predictive-healing memory store, event publisher | Complete |
| M3 — Phoenix Dashboard | React console, blast-radius graph, healing pipeline swim lanes, incident feed, fleet weakness map | Complete |

See the [milestones](https://github.com/CodeBuildder/phoenix/milestones) for the full
build sequence and issue backlog.

## Start here

For the complete Build Week judge experience, use the cluster-free one-command platform
path from the sibling Argus checkout. It starts a disposable local SOG plus the real
local Argus, Phoenix, and Sentinel services; builds an explicitly synthetic service
topology; publishes deterministic cross-agent evidence; and verifies the correlated
Sentinel incident before reporting success.

```text
Projects/
├── argus-k8s/                 # run the command here
└── sentinel-stack/
    ├── phoenix/
    ├── sentinel/
    └── sentinel-platform/
```

Preflight without starting a container, process, or publishing evidence:

```bash
make -C ../../argus-k8s demo-platform-dry-run
```

Launch the complete demo:

```bash
make -C ../../argus-k8s demo-platform
```

Open Argus at **http://127.0.0.1:5173**, Phoenix at
**http://127.0.0.1:5174**, and Sentinel at **http://127.0.0.1:5175**. The command
installs missing local dependencies and labels every topology fixture as
`synthetic_fixture`/`demo-data=synthetic`. Argus evidence is `replayed`; Phoenix outcomes
are `simulator`. A bounded feed updates the dashboards during the presentation. No
Kubernetes API, Hubble relay, Falco workload, or Chaos Mesh fault is used. `Ctrl-C`
stops the local services and removes the disposable Redis container.

For the guarded real k3s proof instead:

```bash
kubectl config use-context argus
make -C ../../argus-k8s demo-platform-live-dry-run
make -C ../../argus-k8s demo-platform-live
```

The dry-run is read-only. The live command requires the exact context and the phrase
`INJECT LIVE FAULT`, creates only `sentinel-live-demo`, and continuously probes a
two-replica HTTP target. Phoenix must create a real Chaos Mesh `PodChaos` for one
disposable replica; the proof passes only after Kubernetes supplies a new Ready pod,
both replicas are Ready, measured availability is recorded, and Sentinel correlates the
observed Argus evidence with Phoenix's verified recovery. `Ctrl-C` deletes only the
isolated namespace.

For Phoenix by itself, choose one of the paths below. The local path proves Phoenix's
safe simulator workflow without touching Kubernetes. The cluster path adds live
topology, Hubble flows, Chaos Mesh, and the OpenAI-powered recovery agent.

| Path | Kubernetes | Dashboard | What you can inject |
|---|---:|---|---|
| **Safe local demo** | No | `http://127.0.0.1:5174` | Synthetic provisioning faults only |
| **Live k3s demo** | Yes | `http://127.0.0.1:3000` | Synthetic faults plus bounded Chaos Mesh experiments |

### Path A — safe local demo, no Kubernetes

Run the simulator, chaos API, taxonomy service, and dashboard in four terminals. The
dashboard intentionally reports cluster topology and agent panels as unavailable;
those are live-only signals, not mocked data.

```bash
# Terminal 1 — provisioning simulator
python3 -m venv sim/.venv
sim/.venv/bin/pip install -r sim/requirements.txt
sim/.venv/bin/python -m uvicorn main:app --app-dir sim/src --host 127.0.0.1 --port 8083
```

```bash
# Terminal 2 — safe simulator-domain injection API
python3 -m venv chaos/.venv
chaos/.venv/bin/pip install -r chaos/requirements.txt
SIMULATOR_URL=http://127.0.0.1:8083 \
  chaos/.venv/bin/python -m uvicorn main:app --app-dir chaos/src --host 127.0.0.1 --port 8082
```

```bash
# Terminal 3 — fault catalog and scenario rankings
python3 -m venv faultlib/.venv
faultlib/.venv/bin/pip install -r faultlib/requirements.txt
CHAOS_URL=http://127.0.0.1:8082 \
  faultlib/.venv/bin/python -m uvicorn main:app --app-dir faultlib/src --host 127.0.0.1 --port 8081
```

```bash
# Terminal 4 — Phoenix console
npm --prefix dashboard install
VITE_ARGUS_URL=http://127.0.0.1:5173 \
VITE_SENTINEL_URL=http://127.0.0.1:5175 \
  npm --prefix dashboard run dev
```

Open **http://127.0.0.1:5174**, choose **Safe Simulation**, and inject a simulator
fault. This path never creates a Kubernetes or Chaos Mesh resource.

### Path B — live k3s demo

Phoenix reuses Argus's real three-node k3s cluster. Verify the context before deploying:

```bash
kubectl config use-context argus
kubectl get nodes
kubectl get pods -n chaos-mesh
```

Expect `k3s-master`, `k3s-worker1`, and `k3s-worker2` to be Ready. Then deploy all
Phoenix services and keep the supervised port-forwards running:

```bash
./deploy.sh
```

Open **http://127.0.0.1:3000**. **Safe Simulation** remains non-disruptive. **Live
k3s** shows the exact namespace, selector, fault, duration, and blast radius and
requires the typed confirmation `INJECT LIVE FAULT` before creating a bounded Chaos
Mesh resource.

For prerequisites, existing-cluster checks, service-by-service development, and
troubleshooting, follow **[setup.md](setup.md)**.

## Stack

FastAPI + LangGraph agent, OpenAI Responses API for reasoning, MCP tools for cluster actions

### Cross-console navigation

The Phoenix top bar switches directly between all three platform consoles. Destinations
are never inferred from fixed ports: configure them explicitly for each environment.
Missing destinations render as disabled instead of navigating to an assumed address:

For the local three-console demo, the reserved ports are:

| Console | URL |
| --- | --- |
| Argus | `http://127.0.0.1:5173` |
| Phoenix | `http://127.0.0.1:5174` |
| Sentinel | `http://127.0.0.1:5175` |

Set the switcher destinations before starting Phoenix locally:

```bash
VITE_ARGUS_URL=http://127.0.0.1:5173 \
VITE_SENTINEL_URL=http://127.0.0.1:5175 \
npm --prefix dashboard run dev
```

For deployed environments, provide their public URLs during the dashboard build:

```bash
VITE_ARGUS_URL=https://argus.example.com \
VITE_SENTINEL_URL=https://sentinel.example.com \
npm --prefix dashboard run build
```
(kubectl, PromQL, Loki, Chaos Mesh, provisioning sim), React + TypeScript + Vite +
Tailwind dashboard. Reuses the existing Prometheus/Grafana/Loki + Cilium stack and k3s
cluster from [argus-k8s](https://github.com/CodeBuildder/argus-k8s) — no duplicate
infrastructure.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

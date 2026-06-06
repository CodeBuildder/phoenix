<!--
Phoenix — Chaos Engineering & Self-Healing Agent
Copyright (c) 2026 Kaushikkumaran
Original work — see NOTICE for details
Commit history: https://github.com/CodeBuildder/phoenix/commits/main
-->

<h1 align="center">Phoenix</h1>

<p align="center">
  A chaos-engineering and self-healing agent for Kubernetes — induces real and synthetic
  infrastructure failures, then detects, diagnoses, and remediates them with Claude and
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
- **LangGraph agent** — detect (Prometheus/Loki anomaly watch) → diagnose (Claude reads
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

## Status

| Module | Description | Status |
|---|---|---|
| M1.1 — Provisioning Simulator | Faultable volume/subnet/instance lifecycle APIs ([`/sim`](sim/)) | Complete |
| M1.2 — Chaos Injection Engine | Chaos Mesh wrapper + simulator fault control surface ([`/chaos`](chaos/)) | Complete |
| M1.3 — Fault Library & Taxonomy Classifier | Failure-mode classification from observed events ([`/faultlib`](faultlib/)) | Complete |
| M1.4 — Blast-Radius Graph Builder | Dependency graph from live cluster topology | Pending |
| M2 — Phoenix Agent | LangGraph detect → diagnose → heal → approve → verify | Not started |
| M3 — Phoenix Dashboard | React console, blast-radius graph, healing pipeline | Not started |

See the [milestones](https://github.com/CodeBuildder/phoenix/milestones) for the full
build sequence and issue backlog.

## Local setup

See **[setup.md](setup.md)** for the full quick-start guide — copy-paste
commands to run the Provisioning Simulator locally or deploy it to the
cluster, plus what's coming next as the rest of M1 lands.

## Stack

FastAPI + LangGraph agent, Claude API for reasoning, MCP tools for cluster actions
(kubectl, PromQL, Loki, Chaos Mesh, provisioning sim), React + TypeScript + Vite +
Tailwind dashboard. Reuses the existing Prometheus/Grafana/Loki + Cilium stack and k3s
cluster from [argus-k8s](https://github.com/CodeBuildder/argus-k8s) — no duplicate
infrastructure.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

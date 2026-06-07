# phoenix-agent — LangGraph Detect → Diagnose → Heal → Approve → Verify

> **Status: Not started (M2).** This README documents the planned interface so
> that `/chaos`, `/graph`, `/faultlib`, the Sentinel event bus, and the
> dashboard (M3) can be designed against a stable contract before implementation
> begins.  Nothing in this directory runs yet.

## What it does

The Phoenix agent is the reasoning and action layer of the platform.  It:

1. **Detects** anomalies from Prometheus alerts and Loki log streams, or
   receives a chaos scenario trigger from the dashboard
2. **Diagnoses** the root cause — queries logs, metrics, the blast-radius
   graph, and the fault taxonomy — then constructs a causal chain:
   *"X failed because Y degraded because Z was chaos-targeted"*
3. **Heals** — selects a remediation action (scale replicas, restart pod,
   roll back, failover) and executes it via MCP tools
4. **Approves** — if the action is high-risk, pauses and sends an approval
   request (with full rationale + predicted outcome) to the human-in-the-loop
   gate before executing
5. **Verifies** — confirms recovery (Prometheus metrics back to baseline, Loki
   clean, chaos scenario stopped), logs MTTR and the causal chain to the
   healing ledger

## State machine

```
IDLE
  │ anomaly detected / chaos scenario started
  ▼
DETECT
  │ alert normalized and enriched (pod context, logs, flows)
  ▼
DIAGNOSE  ←───────────────────────────────────────────┐
  │ root cause + blast radius computed                │
  │                                                   │ retry if
  ▼                                                   │ verification
HEAL_PLAN                                             │ fails
  │ action selected, confidence computed              │
  ├─ low-risk ──────────────────────────────────────► EXECUTE
  │                                                   │
  └─ high-risk ──► APPROVE ──► (human approves) ────► EXECUTE
                              │                       │
                              └─ (human rejects) ─► ABORT
                                                      │
                                                  VERIFY ──────────────────┘
                                                      │ success
                                                  REPORT
                                                      │
                                                   IDLE
```

Implemented as a LangGraph `StateGraph` with typed state nodes and conditional
edges based on action risk score and verification result.

## External dependencies

| Dependency | Purpose | Protocol |
|---|---|---|
| Prometheus / AlertManager | Source of anomaly alerts | HTTP (AlertManager webhook) |
| Loki | Log retrieval for diagnosis | HTTP LogQL |
| `/chaos` (`phoenix-chaos`) | Launch / stop chaos scenarios; read live scenario state | HTTP |
| `/graph` (`phoenix-graph`) | Blast-radius context for diagnosis and pre-run prediction | HTTP |
| `/faultlib` (`phoenix-faultlib`) | Fault classification and taxonomy | HTTP |
| Chaos Mesh CRDs | Observed cluster chaos state (via `/chaos`) | k8s API (indirectly) |
| Sentinel event bus | Publish healing events and MTTR reports fleet-wide | gRPC (M5 interface) |

## MCP tools (planned)

The agent executes cluster actions through Model Context Protocol tool calls
rather than raw kubectl — every action is auditable and can be paused for
human approval.

| Tool | Action |
|---|---|
| `kubectl_scale` | Scale a Deployment's replica count |
| `kubectl_restart` | Rolling restart a Deployment |
| `kubectl_rollout_undo` | Roll back to the previous ReplicaSet |
| `chaos_stop` | Stop an active Chaos Mesh scenario via `/chaos` |
| `promql_query` | Run an instant or range PromQL query |
| `loki_query` | Run a LogQL query |
| `blast_radius` | Call `/graph`'s `/blast-radius` endpoint |
| `classify_fault` | Call `/faultlib`'s `/classify` endpoint |

## API (planned)

```
POST /run              — trigger a diagnose+heal cycle for an alert payload
GET  /runs             — list past agent runs with outcomes
GET  /runs/{id}        — full causal chain, actions taken, MTTR for one run
POST /runs/{id}/approve — human approval gate for a paused high-risk action
GET  /health
```

The approval gate shape:

```json
{
  "run_id": "...",
  "proposed_action": "kubectl_scale",
  "rationale": "phoenix-chaos is pod-killed; faultlib rankings show 3 recent cascading faults targeting this workload; scaling replicas resolved this pattern in 2 of 2 prior incidents in the memory store",
  "predicted_outcome": "MTTR ~45s, success probability 92%",
  "risk_level": "low",
  "requires_approval": false
}
```

## Predictive healing memory store (issue #6)

The agent persists each run's causal chain, action taken, and outcome to a
key-value store indexed by `(fault_type, affected_component)`.  On future
incidents with the same signature it retrieves prior outcomes and includes
them in the diagnosis prompt:

> *"Seen this 3×: scaling replicas resolved 2, failover needed 1.
> Confidence 67%. Suggested action: scale replicas."*

The store is the only stateful part of the agent — everything else (topology,
flows, rankings) is fetched live on each run.

## Relationship to M1 services

```
/sim ──(faults)──► /chaos ──(scenarios)──► /graph (blast radius)
                       │                       │
                       │                       ▼
                       └──────────────► /faultlib (classify)
                                             │
                                             ▼
                                         /agent (detect → diagnose → heal)
                                             │
                                             ▼
                                    Sentinel event bus (M5)
```

The agent does not replace the dashboard's trigger buttons — the dashboard
calls `/chaos` directly for operator-initiated scenarios.  The agent's role is
**autonomous reaction** to anomalies the operator didn't initiate.

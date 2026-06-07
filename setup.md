# Phoenix — Local Setup

A quick-start guide for running Phoenix. Copy-paste the commands in order.

> Phoenix shares its cluster and observability stack with
> [argus-k8s](https://github.com/CodeBuildder/argus-k8s) — there's no separate
> infrastructure to stand up. If you haven't already, follow
> [argus's setup guide](https://github.com/CodeBuildder/argus-k8s/blob/main/setup.md)
> steps 1–3 first (cluster, security stack, observability).

---

## Prerequisites

**Hardware:** macOS on Apple Silicon (M1/M2/M3).

**Tools to install** (skip any you already have from setting up argus):
```bash
brew install orbstack kubectl
```

**Cluster:** the 3-node k3s cluster from argus-k8s must be up and your kubectl
context pointed at it:
```bash
open -a OrbStack
kubectl config use-context argus
kubectl get nodes   # expect 3 nodes in Ready state
```

---

## 1. Provisioning Simulator (`/sim`) — backend

This is the only service M1 ships so far. It's a FastAPI app that mimics
faultable enterprise infrastructure operations (volumes, subnets, instances).

### Run it locally
```bash
cd sim
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8000
```

Try it out:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/volumes \
  -H "Content-Type: application/json" \
  -d '{"name": "my-volume", "size_gb": 10, "zone": "zone-a"}'
curl http://localhost:8000/state
```

Watch a resource move through its lifecycle (`creating → available`, …) by
calling `/state` again a moment later — every transition is logged as a
structured event.

### Deploy it to the cluster
```bash
cd sim
./deploy.sh
```

Builds the image, loads it onto all three k3s nodes, and applies the manifests
into the `phoenix-system` namespace.
```bash
kubectl port-forward -n phoenix-system svc/phoenix-sim 8080:80
kubectl logs -n phoenix-system -l app=phoenix-sim -f
```

### See its events in Grafana
Open Grafana (`make grafana-ui` from argus-k8s, or `kubectl port-forward -n monitoring svc/grafana 3000:80`)
→ Explore → Loki, and run:
```
{app="phoenix-sim"} | json | event_type != ""
```

---

## 2. Chaos Injection Engine (`/chaos`) — backend

This is the service that actually **triggers chaos** — it's the one the
dashboard's "trigger" buttons (M3) and the agent (M2) will call to launch,
watch, and stop scenarios. Everything it launches in the `chaos_mesh` domain
is **real** (genuine pods get killed, real network latency gets injected on
real nodes via Chaos Mesh — already installed in this cluster); the
`simulator` domain drives faults into `/sim`'s fault-injectable lifecycle.
See [chaos/README.md](chaos/README.md#real-vs-simulated--what-this-service-actually-touches)
for the full real-vs-simulated breakdown.

### Run it locally
```bash
cd chaos
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8001
```
(Talking to Chaos Mesh from your laptop requires a working kubeconfig pointed
at the cluster — same `kubectl config use-context argus` from the prerequisites.)

### Trigger a real chaos scenario
This is the actual "trigger button" action — a `POST /scenarios` call. Here's
a mild, real one: 200ms of network latency injected onto `phoenix-sim`'s pod
for 60 seconds via a genuine Chaos Mesh `NetworkChaos` experiment.
```bash
curl -X POST http://localhost:8001/scenarios -H "Content-Type: application/json" -d '{
  "name": "demo-latency",
  "domain": "chaos_mesh",
  "fault_type": "network_latency",
  "target": {"namespace": "phoenix-system", "label_selector": {"app": "phoenix-sim"}},
  "duration_seconds": 60,
  "params": {"latency": "200ms", "jitter": "50ms"}
}'
```
Watch it land as a real object in the cluster, and check on it / stop it early
through the same API the dashboard will use:
```bash
kubectl get networkchaos -n phoenix-system
curl http://localhost:8001/scenarios/<id>            # live_status, read straight from Chaos Mesh
curl -X POST http://localhost:8001/scenarios/<id>/stop
```
A `simulator`-domain scenario (e.g. inject `latency` into `/sim`'s volume
creation) follows the exact same `POST /scenarios` shape — just
`"domain": "simulator"`, `"fault_type": "latency"`, and a
`{"resource_type": ..., "operation": ...}` target. See
[chaos/README.md](chaos/README.md#api) for every fault type and target shape.

### Deploy it to the cluster
```bash
cd chaos
./deploy.sh
```
```bash
kubectl port-forward -n phoenix-system svc/phoenix-chaos 8080:80
kubectl logs -n phoenix-system -l app=phoenix-chaos -f
```

### See its events in Grafana
```
{app="phoenix-chaos"} | json | event_type != ""
```

---

## 3. Fault Library & Taxonomy Classifier (`/faultlib`) — backend

This is the service that turns raw chaos history into something the agent
(M2) and dashboard (M3) can act on: a catalog of every fault `/chaos` can
launch (mechanism, blast-radius shape, typical symptoms), a deterministic
classifier that labels each one's failure mode, and a live ranking of which
components have actually experienced which failure modes — computed fresh,
on every request, from `/chaos`'s real scenario history. Nothing here is
cached or seeded: an empty `/chaos` produces an empty ranking. See
[faultlib/README.md](faultlib/README.md#whats-real-here-whats-reference-data-and-why-nothing-here-can-drift-into-fabrication)
for exactly how each of its three outputs earns its trustworthiness.

### Run it locally
```bash
cd faultlib
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8002
```

### Try it out
```bash
curl http://localhost:8002/catalog                                          # the full fault library
curl http://localhost:8002/catalog/chaos_mesh/pod_kill                      # mechanism, blast radius, symptoms
curl -X POST "http://localhost:8002/classify?domain=chaos_mesh&fault_type=network_latency"
curl http://localhost:8002/rankings                                         # live, off /chaos's real scenario history
```
Launch a real scenario through `/chaos` (see section 2's "Trigger a real
chaos scenario") and call `/rankings` again — the new scenario shows up in
the tally immediately, because every call recomputes it from scratch.

### Deploy it to the cluster
```bash
cd faultlib
./deploy.sh
```
No RBAC needed — unlike `/chaos`, this service never touches the Kubernetes
API; its one dependency is plain HTTP to `/chaos`.
```bash
kubectl port-forward -n phoenix-system svc/phoenix-faultlib 8080:80
kubectl logs -n phoenix-system -l app=phoenix-faultlib -f
```

---

## 4. Blast-Radius Graph Builder (`/graph`) — backend

Derives the service dependency graph from the live cluster and predicts
which downstream services are in the blast radius of a planned chaos
scenario — before it runs.  Two data sources, both 100% real: k8s API
(env-var DNS references between pods) and Hubble relay gRPC (actual
FORWARDED TCP flows observed by Cilium's eBPF probes).

### Run it locally
```bash
cd graph
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8003
```
(Hubble relay access requires a working kubeconfig — `kubectl config use-context argus`.)

### Try it out
```bash
curl http://localhost:8003/health
curl http://localhost:8003/topology | jq '{nodes: [.nodes[] | .id], edges: [.edges[] | {src: .source, tgt: .target, type: .edge_type}]}'

# Blast radius: what's at risk if chaos hits phoenix-chaos?
curl "http://localhost:8003/blast-radius?target_namespace=phoenix-system&fault_type=network_latency&selector=app=phoenix-chaos" | jq .
```

### Deploy it to the cluster
```bash
cd graph
./deploy.sh
```
RBAC needed — the service reads Services, Pods, ReplicaSets, Endpoints, and
Namespaces across all namespaces, and talks to `hubble-relay.kube-system.svc`
via gRPC.  Hubble protos (Cilium v1.15.0) are compiled at Docker build time.
```bash
kubectl port-forward -n phoenix-system svc/phoenix-graph 8080:80
kubectl logs -n phoenix-system -l app=phoenix-graph -f
```

---

## What's coming

The agentic and frontend pieces aren't built yet — this guide will grow a
section for each as it lands:

| Piece | What it'll be | Status |
|---|---|---|
| `/agent` — LangGraph agent (backend) | detect → diagnose → heal → approve → verify, via Claude + MCP tools | Not started (M2) |
| Dashboard (frontend) | React + Vite + Tailwind console — the "trigger" buttons that call `/chaos`'s `POST /scenarios` directly, plus the blast-radius graph and healing pipeline | Not started (M3) |

See the [module status table](README.md#status) for the up-to-date picture.

---

## Troubleshooting

**`kubectl apply` rejected by an admission webhook (Kyverno)**

The cluster enforces `disallow-root-containers` and `approved-registries-only`
on every namespace except a short allow-list. Any new workload's manifest
needs a **container-level** `securityContext.runAsNonRoot: true` and a fully
qualified image reference (e.g. `docker.io/library/<image>:<tag>`, which is
what `docker save`/`ctr images import` already produce for a locally built
`<image>:<tag>`).

**`/sim` pod stuck in `ImagePullBackOff`**

The deployment uses `imagePullPolicy: Never` — the image must be loaded onto
*every* node first. Re-run `./deploy.sh`, which loops over all three nodes.

**No events showing up in Loki**

Give Promtail a few seconds to ship new pod logs, and double check the query
matches the pod's `app` label exactly: `{app="phoenix-sim"}`.

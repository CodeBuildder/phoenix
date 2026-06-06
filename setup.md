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

## What's coming

The rest of M1 — and the agentic and frontend pieces — aren't built yet, so
there's nothing to run for them yet. This guide will grow a section for each
as it lands:

| Piece | What it'll be | Status |
|---|---|---|
| `/chaos` — Chaos injection engine | Wraps Chaos Mesh + the simulator's fault hooks behind one control surface | In progress |
| Fault library & taxonomy classifier | Classifies failures from real observed events | Pending |
| Blast-radius graph builder | Dependency graph from live cluster topology | Pending |
| `/agent` — LangGraph agent (backend) | detect → diagnose → heal → approve → verify, via Claude + MCP tools | Not started (M2) |
| Dashboard (frontend) | React + Vite + Tailwind console — chaos grid, blast-radius graph, healing pipeline | Not started (M3) |

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

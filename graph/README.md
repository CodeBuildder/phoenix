# phoenix-graph — Blast-Radius Graph Builder

Derives the service dependency graph from live Kubernetes topology and
Hubble-observed network flows, then computes which downstream components
are in the blast radius of a planned chaos scenario.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/topology` | Full service dependency graph |
| `GET` | `/blast-radius?target_namespace=X&fault_type=Y&selector=app=Z` | Downstream components at risk |
| `GET` | `/health` | Liveness |

### `GET /topology`

Returns all k8s Services as nodes and their dependency edges.  Every call
reads from the live cluster — nothing is cached.

```json
{
  "nodes": [
    {"id": "phoenix-system/phoenix-faultlib", "name": "phoenix-faultlib", "namespace": "phoenix-system", "kind": "Service", "labels": {...}},
    {"id": "phoenix-system/phoenix-chaos",    "name": "phoenix-chaos",    "namespace": "phoenix-system", "kind": "Service", "labels": {...}}
  ],
  "edges": [
    {
      "source":    "phoenix-system/phoenix-faultlib",
      "target":    "phoenix-system/phoenix-chaos",
      "edge_type": "env_ref",
      "flow_count": 0,
      "env_var":   "CHAOS_URL"
    }
  ],
  "topology_sources": ["kubernetes", "hubble"],
  "node_count": 2,
  "edge_count": 1
}
```

An edge `source → target` means *source depends on target* — source calls
target, so a fault on target puts source in the blast radius.

### `GET /blast-radius`

```
GET /blast-radius
  ?target_namespace=phoenix-system
  &fault_type=network_latency
  &selector=app=phoenix-chaos
```

```json
{
  "target_namespace": "phoenix-system",
  "target_selector": {"app": "phoenix-chaos"},
  "fault_type": "network_latency",
  "matched_nodes": ["phoenix-system/phoenix-chaos"],
  "affected_nodes": [
    {
      "node_id": "phoenix-system/phoenix-faultlib",
      "name": "phoenix-faultlib",
      "namespace": "phoenix-system",
      "distance_hops": 1,
      "severity": "high",
      "via_edge_types": ["env_ref"]
    }
  ],
  "topology_sources": ["kubernetes", "hubble"]
}
```

Severity is derived from graph distance only — not a statistical estimate:
- distance 1 → `high`
- distance 2 → `medium`
- distance 3+ → `low`

## What's real here and why nothing here can be fabricated

| Data | Source | Guarantee |
|---|---|---|
| **Nodes** | k8s `list_service_for_all_namespaces` | Every node is a real running k8s Service. No service = no node. |
| **`env_ref` edges** | Pod environment variables from the k8s API | Every edge traces to a specific `ENV_VAR=http://svc.ns.svc.cluster.local` on a real pod. |
| **`flow_observed` edges** | Hubble relay `Observer.GetFlows` | Every edge is a `FORWARDED` TCP flow Hubble's eBPF actually saw between two workloads. |
| **Blast radius** | BFS on the above graph | Graph-distance computation — no statistical inference, no hardcoded severity. Empty graph = empty blast radius. |

The service has no persistent state.  There is no cache, no database, no
seeded data.  An empty cluster returns an empty topology; a fresh cluster
with no flows returns env-ref edges only.

## Data sources

**Primary (always available):** Kubernetes API via in-cluster `ServiceAccount`
with a `ClusterRole` for `get`/`list` on `services`, `pods`, `namespaces`,
`endpoints`.

**Secondary (best-effort):** Hubble relay gRPC at
`hubble-relay.kube-system.svc.cluster.local:80` (the relay is
already deployed in this cluster as part of the Cilium stack from
[argus-k8s](https://github.com/CodeBuildder/argus-k8s)).  If the relay is
unavailable, topology falls back to k8s-only data and
`topology_sources` will contain only `["kubernetes"]`.

Proto stubs (`flow_pb2`, `observer_pb2`) are compiled from the vendored
Cilium v1.15.0 `.proto` files (`deps/protos/`) at Docker image build time
via `grpc_tools.protoc`.

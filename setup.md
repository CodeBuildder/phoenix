# Phoenix setup guide

This guide has one decision point: run the safe simulator workflow without Kubernetes,
or connect Phoenix to the existing Argus k3s cluster for live topology and bounded chaos.

## Choose a path

| Capability | Safe local | Live k3s |
|---|---:|---:|
| Provisioning simulator | Yes | Yes |
| Synthetic fault injection | Yes | Yes |
| Phoenix dashboard | Yes | Yes |
| Kubernetes topology | No | Yes |
| Cilium Hubble live flows | No | Yes |
| Chaos Mesh faults | No | Yes |
| Phoenix recovery agent | No | Yes |

Phoenix never fills unavailable live signals with invented data. In local mode, cluster
and agent panels remain explicitly disconnected.

## Path A — safe local demo without Kubernetes

### Prerequisites

- Python 3.11 or newer
- Node.js 18 or newer
- npm and curl

No OrbStack, kubeconfig, API key, or cluster is required.

### 1. Start the provisioning simulator

From the repository root:

```bash
python3 -m venv sim/.venv
sim/.venv/bin/pip install -r sim/requirements.txt
sim/.venv/bin/python -m uvicorn main:app --app-dir sim/src --host 127.0.0.1 --port 8083
```

Verify it in another terminal:

```bash
curl http://127.0.0.1:8083/health
```

### 2. Start the safe injection API

```bash
python3 -m venv chaos/.venv
chaos/.venv/bin/pip install -r chaos/requirements.txt
SIMULATOR_URL=http://127.0.0.1:8083 \
  chaos/.venv/bin/python -m uvicorn main:app --app-dir chaos/src --host 127.0.0.1 --port 8082
```

Only choose the `simulator` domain in this path. It registers fault rules against the
local simulator and does not create Kubernetes resources.

### 3. Start the taxonomy service

```bash
python3 -m venv faultlib/.venv
faultlib/.venv/bin/pip install -r faultlib/requirements.txt
CHAOS_URL=http://127.0.0.1:8082 \
  faultlib/.venv/bin/python -m uvicorn main:app --app-dir faultlib/src --host 127.0.0.1 --port 8081
```

### 4. Start the dashboard

```bash
npm --prefix dashboard install
VITE_ARGUS_URL=http://127.0.0.1:5173 \
VITE_SENTINEL_URL=http://127.0.0.1:5175 \
  npm --prefix dashboard run dev
```

Open [http://127.0.0.1:5174](http://127.0.0.1:5174), go to Incidents, choose
**Safe Simulation**, and inject a fault. Topology, Hubble, and recovery-agent panels
remain unavailable because this mode has no cluster.

## Path B — live demo on the existing k3s cluster

Phoenix shares Argus's three-node k3s cluster and its Cilium/Hubble observability stack.
OrbStack's built-in `orbstack` Kubernetes context is not that cluster.

### Prerequisites

- OrbStack running
- `kubectl`, Docker, npm, and SSH access to the three OrbStack machines
- kubeconfig context `argus`
- three Ready nodes: `k3s-master`, `k3s-worker1`, `k3s-worker2`
- Cilium/Hubble and Chaos Mesh running
- `OPENAI_API_KEY` in the repository `.env` for live agent reasoning

Never commit `.env`. Phoenix's deploy script loads it locally and injects required
configuration at build/deploy time.

### 1. Select and verify the cluster

```bash
open -a OrbStack
kubectl config get-contexts
kubectl config use-context argus
kubectl get nodes -o wide
kubectl get pods -n kube-system -l k8s-app=cilium
kubectl get pods -n chaos-mesh
```

Stop here if the context is `orbstack`, any k3s node is NotReady, or Cilium/Chaos Mesh
is not healthy. Complete the [Argus cluster setup](https://github.com/CodeBuildder/argus-k8s/blob/main/setup.md)
before continuing.

### 2. Deploy Phoenix

From the Phoenix repository root:

```bash
./deploy.sh
```

The script builds the services and dashboard, loads images onto all three nodes, applies
the `phoenix-system` manifests, waits for rollouts, and starts supervised port-forwards.
Keep the terminal open.

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

### 3. Choose the correct injection mode

- **Safe Simulation** targets the provisioning simulator. It does not create a Chaos
  Mesh object or disrupt a Kubernetes workload.
- **Live k3s** targets a real workload through Chaos Mesh. Phoenix previews the target,
  fault, duration, and blast radius and requires `INJECT LIVE FAULT` exactly.

Inspect active experiments and Phoenix workloads:

```bash
kubectl get pods -n phoenix-system
kubectl get podchaos,networkchaos,iochaos -A
```

Use the dashboard's stop action for an active experiment. Scenarios with a configured
duration are also cleaned up by the chaos engine.

## Local console ports

| Product | URL |
|---|---|
| Argus | `http://127.0.0.1:5173` |
| Phoenix | `http://127.0.0.1:5174` |
| Sentinel | `http://127.0.0.1:5175` |

The deployed Phoenix dashboard uses `http://127.0.0.1:3000`; that does not change the
reserved local development ports above.

## Service-by-service development

| Service | Local port | Detailed guide |
|---|---:|---|
| Graph/topology | 8080 | [graph/README.md](graph/README.md) |
| Fault library | 8081 | [faultlib/README.md](faultlib/README.md) |
| Chaos API | 8082 | [chaos/README.md](chaos/README.md) |
| Provisioning simulator | 8083 | [sim/README.md](sim/README.md) |
| Phoenix agent | 8084 | [agent/README.md](agent/README.md) |
| Dashboard | 5174 | `npm --prefix dashboard run dev` |

## Verification

```bash
for service in sim chaos faultlib graph agent; do
  (cd "$service" && python -m pytest)
done
npm --prefix dashboard run build
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard opens but cluster cards are disconnected | Safe local mode has no graph or agent | Expected; use live k3s mode for cluster signals |
| Safe injection cannot reach the simulator | `SIMULATOR_URL` is missing or simulator is stopped | Start Path A steps 1 and 2 with the documented ports |
| Failure rankings are unavailable | Faultlib cannot reach chaos | Set `CHAOS_URL=http://127.0.0.1:8082` and restart faultlib |
| `kubectl` shows one node named `orbstack` | Wrong Kubernetes context | Run `kubectl config use-context argus` |
| Cilium or Chaos Mesh pods are missing | Cluster prerequisites are incomplete | Finish Argus cluster setup before deploying Phoenix |
| Dashboard port is occupied | Another local product is on the wrong reserved port | Use Argus 5173, Phoenix 5174, Sentinel 5175 |
| Live injection is disabled | Cluster API unavailable or live mode not confirmed | Restore the cluster connection and type the exact confirmation phrase |
| OpenAI reasoning reports missing quota/key | Credential not loaded or project lacks quota | Set `OPENAI_API_KEY` in `.env`, confirm API billing, and redeploy the agent |

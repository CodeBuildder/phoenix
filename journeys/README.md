# Customer Journey Resilience Lab

This cluster-free service turns a seed into a reproducible customer journey,
load shape, fault, safety budget, and evidence-backed recovery score. It gives
Phoenix a judge-friendly proof loop: **generate → approve when risky → inject →
measure → recover → replay the original journey**.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r journeys/requirements.txt
.venv/bin/uvicorn main:app --app-dir journeys/src --port 8004
```

In another terminal:

```bash
curl -s localhost:8004/scenarios/generate \
  -H 'content-type: application/json' \
  -d '{"seed": 42, "count": 3}'
```

Pass one returned scenario to `POST /scenarios/run` as
`{"scenario": <scenario>, "approved": true}`. Reuse the seed to replay exactly
the same experiment. Omit `approved` to demonstrate the human gate for pod-kill
and dependency-outage scenarios.

This phase uses a deterministic local execution adapter. The response labels
the mode as `cluster-free`; no simulated result is presented as cluster evidence.
The next adapter maps the same scenario contract to the existing Chaos Mesh and
Provisioning Simulator services.

## Test

```bash
.venv/bin/pytest journeys
```

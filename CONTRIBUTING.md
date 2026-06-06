# Contributing to Phoenix

## Branch naming

| Type | Pattern | Example |
|---|---|---|
| New feature | `feat/m{N}-description` | `feat/m1-provisioning-sim` |
| Bug fix | `fix/short-description` | `fix/chaos-mesh-crd-version` |
| Documentation | `docs/short-description` | `docs/agent-state-machine` |
| Chore | `chore/short-description` | `chore/update-deps` |

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add volume create/attach endpoints to provisioning sim
fix: resolve race in chaos scenario stop handler
docs: document the diagnose node's causal-chain prompt
chore: bump langgraph and fastapi versions
```

## Pull requests

- Every PR must reference an issue: `Closes #N` in the description
- Set the milestone (`M1`–`M3`, `M6`, `M7`) and add a type label (`agent`, `dashboard`,
  `chaos`, `provisioning-sim`, `ai`, `ci`) at creation time
- Keep PRs focused — one issue per PR where possible

## Labels

- `agent` — LangGraph detect/diagnose/heal/approve/verify state machine
- `dashboard` — React + TS + Vite + Tailwind UI
- `chaos` — Chaos Mesh wrapper, fault library, failure-mode taxonomy, blast radius
- `provisioning-sim` — synthetic enterprise-infrastructure provisioning simulator
- `ai` — Claude reasoning, diagnosis, predictive healing
- `ci` — CI/CD pipeline

Milestones (`M1`–`M3` for Phoenix's own build, plus `M6`/`M7` for cross-platform
integration and polish) track which phase an issue belongs to — see the
[milestones page](https://github.com/CodeBuildder/phoenix/milestones).

## Dashboard design rules

Dark command-center aesthetic, not generic AI/SaaS: monospace accents, neon-on-near-black,
dense real-time panels, live WebSocket updates, force-directed graph visualizations,
sparklines. Think SOC/NOC wall display.
